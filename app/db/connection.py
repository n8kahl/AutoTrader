from __future__ import annotations

import os
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine


DEFAULT_URL = "postgresql+psycopg2://autotrader:autotrader@db:5432/autotrader"


@lru_cache(maxsize=1)
def get_engine(echo: bool = False) -> Engine:
    """Return a SQLAlchemy engine using the configured DATABASE_URL."""
    url = os.getenv("DATABASE_URL", DEFAULT_URL)
    return create_engine(url, echo=echo, future=True, pool_pre_ping=True)
