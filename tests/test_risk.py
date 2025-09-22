from types import SimpleNamespace

import pytest

from app.engine import risk


@pytest.mark.asyncio
async def test_risk_blocks_notional(monkeypatch):
    cfg = SimpleNamespace(
        trading_window_start="00:00",
        trading_window_end="23:59",
        symbol_blacklist="",
        symbol_whitelist="",
        risk_max_concurrent=3,
        risk_max_open_orders=5,
        risk_max_positions_per_symbol=1,
        risk_max_order_notional_usd=500.0,
        tradier_account_id="TEST",
        min_cash_usd=None,
    )
    monkeypatch.setattr(risk, "settings", lambda: cfg)

    async def fake_snapshot():
        return {"positions": [], "open_orders": []}

    async def fake_last_trade_price(symbol: str):
        return 1.0

    monkeypatch.setattr(risk, "portfolio_snapshot", fake_snapshot)
    monkeypatch.setattr(risk.t, "last_trade_price", fake_last_trade_price)

    signal = {"symbol": "AAPL", "qty": 600, "type": "market"}
    ok, reasons = await risk.evaluate(signal)
    assert not ok
    assert any("notional" in r.lower() for r in reasons)


@pytest.mark.asyncio
async def test_risk_allows_reasonable_trade(monkeypatch):
    cfg = SimpleNamespace(
        trading_window_start="00:00",
        trading_window_end="23:59",
        symbol_blacklist="",
        symbol_whitelist="",
        risk_max_concurrent=3,
        risk_max_open_orders=5,
        risk_max_positions_per_symbol=1,
        risk_max_order_notional_usd=500.0,
        tradier_account_id="TEST",
        min_cash_usd=None,
    )
    monkeypatch.setattr(risk, "settings", lambda: cfg)

    async def fake_snapshot():
        return {"positions": [], "open_orders": []}

    async def fake_last_trade_price(symbol: str):
        return 2.0

    monkeypatch.setattr(risk, "portfolio_snapshot", fake_snapshot)
    monkeypatch.setattr(risk.t, "last_trade_price", fake_last_trade_price)

    signal = {"symbol": "AAPL", "qty": 100, "type": "market"}
    ok, reasons = await risk.evaluate(signal)
    assert ok
    assert reasons == []
