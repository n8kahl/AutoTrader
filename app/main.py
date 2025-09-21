from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
import os

from .config import settings
from .providers import tradier as t

app = FastAPI(title="AutoTrader API")


@app.exception_handler(Exception)
async def all_exception_handler(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"ok": False, "error": type(exc).__name__, "detail": str(exc)})


@app.get("/api/v1/diag/health")
async def health():
    cfg = settings()
    return {"ok": True, "dry_run": bool(cfg.dry_run)}


@app.get("/api/v1/diag/providers")
async def providers():
    cfg = settings()
    token_present = bool(os.getenv("TRADIER_ACCESS_TOKEN") or os.getenv("TRADIER_API_KEY"))
    base = (os.getenv("TRADIER_BASE") or ("https://sandbox.tradier.com" if cfg.tradier_env == "sandbox" else "https://api.tradier.com"))
    return {
        "tradier_token_present": token_present,
        "tradier_env": cfg.tradier_env,
        "tradier_base_resolved": base.rstrip("/") + "/v1",
        "polygon_key_present": bool(os.getenv("POLYGON_API_KEY")),
    }


@app.post("/api/v1/trade/dryrun")
async def dryrun(body: dict):
    cfg = settings()
    symbol = (body.get("symbol") or "").upper()
    side = body.get("side") or "buy"
    qty = int(body.get("qty") or 1)
    otype = body.get("type") or "market"
    duration = body.get("duration") or "day"
    price = body.get("price")
    stop = body.get("stop")
    if not symbol:
        return {"ok": False, "error": "symbol is required"}
    if cfg.dry_run:
        return {"ok": True, "dry_run": True, "would_send": {"symbol": symbol, "side": side, "qty": qty, "type": otype, "duration": duration, "price": price, "stop": stop}}
    if not cfg.tradier_account_id:
        return {"ok": False, "error": "TRADIER_ACCOUNT_ID is required when DRY_RUN=0"}
    try:
        resp = await t.place_equity_order(cfg.tradier_account_id, symbol, side, qty, otype, duration, price, stop)
        return {"ok": True, "dry_run": False, "resp": resp}
    except Exception as e:
        return {"ok": False, "error": type(e).__name__, "detail": str(e)}


Instrumentator().instrument(app).expose(app)

# ----- Order management -----
@app.get("/api/v1/orders")
async def orders(status: str | None = None):
    cfg = settings()
    if not cfg.tradier_account_id:
        return {"ok": False, "error": "TRADIER_ACCOUNT_ID is not set"}
    try:
        j = await t.list_orders(cfg.tradier_account_id, status=status)
        return {"ok": True, "orders": j}
    except Exception as e:
        return {"ok": False, "error": type(e).__name__, "detail": str(e)}


@app.get("/api/v1/orders/{order_id}")
async def order_get(order_id: str):
    cfg = settings()
    if not cfg.tradier_account_id:
        return {"ok": False, "error": "TRADIER_ACCOUNT_ID is not set"}
    try:
        j = await t.get_order(cfg.tradier_account_id, order_id)
        return {"ok": True, "order": j}
    except Exception as e:
        return {"ok": False, "error": type(e).__name__, "detail": str(e)}


@app.post("/api/v1/orders/{order_id}/cancel")
async def order_cancel(order_id: str):
    cfg = settings()
    if not cfg.tradier_account_id:
        return {"ok": False, "error": "TRADIER_ACCOUNT_ID is not set"}
    try:
        j = await t.cancel_order(cfg.tradier_account_id, order_id)
        return {"ok": True, "canceled": j}
    except Exception as e:
        return {"ok": False, "error": type(e).__name__, "detail": str(e)}


@app.get("/api/v1/positions")
async def positions():
    cfg = settings()
    if not cfg.tradier_account_id:
        return {"ok": False, "error": "TRADIER_ACCOUNT_ID is not set"}
    try:
        j = await t.list_positions(cfg.tradier_account_id)
        return {"ok": True, "positions": j}
    except Exception as e:
        return {"ok": False, "error": type(e).__name__, "detail": str(e)}


@app.get("/api/v1/account/balances")
async def balances():
    cfg = settings()
    if not cfg.tradier_account_id:
        return {"ok": False, "error": "TRADIER_ACCOUNT_ID is not set"}
    try:
        j = await t.get_balances(cfg.tradier_account_id)
        return {"ok": True, "balances": j}
    except Exception as e:
        return {"ok": False, "error": type(e).__name__, "detail": str(e)}
