from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
import os

from .config import settings
from .providers import tradier as t
from .engine import risk as riskmod
from .engine import strategy as strat

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


@app.post("/api/v1/orders/cancel_all")
async def orders_cancel_all(symbol: str | None = None, status: str = "open"):
    cfg = settings()
    if not cfg.tradier_account_id:
        return {"ok": False, "error": "TRADIER_ACCOUNT_ID is not set"}
    try:
        j = await t.list_orders(cfg.tradier_account_id, status=status)
        raw = (j.get("orders") or {}).get("order") or []
        items = raw if isinstance(raw, list) else [raw]
        if symbol:
            s = symbol.upper()
            items = [o for o in items if (o.get("symbol") or "").upper() == s]
        results = []
        for o in items:
            oid = o.get("id")
            st = (o.get("status") or "").lower()
            if not oid:
                continue
            if st not in ("pending", "open", "received", "accepted"):
                results.append({"id": oid, "skipped": True, "status": st})
                continue
            try:
                r = await t.cancel_order(cfg.tradier_account_id, str(oid))
                results.append({"id": oid, "canceled": True, "resp": r})
            except Exception as e:
                results.append({"id": oid, "error": type(e).__name__, "detail": str(e)})
        return {"ok": True, "results": results}
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


@app.post("/api/v1/positions/flatten")
async def flatten(symbol: str | None = None):
    cfg = settings()
    if not cfg.tradier_account_id:
        return {"ok": False, "error": "TRADIER_ACCOUNT_ID is not set"}
    snap = await riskmod.portfolio_snapshot()
    positions = snap.get("positions") or []
    if isinstance(positions, dict):
        positions = [positions]
    targets = [p for p in positions if float(p.get("quantity") or 0) != 0]
    if symbol:
        s = symbol.upper()
        targets = [p for p in targets if (p.get("symbol") or "").upper() == s]
    results = []
    for p in targets:
        sym = (p.get("symbol") or "").upper()
        qty = int(abs(float(p.get("quantity") or 0)))
        side = "sell" if float(p.get("quantity") or 0) > 0 else "buy_to_cover"
        if cfg.dry_run:
            results.append({"symbol": sym, "qty": qty, "side": side, "dry_run": True})
            continue
        try:
            resp = await t.place_equity_order(cfg.tradier_account_id, sym, side, qty, order_type="market", duration="day")
            results.append({"symbol": sym, "qty": qty, "side": side, "resp": resp})
        except Exception as e:
            results.append({"symbol": sym, "error": type(e).__name__, "detail": str(e)})
    return {"ok": True, "actions": results}


@app.get("/api/v1/signals")
async def signals_preview():
    try:
        sigs = await strat.ema_crossover_signals()
    except Exception as e:
        return {"ok": True, "signals": [], "provider_error": f"{type(e).__name__}: {e}"}
    out = []
    for s in sigs:
        ok, reasons = await riskmod.evaluate(s)
        out.append({"signal": s, "pass": ok, "reasons": reasons})
    return {"ok": True, "signals": out}


@app.get("/api/v1/bracket/preview")
async def bracket_preview(symbol: str, qty: int = 1, stop_pct: float | None = None, tp_pct: float | None = None):
    cfg = settings()
    stop_p = stop_pct if stop_pct is not None else cfg.stop_pct
    tp_p = tp_pct if tp_pct is not None else cfg.tp_pct
    if stop_p is None or tp_p is None:
        return {"ok": False, "error": "Missing stop_pct or tp_pct (or STOP_PCT/TP_PCT not set)"}
    try:
        lt = await strat.poly.last_trade(symbol)
        price = float(lt.get("price") or 0)
        if not price:
            return {"ok": False, "error": "No price"}
        stop = round(price * (1 - float(stop_p)), 2)
        tp = round(price * (1 + float(tp_p)), 2)
        notional = round(price * qty, 2)
        sig = {"symbol": symbol.upper(), "side": "buy", "qty": qty, "type": "market"}
        ok, reasons = await riskmod.evaluate(sig)
        return {"ok": True, "price": price, "qty": qty, "notional": notional, "stop": stop, "take_profit": tp, "risk_pass": ok, "risk_reasons": reasons}
    except Exception as e:
        return {"ok": False, "error": type(e).__name__, "detail": str(e)}
