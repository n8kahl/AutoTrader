from __future__ import annotations
from typing import Dict, Any, List, Tuple

from ..config import settings
from ..providers import polygon as poly


def ema(series: List[float], period: int) -> List[float]:
    if not series:
        return []
    k = 2 / (period + 1)
    out: List[float] = []
    ema_prev = series[0]
    for x in series:
        ema_prev = x * k + ema_prev * (1 - k)
        out.append(ema_prev)
    return out


async def ema_crossover_signals() -> List[Dict[str, Any]]:
    """Very simple EMA20/EMA50 cross strategy on 1m bars.
    - Buy when EMA20 crosses above EMA50 and price above EMA50.
    - Sell when EMA20 crosses below EMA50 and price below EMA50. (not used yet)
    Returns market order signals with qty from settings.
    """
    cfg = settings()
    syms = [s.strip().upper() for s in cfg.symbols.split(",") if s.strip()]
    out: List[Dict[str, Any]] = []
    for s in syms:
        bars = await poly.minute_bars(s, minutes=180)
        closes = [float(b.get("c") or 0) for b in bars]
        if len(closes) < 60:
            continue
        e20 = ema(closes, 20)
        e50 = ema(closes, 50)
        p = closes[-1]
        # Cross up detection: previous diff <=0 and current diff >0
        diff_prev = e20[-2] - e50[-2]
        diff_now = e20[-1] - e50[-1]
        if diff_prev <= 0 and diff_now > 0 and p > e50[-1]:
            out.append({
                "symbol": s,
                "side": "buy",
                "qty": cfg.default_qty,
                "type": "market",
            })
        # For now we don't auto-exit; add short/exit logic later
    return out

