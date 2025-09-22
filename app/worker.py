from __future__ import annotations
import asyncio, time
from typing import Any, Dict, Optional

from .config import settings, symbol_overrides
from .providers import tradier as t
from .providers.tradier import TradierHTTPError
from .state import load_high_water, load_trade_state, save_high_water, save_trade_state
from . import ledger
from .metrics import autotrader_signal_total
from .engine import strategy
from .engine import risk

from dataclasses import dataclass

_HIGH_WATER: Dict[str, float] = {}
_ACTIVE_TRADES: Dict[str, Dict[str, Any]] = {}


@dataclass
class OrderPlan:
    qty: int
    entry_price: Optional[float]
    stop_price: Optional[float]
    target1: Optional[float]
    target2: Optional[float]
    metadata: Dict[str, Any]


def compute_order_plan(sig: Dict[str, Any], cfg) -> OrderPlan:
    symbol = (sig.get("symbol") or "").upper()
    metadata = sig.get("metadata") or {}
    entry_price = _as_float(metadata.get("entry_price"))
    stop_price = _as_float(metadata.get("stop_price"))
    target1 = _as_float(metadata.get("target1"))
    target2 = _as_float(metadata.get("target2"))
    atr = _as_float(metadata.get("atr"))

    base_qty = int(sig.get("qty") or cfg.default_qty)
    overrides = symbol_overrides(symbol)

    qty_override = overrides.get("qty")
    stop_pct_override = overrides.get("stop_pct", cfg.stop_pct)
    tp_pct_override = overrides.get("tp_pct", cfg.tp_pct)

    if entry_price is None:
        entry_price = _as_float(sig.get("price"))

    if stop_price is None and entry_price is not None:
        if stop_pct_override is not None:
            stop_price = entry_price * (1 - float(stop_pct_override))
        elif atr is not None:
            stop_price = entry_price - cfg.risk_stop_atr_multiplier * atr

    if target1 is None and entry_price is not None:
        if tp_pct_override is not None:
            target1 = entry_price * (1 + float(tp_pct_override))
        elif atr is not None:
            target1 = entry_price + cfg.target_one_atr_multiplier * atr

    if target2 is None and entry_price is not None:
        if atr is not None:
            target2 = entry_price + cfg.target_two_atr_multiplier * atr
        else:
            target2 = target1

    qty = int(qty_override) if qty_override is not None else base_qty
    qty = max(1, qty)

    if (
        cfg.risk_per_trade_usd
        and entry_price is not None
        and stop_price is not None
        and entry_price > stop_price
    ):
        stop_distance = entry_price - stop_price
        if stop_distance > 0:
            risk_qty = int(cfg.risk_per_trade_usd / stop_distance)
            qty = max(1, risk_qty)

    return OrderPlan(
        qty=qty,
        entry_price=entry_price,
        stop_price=stop_price,
        target1=target1,
        target2=target2,
        metadata=metadata,
    )


def register_trade(sig: Dict[str, Any], plan: OrderPlan, cfg, dry_run: bool) -> None:
    symbol = (sig.get("symbol") or "").upper()
    if not symbol or plan.entry_price is None:
        return
    state = _ACTIVE_TRADES.get(symbol, {}).copy()
    state.update(
        {
            "entry_price": plan.entry_price,
            "stop_price": plan.stop_price,
            "target1": plan.target1,
            "target2": plan.target2,
            "qty": plan.qty,
            "partial_exited": state.get("partial_exited", False),
            "entry_ts": time.time(),
        }
    )
    _ACTIVE_TRADES[symbol] = state
    save_trade_state(_ACTIVE_TRADES)


def cleanup_trade(symbol: str) -> None:
    symbol = symbol.upper()
    if symbol in _ACTIVE_TRADES:
        _ACTIVE_TRADES.pop(symbol, None)
        save_trade_state(_ACTIVE_TRADES)


def _as_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        f = float(value)
        if not (f == f):  # NaN check
            return None
        return f
    except (TypeError, ValueError):
        return None


async def _get_price(symbol: str, cache: Optional[Dict[str, float]] = None) -> Optional[float]:
    symbol = symbol.upper()
    if cache and symbol in cache:
        return cache[symbol]
    price = None
    try:
        price = await t.last_trade_price(symbol)
    except TradierHTTPError:
        price = None
    if not price:
        try:
            q = await t.get_quote(symbol)
            qq = (q.get("quotes") or {}).get("quote")
            if isinstance(qq, list):
                qq = qq[0] if qq else {}
            price = float((qq or {}).get("last") or 0) or None
        except Exception:
            price = None
    if price and cache is not None:
        cache[symbol] = price
    return price


async def _execute_exit_order(cfg, symbol: str, qty: int, reason: str, dry_run: bool):
    if qty <= 0:
        return None
    if dry_run:
        print(f"[worker] EXIT DRY_RUN {reason} {qty} {symbol}")
        ledger.event("order_exit", data={"symbol": symbol, "qty": qty, "reason": reason, "dry_run": True})
        return None
    resp = await t.place_equity_order(
        account_id=cfg.tradier_account_id,
        symbol=symbol,
        side="sell",
        qty=qty,
        order_type="market",
        duration="day",
    )
    print(f"[worker] EXIT ({reason}) order response:", resp)
    ledger.event("order_exit", data={"symbol": symbol, "qty": qty, "reason": reason, "resp": resp})
    return resp


async def scan_once(cfg) -> None:
    signals = await strategy.ema_crossover_signals()
    if not signals:
        print("[worker] no signals")
    for sig in signals:
        setup = (sig.get("setup") or "UNKNOWN").upper()
        ledger.event("signal_generated", data={"setup": setup, "symbol": sig.get("symbol"), "signal": sig})
        autotrader_signal_total.labels(setup=setup, outcome="generated").inc()
        plan = compute_order_plan(sig, cfg)
        risk_check_payload = {**sig, "qty": plan.qty}
        ok, reasons = await risk.evaluate(risk_check_payload)
        if not ok:
            print(f"[worker] blocked by risk: {sig['symbol']} — {', '.join(reasons)}")
            ledger.event("signal_blocked", data={"setup": setup, "symbol": sig.get("symbol"), "reasons": reasons})
            autotrader_signal_total.labels(setup=setup, outcome="risk_blocked").inc()
            continue
        print(f"[worker] PASS risk: {sig}")
        ledger.event("signal_approved", data={"setup": setup, "symbol": sig.get("symbol"), "signal": sig})
        autotrader_signal_total.labels(setup=setup, outcome="approved").inc()
        if cfg.dry_run:
            print("[worker] DRY_RUN=1 — not sending order")
            autotrader_signal_total.labels(setup=setup, outcome="dry_run").inc()
            register_trade(sig, plan, cfg, dry_run=True)
            continue
        if not cfg.tradier_account_id:
            print("[worker] missing TRADIER_ACCOUNT_ID — skipping order")
            continue
        try:
            advanced = None
            stop = plan.stop_price
            take_profit = plan.target2
            entry_price = plan.entry_price or await _get_price(sig["symbol"])
            plan.entry_price = entry_price
            if stop and take_profit:
                advanced = "otoco"

            resp = await t.place_equity_order(
                account_id=cfg.tradier_account_id,
                symbol=sig["symbol"],
                side=sig.get("side", "buy"),
                qty=plan.qty,
                order_type=sig.get("type", "market"),
                duration=sig.get("duration", "day"),
                price=entry_price,
                stop=stop,
                advanced=advanced,
                take_profit=take_profit,
            )
            print("[worker] order response:", resp)
            autotrader_signal_total.labels(setup=setup, outcome="submitted").inc()
            try:
                oid = (resp.get("order") or {}).get("id")
                ledger.event(
                    "order_placed",
                    data={
                        "id": oid,
                        "symbol": sig["symbol"],
                        "side": sig.get("side", "buy"),
                        "qty": plan.qty,
                        "advanced": advanced,
                        "stop": stop,
                        "tp": take_profit,
                        "entry": entry_price,
                    },
                )
            except Exception:
                pass
            register_trade(sig, plan, cfg, dry_run=False)
        except Exception as e:
            print("[worker] order error:", type(e).__name__, str(e))


async def partial_exit_pass(cfg) -> None:
    if not _ACTIVE_TRADES:
        return
    snapshot = await risk.portfolio_snapshot()
    positions = snapshot.get("positions") or []
    position_qty = {str(p.get("symbol") or "").upper(): float(p.get("quantity") or 0) for p in positions}
    price_cache: Dict[str, float] = {}
    now = time.time()

    for sym, state in list(_ACTIVE_TRADES.items()):
        sym_up = sym.upper()
        orig_qty = int(state.get("qty") or 0)
        pos_qty = position_qty.get(sym_up, 0.0)
        if pos_qty <= 0 and not cfg.dry_run:
            cleanup_trade(sym_up)
            continue
        price = await _get_price(sym_up, price_cache)
        if price is None:
            continue

        target1 = _as_float(state.get("target1"))
        target2 = _as_float(state.get("target2"))
        entry_ts = float(state.get("entry_ts") or now)
        partial_done = bool(state.get("partial_exited"))

        if not partial_done and target1 is not None and price >= target1:
            qty_to_sell = max(1, int(max(orig_qty, pos_qty) * float(cfg.partial_exit_pct)))
            qty_to_sell = min(int(pos_qty if not cfg.dry_run else orig_qty), qty_to_sell)
            await _execute_exit_order(cfg, sym_up, qty_to_sell, reason="partial_target", dry_run=cfg.dry_run)
            state["partial_exited"] = True
            entry_price = _as_float(state.get("entry_price"))
            if entry_price is not None:
                state["stop_price"] = max(_as_float(state.get("stop_price")) or 0.0, entry_price)
            save_trade_state(_ACTIVE_TRADES)

        if target2 is not None and price >= target2:
            qty_to_sell = int(pos_qty if not cfg.dry_run else orig_qty)
            await _execute_exit_order(cfg, sym_up, qty_to_sell, reason="final_target", dry_run=cfg.dry_run)
            cleanup_trade(sym_up)
            continue

        timeout_min = cfg.trade_timeout_min or 0
        if timeout_min > 0 and now - entry_ts > timeout_min * 60:
            qty_to_sell = int(pos_qty if not cfg.dry_run else orig_qty)
            await _execute_exit_order(cfg, sym_up, qty_to_sell, reason="timeout_exit", dry_run=cfg.dry_run)
            cleanup_trade(sym_up)


async def ema_exit_pass(cfg) -> None:
    snapshot = await risk.portfolio_snapshot()
    tracked_syms = {s.strip().upper() for s in cfg.symbols.split(",") if s.strip()}
    for ppos in (snapshot.get("positions") or []):
        qty = int(float(ppos.get("quantity") or 0))
        if qty <= 0:
            continue
        sym = (ppos.get("symbol") or "").upper()
        if tracked_syms and sym not in tracked_syms:
            continue
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
            await _execute_exit_order(cfg, sym, qty, reason="ema_cross_down", dry_run=cfg.dry_run)
            cleanup_trade(sym)

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
        price = await _get_price(sym)
        if price is None:
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
                cleanup_trade(sym)
                continue
            try:
                await _execute_exit_order(cfg, sym, qty, reason="trailing_exit", dry_run=cfg.dry_run)
                _HIGH_WATER.pop(sym, None)
                cleanup_trade(sym)
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
    try:
        trades = load_trade_state()
        if trades:
            _ACTIVE_TRADES.update(trades)
            print(f"[worker] restored {len(_ACTIVE_TRADES)} tracked trades")
    except Exception as e:
        print("[worker] trade-state load error:", type(e).__name__, str(e))
    while True:
        try:
            await scan_once(cfg)
            await partial_exit_pass(cfg)
            await ema_exit_pass(cfg)
            await trailing_exit_pass(cfg)
        except Exception as e:
            print("[worker] scan error:", type(e).__name__, str(e))
        await asyncio.sleep(max(5, int(cfg.scan_interval_sec)))


if __name__ == "__main__":
    asyncio.run(main())
