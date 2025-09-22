import time

from app.engine.plays import StrategyContext


def test_strategy_context_cooldown():
    ctx = StrategyContext()
    now = time.time()
    assert ctx.can_emit("VWAP_RECLAIM", "AAPL", now, cooldown_sec=10)
    ctx.mark_emit("VWAP_RECLAIM", "AAPL", now)
    assert not ctx.can_emit("VWAP_RECLAIM", "AAPL", now + 5, cooldown_sec=10)
    assert ctx.can_emit("VWAP_RECLAIM", "AAPL", now + 11, cooldown_sec=10)
    # Distinct setup retains separate timestamps
    assert ctx.can_emit("EMA_CROSS", "AAPL", now + 5, cooldown_sec=10)
