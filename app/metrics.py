from __future__ import annotations

from prometheus_client import Counter, Histogram

# AutoTrader-specific Polygon REST request counters.
autotrader_polygon_request_total = Counter(
    "autotrader_polygon_request_total",
    "AutoTrader Polygon REST requests grouped by path and status.",
    ("path", "status"),
)

autotrader_polygon_request_retry_total = Counter(
    "autotrader_polygon_request_retry_total",
    "AutoTrader Polygon REST retries grouped by path and reason.",
    ("path", "reason"),
)

autotrader_polygon_request_latency = Histogram(
    "autotrader_polygon_request_latency_seconds",
    "AutoTrader Polygon REST request latency in seconds by path.",
    ("path",),
)

# AutoTrader Tradier REST metrics for equity data consumption.
autotrader_tradier_request_total = Counter(
    "autotrader_tradier_request_total",
    "AutoTrader Tradier REST requests grouped by path and status.",
    ("path", "status"),
)

autotrader_tradier_request_retry_total = Counter(
    "autotrader_tradier_request_retry_total",
    "AutoTrader Tradier REST retries grouped by path and reason.",
    ("path", "reason"),
)

autotrader_tradier_request_latency = Histogram(
    "autotrader_tradier_request_latency_seconds",
    "AutoTrader Tradier REST request latency in seconds by path.",
    ("path",),
)

autotrader_signal_total = Counter(
    "autotrader_signal_total",
    "Signals processed grouped by strategy setup and outcome.",
    ("setup", "outcome"),
)

__all__ = [
    "autotrader_polygon_request_total",
    "autotrader_polygon_request_retry_total",
    "autotrader_polygon_request_latency",
    "autotrader_tradier_request_total",
    "autotrader_tradier_request_retry_total",
    "autotrader_tradier_request_latency",
    "autotrader_signal_total",
]
