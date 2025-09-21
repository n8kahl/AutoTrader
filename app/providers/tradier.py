from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import httpx
from zoneinfo import ZoneInfo

from ..metrics import (
    autotrader_tradier_request_latency,
    autotrader_tradier_request_retry_total,
    autotrader_tradier_request_total,
)


def _resolve_base() -> str:
    base = os.getenv("TRADIER_BASE")
    env = (os.getenv("TRADIER_ENV") or "sandbox").lower()
    if not base:
        base = "https://sandbox.tradier.com" if env == "sandbox" else "https://api.tradier.com"
    if not base.rstrip("/").endswith("/v1"):
        base = base.rstrip("/") + "/v1"
    return base


def _token() -> str:
    return os.getenv("TRADIER_ACCESS_TOKEN") or os.getenv("TRADIER_API_KEY") or ""


class TradierHTTPError(Exception):
    pass


_NY_TZ = ZoneInfo("America/New_York")
_BAR_CACHE: Dict[Tuple[str, str, int], Tuple[float, List[Dict[str, Any]]]] = {}
_BAR_CACHE_TTL = 30.0  # seconds


async def _request(
    method: str,
    path: str,
    *,
    params: Dict[str, Any] | None = None,
    data: Dict[str, Any] | None = None,
    timeout: float = 10.0,
    max_attempts: int = 3,
    extra_headers: Dict[str, str] | None = None,
) -> Dict[str, Any]:
    url = f"{_resolve_base()}{path}"
    headers = {
        "Authorization": f"Bearer {_token()}",
        "Accept": "application/json",
    }
    if method.upper() in {"POST", "PUT"}:
        headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
    if extra_headers:
        headers.update(extra_headers)

    async with httpx.AsyncClient(timeout=timeout) as client:
        backoff = 0.25
        last_error: Optional[Exception] = None
        for attempt in range(1, max_attempts + 1):
            start = time.perf_counter()
            try:
                resp = await client.request(method, url, headers=headers, params=params, data=data)
            except httpx.TimeoutException as exc:
                duration = time.perf_counter() - start
                autotrader_tradier_request_latency.labels(path=path).observe(duration)
                autotrader_tradier_request_total.labels(path=path, status="timeout").inc()
                autotrader_tradier_request_retry_total.labels(path=path, reason="timeout").inc()
                last_error = exc
                await asyncio.sleep(backoff)
                backoff = min(2.0, backoff * 2)
                continue
            except httpx.HTTPError as exc:
                duration = time.perf_counter() - start
                autotrader_tradier_request_latency.labels(path=path).observe(duration)
                autotrader_tradier_request_total.labels(path=path, status="http_error").inc()
                autotrader_tradier_request_retry_total.labels(path=path, reason=exc.__class__.__name__).inc()
                last_error = exc
                await asyncio.sleep(backoff)
                backoff = min(2.0, backoff * 2)
                continue

            duration = time.perf_counter() - start
            status = resp.status_code
            autotrader_tradier_request_latency.labels(path=path).observe(duration)
            autotrader_tradier_request_total.labels(path=path, status=str(status)).inc()

            if status == 429 or 500 <= status < 600:
                autotrader_tradier_request_retry_total.labels(path=path, reason=str(status)).inc()
                last_error = TradierHTTPError(f"{status}: {resp.text}")
                await asyncio.sleep(backoff)
                backoff = min(2.0, backoff * 2)
                continue

            if status >= 400:
                raise TradierHTTPError(f"{status}: {resp.text}")

            try:
                return resp.json() or {}
            except ValueError:
                return {}

    if last_error:
        raise last_error
    raise TradierHTTPError(f"Tradier request failed for {path}")


async def get_quote(symbol: str, timeout: float = 10.0) -> Dict[str, Any]:
    params = {"symbols": symbol.upper()}
    return await _request("GET", "/markets/quotes", params=params, timeout=timeout)


async def place_equity_order(
    account_id: str,
    symbol: str,
    side: str,  # buy|sell|buy_to_cover|sell_short
    qty: int,
    order_type: str = "market",  # market|limit|stop|stop_limit
    duration: str = "day",
    price: float | None = None,
    stop: float | None = None,
    advanced: str | None = None,  # oco|oto|otoco
    take_profit: float | None = None,
    client_order_id: str | None = None,
    timeout: float = 10.0,
) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "class": "equity",
        "symbol": symbol.upper(),
        "side": side,
        "quantity": qty,
        "type": order_type,
        "duration": duration,
    }
    if price is not None:
        data["price"] = price
    if stop is not None:
        data["stop"] = stop
    if advanced:
        data["advanced"] = advanced
    if take_profit is not None:
        data["take_profit"] = take_profit
    if client_order_id:
        data["client_order_id"] = client_order_id

    return await _request(
        "POST",
        f"/accounts/{account_id}/orders",
        data=data,
        timeout=timeout,
    )


async def list_orders(account_id: str, status: str | None = None, timeout: float = 10.0) -> Dict[str, Any]:
    params: Dict[str, Any] = {}
    if status:
        params["status"] = status
    return await _request("GET", f"/accounts/{account_id}/orders", params=params, timeout=timeout)


async def get_order(account_id: str, order_id: str, timeout: float = 10.0) -> Dict[str, Any]:
    return await _request("GET", f"/accounts/{account_id}/orders/{order_id}", timeout=timeout)


async def cancel_order(account_id: str, order_id: str, timeout: float = 10.0) -> Dict[str, Any]:
    return await _request("DELETE", f"/accounts/{account_id}/orders/{order_id}", timeout=timeout)


async def list_positions(account_id: str, timeout: float = 10.0) -> Dict[str, Any]:
    return await _request("GET", f"/accounts/{account_id}/positions", timeout=timeout)


async def get_balances(account_id: str, timeout: float = 10.0) -> Dict[str, Any]:
    return await _request("GET", f"/accounts/{account_id}/balances", timeout=timeout)


async def last_trade_price(symbol: str, timeout: float = 10.0) -> Optional[float]:
    try:
        j = await get_quote(symbol, timeout=timeout)
    except TradierHTTPError:
        return None
    quotes = (j.get("quotes") or {}).get("quote")
    if isinstance(quotes, list):
        quote = quotes[0] if quotes else {}
    else:
        quote = quotes or {}
    try_fields = ["last", "close", "prevclose"]
    for field in try_fields:
        try:
            val = float(quote.get(field))
            if val:
                return val
        except (TypeError, ValueError):
            continue
    return None


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=_NY_TZ)
        except (TypeError, ValueError, OSError):
            return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=_NY_TZ)
    text = str(value)
    text_norm = text.replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(text_norm, fmt)
            return dt.replace(tzinfo=_NY_TZ)
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=_NY_TZ)
    except ValueError:
        return None


def _maybe_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _cache_key(symbol: str, interval: str, minutes: int) -> Tuple[str, str, int]:
    return symbol.upper(), interval, minutes


def _cache_get(symbol: str, interval: str, minutes: int) -> Optional[List[Dict[str, Any]]]:
    key = _cache_key(symbol, interval, minutes)
    item = _BAR_CACHE.get(key)
    if not item:
        return None
    ts, data = item
    if time.time() - ts > _BAR_CACHE_TTL:
        _BAR_CACHE.pop(key, None)
        return None
    return data


def _cache_put(symbol: str, interval: str, minutes: int, value: List[Dict[str, Any]]) -> None:
    key = _cache_key(symbol, interval, minutes)
    _BAR_CACHE[key] = (time.time(), value)


async def _timesales_bars(
    symbol: str,
    *,
    interval: str,
    minutes: int,
    timeout: float,
) -> List[Dict[str, Any]]:
    cached = _cache_get(symbol, interval, minutes)
    if cached is not None:
        return cached

    end_et = datetime.now(_NY_TZ)
    start_et = end_et - timedelta(minutes=max(minutes, 1) + 1)
    params = {
        "symbol": symbol.upper(),
        "interval": interval,
        "start": start_et.strftime("%Y-%m-%d %H:%M"),
        "end": end_et.strftime("%Y-%m-%d %H:%M"),
        "session_filter": "all",
    }
    payload = await _request("GET", "/markets/timesales", params=params, timeout=timeout)
    series = ((payload.get("series") or {}).get("data")) or []
    bars: List[Dict[str, Any]] = []
    for row in series:
        ts = _parse_timestamp(row.get("timestamp") or row.get("time"))
        if not ts:
            continue
        bars.append(
            {
                "t": int(ts.timestamp() * 1000),
                "o": _maybe_float(row.get("open")),
                "h": _maybe_float(row.get("high")),
                "l": _maybe_float(row.get("low")),
                "c": _maybe_float(row.get("close")),
                "v": _maybe_float(row.get("volume")),
            }
        )
    bars.sort(key=lambda b: b.get("t") or 0)
    _cache_put(symbol, interval, minutes, bars)
    return bars


async def minute_bars(symbol: str, minutes: int = 180, timeout: float = 10.0) -> List[Dict[str, Any]]:
    return await _timesales_bars(symbol, interval="1min", minutes=minutes, timeout=timeout)


async def five_minute_bars(symbol: str, minutes: int = 300, timeout: float = 10.0) -> List[Dict[str, Any]]:
    bars = await _timesales_bars(symbol, interval="5min", minutes=minutes, timeout=timeout)
    if bars:
        return bars
    # Fallback: aggregate 1-minute bars when direct 5-minute data is unavailable.
    one_minute = await minute_bars(symbol, minutes=minutes, timeout=timeout)
    if not one_minute:
        return []
    aggregated: List[Dict[str, Any]] = []
    bucket: List[Dict[str, Any]] = []
    for bar in one_minute:
        bucket.append(bar)
        if len(bucket) == 5:
            aggregated.append(_aggregate_bucket(bucket))
            bucket = []
    if bucket:
        aggregated.append(_aggregate_bucket(bucket))
    return aggregated


def _aggregate_bucket(bucket: List[Dict[str, Any]]) -> Dict[str, Any]:
    o = _maybe_float(bucket[0].get("o"))
    h = max((_maybe_float(b.get("h")) or float("-inf")) for b in bucket)
    l = min((_maybe_float(b.get("l")) or float("inf")) for b in bucket)
    c = _maybe_float(bucket[-1].get("c"))
    v = sum((_maybe_float(b.get("v")) or 0.0) for b in bucket)
    t = bucket[-1].get("t")
    if h == float("-inf"):
        h = None
    if l == float("inf"):
        l = None
    return {"t": t, "o": o, "h": h, "l": l, "c": c, "v": v}


__all__ = [
    "TradierHTTPError",
    "get_quote",
    "place_equity_order",
    "list_orders",
    "get_order",
    "cancel_order",
    "list_positions",
    "get_balances",
    "last_trade_price",
    "minute_bars",
    "five_minute_bars",
]
