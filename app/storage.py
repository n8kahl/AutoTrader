from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, Integer, String, Table, Text, create_engine, insert, update, MetaData

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///state/trades.db")
os.makedirs("state", exist_ok=True)

engine = create_engine(DATABASE_URL, future=True)
metadata = MetaData()

signals_table = Table(
    "signals",
    metadata,
    Column("id", String, primary_key=True),
    Column("symbol", String),
    Column("setup", String),
    Column("stage", String),
    Column("reasons", Text),
    Column("plan", Text),
    Column("event_ts", DateTime(timezone=True)),
)

trades_table = Table(
    "trades",
    metadata,
    Column("id", String, primary_key=True),
    Column("symbol", String),
    Column("setup", String),
    Column("qty", Integer),
    Column("entry_price", Float),
    Column("stop_price", Float),
    Column("target1", Float),
    Column("target2", Float),
    Column("entry_ts", DateTime(timezone=True)),
    Column("exit_price", Float),
    Column("exit_reason", String),
    Column("exit_ts", DateTime(timezone=True)),
)

metadata.create_all(engine)


def _ts(timestamp: float | None) -> datetime:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc) if timestamp else datetime.now(timezone.utc)


def record_signal(symbol: str, setup: str, stage: str, ts: float, reasons: list[str] | None, plan: dict) -> None:
    data = {
        "id": str(uuid.uuid4()),
        "symbol": symbol,
        "setup": setup,
        "stage": stage,
        "reasons": json.dumps(reasons or []),
        "plan": json.dumps(plan or {}),
        "event_ts": _ts(ts),
    }
    with engine.begin() as conn:
        conn.execute(insert(signals_table).values(**data))


def create_trade(trade_id: str, symbol: str, setup: str, qty: int, entry_price: float | None, stop: float | None, t1: float | None, t2: float | None, ts: float) -> None:
    data = {
        "id": trade_id,
        "symbol": symbol,
        "setup": setup,
        "qty": qty,
        "entry_price": entry_price,
        "stop_price": stop,
        "target1": t1,
        "target2": t2,
        "entry_ts": _ts(ts),
    }
    with engine.begin() as conn:
        conn.execute(insert(trades_table).values(**data))


def close_trade(trade_id: str, exit_price: float | None, reason: str, ts: float) -> None:
    with engine.begin() as conn:
        conn.execute(
            update(trades_table)
            .where(trades_table.c.id == trade_id)
            .values(exit_price=exit_price, exit_reason=reason, exit_ts=_ts(ts))
        )
