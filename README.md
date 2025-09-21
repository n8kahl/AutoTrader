AutoTrader — Lean, Self‑Hosted Autotrading Service

Purpose
- Automate entries based on your existing trading setups with tight risk controls.
- Run on a single VM with Docker Compose. Tradier supplies equity quotes/bars + order routing; Polygon powers options analytics (IV, OI, chains).

Components
- `api`: FastAPI service with health, provider checks, dry‑run order endpoint, and Prometheus metrics.
- `worker`: Background loop that scans and (optionally) places orders according to simple rules (dry‑run by default).

Quick Start (Sandbox)
1) Copy env template and fill keys
   - `cp .env.example .env`
   - Set: `TRADIER_ACCESS_TOKEN`, `TRADIER_ENV=sandbox`, `TRADIER_ACCOUNT_ID`, `POLYGON_API_KEY`
   - Optional: `USE_POLYGON_EQUITY=1` once your Polygon tier includes real-time stock aggregates (kept `0` in sandbox to avoid 403 errors)
   - Keep `DRY_RUN=1` until you’re ready to send real orders.
2) Build and run
   - `docker compose build`
   - `docker compose up -d`
3) Verify
   - Health: `http://YOUR_HOST:8080/api/v1/diag/health`
   - Providers: `http://YOUR_HOST:8080/api/v1/diag/providers`
   - Metrics: `http://YOUR_HOST:8080/metrics`
   - Dry‑run trade (Terminal):
     ```
     curl -s -X POST http://YOUR_HOST:8080/api/v1/trade/dryrun \
      -H 'Content-Type: application/json' \
      -d '{"symbol":"AAPL","side":"buy","qty":1,"type":"market"}' | jq
     ```

Strategy (EMA crossover)
- Signals: Buy when 1m EMA20 crosses above EMA50 and price is above EMA50; one signal per symbol when the cross happens.
- Configure symbols and qty in `.env`:
  - `SYMBOLS=AAPL,MSFT,TSLA,SPY,QQQ`
  - `ORDER_QTY=1`
  - `STRATEGY_INTERVAL=1m|5m|1d` (defaults to 1m; 5m or 1d if your data tier limits intraday)
- State machines for VWAP/Sigma/HOD plays are scaffolded under `app/engine/plays.py`; legacy EMA crossover remains the default until the new logic is enabled.

Risk Guardrails
- Time window in America/New_York: `TRADING_WINDOW_START=09:31`, `TRADING_WINDOW_END=15:55`
- Concurrency: `RISK_MAX_CONCURRENT=3`, `RISK_MAX_OPEN_ORDERS=5`
- Optional limits: `SYMBOL_WHITELIST`, `SYMBOL_BLACKLIST`, `MIN_CASH_USD`
- The worker prints reasons when a signal is blocked by risk.

Session Policies (advanced)
- Define time-of-day playbooks and setup gates in `session_policies.yaml` (copy from `session_policies.example.yaml`).
- Point to a custom file with `SESSION_POLICY_FILE=/path/to/policies.yaml` if desired.
- When present, the risk engine uses the active session window instead of the global trading window settings.

Brackets (optional)
- Enable a simple bracket when entering longs by setting both:
  - `STOP_PCT=0.01` and `TP_PCT=0.02` (example = 1% stop, 2% target)
- The worker sends an advanced OTOCO order using last trade as the base.

Signals preview
- See what the worker would do and which risk checks would block it:
  - `curl -s http://YOUR_HOST:8080/api/v1/signals | jq`

Per‑symbol overrides
- Set env vars for specific symbols (decimals for pct values):
  - `QTY_AAPL=2`
  - `STOP_AAPL=0.0125` (1.25%)
  - `TP_AAPL=0.02` (2%)
  - `TRAIL_AAPL=0.01`, `TRAIL_ACT_AAPL=0.01`
- Check effective config:
  - `curl -s "http://YOUR_HOST:8080/api/v1/config/effective?symbol=AAPL" | jq`

Cancel helpers
- Cancel all open orders (optionally for one symbol):
  - All: `curl -s -X POST "http://YOUR_HOST:8080/api/v1/orders/cancel_all" | jq`
  - One: `curl -s -X POST "http://YOUR_HOST:8080/api/v1/orders/cancel_all?symbol=AAPL" | jq`
 - Cancel stale (> N minutes):
  - `curl -s -X POST "http://YOUR_HOST:8080/api/v1/orders/cancel_stale?minutes=60" | jq`

Bracket preview
- Preview stop/target and notional before placing:
  - `curl -s "http://YOUR_HOST:8080/api/v1/bracket/preview?symbol=AAPL&qty=1&stop_pct=0.01&tp_pct=0.02" | jq`
  - Add `&price=235.10` to override price when data providers are limited.

Place bracket order
- POST with JSON body; respects DRY_RUN and risk checks (use `force:true` to bypass risk):
```
curl -s -X POST http://YOUR_HOST:8080/api/v1/bracket/place \
 -H 'Content-Type: application/json' \
 -d '{
   "symbol":"AAPL", "qty":1, "type":"market",
   "stop_pct":0.01, "tp_pct":0.02
 }' | jq
```
- Limit entry example (uses price as entry and as bracket base):
```
curl -s -X POST http://YOUR_HOST:8080/api/v1/bracket/place \
 -H 'Content-Type: application/json' \
 -d '{
   "symbol":"AAPL", "qty":1, "type":"limit", "price":235.10,
   "stop_pct":0.01, "tp_pct":0.02
 }' | jq
```

Trailing exit (optional)
- Enable in `.env`: `TRAIL_PCT=0.01` (1% trail), optionally `TRAIL_ACT_PCT=0.01` to activate after 1% gain.
- Worker tracks a simple in‑memory high watermark per symbol and sells when price <= high*(1-TRAIL_PCT).

Environment
- `TRADIER_ACCESS_TOKEN` — sandbox or production token
- `TRADIER_ENV` — `sandbox` or `prod` (selects base URL)
- `TRADIER_ACCOUNT_ID` — e.g., `VA12345678`
- `POLYGON_API_KEY` — for quotes/bars
- `DRY_RUN` — `1` to simulate orders, `0` to send to Tradier
- `SCAN_INTERVAL_SEC` — how often the worker scans (default 30)

Notes
- Sandbox quotes/orders are delayed ~15 minutes; streaming is not available.
- Start with `DRY_RUN=1`. Switch to `0` only after confirming behavior.

Roadmap & Data
- `docs/data_capture_plan.md` outlines the TimescaleDB ingest, feature store, and logging roadmap that powers backtests and ML analysis.

Order Management (new)
- List orders:
  - `curl -s http://YOUR_HOST:8080/api/v1/orders | jq`
- Get one order:
  - `curl -s http://YOUR_HOST:8080/api/v1/orders/ORDER_ID | jq`
- Cancel order:
  - `curl -s -X POST http://YOUR_HOST:8080/api/v1/orders/ORDER_ID/cancel | jq`
- Positions:
  - `curl -s http://YOUR_HOST:8080/api/v1/positions | jq`
- Account balances:
  - `curl -s http://YOUR_HOST:8080/api/v1/account/balances | jq`

Flatten positions (safety)
- Close all or a single symbol at market:
  - All: `curl -s -X POST "http://YOUR_HOST:8080/api/v1/positions/flatten" | jq`
  - One: `curl -s -X POST "http://YOUR_HOST:8080/api/v1/positions/flatten?symbol=AAPL" | jq`
Risk preview
- Evaluate a hypothetical order with current risk settings and get rough notional:
  - `curl -s "http://YOUR_HOST:8080/api/v1/risk/preview?symbol=AAPL&qty=1" | jq`

State persistence
- Trailing high-water survives restarts (stored under `/srv/state`). Docker Compose mounts `./state` so the data persists.
