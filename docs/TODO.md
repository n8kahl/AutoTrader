# TODO — SPX/NDX Scalper Build

- [ ] Add TimescaleDB container + migrations (ticks, features, signals, orders, fills).
- [ ] Implement `scripts/polygon_ws.py` to stream SPX/NDX second aggregates into Timescale with retry/backoff and Prometheus metrics.
- [ ] Write `scripts/import_flatfiles.py` to sync Polygon flat files (SPX, NDX, SPY, QQQ) and load them into the new tables.
- [ ] Extend `FeatureEngine` for 1s+1m blended features (VWAP, sigma, ATR, EMA slopes, cumulative delta).
- [ ] Create regime labeling job (`scripts/label_regimes.py`) that classifies each session (trend vs consolidation) and stores results.
- [ ] Implement `SPX_TREND_BURST` and `SPX_BALANCED_BREAK` plays plus QQQ proxies with configurable thresholds.
- [ ] Update risk module with regime-aware position sizing and bracket presets tuned for index scalps.
- [ ] Build replay/backtest CLI that rehydrates tick data to verify plays and output expectancy reports.
- [ ] Create Grafana dashboards for regime score, play hit rates, slippage, and latency.
- [ ] Add Discord alerts for websocket disconnects, data lag, and regime flips.
