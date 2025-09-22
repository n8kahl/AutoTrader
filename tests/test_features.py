import asyncio
from datetime import datetime, timezone

import pytest

from app.engine.features import FeatureEngine
from app.providers import tradier


@pytest.mark.asyncio
async def test_feature_engine_snapshot(monkeypatch):
    bars = []
    price = 100.0
    for i in range(1, 26):
        price += 0.2
        bars.append(
            {
                "t": i * 60,
                "o": price,
                "h": price + 0.5,
                "l": price - 0.5,
                "c": price,
                "v": 1_000 + i * 10,
            }
        )

    async def fake_minute_bars(symbol: str, minutes: int = 180, timeout: float = 10.0):
        return bars

    async def fake_five_minute_bars(symbol: str, minutes: int = 180, timeout: float = 10.0):
        out = []
        for i in range(0, len(bars), 5):
            chunk = bars[i : i + 5]
            if not chunk:
                continue
            out.append(
                {
                    "t": chunk[-1]["t"],
                    "o": chunk[0]["o"],
                    "h": max(c["h"] for c in chunk),
                    "l": min(c["l"] for c in chunk),
                    "c": chunk[-1]["c"],
                    "v": sum(c["v"] for c in chunk),
                }
            )
        return out

    monkeypatch.setattr(tradier, "minute_bars", fake_minute_bars)
    monkeypatch.setattr(tradier, "five_minute_bars", fake_five_minute_bars)

    engine = FeatureEngine(lookback_minutes=2)
    snapshot = await engine.snapshot("AAPL")

    assert snapshot.symbol == "AAPL"
    assert snapshot.last_price == pytest.approx(bars[-1]["c"])
    assert snapshot.prev_close is not None
    assert snapshot.vwap is not None
    assert snapshot.ema20 is not None
    assert snapshot.relative_volume is None
    assert snapshot.atr14 is not None
    assert snapshot.opening_range_high is not None
    assert snapshot.market_regime_score is not None


@pytest.mark.asyncio
async def test_feature_engine_empty(monkeypatch):
    async def fake_minute_bars(symbol: str, minutes: int = 180, timeout: float = 10.0):
        return []

    monkeypatch.setattr(tradier, "minute_bars", fake_minute_bars)
    monkeypatch.setattr(tradier, "five_minute_bars", fake_minute_bars)

    engine = FeatureEngine(lookback_minutes=2)
    snapshot = await engine.snapshot("AAPL")

    assert snapshot.symbol == "AAPL"
    assert snapshot.last_price is None
    assert snapshot.vwap is None
    assert snapshot.ema20 is None
    assert snapshot.atr14 is None
    assert snapshot.market_regime_score is None
