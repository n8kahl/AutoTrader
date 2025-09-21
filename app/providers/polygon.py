import os, time, httpx, asyncio, logging
from typing import Dict, Any, List, Tuple, Optional

from ..metrics import (
    autotrader_polygon_request_latency,
    autotrader_polygon_request_retry_total,
    autotrader_polygon_request_total,
)


class RateLimitError(RuntimeError):
    """Raised when Polygon responds with HTTP 429 and no cached data is available."""


class PermissionDeniedError(RuntimeError):
    """Raised when the Polygon key lacks access to the requested resource."""


_BAR_CACHE: Dict[Tuple[str, str], Tuple[float, List[Dict[str, Any]]]] = {}
_CACHE_TTL_SEC = 20.0


BASE = "https://api.polygon.io"

logger = logging.getLogger("autotrader.providers.polygon")


async def _get(path: str, params: Dict[str, Any] | None = None, timeout: float = 10.0) -> Dict[str, Any]:
    key = os.getenv("POLYGON_API_KEY", "")
    resolved_params = dict(params or {})
    resolved_params.setdefault("apiKey", key)
    url = f"{BASE}{path}"

    async with httpx.AsyncClient(timeout=timeout) as client:
        backoff = 0.25
        last_response: Optional[httpx.Response] = None
        last_error: Optional[Exception] = None
        for attempt in range(1, 6):
            start = time.perf_counter()
            try:
                resp = await client.get(url, params=resolved_params)
            except httpx.TimeoutException as exc:
                duration = time.perf_counter() - start
                autotrader_polygon_request_latency.labels(path=path).observe(duration)
                autotrader_polygon_request_total.labels(path=path, status="timeout").inc()
                autotrader_polygon_request_retry_total.labels(path=path, reason="timeout").inc()
                logger.warning("Polygon timeout on %s (attempt %s)", path, attempt)
                last_error = exc
                await asyncio.sleep(backoff)
                backoff = min(2.0, backoff * 2)
                continue
            except httpx.HTTPError as exc:
                duration = time.perf_counter() - start
                autotrader_polygon_request_latency.labels(path=path).observe(duration)
                autotrader_polygon_request_total.labels(path=path, status="http_error").inc()
                autotrader_polygon_request_retry_total.labels(path=path, reason=exc.__class__.__name__).inc()
                logger.warning("Polygon HTTP error on %s (attempt %s): %s", path, attempt, exc)
                last_error = exc
                await asyncio.sleep(backoff)
                backoff = min(2.0, backoff * 2)
                continue

            duration = time.perf_counter() - start
            status = resp.status_code
            autotrader_polygon_request_latency.labels(path=path).observe(duration)
            autotrader_polygon_request_total.labels(path=path, status=str(status)).inc()
            last_response = resp

            if status in (401, 402, 403):
                logger.error(
                    "Polygon %s on %s — check API key permissions or plan tier",
                    status,
                    path,
                )
                raise PermissionDeniedError(f"Polygon returned {status} for {path}")

            if status == 429:
                autotrader_polygon_request_retry_total.labels(path=path, reason="429").inc()
                logger.warning("Polygon 429 on %s (attempt %s)", path, attempt)
                await asyncio.sleep(backoff)
                backoff = min(2.0, backoff * 2)
                continue

            if 500 <= status < 600:
                autotrader_polygon_request_retry_total.labels(path=path, reason="5xx").inc()
                logger.warning("Polygon %s on %s (attempt %s)", status, path, attempt)
                await asyncio.sleep(backoff)
                backoff = min(2.0, backoff * 2)
                continue

            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.error("Polygon HTTP error %s on %s", status, path, exc_info=exc)
                raise

            return resp.json() or {}

    if last_response is not None:
        if last_response.status_code == 429:
            logger.error("Polygon rate limit exhaustion on %s", path)
            raise RateLimitError("Polygon rate limited")
        try:
            last_response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error("Polygon request failed after retries for %s", path, exc_info=exc)
            raise
        return last_response.json() or {}

    if last_error is not None:
        logger.error("Polygon request errored after retries for %s: %s", path, last_error)
        raise last_error

    raise RuntimeError(f"Polygon request failed without response for {path}")


async def last_trade(symbol: str, timeout: float = 10.0) -> Dict[str, Any]:
    j = await _get(
        f"/v2/snapshot/locale/us/markets/stocks/tickers/{symbol.upper()}",
        params=None,
        timeout=timeout,
    )
    lt = (j.get("ticker") or {}).get("lastTrade") or {}
    return {"symbol": symbol.upper(), "price": lt.get("p"), "t": lt.get("t")}


async def minute_bars(symbol: str, minutes: int = 120, timeout: float = 10.0) -> List[Dict[str, Any]]:
    """Fetch recent bars with graceful fallbacks.
    Tries 1m first, then 5m, then returns [] if unavailable.
    """
    now_ms = int(time.time() * 1000)
    frm = now_ms - max(1, minutes) * 60_000
    symbol_upper = symbol.upper()
    cache_key = (symbol_upper, f"{minutes}")
    now = time.time()
    cached = _BAR_CACHE.get(cache_key)
    if cached and (now - cached[0]) <= _CACHE_TTL_SEC:
        return cached[1]

    # Try 1-minute bars first.
    try:
        j = await _get(
            f"/v2/aggs/ticker/{symbol_upper}/range/1/minute/{frm}/{now_ms}",
            params={"adjusted": "true", "sort": "asc", "limit": 5000},
            timeout=timeout,
        )
        data = [
            {"t": b.get("t"), "o": b.get("o"), "h": b.get("h"), "l": b.get("l"), "c": b.get("c"), "v": b.get("v")}
            for b in (j.get("results") or [])
        ]
        _BAR_CACHE[cache_key] = (now, data)
        return data
    except RateLimitError:
        if cached:
            logger.debug("Polygon 1m bars served from cache for %s due to rate limit", symbol_upper)
            return cached[1]
    except PermissionDeniedError:
        if cached:
            logger.debug("Polygon 1m bars served from cache for %s due to permission error", symbol_upper)
            return cached[1]
        raise
    except httpx.HTTPStatusError as exc:
        if exc.response is None or exc.response.status_code not in (401, 402, 403):
            raise

    # Fallback to 5-minute bars.
    try:
        j = await _get(
            f"/v2/aggs/ticker/{symbol_upper}/range/5/minute/{frm}/{now_ms}",
            params={"adjusted": "true", "sort": "asc", "limit": 5000},
            timeout=timeout,
        )
        data = [
            {"t": b.get("t"), "o": b.get("o"), "h": b.get("h"), "l": b.get("l"), "c": b.get("c"), "v": b.get("v")}
            for b in (j.get("results") or [])
        ]
        _BAR_CACHE[cache_key] = (now, data)
        return data
    except RateLimitError:
        if cached:
            logger.debug("Polygon 5m bars served from cache for %s due to rate limit", symbol_upper)
            return cached[1]
        raise
    except PermissionDeniedError:
        if cached:
            logger.debug("Polygon 5m bars served from cache for %s due to permission error", symbol_upper)
            return cached[1]
        raise
    except Exception:
        if cached:
            logger.debug("Polygon 5m bars fallback cache hit for %s after error", symbol_upper)
            return cached[1]
        raise RateLimitError("Polygon minute bars rate limited")


def clear_cache() -> None:
    _BAR_CACHE.clear()


async def daily_bars(symbol: str, days: int = 120, timeout: float = 10.0) -> List[Dict[str, Any]]:
    now_ms = int(time.time() * 1000)
    frm = now_ms - max(1, days) * 86_400_000
    j = await _get(
        f"/v2/aggs/ticker/{symbol.upper()}/range/1/day/{frm}/{now_ms}",
        params={"adjusted": "true", "sort": "asc", "limit": 5000},
        timeout=timeout,
    )
    return [
        {"t": b.get("t"), "o": b.get("o"), "h": b.get("h"), "l": b.get("l"), "c": b.get("c"), "v": b.get("v")}
        for b in (j.get("results") or [])
    ]
