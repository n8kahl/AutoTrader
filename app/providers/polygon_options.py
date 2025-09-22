from __future__ import annotations

import os
from typing import Dict, Optional

import httpx

API_KEY = os.getenv("POLYGON_API_KEY", "")
BASE = "https://api.polygon.io"


async def top_contract_stats(
    symbol: str,
    contract_type: str,
    timeout: float = 5.0,
) -> Optional[Dict[str, float]]:
    if not API_KEY:
        return None
    params = {
        "underlying_ticker": symbol.upper(),
        "contract_type": contract_type,
        "expired": "false",
        "order": "desc",
        "sort": "day.volume",
        "limit": 1,
        "apiKey": API_KEY,
    }
    url = f"{BASE}/v3/reference/options/contracts"
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(url, params=params)
        if resp.status_code >= 400:
            return None
        data = resp.json() or {}
    results = data.get("results") or []
    if not results:
        return None
    result = results[0]
    day = result.get("day") or {}
    return {
        "volume": float(day.get("volume") or 0.0),
        "iv": float(result.get("implied_volatility") or 0.0),
    }


async def option_feedback(symbol: str, timeout: float = 5.0) -> Optional[Dict[str, float]]:
    call_stats = await top_contract_stats(symbol, "call", timeout=timeout)
    put_stats = await top_contract_stats(symbol, "put", timeout=timeout)
    if not call_stats and not put_stats:
        return None
    return {
        "call_volume": (call_stats or {}).get("volume", 0.0),
        "put_volume": (put_stats or {}).get("volume", 0.0),
        "call_iv": (call_stats or {}).get("iv", 0.0),
        "put_iv": (put_stats or {}).get("iv", 0.0),
    }


__all__ = ["option_feedback"]
