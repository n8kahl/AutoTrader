from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Dict, List, Optional

from .. import ledger
from ..providers import tradier


@dataclass
class ReplayResult:
    symbol: str
    setup: str
    entry_price: float
    exit_price: float
    return_pct: float
    duration_min: float
    ts: float


async def _default_fetch_bars(symbol: str, start: datetime, end: datetime) -> List[Dict[str, float]]:
    """Fetch minute bars around *end* time. Works best for recent signals."""
    horizon = max(1, int((end - start).total_seconds() // 60) + 1)
    bars = await tradier.minute_bars(symbol, minutes=horizon)
    return bars


async def replay_signals(
    limit: int = 500,
    horizon_minutes: int = 15,
    fetch_bars: Optional[Callable[[str, datetime, datetime], Awaitable[List[Dict[str, float]]]]] = None,
) -> Dict[str, object]:
    """Replay recent approved signals to estimate expectancy.

    Parameters
    ----------
    limit: int
        Maximum number of ledger events to inspect.
    horizon_minutes: int
        Minutes after the signal timestamp to measure outcome.
    fetch_bars: coroutine
        Optional custom function to retrieve OHLCV bars. Defaults to a
        lightweight Tradier wrapper suitable for recent signals.
    """
    fetch = fetch_bars or _default_fetch_bars
    events = ledger.read_events(limit=limit)
    horizon = timedelta(minutes=horizon_minutes)

    results: List[ReplayResult] = []
    for ev in events:
        if ev.get("kind") != "signal_approved":
            continue
        data = ev.get("data") or {}
        signal = data.get("signal") or {}
        metadata = signal.get("metadata") or {}
        entry_price = metadata.get("last_price") or signal.get("price")
        if not entry_price:
            continue
        entry_price = float(entry_price)
        setup = (signal.get("setup") or metadata.get("setup") or "UNKNOWN").upper()
        symbol = (signal.get("symbol") or metadata.get("symbol") or "").upper()
        if not symbol:
            continue
        ts = float(ev.get("ts") or 0.0)
        start = datetime.fromtimestamp(ts, tz=timezone.utc)
        end = start + horizon
        bars = await fetch(symbol, start, end)
        if not bars:
            continue
        exit_price = bars[-1].get("c") or bars[-1].get("close")
        if exit_price is None:
            continue
        exit_price = float(exit_price)
        duration = (len(bars) - 1) if len(bars) > 1 else horizon_minutes
        result = ReplayResult(
            symbol=symbol,
            setup=setup,
            entry_price=entry_price,
            exit_price=exit_price,
            return_pct=(exit_price - entry_price) / entry_price,
            duration_min=float(duration),
            ts=ts,
        )
        results.append(result)

    summary: Dict[str, object] = {"results": results, "per_setup": {}, "overall": {}}
    per_setup: Dict[str, Dict[str, float]] = {}

    for res in results:
        stats = per_setup.setdefault(res.setup, {"count": 0, "avg_return": 0.0, "win_rate": 0.0})
        stats["count"] += 1
        stats["avg_return"] += res.return_pct
        if res.return_pct > 0:
            stats["win_rate"] += 1

    for setup, stats in per_setup.items():
        count = stats["count"] or 1
        avg_return = stats["avg_return"] / count
        win_rate = stats["win_rate"] / count
        summary["per_setup"][setup] = {
            "count": count,
            "avg_return": avg_return,
            "win_rate": win_rate,
        }

    if results:
        summary["overall"] = {
            "count": len(results),
            "avg_return": sum(r.return_pct for r in results) / len(results),
            "win_rate": sum(1 for r in results if r.return_pct > 0) / len(results),
        }
    else:
        summary["overall"] = {"count": 0, "avg_return": 0.0, "win_rate": 0.0}

    return summary


def replay_signals_sync(**kwargs) -> Dict[str, object]:
    """Synchronous helper for notebooks/CLI usage."""
    return asyncio.run(replay_signals(**kwargs))
