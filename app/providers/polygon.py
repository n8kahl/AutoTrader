import os, time, httpx
from typing import Dict, Any, List


BASE = "https://api.polygon.io"


async def last_trade(symbol: str, timeout: float = 10.0) -> Dict[str, Any]:
    key = os.getenv("POLYGON_API_KEY", "")
    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.get(f"{BASE}/v2/snapshot/locale/us/markets/stocks/tickers/{symbol.upper()}", params={"apiKey": key})
        r.raise_for_status()
        j = r.json() or {}
        lt = (j.get("ticker") or {}).get("lastTrade") or {}
        return {"symbol": symbol.upper(), "price": lt.get("p"), "t": lt.get("t")}


async def minute_bars(symbol: str, minutes: int = 120, timeout: float = 10.0) -> List[Dict[str, Any]]:
    """Fetch recent bars with graceful fallbacks.
    Tries 1m first, then 5m, then returns [] if unavailable.
    """
    key = os.getenv("POLYGON_API_KEY", "")
    now_ms = int(time.time() * 1000)
    frm = now_ms - max(1, minutes) * 60_000
    async with httpx.AsyncClient(timeout=timeout) as c:
        # Try 1-minute
        try:
            r = await c.get(
                f"{BASE}/v2/aggs/ticker/{symbol.upper()}/range/1/minute/{frm}/{now_ms}",
                params={"apiKey": key, "adjusted": "true", "sort": "asc", "limit": 5000},
            )
            r.raise_for_status()
            j = r.json() or {}
            return [
                {"t": b.get("t"), "o": b.get("o"), "h": b.get("h"), "l": b.get("l"), "c": b.get("c"), "v": b.get("v")}
                for b in (j.get("results") or [])
            ]
        except httpx.HTTPStatusError as e:
            # Fallback to 5-minute if 1m is forbidden
            if e.response is None or e.response.status_code not in (401, 402, 403):
                raise
        except Exception:
            pass
        # Try 5-minute fallback
        try:
            r = await c.get(
                f"{BASE}/v2/aggs/ticker/{symbol.upper()}/range/5/minute/{frm}/{now_ms}",
                params={"apiKey": key, "adjusted": "true", "sort": "asc", "limit": 5000},
            )
            r.raise_for_status()
            j = r.json() or {}
            return [
                {"t": b.get("t"), "o": b.get("o"), "h": b.get("h"), "l": b.get("l"), "c": b.get("c"), "v": b.get("v")}
                for b in (j.get("results") or [])
            ]
        except Exception:
            return []


async def daily_bars(symbol: str, days: int = 120, timeout: float = 10.0) -> List[Dict[str, Any]]:
    key = os.getenv("POLYGON_API_KEY", "")
    now_ms = int(time.time() * 1000)
    frm = now_ms - max(1, days) * 86_400_000
    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.get(
            f"{BASE}/v2/aggs/ticker/{symbol.upper()}/range/1/day/{frm}/{now_ms}",
            params={"apiKey": key, "adjusted": "true", "sort": "asc", "limit": 5000},
        )
        r.raise_for_status()
        j = r.json() or {}
        return [
            {"t": b.get("t"), "o": b.get("o"), "h": b.get("h"), "l": b.get("l"), "c": b.get("c"), "v": b.get("v")}
            for b in (j.get("results") or [])
        ]
