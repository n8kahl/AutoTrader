#!/usr/bin/env python3
"""Import Polygon flat-file aggregates into TimescaleDB.

Usage examples
--------------

1) Import all SPX/NDX/SPY/QQQ second aggregates for a date:

    python scripts/import_flatfiles.py --date 2025-09-20 --symbols SPX,NDX,SPY,QQQ

2) Import every CSV/GZ under a custom prefix:

    python scripts/import_flatfiles.py --prefix options/seconds/2025-09-20/

Environment variables expected:
- POLYGON_FLATFILES_ACCESS_KEY
- POLYGON_FLATFILES_SECRET_KEY
- POLYGON_FLATFILES_ENDPOINT (e.g., https://files.polygon.io)
- POLYGON_FLATFILES_BUCKET (defaults to "flatfiles")

The script streams objects from S3, parses CSV rows, and upserts into the
`ticks` hypertable via SQLAlchemy.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import logging
import os
from datetime import datetime, timezone
from typing import Dict, Iterable, Iterator, List, Optional

import boto3
from sqlalchemy import text

from app.db import get_engine

logger = logging.getLogger("flatfiles")
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(message)s")

DEFAULT_BUCKET = os.getenv("POLYGON_FLATFILES_BUCKET", "flatfiles")
DEFAULT_PREFIX = "options/seconds"
DEFAULT_SYMBOLS = ["SPX", "NDX", "SPY", "QQQ"]
BATCH_SIZE = 5_000

INSERT_SQL = text(
    """
    INSERT INTO ticks (symbol, ts, open, high, low, close, volume, vwap, transactions, source)
    VALUES (:symbol, :ts, :open, :high, :low, :close, :volume, :vwap, :transactions, :source)
    ON CONFLICT (symbol, ts)
    DO UPDATE SET
        open = EXCLUDED.open,
        high = EXCLUDED.high,
        low = EXCLUDED.low,
        close = EXCLUDED.close,
        volume = EXCLUDED.volume,
        vwap = EXCLUDED.vwap,
        transactions = EXCLUDED.transactions,
        source = EXCLUDED.source;
    """
)


def iter_objects(client, bucket: str, prefix: str) -> Iterator[Dict[str, str]]:
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith(".csv") or key.endswith(".csv.gz"):
                yield obj


def parse_row(row: Dict[str, str]) -> Optional[Dict[str, object]]:
    """Map common flat-file columns to the ticks table schema."""
    ts_raw = row.get("timestamp") or row.get("ts") or row.get("t") or row.get("window_start")
    if not ts_raw:
        return None
    try:
        ts_int = int(ts_raw)
    except ValueError:
        return None
    # Some datasets provide milliseconds, others nanoseconds. Detect scale.
    if ts_int > 10**15:  # nanoseconds
        ts = datetime.fromtimestamp(ts_int / 1_000_000_000, tz=timezone.utc)
    else:  # milliseconds or seconds
        ts = datetime.fromtimestamp(ts_int / 1000 if ts_int > 10**11 else ts_int, tz=timezone.utc)
    symbol = row.get("ticker") or row.get("symbol") or row.get("sym")
    if not symbol:
        return None

    def _f(key: str) -> Optional[float]:
        val = row.get(key)
        if val in (None, ""):
            return None
        try:
            return float(val)
        except ValueError:
            return None

    record = {
        "symbol": symbol.upper(),
        "ts": ts,
        "open": _f("open") or _f("o"),
        "high": _f("high") or _f("h"),
        "low": _f("low") or _f("l"),
        "close": _f("close") or _f("c"),
        "volume": (_f("volume") or _f("v")),
        "vwap": _f("vwap") or _f("vw"),
        "transactions": (_f("transactions") or _f("n") or _f("z")),
        "source": "polygon_flatfile",
    }
    return record


def stream_records(stream: io.BufferedReader) -> Iterator[Dict[str, object]]:
    text_stream = io.TextIOWrapper(stream, encoding="utf-8")
    reader = csv.DictReader(text_stream)
    for row in reader:
        record = parse_row(row)
        if record:
            yield record


def ingest_object(client, bucket: str, key: str, symbols: Optional[Iterable[str]]) -> int:
    logger.info("Downloading %s", key)
    resp = client.get_object(Bucket=bucket, Key=key)
    body = resp["Body"].read()
    data_stream: io.BufferedReader
    if key.endswith(".gz"):
        data_stream = io.BufferedReader(gzip.GzipFile(fileobj=io.BytesIO(body)))
    else:
        data_stream = io.BufferedReader(io.BytesIO(body))

    engine = get_engine()
    total = 0
    batch: List[Dict[str, object]] = []
    symbol_filter = [s.upper() for s in symbols] if symbols else None

    for record in stream_records(data_stream):
        sym = record["symbol"].upper()
        sym_clean = sym.split(":", 1)[-1]
        if symbol_filter and not any(
            sym.startswith(pref) or sym_clean.startswith(pref)
            for pref in symbol_filter
        ):
            continue
        batch.append(record)
        if len(batch) >= BATCH_SIZE:
            _flush(engine, batch)
            total += len(batch)
            batch.clear()

    if batch:
        _flush(engine, batch)
        total += len(batch)

    logger.info("Imported %s rows from %s", total, key)
    return total


def _flush(engine, batch: List[Dict[str, object]]) -> None:
    with engine.begin() as conn:
        conn.execute(INSERT_SQL, batch)


def run(prefix: str, date: Optional[str], symbols: Optional[List[str]]) -> None:
    access = os.getenv("POLYGON_FLATFILES_ACCESS_KEY")
    secret = os.getenv("POLYGON_FLATFILES_SECRET_KEY")
    endpoint = os.getenv("POLYGON_FLATFILES_ENDPOINT")
    bucket = os.getenv("POLYGON_FLATFILES_BUCKET", DEFAULT_BUCKET)
    if not access or not secret or not endpoint:
        raise SystemExit("Flat-file credentials not configured (see README).")

    session = boto3.session.Session()
    client = session.client(
        "s3",
        aws_access_key_id=access,
        aws_secret_access_key=secret,
        endpoint_url=endpoint,
    )

    prefix_norm = prefix.strip("/")
    if date:
        fmt_date = date
        ts_path = None
        for fmt in ("%Y-%m-%d", "%Y/%m/%d",
                    "%Y%m%d"):
            try:
                dt = datetime.strptime(date, fmt)
                ts_path = f"{dt.year:04d}/{dt.month:02d}/{dt.day:02d}"
                fmt_date = dt.strftime("%Y-%m-%d")
                break
            except ValueError:
                continue
        if ts_path is None:
            logger.warning("Unrecognized date format '%s'; using literal folder name", date)
            ts_path = date
        prefix_norm = f"{prefix_norm}/{ts_path}"
        logger.info("Resolved date %s to prefix fragment %s", fmt_date, ts_path)
    if prefix_norm and not prefix_norm.endswith("/"):
        prefix_norm += "/"

    logger.info("Listing objects under s3://%s/%s", bucket, prefix_norm)
    objects = list(iter_objects(client, bucket, prefix_norm))
    if not objects:
        logger.warning("No objects found under prefix %s", prefix_norm)
        return

    total_rows = 0
    for obj in objects:
        key = obj["Key"]
        try:
            total_rows += ingest_object(client, bucket, key, symbols)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Failed to ingest %s: %s", key, exc)

    logger.info("Imported %s rows total", total_rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import Polygon flat-file aggregates into TimescaleDB.")
    parser.add_argument("--prefix", default=DEFAULT_PREFIX, help="S3 prefix to scan (default: %(default)s)")
    parser.add_argument("--date", help="Optional YYYY-MM-DD to append to the prefix")
    parser.add_argument(
        "--symbols",
        help="Comma-separated list of symbols to keep (default: SPX,NDX,SPY,QQQ)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    symbols = (
        [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
        if args.symbols
        else DEFAULT_SYMBOLS
    )
    run(prefix=args.prefix, date=args.date, symbols=symbols)


if __name__ == "__main__":
    main()
