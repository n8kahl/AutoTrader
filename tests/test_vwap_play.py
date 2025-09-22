from datetime import datetime as dt, timezone
from types import SimpleNamespace

import pytest

from app.engine.plays import (
    HodFailurePlay,
    SigmaFadePlay,
    StrategyContext,
    VWAPReclaimPlay,
    settings,
)
from app.engine.features import FeatureSnapshot


def make_snapshot(**overrides):
    base = dict(
        symbol="AAPL",
        as_of=dt(2024, 5, 10, 19, 30, tzinfo=timezone.utc),
        last_price=101.0,
        prev_close=99.0,
        vwap=100.0,
        sigma_upper=None,
        sigma_lower=None,
        ema20=102.0,
        ema50=100.0,
        ema20_prev=98.0,
        ema50_prev=99.5,
        ema20_slope=0.02,
        relative_volume=1.3,
        hod=102.5,
        lod=98.5,
        cumulative_delta=None,
        orderbook_imbalance=None,
        atr14=1.5,
    )
    base.update(overrides)
    return FeatureSnapshot(**base)


@pytest.mark.asyncio
async def test_vwap_reclaim_emits_signal(monkeypatch):
    cfg = SimpleNamespace(
        default_qty=2,
        vwap_cooldown_sec=60,
        vwap_min_rvol=1.1,
        power_hour_symbols="",
        power_hour_start="15:00",
        risk_stop_atr_multiplier=1.2,
        target_one_atr_multiplier=1.0,
        target_two_atr_multiplier=2.0,
        partial_exit_pct=0.5,
        trade_timeout_min=30,
        risk_per_trade_usd=100.0,
        stop_pct=None,
        tp_pct=None,
    )
    monkeypatch.setattr("app.engine.plays.settings", lambda: cfg)

    play = VWAPReclaimPlay()
    ctx = StrategyContext()
    snapshot = make_snapshot()

    signals = play.evaluate(snapshot, session=None, ctx=ctx)
    assert len(signals) == 1
    sig = signals[0]
    assert sig.symbol == "AAPL"
    assert sig.setup == "VWAP_RECLAIM"
    assert sig.metadata["reason"] == "vwap_reclaim"
    assert sig.metadata["stop_price"] is not None
    assert sig.metadata["target1"] is not None
    assert sig.metadata["target2"] is not None


@pytest.mark.asyncio
async def test_vwap_reclaim_respects_relative_volume(monkeypatch):
    cfg = SimpleNamespace(
        default_qty=1,
        vwap_cooldown_sec=0,
        vwap_min_rvol=1.2,
        power_hour_symbols="",
        power_hour_start="15:00",
        risk_stop_atr_multiplier=1.2,
        target_one_atr_multiplier=1.0,
        target_two_atr_multiplier=2.0,
        partial_exit_pct=0.5,
        trade_timeout_min=30,
        risk_per_trade_usd=100.0,
        stop_pct=None,
        tp_pct=None,
    )
    monkeypatch.setattr("app.engine.plays.settings", lambda: cfg)

    play = VWAPReclaimPlay()
    ctx = StrategyContext()
    snapshot = make_snapshot(relative_volume=1.0)

    assert play.evaluate(snapshot, session=None, ctx=ctx) == []


@pytest.mark.asyncio
async def test_vwap_reclaim_cooldown(monkeypatch):
    cfg = SimpleNamespace(
        default_qty=1,
        vwap_cooldown_sec=600,
        vwap_min_rvol=1.0,
        power_hour_symbols="",
        power_hour_start="15:00",
        risk_stop_atr_multiplier=1.2,
        target_one_atr_multiplier=1.0,
        target_two_atr_multiplier=2.0,
        partial_exit_pct=0.5,
        trade_timeout_min=30,
        risk_per_trade_usd=100.0,
        stop_pct=None,
        tp_pct=None,
    )
    monkeypatch.setattr("app.engine.plays.settings", lambda: cfg)

    play = VWAPReclaimPlay()
    ctx = StrategyContext()
    snapshot = make_snapshot()

    first = play.evaluate(snapshot, session=None, ctx=ctx)
    assert len(first) == 1
    second = play.evaluate(snapshot, session=None, ctx=ctx)
    assert second == []


class _FixedDateTime(dt):
    @classmethod
    def now(cls, tz=None):
        return dt(2024, 5, 10, 14, 0, tzinfo=tz)

    @classmethod
    def strptime(cls, date_string, fmt):
        return dt.strptime(date_string, fmt)


@pytest.mark.asyncio
async def test_vwap_reclaim_power_hour_gate(monkeypatch):
    cfg = SimpleNamespace(
        default_qty=1,
        vwap_cooldown_sec=0,
        vwap_min_rvol=1.0,
        power_hour_symbols="SPX",
        power_hour_start="15:00",
        risk_stop_atr_multiplier=1.2,
        target_one_atr_multiplier=1.0,
        target_two_atr_multiplier=2.0,
        partial_exit_pct=0.5,
        trade_timeout_min=30,
        risk_per_trade_usd=100.0,
        stop_pct=None,
        tp_pct=None,
    )
    monkeypatch.setattr("app.engine.plays.settings", lambda: cfg)
    monkeypatch.setattr("app.engine.plays.datetime", _FixedDateTime)

    play = VWAPReclaimPlay()
    ctx = StrategyContext()
    snapshot = make_snapshot(symbol="SPX")

    assert play.evaluate(snapshot, session=None, ctx=ctx) == []

    # Move start before mocked time to allow signal
    cfg.power_hour_start = "13:00"
    signals = play.evaluate(snapshot, session=None, ctx=ctx)
    assert len(signals) == 1


@pytest.mark.asyncio
async def test_sigma_fade_emits_signal(monkeypatch):
    cfg = SimpleNamespace(
        default_qty=1,
        vwap_cooldown_sec=0,
        vwap_min_rvol=0.8,
        power_hour_symbols="",
        power_hour_start="15:00",
        risk_stop_atr_multiplier=1.2,
        target_one_atr_multiplier=1.0,
        target_two_atr_multiplier=2.0,
        partial_exit_pct=0.5,
        trade_timeout_min=30,
        risk_per_trade_usd=100.0,
        stop_pct=None,
        tp_pct=None,
    )
    monkeypatch.setattr("app.engine.plays.settings", lambda: cfg)

    play = SigmaFadePlay()
    ctx = StrategyContext()
    snapshot = make_snapshot(sigma_lower=100.8, last_price=100.5, relative_volume=1.0)

    signals = play.evaluate(snapshot, session=None, ctx=ctx)
    assert len(signals) == 1
    sig = signals[0]
    assert sig.setup == "SIGMA_FADE"
    assert sig.metadata["stop_price"] is not None


@pytest.mark.asyncio
async def test_hod_failure_emits_signal(monkeypatch):
    cfg = SimpleNamespace(
        default_qty=1,
        vwap_cooldown_sec=0,
        vwap_min_rvol=1.0,
        power_hour_symbols="",
        power_hour_start="15:00",
        risk_stop_atr_multiplier=1.2,
        target_one_atr_multiplier=1.0,
        target_two_atr_multiplier=2.0,
        partial_exit_pct=0.5,
        trade_timeout_min=30,
        risk_per_trade_usd=100.0,
        stop_pct=None,
        tp_pct=None,
    )
    monkeypatch.setattr("app.engine.plays.settings", lambda: cfg)

    play = HodFailurePlay()
    ctx = StrategyContext()
    snapshot = make_snapshot(hod=104.0, last_price=102.0, vwap=101.5)

    signals = play.evaluate(snapshot, session=None, ctx=ctx)
    assert len(signals) == 1
    sig = signals[0]
    assert sig.setup == "HOD_FAIL"
