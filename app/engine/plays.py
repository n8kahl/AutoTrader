from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..config import settings
from ..session import SessionPolicy, load_session_config
from .features import FeatureSnapshot, FeatureEngine


@dataclass
class StrategySignal:
    symbol: str
    setup: str
    side: str
    qty: int
    order_type: str = "market"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_order(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "qty": self.qty,
            "type": self.order_type,
            **self.metadata,
        }


@dataclass
class StrategyContext:
    """Keeps minimal per-symbol state shared across plays."""

    last_signal_ts: Dict[str, float] = field(default_factory=dict)


class Play:
    name: str
    side: Optional[str] = None

    def allowed_in(self, session: Optional[SessionPolicy]) -> bool:
        if session is None:
            return True
        return session.allows_setup(self.name)

    def evaluate(self, snapshot: FeatureSnapshot, session: Optional[SessionPolicy], ctx: StrategyContext) -> List[StrategySignal]:
        raise NotImplementedError


class LegacyEmaCrossoverPlay(Play):
    name = "EMA_CROSS"

    def evaluate(self, snapshot: FeatureSnapshot, session: Optional[SessionPolicy], ctx: StrategyContext) -> List[StrategySignal]:
        if snapshot.ema20 is None or snapshot.ema50 is None:
            return []
        if snapshot.ema20_prev is None or snapshot.ema50_prev is None:
            return []
        diff_prev = snapshot.ema20_prev - snapshot.ema50_prev
        diff_now = snapshot.ema20 - snapshot.ema50
        if diff_prev <= 0 < diff_now and snapshot.last_price and snapshot.last_price > snapshot.ema50:
            cfg = settings()
            return [
                StrategySignal(
                    symbol=snapshot.symbol,
                    setup=self.name,
                    side="buy",
                    qty=cfg.default_qty,
                    metadata={"reason": "ema20_cross_up"},
                )
            ]
        return []


class VWAPReclaimPlay(Play):
    name = "VWAP_RECLAIM"

    def evaluate(self, snapshot: FeatureSnapshot, session: Optional[SessionPolicy], ctx: StrategyContext) -> List[StrategySignal]:
        # Full logic will compare VWAP reclaim patterns; placeholder only.
        return []


class SigmaFadePlay(Play):
    name = "SIGMA_FADE"

    def evaluate(self, snapshot: FeatureSnapshot, session: Optional[SessionPolicy], ctx: StrategyContext) -> List[StrategySignal]:
        # Placeholder for ±1σ reversal logic.
        return []


class HodFailurePlay(Play):
    name = "HOD_FAIL"

    def evaluate(self, snapshot: FeatureSnapshot, session: Optional[SessionPolicy], ctx: StrategyContext) -> List[StrategySignal]:
        # Placeholder for HOD/LOD breakout failure logic.
        return []


class StrategyEngine:
    def __init__(self, feature_engine: Optional[FeatureEngine] = None, plays: Optional[List[Play]] = None) -> None:
        self.feature_engine = feature_engine or FeatureEngine()
        self.plays = plays or [
            VWAPReclaimPlay(),
            SigmaFadePlay(),
            HodFailurePlay(),
            LegacyEmaCrossoverPlay(),
        ]
        self.ctx = StrategyContext()

    async def generate_signals(self) -> List[Dict[str, Any]]:
        cfg = settings()
        syms = [s.strip().upper() for s in cfg.symbols.split(",") if s.strip()]
        if not syms:
            return []

        try:
            session_cfg = load_session_config()
            current_session = session_cfg.current()
        except Exception:
            current_session = None

        out: List[Dict[str, Any]] = []
        for sym in syms:
            snapshot = await self.feature_engine.snapshot(sym)
            for play in self.plays:
                if not play.allowed_in(current_session):
                    continue
                for sig in play.evaluate(snapshot, current_session, self.ctx):
                    out.append(sig.to_order())
        return out


_engine: Optional[StrategyEngine] = None


def get_engine() -> StrategyEngine:
    global _engine
    if _engine is None:
        _engine = StrategyEngine()
    return _engine


async def generate_signals() -> List[Dict[str, Any]]:
    return await get_engine().generate_signals()
