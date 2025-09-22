from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple

from .. import ledger

_SIGNAL_KINDS = {
    "signal_generated": "generated",
    "signal_blocked": "risk_blocked",
    "signal_approved": "approved",
}


@dataclass
class SignalEvent:
    ts: float
    setup: str
    symbol: str
    outcome: str


def _extract_signal_events(limit: int) -> Iterable[SignalEvent]:
    for raw in ledger.read_events(limit=limit):
        kind = raw.get("kind")
        if kind not in _SIGNAL_KINDS:
            continue
        data = raw.get("data") or {
            k: v for k, v in raw.items() if k not in {"ts", "kind"}
        }
        setup = (data.get("setup") or data.get("signal", {}).get("setup") or "UNKNOWN").upper()
        symbol = (data.get("symbol") or data.get("signal", {}).get("symbol") or "").upper()
        if not symbol:
            continue
        yield SignalEvent(
            ts=float(raw.get("ts") or 0.0),
            setup=setup,
            symbol=symbol,
            outcome=_SIGNAL_KINDS[kind],
        )


def summarize_signals(limit: int = 5_000) -> Dict[str, object]:
    """Summarize recent signal events from the ledger for quick tuning.

    Returns a dict with per-setup counts, approval rates, and a timeline
    that can be fed into notebooks or dashboards.
    """
    per_setup: Dict[str, Counter] = defaultdict(Counter)
    timeline: List[SignalEvent] = []

    for ev in _extract_signal_events(limit):
        per_setup[ev.setup][ev.outcome] += 1
        timeline.append(ev)

    summary = {}
    for setup, counter in per_setup.items():
        generated = counter.get("generated", 0)
        approved = counter.get("approved", 0)
        approval_rate = approved / generated if generated else 0.0
        summary[setup] = {
            "counts": dict(counter),
            "approval_rate": approval_rate,
        }

    timeline.sort(key=lambda e: e.ts)
    timeline_payload = [
        {"ts": ev.ts, "setup": ev.setup, "symbol": ev.symbol, "outcome": ev.outcome}
        for ev in timeline
    ]

    return {
        "per_setup": summary,
        "timeline": timeline_payload,
    }
