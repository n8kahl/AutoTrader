from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import mean, pstdev
from typing import Iterable, List, Optional

from ..providers import polygon
from . import strategy


@dataclass
class FeatureSnapshot:
    symbol: str
    as_of: datetime
    last_price: Optional[float]
    vwap: Optional[float]
    sigma_upper: Optional[float]
    sigma_lower: Optional[float]
    ema20: Optional[float]
    ema50: Optional[float]
    ema20_slope: Optional[float]
    relative_volume: Optional[float]
    hod: Optional[float]
    lod: Optional[float]
    prev_close: Optional[float]
    cumulative_delta: Optional[float] = None
    orderbook_imbalance: Optional[float] = None


class FeatureEngine:
    """Fetches raw data and derives feature snapshots for strategy modules."""

    def __init__(self, lookback_minutes: int = 180) -> None:
        self.lookback_minutes = lookback_minutes

    async def snapshot(self, symbol: str) -> FeatureSnapshot:
        bars = await polygon.minute_bars(symbol, minutes=self.lookback_minutes)
        if not bars:
            return FeatureSnapshot(
                symbol=symbol.upper(),
                as_of=datetime.now(timezone.utc),
                last_price=None,
                vwap=None,
                sigma_upper=None,
                sigma_lower=None,
                ema20=None,
                ema50=None,
                ema20_slope=None,
                relative_volume=None,
                hod=None,
                lod=None,
                prev_close=None,
            )

        closes: List[float] = [float(b.get("c") or 0) for b in bars if b.get("c") is not None]
        volumes: List[float] = [float(b.get("v") or 0) for b in bars]
        highs: List[float] = [float(b.get("h") or 0) for b in bars]
        lows: List[float] = [float(b.get("l") or 0) for b in bars]

        last_price = closes[-1] if closes else None

        vwap_val = _compute_vwap(closes, volumes)
        sigma = _compute_sigma(closes, vwap_val)

        ema20_series = strategy.ema(closes, 20) if len(closes) >= 20 else []
        ema50_series = strategy.ema(closes, 50) if len(closes) >= 50 else []
        ema20_val = ema20_series[-1] if ema20_series else None
        ema50_val = ema50_series[-1] if ema50_series else None
        ema20_slope = _compute_slope(ema20_series)

        rvol = _compute_relative_volume(volumes)

        return FeatureSnapshot(
            symbol=symbol.upper(),
            as_of=_resolve_timestamp(bars[-1]),
            last_price=last_price,
            vwap=vwap_val,
            sigma_upper=vwap_val + sigma if vwap_val is not None and sigma is not None else None,
            sigma_lower=vwap_val - sigma if vwap_val is not None and sigma is not None else None,
            ema20=ema20_val,
            ema50=ema50_val,
            ema20_slope=ema20_slope,
            relative_volume=rvol,
            hod=max(highs) if highs else None,
            lod=min(lows) if lows else None,
            prev_close=None,
        )


def _compute_vwap(prices: Iterable[float], volumes: Iterable[float]) -> Optional[float]:
    total_volume = 0.0
    weighted_price = 0.0
    for price, volume in zip(prices, volumes):
        if volume <= 0:
            continue
        total_volume += volume
        weighted_price += price * volume
    if total_volume <= 0:
        return None
    return weighted_price / total_volume


def _compute_sigma(prices: List[float], vwap_val: Optional[float]) -> Optional[float]:
    if vwap_val is None or len(prices) < 2:
        return None
    deviations = [p - vwap_val for p in prices]
    return abs(pstdev(deviations)) if len(deviations) > 1 else None


def _compute_slope(series: List[float], lookback: int = 5) -> Optional[float]:
    if len(series) <= lookback:
        return None
    recent = series[-lookback:]
    start = recent[0]
    end = recent[-1]
    if start == 0:
        return None
    return (end - start) / abs(start)


def _compute_relative_volume(volumes: List[float], lookback: int = 30) -> Optional[float]:
    if len(volumes) < lookback:
        return None
    recent = volumes[-lookback:]
    if not recent:
        return None
    average = mean(volumes[:-lookback]) if len(volumes) > lookback else mean(volumes)
    if average == 0:
        return None
    return mean(recent) / average


def _resolve_timestamp(bar: dict) -> datetime:
    ts = bar.get("t")
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(float(ts) / 1000.0, tz=timezone.utc)
    return datetime.now(timezone.utc)
