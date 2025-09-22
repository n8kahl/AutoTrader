#!/usr/bin/env python3
"""Replay recent signals to estimate expectancy."""

import argparse
import json

from app.backtest.replay import replay_signals_sync


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=500, help="Number of ledger events to inspect")
    parser.add_argument("--horizon", type=int, default=15, help="Minutes ahead to measure outcome")
    args = parser.parse_args()

    summary = replay_signals_sync(limit=args.limit, horizon_minutes=args.horizon)
    print(json.dumps(summary, indent=2, default=lambda o: o.__dict__))


if __name__ == "__main__":
    main()
