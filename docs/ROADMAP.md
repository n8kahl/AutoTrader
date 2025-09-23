# Roadmap — SPX/NDX Scalper

Purpose: build a profitable SPX and NDX intraday scalping bot that executes via SPY/QQQ proxies, powered by real-time Polygon websocket data and historical flat-file analysis.

## Phase 1 — Data Backbone (Week 1)
- Provision TimescaleDB/Postgres service in Docker Compose with migrations for ticks (`agg_1s`), bars, features, signals, orders, fills.
- Ship a resilient Polygon websocket consumer that streams SPX/NDX second aggregates into the database with caching and metrics.
- Add a flat-file ingestion script (S3 sync or boto3) to backfill historical SPX/NDX seconds and options chains into Timescale.

## Phase 2 — Feature & Regime Engine (Week 2)
- Extend `FeatureEngine` to fuse 1s + 1m data, incremental VWAP/sigma, anchored VWAPs, cumulative delta, and multi-timeframe EMA slopes.
- Implement daily regime labeling (trend vs consolidation) using historical stats and store labels for live reference.
- Cache live features in memory for the worker while persisting snapshots to the features table.

## Phase 3 — SPX/NDX Playbooks (Week 3)
- Create two dedicated plays: `SPX_TREND_BURST` (breakout continuation) and `SPX_BALANCED_BREAK` (range compression release) with QQQ counterparts.
- Wire session policies that flip aggressiveness based on morning regime score and economic calendar flags.
- Add options/flow heuristics (IV rank, gamma zones, relative 0DTE volume) as gating signals.

## Phase 4 — Risk, Execution, Analytics (Week 4)
- Tune position sizing, brackets, and trailing exits per regime using historical expectancy.
- Build replay/backtest CLI that replays recorded ticks to validate every play, logging PnL distributions.
- Publish Grafana dashboards: regime label accuracy, play expectancy, slippage, holding time.

## Phase 5 — Harden & Iterate (Ongoing)
- Add alerting (Discord) when websocket stream stalls or regime flips unexpectedly.
- Schedule nightly flat-file sync + database vacuum/retention jobs.
- Iterate thresholds weekly based on replay output; document each change in `docs/PROGRESS.md`.
