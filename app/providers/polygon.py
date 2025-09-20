import os, httpx
from typing import Dict, Any


BASE = "https://api.polygon.io"


async def last_trade(symbol: str, timeout: float = 10.0) -> Dict[str, Any]:
    key = os.getenv("POLYGON_API_KEY", "")
    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.get(f"{BASE}/v2/snapshot/locale/us/markets/stocks/tickers/{symbol.upper()}", params={"apiKey": key})
        r.raise_for_status()
        j = r.json() or {}
        lt = (j.get("ticker") or {}).get("lastTrade") or {}
        return {"symbol": symbol.upper(), "price": lt.get("p"), "t": lt.get("t")}

