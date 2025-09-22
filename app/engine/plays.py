from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

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
            "setup": self.setup,
            **self.metadata,
        }


@dataclass
class StrategyContext:
    """Keeps minimal per-symbol state shared across plays."""

    last_signal_ts: Dict[str, float] = field(default_factory=dict)

    def _key(self, setup: str, symbol: str) -> str:
        return f"{setup}:{symbol.upper()}"

    def can_emit(self, setup: str, symbol: str, now_ts: float, cooldown_sec: int | None) -> bool:
        if not cooldown_sec or cooldown_sec <= 0:
            return True
        last = self.last_signal_ts.get(self._key(setup, symbol))
        if last is None:
            return True
        return (now_ts - last) >= cooldown_sec

    def mark_emit(self, setup: str, symbol: str, now_ts: float) -> None:
        self.last_signal_ts[self._key(setup, symbol)] = now_ts


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
            entry = snapshot.last_price
            atr = snapshot.atr14
            stop_price = entry - cfg.risk_stop_atr_multiplier * atr if atr else None
            target1 = entry + cfg.target_one_atr_multiplier * atr if atr else None
            target2 = entry + cfg.target_two_atr_multiplier * atr if atr else None
            metadata = {
                "reason": "ema20_cross_up",
                "entry_price": entry,
                "stop_price": stop_price,
                "target1": target1,
                "target2": target2,
                "atr": atr,
            }
            return [
                StrategySignal(
                    symbol=snapshot.symbol,
                    setup=self.name,
                    side="buy",
                    qty=cfg.default_qty,
                    metadata=metadata,
                )
            ]
        return []


class VWAPReclaimPlay(Play):
    name = "VWAP_RECLAIM"

    def evaluate(self, snapshot: FeatureSnapshot, session: Optional[SessionPolicy], ctx: StrategyContext) -> List[StrategySignal]:
        cfg = settings()
        last = snapshot.last_price
        prev = snapshot.prev_close
        vwap = snapshot.vwap
        if last is None or prev is None or vwap is None:
            return []

        # Require price to reclaim VWAP from below
        if not (prev < vwap and last > vwap):
            return []

        # Momentum confirmation: fast EMA above slow EMA and slope positive if available
        if snapshot.ema20 is not None and snapshot.ema50 is not None and snapshot.ema20 <= snapshot.ema50:
            return []
        if snapshot.ema20_slope is not None and snapshot.ema20_slope <= 0:
            return []

        # Liquidity check via relative volume
        if snapshot.relative_volume is not None and snapshot.relative_volume < cfg.vwap_min_rvol:
            return []

        # Cooling period to avoid repeat entries
        now_ts = snapshot.as_of.timestamp() if snapshot.as_of else time.time()
        if not ctx.can_emit(self.name, snapshot.symbol, now_ts, cfg.vwap_cooldown_sec):
            return []

        # Power hour gating for selected symbols
        power_syms = {s.strip().upper() for s in cfg.power_hour_symbols.split(",") if s.strip()}
        if power_syms:
            if snapshot.symbol.upper() in power_syms:
                try:
                    start_dt = datetime.strptime(cfg.power_hour_start, "%H:%M").time()
                except ValueError:
                    start_dt = datetime.strptime("15:00", "%H:%M").time()
                now_et = datetime.now(ZoneInfo("America/New_York")).time()
                if now_et < start_dt:
                    return []

        ctx.mark_emit(self.name, snapshot.symbol, now_ts)

        delta_above = (last - vwap) / vwap if vwap else None
        metadata = {
            "reason": "vwap_reclaim",
            "vwap": vwap,
            "last_price": last,
            "prev_close": prev,
            "delta_above_vwap": delta_above,
            "relative_volume": snapshot.relative_volume,
            "ema20": snapshot.ema20,
            "ema50": snapshot.ema50,
            "power_hour": snapshot.symbol.upper() in power_syms,
            "entry_price": last,
            "stop_price": last - cfg.risk_stop_atr_multiplier * (snapshot.atr14 or 0.0) if snapshot.atr14 else None,
            "target1": last + cfg.target_one_atr_multiplier * (snapshot.atr14 or 0.0) if snapshot.atr14 else None,
            "target2": last + cfg.target_two_atr_multiplier * (snapshot.atr14 or 0.0) if snapshot.atr14 else None,
            "atr": snapshot.atr14,
        }
        return [
            StrategySignal(
                symbol=snapshot.symbol,
                setup=self.name,
                side="buy",
                qty=cfg.default_qty,
                metadata=metadata,
            )
        ]


class SigmaFadePlay(Play):
    name = "SIGMA_FADE"

    def evaluate(self, snapshot: FeatureSnapshot, session: Optional[SessionPolicy], ctx: StrategyContext) -> List[StrategySignal]:
        cfg = settings()
        last = snapshot.last_price
        atr = snapshot.atr14
        if last is None or atr is None:
            return []
        if snapshot.sigma_lower is None:
            return []
        if last > snapshot.sigma_lower:
            return []
        if snapshot.relative_volume is not None and snapshot.relative_volume < 0.9:
            return []
        if snapshot.ema20 is not None and snapshot.ema20 < snapshot.ema50:
            return []
        now_ts = snapshot.as_of.timestamp() if snapshot.as_of else time.time()
        if not ctx.can_emit(self.name, snapshot.symbol, now_ts, cfg.vwap_cooldown_sec):
            return []
        stop_price = last - cfg.risk_stop_atr_multiplier * atr
        target1 = last + cfg.target_one_atr_multiplier * atr
        target2 = last + cfg.target_two_atr_multiplier * atr
        metadata = {
            "reason": "sigma_fade",
            "sigma_lower": snapshot.sigma_lower,
            "entry_price": last,
            "stop_price": stop_price,
            "target1": target1,
            "target2": target2,
            "atr": atr,
        }
        ctx.mark_emit(self.name, snapshot.symbol, now_ts)
        return [
            StrategySignal(
                symbol=snapshot.symbol,
                setup=self.name,
                side="buy",
                qty=cfg.default_qty,
                metadata=metadata,
            )
        ]


class HodFailurePlay(Play):
    name = "HOD_FAIL"

    def evaluate(self, snapshot: FeatureSnapshot, session: Optional[SessionPolicy], ctx: StrategyContext) -> List[StrategySignal]:
        cfg = settings()
        last = snapshot.last_price
        atr = snapshot.atr14
        if last is None or atr is None or snapshot.hod is None or snapshot.vwap is None:
            return []
        pullback = snapshot.hod - last
        if pullback < 0.5 * atr:
            return []
        if last < snapshot.vwap:
            return []
        if snapshot.ema20 is not None and snapshot.ema20 < snapshot.ema50:
            return []
        now_ts = snapshot.as_of.timestamp() if snapshot.as_of else time.time()
        if not ctx.can_emit(self.name, snapshot.symbol, now_ts, cfg.vwap_cooldown_sec):
            return []
        stop_price = last - cfg.risk_stop_atr_multiplier * atr
        target1 = last + cfg.target_one_atr_multiplier * atr
        target2 = last + cfg.target_two_atr_multiplier * atr
        metadata = {
            "reason": "hod_failure_pullback",
            "hod": snapshot.hod,
            "entry_price": last,
            "stop_price": stop_price,
            "target1": target1,
            "target2": target2,
            "atr": atr,
        }
        ctx.mark_emit(self.name, snapshot.symbol, now_ts)
        return [
            StrategySignal(
                symbol=snapshot.symbol,
                setup=self.name,
                side="buy",
                qty=cfg.default_qty,
                metadata=metadata,
            )
        ]


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
