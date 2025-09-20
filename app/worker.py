from __future__ import annotations
import asyncio, time
from typing import Dict, Any

from .config import settings
from .providers import tradier as t
from .providers import polygon as p
from .engine import strategy


async def scan_once(cfg) -> None:
    ctx: Dict[str, Any] = {
        "ts": time.time(),
    }
    signals = await strategy.simple_signal(ctx)
    if not signals:
        print("[worker] no signals")
        return
    for sig in signals:
        print(f"[worker] signal: {sig}")
        if cfg.dry_run:
            print("[worker] DRY_RUN=1 — not sending order")
            continue
        if not cfg.tradier_account_id:
            print("[worker] missing TRADIER_ACCOUNT_ID — skipping order")
            continue
        try:
            resp = await t.place_equity_order(
                account_id=cfg.tradier_account_id,
                symbol=sig["symbol"],
                side=sig.get("side", "buy"),
                qty=int(sig.get("qty", 1)),
                order_type=sig.get("type", "market"),
                duration=sig.get("duration", "day"),
                price=sig.get("price"),
                stop=sig.get("stop"),
            )
            print("[worker] order response:", resp)
        except Exception as e:
            print("[worker] order error:", type(e).__name__, str(e))


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

