import os, json, threading
from typing import Any, Dict

_lock = threading.Lock()
STATE_DIR = os.getenv("STATE_DIR", "/srv/state")
os.makedirs(STATE_DIR, exist_ok=True)
_HF_PATH = os.path.join(STATE_DIR, "high_water.json")
_PROC_PATH = os.path.join(STATE_DIR, "processed.json")
_TRADES_PATH = os.path.join(STATE_DIR, "trades.json")


def _load(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _save(path: str, data: Dict[str, Any]) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def load_high_water() -> Dict[str, float]:
    with _lock:
        d = _load(_HF_PATH)
        return {str(k): float(v) for k, v in d.items()} if isinstance(d, dict) else {}


def save_high_water(d: Dict[str, float]) -> None:
    with _lock:
        _save(_HF_PATH, d)


def load_processed(section: str) -> Dict[str, bool]:
    with _lock:
        d = _load(_PROC_PATH)
        return (d.get(section) if isinstance(d, dict) else {}) or {}


def mark_processed(section: str, key: str) -> None:
    with _lock:
        d = _load(_PROC_PATH)
        if not isinstance(d, dict):
            d = {}
        sec = d.get(section) or {}
        sec[str(key)] = True
        d[section] = sec
        _save(_PROC_PATH, d)


def load_trade_state() -> Dict[str, Any]:
    with _lock:
        data = _load(_TRADES_PATH)
        return data if isinstance(data, dict) else {}


def save_trade_state(data: Dict[str, Any]) -> None:
    with _lock:
        _save(_TRADES_PATH, data)
