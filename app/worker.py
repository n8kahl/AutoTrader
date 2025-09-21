from __future__ import annotations
import asyncio, time
from typing import Dict, Any

from .config import settings, symbol_overrides
from .providers import tradier as t
from .providers.tradier import TradierHTTPError
from .state import load_high_water, save_high_water
from . import ledger
from .engine import strategy
from .engine import risk


async def scan_once(cfg) -> None:
    signals = await strategy.ema_crossover_signals()
    if not signals:
        print("[worker] no signals")
    for sig in signals:
        ok, reasons = await risk.evaluate(sig)
        if not ok:
            print(f"[worker] blocked by risk: {sig['symbol']} — {', '.join(reasons)}")
            continue
        print(f"[worker] PASS risk: {sig}")
        if cfg.dry_run:
            print("[worker] DRY_RUN=1 — not sending order")
            continue
        if not cfg.tradier_account_id:
            print("[worker] missing TRADIER_ACCOUNT_ID — skipping order")
            continue
        try:
            advanced = None
            stop = sig.get("stop")
            take_profit = None
            price_for_bracket = None
            # Apply bracket if configured and this is a buy
            ov = symbol_overrides(sig["symbol"])
            qty = int(ov.get("qty", sig.get("qty", 1)))
            sp = ov.get("stop_pct", cfg.stop_pct)
            tp = ov.get("tp_pct", cfg.tp_pct)
            if sig.get("side", "buy") == "buy" and sp and tp:
                try:
                    price_for_bracket = await t.last_trade_price(sig["symbol"])  # delayed last price
                except TradierHTTPError:
                    price_for_bracket = None
                if price_for_bracket and price_for_bracket > 0:
                    advanced = "otoco"
                    stop = round(price_for_bracket * (1 - float(sp)), 2)
                    take_profit = round(price_for_bracket * (1 + float(tp)), 2)

            resp = await t.place_equity_order(
                account_id=cfg.tradier_account_id,
                symbol=sig["symbol"],
                side=sig.get("side", "buy"),
                qty=qty,
                order_type=sig.get("type", "market"),
                duration=sig.get("duration", "day"),
                price=sig.get("price"),
                stop=stop,
                advanced=advanced,
                take_profit=take_profit,
            )
            print("[worker] order response:", resp)
            try:
                oid = (resp.get("order") or {}).get("id")
                ledger.event("order_placed", data={"id": oid, "symbol": sig["symbol"], "side": sig.get("side", "buy"), "qty": qty, "advanced": advanced, "stop": stop, "tp": take_profit})
            except Exception:
                pass
        except Exception as e:
            print("[worker] order error:", type(e).__name__, str(e))

    # Exit logic (always allowed even outside window)
    try:
        snap = await risk.portfolio_snapshot()
        open_pos = [p for p in (snap.get("positions") or []) if float(p.get("quantity") or 0) > 0]
        tracked_syms = {s.strip().upper() for s in cfg.symbols.split(",") if s.strip()}
        for ppos in open_pos:
            sym = (ppos.get("symbol") or "").upper()
            if tracked_syms and sym not in tracked_syms:
                print(f"[worker] EXIT skip unmanaged symbol {sym}")
                continue
            # Compute EMA cross-down
            try:
                bars = await t.minute_bars(sym, minutes=180)
            except TradierHTTPError as exc:
                print(f"[worker] EXIT Tradier error fetching bars for {sym}: {exc}")
                continue
            closes = [float(b.get("c") or 0) for b in bars]
            if len(closes) < 60:
                continue
            e20 = strategy.ema(closes, 20)
            e50 = strategy.ema(closes, 50)
            diff_prev = e20[-2] - e50[-2]
            diff_now = e20[-1] - e50[-1]
            if diff_prev >= 0 and diff_now < 0 and closes[-1] < e50[-1]:
                qty = int(float(ppos.get("quantity") or 0))
                if qty <= 0:
                    continue
                if cfg.dry_run:
                    print(f"[worker] EXIT DRY_RUN sell {qty} {sym} — EMA20 cross down")
                    continue
                try:
                    resp = await t.place_equity_order(
                        account_id=cfg.tradier_account_id,
                        symbol=sym,
                        side="sell",
                        qty=qty,
                        order_type="market",
                        duration="day",
                    )
                    print("[worker] EXIT order response:", resp)
                    try:
                        oid = (resp.get("order") or {}).get("id")
                        ledger.event("order_placed", data={"id": oid, "symbol": sym, "side": "sell", "qty": qty, "reason": "ema_cross_down"})
                    except Exception:
                        pass
                except Exception as e:
                    print("[worker] EXIT order error:", type(e).__name__, str(e))
    except Exception as e:
        print("[worker] exit-scan error:", type(e).__name__, str(e))


# Simple in-memory trailing state (resets on restart)
_HIGH_WATER: dict[str, float] = {}


async def trailing_exit_pass(cfg) -> None:
    if not (cfg.trail_pct and cfg.trail_pct > 0):
        return
    snap = await risk.portfolio_snapshot()
    open_pos = [p for p in (snap.get("positions") or []) if float(p.get("quantity") or 0) > 0]
    for ppos in open_pos:
        sym = (ppos.get("symbol") or "").upper()
        qty = int(float(ppos.get("quantity") or 0))
        if qty <= 0:
            continue
        # Resolve price from Tradier (delayed when using paper accounts)
        price = None
        try:
            price = await t.last_trade_price(sym)
        except TradierHTTPError:
            price = None
        if not price:
            try:
                q = await t.get_quote(sym)
                qq = (q.get("quotes") or {}).get("quote")
                if isinstance(qq, list):
                    qq = qq[0] if qq else {}
                price = float((qq or {}).get("last") or 0) or None
            except Exception:
                price = None
        if not price:
            continue

        # Update high watermark
        hi = _HIGH_WATER.get(sym, price)
        if price > hi:
            hi = price
            _HIGH_WATER[sym] = hi
            try:
                save_high_water(_HIGH_WATER)
            except Exception:
                pass

        # Optional activation threshold based on cost_basis
        activate = True
        if cfg.trail_activation_pct is not None:
            try:
                cb = float(ppos.get("cost_basis") or 0) or None
            except Exception:
                cb = None
            if cb:
                activate = hi >= cb * (1 + float(cfg.trail_activation_pct))

        if not activate:
            continue

        trigger = hi * (1 - float(cfg.trail_pct))
        if price <= trigger:
            if cfg.dry_run:
                print(f"[worker] EXIT DRY_RUN trail {qty} {sym} @ {price:.2f} (hi {hi:.2f}, trigger {trigger:.2f})")
                _HIGH_WATER.pop(sym, None)
                continue
            try:
                resp = await t.place_equity_order(
                    account_id=cfg.tradier_account_id,
                    symbol=sym,
                    side="sell",
                    qty=qty,
                    order_type="market",
                    duration="day",
                )
                print("[worker] EXIT (trailing) order response:", resp)
                _HIGH_WATER.pop(sym, None)
                try:
                    save_high_water(_HIGH_WATER)
                except Exception:
                    pass
            except Exception as e:
                print("[worker] EXIT (trailing) order error:", type(e).__name__, str(e))


async def main() -> None:
    cfg = settings()
    print("[worker] started, interval:", cfg.scan_interval_sec)
    # load trailing state
    try:
        _loaded = load_high_water()
        if _loaded:
            _HIGH_WATER.update(_loaded)
            print(f"[worker] loaded high_water for {len(_HIGH_WATER)} symbols")
    except Exception as e:
        print("[worker] load state error:", type(e).__name__, str(e))
    while True:
        try:
            await scan_once(cfg)
            await trailing_exit_pass(cfg)
        except Exception as e:
            print("[worker] scan error:", type(e).__name__, str(e))
        await asyncio.sleep(max(5, int(cfg.scan_interval_sec)))


if __name__ == "__main__":
    asyncio.run(main())
