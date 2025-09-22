import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_STATE_DIR = PROJECT_ROOT / "tests" / ".pytest_state"
DEFAULT_STATE_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("STATE_DIR", str(DEFAULT_STATE_DIR))

from app import ledger
from app.metrics import autotrader_signal_total
from app import worker
from app.state import save_high_water, save_trade_state


@pytest.fixture(autouse=True)
def _temp_state_dir(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setenv("STATE_DIR", str(state_dir))
    monkeypatch.setattr(ledger, "STATE_DIR", str(state_dir))
    monkeypatch.setattr(ledger, "_EV_PATH", str(state_dir / "events.jsonl"))
    yield


@pytest.fixture(autouse=True)
def _reset_signal_metric():
    autotrader_signal_total._metrics.clear()
    try:
        yield
    finally:
        autotrader_signal_total._metrics.clear()


@pytest.fixture(autouse=True)
def _reset_worker_state():
    worker._ACTIVE_TRADES.clear()
    worker._HIGH_WATER.clear()
    save_trade_state({})
    save_high_water({})
    yield
