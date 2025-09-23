from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from queue import Empty, Queue
from threading import Event, Thread
from typing import Any, Dict, Iterable, List

from sqlalchemy import text
from websocket import WebSocketApp

from app.db import get_engine

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(message)s")
logger = logging.getLogger("polygon_ws")

DEFAULT_SYMBOLS = ["SPY", "QQQ", "SPX", "NDX"]
INDEX_SYMBOLS = {"SPX", "NDX"}

WS_URL = os.getenv("POLYGON_WS_URL", "wss://socket.polygon.io/stocks")
API_KEY = os.getenv("POLYGON_WS_KEY") or os.getenv("POLYGON_API_KEY")
STREAM_SYMBOLS = [s.strip().upper() for s in os.getenv("POLYGON_WS_SYMBOLS", ",".join(DEFAULT_SYMBOLS)).split(",") if s.strip()]
BATCH_SIZE = int(os.getenv("POLYGON_WS_BATCH", "100"))
FLUSH_INTERVAL_SEC = float(os.getenv("POLYGON_WS_FLUSH_INTERVAL", "2.0"))
SOURCE_NAME = "polygon_ws"

if not API_KEY:
    logger.error("POLYGON_WS_KEY or POLYGON_API_KEY must be set for websocket auth")
    sys.exit(1)

if not STREAM_SYMBOLS:
    STREAM_SYMBOLS = DEFAULT_SYMBOLS

INSERT_SQL = text(
    """
    INSERT INTO ticks (symbol, ts, open, high, low, close, volume, vwap, transactions, source)
    VALUES (:symbol, :ts, :open, :high, :low, :close, :volume, :vwap, :transactions, :source)
    ON CONFLICT (symbol, ts)
    DO UPDATE SET
        open = EXCLUDED.open,
        high = EXCLUDED.high,
        low = EXCLUDED.low,
        close = EXCLUDED.close,
        volume = EXCLUDED.volume,
        vwap = EXCLUDED.vwap,
        transactions = EXCLUDED.transactions,
        source = EXCLUDED.source;
    """
)


def map_channel(symbol: str) -> str:
    symbol = symbol.upper()
    if symbol in INDEX_SYMBOLS or symbol.startswith("X"):
        return f"XA.{symbol}"
    return f"A.{symbol}"


class PolygonStreamer:
    def __init__(self, url: str, api_key: str, symbols: Iterable[str]) -> None:
        self.url = url
        self.api_key = api_key
        self.symbols = list(symbols)
        self._ws: WebSocketApp | None = None
        self._running = Event()
        self._running.set()
        self._queue: Queue[Dict[str, Any]] = Queue(maxsize=10000)
        self._writer_thread = Thread(target=self._writer_loop, daemon=True)
        self._last_flush = time.time()

    def run(self) -> None:
        self._writer_thread.start()
        while self._running.is_set():
            try:
                self._connect_and_listen()
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.exception("Websocket error: %s", exc)
            if self._running.is_set():
                logger.info("Reconnecting in 5 seconds...")
                time.sleep(5)
        logger.info("Streamer stopped")

    def stop(self) -> None:
        self._running.clear()
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
        logger.info("Stop signal received; waiting for writer to drain queue")
        self._writer_thread.join(timeout=10)

    # Websocket callbacks -------------------------------------------------
    def _connect_and_listen(self) -> None:
        channels = ",".join(map(map_channel, self.symbols))
        logger.info("Connecting to %s for channels %s", self.url, channels)
        self._ws = WebSocketApp(
            self.url,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
            on_open=self._on_open,
        )
        self._ws.run_forever(ping_interval=20, ping_timeout=10)

    def _on_open(self, ws: WebSocketApp) -> None:  # pragma: no cover - network
        auth_msg = json.dumps({"action": "auth", "params": self.api_key})
        ws.send(auth_msg)
        channels = ",".join(map(map_channel, self.symbols))
        sub_msg = json.dumps({"action": "subscribe", "params": channels})
        ws.send(sub_msg)
        logger.info("Authenticated and subscribed to %s", channels)

    def _on_message(self, ws: WebSocketApp, message: str) -> None:  # pragma: no cover - network
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            logger.warning("Failed to decode message: %s", message)
            return
        events: List[Dict[str, Any]]
        if isinstance(payload, list):
            events = payload
        else:
            events = [payload]
        for event in events:
            if event.get("ev") == "status":
                logger.warning("Status event: %s", event)
                self._handle_status(event)
                continue
            record = self._parse_event(event)
            if record:
                try:
                    self._queue.put_nowait(record)
                except Exception:
                    logger.warning("Queue full; dropping tick for %s", record.get("symbol"))

    def _on_error(self, ws: WebSocketApp, error: Any) -> None:  # pragma: no cover - network
        logger.error("Websocket error: %s", error)

    def _on_close(self, ws: WebSocketApp, close_status_code: int | None, close_msg: str | None) -> None:  # pragma: no cover - network
        logger.warning("Websocket closed (%s): %s", close_status_code, close_msg)

    # Data handling -------------------------------------------------------
    def _writer_loop(self) -> None:
        engine = get_engine()
        while self._running.is_set() or not self._queue.empty():
            batch: List[Dict[str, Any]] = []
            try:
                item = self._queue.get(timeout=1.0)
                batch.append(item)
            except Empty:
                self._flush(engine, batch)
                continue

            while len(batch) < BATCH_SIZE:
                try:
                    batch.append(self._queue.get_nowait())
                except Empty:
                    break

            self._flush(engine, batch)

    def _flush(self, engine, batch: List[Dict[str, Any]]) -> None:
        now = time.time()
        if not batch and (now - self._last_flush) < FLUSH_INTERVAL_SEC:
            return
        if not batch and self._queue.empty():
            self._last_flush = now
            return
        if not batch:
            return
        try:
            with engine.begin() as conn:
                conn.execute(INSERT_SQL, batch)
            logger.debug("Inserted %s ticks", len(batch))
        except Exception as exc:
            logger.exception("Failed to insert batch: %s", exc)
        finally:
            self._last_flush = time.time()

    def _parse_event(self, event: Dict[str, Any]) -> Dict[str, Any] | None:
        ev_type = event.get("ev")
        if ev_type not in {"A", "AM", "XA"}:
            return None
        sym = event.get("sym")
        if not sym:
            return None
        ts_ms = event.get("s")
        if not ts_ms:
            return None
        ts = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        record = {
            "symbol": sym.upper(),
            "ts": ts,
            "open": event.get("o"),
            "high": event.get("h"),
            "low": event.get("l"),
            "close": event.get("c"),
            "volume": event.get("v"),
            "vwap": event.get("vw"),
            "transactions": event.get("z") or event.get("t") or None,
            "source": SOURCE_NAME,
        }
        return record

    def _handle_status(self, event: Dict[str, Any]) -> None:
        """Handle Polygon status frames (unauthorized subscriptions, etc.)."""
        message = (event.get("message") or "").lower()
        params = event.get("params") or ""
        if "unauthorized" in message and params:
            symbol = params.split(".")[-1]
            if symbol and symbol in self.symbols:
                logger.warning("Removing symbol %s due to unauthorized subscription", symbol)
                self.symbols = [s for s in self.symbols if s != symbol]
                # Force reconnect with cleaned list
                if self._ws:
                    try:
                        self._ws.close()
                    except Exception:
                        pass


def main() -> None:
    streamer = PolygonStreamer(WS_URL, API_KEY, STREAM_SYMBOLS)

    def handle_signal(signum, frame):  # pragma: no cover - system
        logger.info("Received signal %s; shutting down", signum)
        streamer.stop()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        streamer.run()
    except KeyboardInterrupt:  # pragma: no cover - console
        streamer.stop()


if __name__ == "__main__":
    main()
