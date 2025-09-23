from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine


CREATE_EXTENSION_SQL = "CREATE EXTENSION IF NOT EXISTS timescaledb;"

CREATE_TICKS_SQL = """
CREATE TABLE IF NOT EXISTS ticks (
    symbol TEXT NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    open DOUBLE PRECISION,
    high DOUBLE PRECISION,
    low DOUBLE PRECISION,
    close DOUBLE PRECISION,
    volume BIGINT,
    vwap DOUBLE PRECISION,
    transactions BIGINT,
    source TEXT DEFAULT 'polygon',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, ts)
);
"""

CREATE_BARS_SQL = """
CREATE TABLE IF NOT EXISTS bars_1m (
    symbol TEXT NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    open DOUBLE PRECISION,
    high DOUBLE PRECISION,
    low DOUBLE PRECISION,
    close DOUBLE PRECISION,
    volume BIGINT,
    vwap DOUBLE PRECISION,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, ts)
);
"""

CREATE_FEATURES_SQL = """
CREATE TABLE IF NOT EXISTS features (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    bucket_ts TIMESTAMPTZ NOT NULL,
    regime TEXT,
    data JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (symbol, bucket_ts)
);
CREATE INDEX IF NOT EXISTS idx_features_symbol_ts ON features (symbol, bucket_ts DESC);
"""

CREATE_SIGNALS_SQL = """
CREATE TABLE IF NOT EXISTS signals (
    id UUID PRIMARY KEY,
    symbol TEXT NOT NULL,
    source_symbol TEXT NOT NULL,
    setup TEXT NOT NULL,
    status TEXT NOT NULL,
    metadata JSONB,
    reasons JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals (symbol);
CREATE INDEX IF NOT EXISTS idx_signals_created_at ON signals (created_at DESC);
"""

CREATE_ORDERS_SQL = """
CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    source_symbol TEXT,
    side TEXT,
    qty NUMERIC,
    price NUMERIC,
    status TEXT,
    broker TEXT DEFAULT 'tradier',
    payload JSONB,
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_orders_symbol ON orders (symbol);
"""

CREATE_FILLS_SQL = """
CREATE TABLE IF NOT EXISTS fills (
    id BIGSERIAL PRIMARY KEY,
    order_id TEXT REFERENCES orders(order_id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    qty NUMERIC,
    price NUMERIC,
    fee NUMERIC,
    liquidity TEXT,
    filled_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_fills_symbol ON fills (symbol);
CREATE INDEX IF NOT EXISTS idx_fills_order_id ON fills (order_id);
"""

CREATE_ACCOUNT_SNAPSHOTS_SQL = """
CREATE TABLE IF NOT EXISTS account_snapshots (
    id BIGSERIAL PRIMARY KEY,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    cash NUMERIC,
    equity NUMERIC,
    buying_power NUMERIC,
    positions JSONB
);
CREATE INDEX IF NOT EXISTS idx_account_snapshots_captured_at ON account_snapshots (captured_at DESC);
"""

CREATE_SESSION_LABELS_SQL = """
CREATE TABLE IF NOT EXISTS session_labels (
    trade_date DATE PRIMARY KEY,
    symbol TEXT NOT NULL,
    regime TEXT NOT NULL,
    features JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


HYPERTABLE_SQL = [
    "SELECT create_hypertable('ticks', 'ts', if_not_exists => TRUE);",
    "SELECT create_hypertable('bars_1m', 'ts', if_not_exists => TRUE);",
]


def run_migrations(engine: Engine) -> None:
    """Create core tables required for the SPX/NDX scalper."""
    with engine.begin() as conn:
        conn.execute(text(CREATE_EXTENSION_SQL))
        conn.execute(text(CREATE_TICKS_SQL))
        conn.execute(text(CREATE_BARS_SQL))
        conn.execute(text(CREATE_FEATURES_SQL))
        conn.execute(text(CREATE_SIGNALS_SQL))
        conn.execute(text(CREATE_ORDERS_SQL))
        conn.execute(text(CREATE_FILLS_SQL))
        conn.execute(text(CREATE_ACCOUNT_SNAPSHOTS_SQL))
        conn.execute(text(CREATE_SESSION_LABELS_SQL))
        for stmt in HYPERTABLE_SQL:
            conn.execute(text(stmt))
