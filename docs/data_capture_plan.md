# Data Capture & Backtesting Plan

This document tracks the data architecture required to support historical analysis, backtesting, and ML-assisted tuning for the SPY/QQQ scalp bot.

## Objectives
- Persist every input the live strategy consumes so intraday sessions can be replayed exactly.
- Record derived features, strategy outputs, risk decisions, orders, and PnL for supervised learning and expectancy validation.
- Keep storage lean (single-node TimescaleDB) while maintaining enough granularity for tick-level diagnostics.

## Components & Responsibilities

### Market Data Ingest
- **Source:** Polygon WebSocket streams (trades, quotes) plus REST fallbacks/backfill.
- **Storage:** TimescaleDB hypertables.
  - `market_trades(symbol, ts, price, size, conditions, exchange)`
  - `market_quotes(symbol, ts, bid, ask, bid_size, ask_size)`
  - `bars_1m(symbol, ts, o, h, l, c, v, vwap, aggregated_from)`
  - `options_chain(contract_symbol, ts, bid, ask, last, volume, open_interest, iv, delta, gamma, theta, vega)`
- **Retention:** 30 days tick-level; roll older data into 1m aggregates and archive raw ticks if needed.

### Feature Store
- Extend `FeatureEngine` to persist each snapshot after computation.
  - Table: `features(symbol, ts, session, vwap, sigma_upper, sigma_lower, ema20, ema50, ema20_slope, rvol, hod, lod, prev_close, cvd, ob_imbalance, source_commit)`
  - Record config hash (`session_policy_digest`, `.env` hash) to reproduce the environment.
- Ensure warm-up windows are tracked (e.g., `lookback_min`, `lookback_days`).

### Strategy Signals
- Each state machine emits events into a `signals` table.
  - Columns: `id`, `symbol`, `ts`, `session`, `setup`, `score`, `features_ref`, `filters_passed`, `filters_blocked`, `status (generated|blocked|promoted)`.
- Risk module writes veto reasons with foreign key to `signals.id`.

### Orders & Fills
- On order submission: insert into `orders` table with payload snapshot (qty, type, price guard, oco legs).
- Poll Tradier for status/fills or subscribe to webhook; persist into `fills` table (fill price, qty, slippage vs signal reference, latency).
- Derive per-trade PnL and store in `trade_ledger` (links signal → order → fill sequence).

### Account & Session Metrics
- Periodic snapshots of balances and open positions in `account_snapshot(ts, cash, equity, unrealized_pnl, realized_pnl, session)`.
- Daily roll-up table for guardrails: `risk_day(ts_date, trades_taken, r_realized, max_drawdown, breach_flags)`.

### Logging & Audit
- Standardize JSON event logs and stream them to both stdout and a file sink.
- Provide a `ledger` helper that writes to Postgres asynchronously to avoid blocking the trading loop.

## Backtesting & ML Workflow
1. **Replay Engine:** Read `features` and `signals` to re-run strategy logic offline; compare simulated decisions to live `orders` for drift detection.
2. **Label Generation:** Compute outcomes (TP, SL, time stop) using `fills` and `account_snapshot`; attach labels to corresponding `signals`.
3. **Feature Selection:** Export merged dataset (`features` + labels) to notebooks or ML pipelines for tuning thresholds.
4. **Model Deployment:** Any ML-derived settings feed back into YAML `session_policies.yaml` or environment overrides—GPT/analyst review remains human-in-loop.

## Next Steps
- Add TimescaleDB service to `docker-compose.yml` and create migration scripts for tables above.
- Update ingestion services to stream Polygon data into the new tables.
- Extend `FeatureEngine` and state machines to emit persistence events via the central ledger.
- Document retention/backfill procedures and automated maintenance jobs.
