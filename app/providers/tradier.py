from __future__ import annotations
import os
import httpx
from typing import Dict, Any


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


async def get_quote(symbol: str, timeout: float = 10.0) -> Dict[str, Any]:
    url = f"{_resolve_base()}/markets/quotes"
    headers = {
        "Authorization": f"Bearer {_token()}",
        "Accept": "application/json",
    }
    params = {"symbols": symbol.upper()}
    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.get(url, headers=headers, params=params)
        if r.status_code >= 400:
            raise TradierHTTPError(f"{r.status_code}: {r.text}")
        return r.json() or {}


async def place_equity_order(
    account_id: str,
    symbol: str,
    side: str,  # buy|sell|buy_to_cover|sell_short
    qty: int,
    order_type: str = "market",  # market|limit|stop|stop_limit
    duration: str = "day",
    price: float | None = None,
    stop: float | None = None,
    timeout: float = 10.0,
) -> Dict[str, Any]:
    url = f"{_resolve_base()}/accounts/{account_id}/orders"
    headers = {
        "Authorization": f"Bearer {_token()}",
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    }
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

    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.post(url, headers=headers, data=data)
        if r.status_code >= 400:
            raise TradierHTTPError(f"{r.status_code}: {r.text}")
        return r.json() or {}

