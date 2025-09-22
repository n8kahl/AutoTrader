from types import SimpleNamespace

import pytest

from app import ledger
from app.engine import risk as risk_module
from app.engine import strategy as strategy_module
from app.metrics import autotrader_signal_total
from app import worker


@pytest.mark.asyncio
async def test_worker_scan_journals_and_counts(monkeypatch):
    signal = {
        "symbol": "AAPL",
        "setup": "VWAP_RECLAIM",
        "side": "buy",
        "qty": 1,
        "type": "market",
        "metadata": {
            "entry_price": 100.0,
            "stop_price": 99.0,
            "target1": 101.0,
            "target2": 102.0,
        },
    }

    async def fake_signals():
        return [signal]

    async def fake_risk_evaluate(sig):
        return True, []

    async def fake_minute_bars(symbol: str, minutes: int = 180):
        return []

    async def fake_portfolio_snapshot():
        return {"positions": [], "open_orders": []}

    events = []

    def capture_event(kind: str, **data):
        events.append({"kind": kind, "data": data.get("data", data)})

    monkeypatch.setattr(strategy_module, "ema_crossover_signals", fake_signals)
    monkeypatch.setattr(risk_module, "evaluate", fake_risk_evaluate)
    monkeypatch.setattr(worker.t, "minute_bars", fake_minute_bars)
    monkeypatch.setattr(risk_module, "portfolio_snapshot", fake_portfolio_snapshot)
    monkeypatch.setattr(ledger, "event", capture_event)
    async def fake_quote(symbol: str):
        return {"quotes": {"quote": {"last": 100.0, "bid": 99.9, "ask": 100.1}}}

    async def fake_last_price(symbol: str):
        return 100.0

    monkeypatch.setattr(worker.t, "get_quote", fake_quote)
    monkeypatch.setattr(worker.t, "last_trade_price", fake_last_price)

    cfg = SimpleNamespace(
        dry_run=1,
        tradier_account_id="TEST",
        stop_pct=None,
        tp_pct=None,
        symbols="AAPL",
        trail_pct=None,
        trail_activation_pct=None,
        risk_per_trade_usd=0.0,
        risk_stop_atr_multiplier=1.2,
        target_one_atr_multiplier=1.0,
        target_two_atr_multiplier=2.0,
        partial_exit_pct=0.5,
        trade_timeout_min=30,
        power_hour_symbols="",
        power_hour_start="15:00",
        vwap_cooldown_sec=0,
        vwap_min_rvol=1.0,
        default_qty=1,
        enable_options_feedback=0,
        entry_spread_bps=10,
        entry_limit_offset_bps=2.0,
        entry_limit_timeout_sec=2,
    )

    await worker.scan_once(cfg)

    generated = autotrader_signal_total.labels(setup="VWAP_RECLAIM", outcome="generated")._value.get()
    approved = autotrader_signal_total.labels(setup="VWAP_RECLAIM", outcome="approved")._value.get()
    dry_run = autotrader_signal_total.labels(setup="VWAP_RECLAIM", outcome="dry_run")._value.get()

    assert generated == 1.0
    assert approved == 1.0
    assert dry_run == 1.0

    kinds = [ev["kind"] for ev in events]
    assert "signal_generated" in kinds
    assert "signal_approved" in kinds

    worker._ACTIVE_TRADES.clear()


@pytest.mark.asyncio
async def test_options_feedback_blocks(monkeypatch):
    signal = {
        "symbol": "AAPL",
        "setup": "VWAP_RECLAIM",
        "side": "buy",
        "qty": 1,
        "type": "market",
    }

    async def fake_signals():
        return [signal]

    async def fake_option_feedback(symbol: str, timeout: float = 5.0):
        return {"call_volume": 10.0, "put_volume": 5.0, "call_iv": 4.0}

    monkeypatch.setattr("app.worker.option_feedback", fake_option_feedback)
    monkeypatch.setattr(strategy_module, "ema_crossover_signals", fake_signals)

    cfg = SimpleNamespace(
        dry_run=1,
        tradier_account_id="TEST",
        stop_pct=None,
        tp_pct=None,
        symbols="AAPL",
        trail_pct=None,
        trail_activation_pct=None,
        risk_per_trade_usd=0.0,
        risk_stop_atr_multiplier=1.2,
        target_one_atr_multiplier=1.0,
        target_two_atr_multiplier=2.0,
        partial_exit_pct=0.5,
        trade_timeout_min=30,
        power_hour_symbols="",
        power_hour_start="15:00",
        vwap_cooldown_sec=0,
        vwap_min_rvol=1.0,
        default_qty=1,
        enable_options_feedback=1,
        options_min_volume=100,
        options_max_iv=3.0,
        options_cache_ttl_sec=300,
        entry_spread_bps=10,
        entry_limit_offset_bps=2.0,
        entry_limit_timeout_sec=2,
    )

    events = []

    def capture_event(kind: str, **payload):
        if "data" in payload:
            events.append({"kind": kind, "data": payload["data"]})
        else:
            events.append({"kind": kind, "data": payload})

    monkeypatch.setattr(ledger, "event", capture_event)

    await worker.scan_once(cfg)

    outcomes = [ev["data"].get("reasons") for ev in events if ev["kind"] == "signal_blocked"]
    assert any(outcomes)
