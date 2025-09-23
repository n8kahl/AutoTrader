from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.engine.plays import Play, StrategyEngine, StrategySignal
from app.engine.features import FeatureSnapshot


class DummyFeatureEngine:
    async def snapshot(self, symbol: str) -> FeatureSnapshot:
        return FeatureSnapshot(
            symbol=symbol.upper(),
            as_of=datetime.now(timezone.utc),
            last_price=100.0,
            vwap=99.5,
            sigma_upper=None,
            sigma_lower=None,
            ema20=None,
            ema50=None,
            ema20_prev=None,
            ema50_prev=None,
            ema20_slope=None,
            relative_volume=1.0,
            hod=None,
            lod=None,
            prev_close=99.0,
            atr14=1.0,
            ema5m_20=None,
            ema5m_50=None,
            ema15m_20=None,
            ema15m_50=None,
            opening_range_high=None,
            opening_range_low=None,
            market_regime_score=None,
        )


class DummyPlay(Play):
    name = "DUMMY"

    def allowed_in(self, session):  # type: ignore[override]
        return True

    def evaluate(self, snapshot, session, ctx):  # type: ignore[override]
        return [
            StrategySignal(
                symbol=snapshot.symbol,
                setup=self.name,
                side="buy",
                qty=1,
                metadata={"entry_price": snapshot.last_price},
            )
        ]


@pytest.mark.asyncio
async def test_strategy_engine_applies_execution_mapping(monkeypatch):
    monkeypatch.setenv("SYMBOLS", "SPX")
    monkeypatch.setenv("SYMBOL_EXECUTION_MAP", "SPX:SPY")
    monkeypatch.setenv("POWER_HOUR_SYMBOLS", "")

    monkeypatch.setattr(
        "app.engine.plays.load_session_config",
        lambda: SimpleNamespace(current=lambda *args, **kwargs: None),
    )

    engine = StrategyEngine(feature_engine=DummyFeatureEngine(), plays=[DummyPlay()])
    signals = await engine.generate_signals()

    assert signals, "expected a signal"
    sig = signals[0]
    assert sig["symbol"] == "SPY"
    assert sig["source_symbol"] == "SPX"
    assert sig["metadata"]["execution_symbol"] == "SPY"
    assert sig["metadata"]["source_symbol"] == "SPX"
