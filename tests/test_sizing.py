from types import SimpleNamespace

import pytest

from app import worker


def test_compute_order_plan_risk_sizing(monkeypatch):
    sig = {
        "symbol": "AAPL",
        "side": "buy",
        "setup": "VWAP_RECLAIM",
        "qty": 1,
        "metadata": {
            "entry_price": 100.0,
            "stop_price": 98.0,
            "target1": 102.0,
            "target2": 104.0,
        },
    }

    cfg = SimpleNamespace(
        default_qty=1,
        risk_per_trade_usd=200.0,
        risk_stop_atr_multiplier=1.2,
        target_one_atr_multiplier=1.0,
        target_two_atr_multiplier=2.0,
        partial_exit_pct=0.5,
        trade_timeout_min=30,
        stop_pct=None,
        tp_pct=None,
    )

    monkeypatch.setattr("app.worker.symbol_overrides", lambda symbol: {})

    plan = worker.compute_order_plan(sig, cfg)
    # stop distance 2.0 -> qty should be 100
    assert plan.qty == 100
    assert plan.stop_price == 98.0
    assert plan.target2 == 104.0


def test_compute_order_plan_overrides(monkeypatch):
    sig = {
        "symbol": "AAPL",
        "side": "buy",
        "setup": "VWAP_RECLAIM",
        "qty": 1,
        "metadata": {
            "entry_price": 50.0,
            "atr": 1.5,
        },
    }

    cfg = SimpleNamespace(
        default_qty=1,
        risk_per_trade_usd=0.0,
        risk_stop_atr_multiplier=1.2,
        target_one_atr_multiplier=1.0,
        target_two_atr_multiplier=2.0,
        partial_exit_pct=0.5,
        trade_timeout_min=30,
        stop_pct=None,
        tp_pct=None,
    )

    monkeypatch.setattr(
        "app.worker.symbol_overrides",
        lambda symbol: {"stop_pct": 0.02, "tp_pct": 0.04, "qty": 3},
    )

    plan = worker.compute_order_plan(sig, cfg)
    assert plan.qty == 3
    assert plan.stop_price == 49.0
    assert plan.target1 == 52.0
