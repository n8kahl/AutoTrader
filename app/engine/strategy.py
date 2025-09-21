from __future__ import annotations
from typing import Dict, Any, List, Tuple

from .plays import generate_signals as _generate_state_signals


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
    """Compatibility shim returning the new strategy engine outputs."""

    return await _generate_state_signals()
