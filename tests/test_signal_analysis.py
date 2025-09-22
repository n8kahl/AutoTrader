from app.analytics.signals import summarize_signals
from app import ledger


def test_summarize_signals(monkeypatch):
    ledger.event("signal_generated", data={"setup": "VWAP_RECLAIM", "symbol": "AAPL"})
    ledger.event("signal_blocked", data={"setup": "VWAP_RECLAIM", "symbol": "AAPL"})
    ledger.event("signal_generated", data={"setup": "EMA_CROSS", "symbol": "MSFT"})
    ledger.event("signal_approved", data={"signal": {"setup": "EMA_CROSS", "symbol": "MSFT"}})

    summary = summarize_signals(limit=10)
    assert "VWAP_RECLAIM" in summary["per_setup"]
    assert summary["per_setup"]["VWAP_RECLAIM"]["counts"]["generated"] == 1
    assert summary["per_setup"]["EMA_CROSS"]["counts"]["approved"] == 1
    assert summary["per_setup"]["EMA_CROSS"]["approval_rate"] == 1.0
    assert summary["timeline"]
