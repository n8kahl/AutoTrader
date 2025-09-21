from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
import os

from .config import settings
from .config import symbol_overrides
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


@app.get("/api/v1/config/effective")
async def config_effective(symbol: str | None = None):
    cfg = settings()
    base = {
        "default_qty": cfg.default_qty,
        "stop_pct": cfg.stop_pct,
        "tp_pct": cfg.tp_pct,
        "trail_pct": cfg.trail_pct,
        "trail_activation_pct": cfg.trail_activation_pct,
        "strategy_interval": cfg.strategy_interval,
        "lookback_min": cfg.lookback_min,
        "lookback_days": cfg.lookback_days,
        "risk_max_concurrent": cfg.risk_max_concurrent,
        "risk_max_open_orders": cfg.risk_max_open_orders,
    }
    if symbol:
        ov = symbol_overrides(symbol)
        eff = base.copy()
        eff.update({k: v for k, v in ov.items() if v is not None})
        return {"ok": True, "symbol": symbol.upper(), "effective": eff, "overrides": ov}
    return {"ok": True, "effective": base}


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
async def bracket_preview(symbol: str, qty: int = 1, stop_pct: float | None = None, tp_pct: float | None = None, price: float | None = None):
    cfg = settings()
    ov = symbol_overrides(symbol)
    qty = int(ov.get("qty", qty))
    stop_p = stop_pct if stop_pct is not None else ov.get("stop_pct", cfg.stop_pct)
    tp_p = tp_pct if tp_pct is not None else ov.get("tp_pct", cfg.tp_pct)
    if stop_p is None or tp_p is None:
        return {"ok": False, "error": "Missing stop_pct or tp_pct (or STOP_PCT/TP_PCT not set)"}
    # Resolve price: explicit param > Polygon snapshot > Tradier quote > error
    try:
        px = None
        if price is not None and float(price) > 0:
            px = float(price)
        else:
            try:
                lt = await strat.poly.last_trade(symbol)
                px = float(lt.get("price") or 0) or None
            except Exception:
                px = None
            if not px:
                try:
                    q = await t.get_quote(symbol)
                    qq = (q.get("quotes") or {}).get("quote")
                    if isinstance(qq, list):
                        qq = qq[0] if qq else {}
                    px = float((qq or {}).get("last") or 0) or None
                except Exception:
                    px = None
        if not px:
            return {"ok": False, "error": "No price available (Polygon/Tradier denied or empty). Optionally pass ?price=..."}
        stop = round(px * (1 - float(stop_p)), 2)
        tp = round(px * (1 + float(tp_p)), 2)
        notional = round(px * qty, 2)
        sig = {"symbol": symbol.upper(), "side": "buy", "qty": qty, "type": "market"}
        ok, reasons = await riskmod.evaluate(sig)
        return {"ok": True, "price": px, "qty": qty, "notional": notional, "stop": stop, "take_profit": tp, "risk_pass": ok, "risk_reasons": reasons}
    except Exception as e:
        return {"ok": False, "error": type(e).__name__, "detail": str(e)}


@app.post("/api/v1/bracket/place")
async def bracket_place(body: dict):
    cfg = settings()
    sym = (body.get("symbol") or "").upper()
    ov = symbol_overrides(sym)
    qty = int(body.get("qty") or ov.get("qty") or cfg.default_qty)
    stop_pct = body.get("stop_pct")
    tp_pct = body.get("tp_pct")
    price = body.get("price")  # optional price reference for stop/tp calc; also used for limit
    order_type = (body.get("type") or "market").lower()  # market|limit
    duration = body.get("duration") or "day"
    force = bool(body.get("force") or False)
    if not sym:
        return {"ok": False, "error": "symbol is required"}
    # Resolve pct from env if not provided
    sp = float(stop_pct) if stop_pct is not None else (ov.get("stop_pct") if ov.get("stop_pct") is not None else (cfg.stop_pct if cfg.stop_pct is not None else None))
    tp = float(tp_pct) if tp_pct is not None else (ov.get("tp_pct") if ov.get("tp_pct") is not None else (cfg.tp_pct if cfg.tp_pct is not None else None))
    if sp is None or tp is None:
        return {"ok": False, "error": "Missing stop_pct/tp_pct or STOP_PCT/TP_PCT not set"}

    # Price reference (for bracket calc)
    px = None
    if price is not None:
        try:
            px = float(price)
        except Exception:
            px = None
    if not px:
        try:
            lt = await strat.poly.last_trade(sym)
            px = float(lt.get("price") or 0) or None
        except Exception:
            px = None
    if not px:
        try:
            q = await t.get_quote(sym)
            qq = (q.get("quotes") or {}).get("quote")
            if isinstance(qq, list):
                qq = qq[0] if qq else {}
            px = float((qq or {}).get("last") or 0) or None
        except Exception:
            px = None
    if not px:
        return {"ok": False, "error": "No price available (Polygon/Tradier denied or empty). Provide body.price if needed."}

    stop = round(px * (1 - float(sp)), 2)
    take_profit = round(px * (1 + float(tp)), 2)

    sig = {"symbol": sym, "side": "buy", "qty": qty, "type": order_type}
    ok, reasons = await riskmod.evaluate(sig)
    if not ok and not force:
        return {"ok": False, "blocked": True, "reasons": reasons}

    if cfg.dry_run:
        out = {"symbol": sym, "qty": qty, "type": order_type, "duration": duration, "stop": stop, "take_profit": take_profit}
        if order_type == "limit":
            out["price"] = px
        return {"ok": True, "dry_run": True, "would_send": out}

    try:
        resp = await t.place_equity_order(
            account_id=cfg.tradier_account_id,
            symbol=sym,
            side="buy",
            qty=qty,
            order_type=order_type,
            duration=duration,
            price=(px if order_type == "limit" else None),
            stop=stop,
            advanced="otoco",
            take_profit=take_profit,
        )
        return {"ok": True, "dry_run": False, "resp": resp}
    except Exception as e:
        return {"ok": False, "error": type(e).__name__, "detail": str(e)}
