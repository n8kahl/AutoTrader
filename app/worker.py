from __future__ import annotations
import asyncio, time
from typing import Dict, Any

from .config import settings
from .providers import tradier as t
from .providers import polygon as poly
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
            if sig.get("side", "buy") == "buy" and cfg.stop_pct and cfg.tp_pct:
                try:
                    lt = await poly.last_trade(sig["symbol"])  # last price as base
                    price_for_bracket = float(lt.get("price") or 0)
                except Exception:
                    price_for_bracket = None
                if price_for_bracket and price_for_bracket > 0:
                    advanced = "otoco"
                    stop = round(price_for_bracket * (1 - float(cfg.stop_pct)), 2)
                    take_profit = round(price_for_bracket * (1 + float(cfg.tp_pct)), 2)

            resp = await t.place_equity_order(
                account_id=cfg.tradier_account_id,
                symbol=sig["symbol"],
                side=sig.get("side", "buy"),
                qty=int(sig.get("qty", 1)),
                order_type=sig.get("type", "market"),
                duration=sig.get("duration", "day"),
                price=sig.get("price"),
                stop=stop,
                advanced=advanced,
                take_profit=take_profit,
            )
            print("[worker] order response:", resp)
        except Exception as e:
            print("[worker] order error:", type(e).__name__, str(e))

    # Exit logic (always allowed even outside window)
    try:
        snap = await risk.portfolio_snapshot()
        open_pos = [p for p in (snap.get("positions") or []) if float(p.get("quantity") or 0) > 0]
        for ppos in open_pos:
            sym = (ppos.get("symbol") or "").upper()
            # Compute EMA cross-down
            bars = await poly.minute_bars(sym, minutes=180)
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
                except Exception as e:
                    print("[worker] EXIT order error:", type(e).__name__, str(e))
    except Exception as e:
        print("[worker] exit-scan error:", type(e).__name__, str(e))


async def main() -> None:
    cfg = settings()
    print("[worker] started, interval:", cfg.scan_interval_sec)
    while True:
        try:
            await scan_once(cfg)
        except Exception as e:
            print("[worker] scan error:", type(e).__name__, str(e))
        await asyncio.sleep(max(5, int(cfg.scan_interval_sec)))


if __name__ == "__main__":
    asyncio.run(main())
