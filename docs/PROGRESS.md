# Progress Log — SPX/NDX Scalper

## 2025-09-21
- Re-focused project scope exclusively on the SPX/NDX scalping bot executed through SPY/QQQ proxies.
- Defined roadmap phases covering data backbone, feature/regime engine, dedicated plays, and analytics hardening.
- Captured actionable TODO list: Timescale backbone, Polygon websocket consumer, flat-file ingestion, new plays, risk, replay tooling, dashboards, and alerting.
- Ready to begin with the data backbone tasks (Timescale + websocket ingest).

## 2025-09-22
- Added TimescaleDB service with schema migrations for ticks, bars, features, signals, orders, fills, account snapshots, and session labels.
- Deployed `scripts/polygon_ws.py` plus the `streamer` docker service to capture SPX/NDX/SPY/QQQ second aggregates directly into Timescale.
- Updated `.env.example`, `README.md`, and Dockerfile to document the websocket streamer and required environment variables.
- Next: build the Polygon flat-file ingestion pipeline for historical backfill.

## 2025-09-23
- Added `scripts/import_flatfiles.py` to pull Polygon flat-file aggregates from S3 (SPX/NDX/SPY/QQQ) and upsert into the `ticks` hypertable.
- Expanded requirements with `boto3` and documented the new env variables for flat-file access and the import workflow.
- Next: schedule regular backfill runs and begin feature/regime labeling on the imported data.
