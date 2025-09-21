from __future__ import annotations
import os, json, time, threading
from typing import Any, Dict, List, Tuple

STATE_DIR = os.getenv("STATE_DIR", "/srv/state")
os.makedirs(STATE_DIR, exist_ok=True)
_EV_PATH = os.path.join(STATE_DIR, "events.jsonl")
_lock = threading.Lock()


def _append(obj: Dict[str, Any]) -> None:
    line = json.dumps(obj, ensure_ascii=False)
    with _lock:
        with open(_EV_PATH, "a") as f:
            f.write(line + "\n")


def event(kind: str, **data: Any) -> None:
    rec = {"ts": time.time(), "kind": kind, **data}
    _append(rec)


def read_events(limit: int = 200) -> List[Dict[str, Any]]:
    if not os.path.exists(_EV_PATH):
        return []
    with _lock:
        try:
            with open(_EV_PATH, "r") as f:
                lines = f.readlines()[-int(limit):]
        except Exception:
            return []
    out: List[Dict[str, Any]] = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    return out


def known_order_ids() -> List[str]:
    ids: List[str] = []
    for ev in read_events(limit=10_000):
        oid = None
        if ev.get("kind") in ("order_placed", "order_status", "order_cancel_req", "order_cancel_resp"):
            d = ev.get("data") or {}
            oid = d.get("id") or d.get("order_id")
        if oid and str(oid) not in ids:
            ids.append(str(oid))
    return ids


def summarize_orders() -> List[Dict[str, Any]]:
    # Last status per id
    last: Dict[str, Dict[str, Any]] = {}
    for ev in read_events(limit=10_000):
        if ev.get("kind") in ("order_placed", "order_status", "order_cancel_resp"):
            d = (ev.get("data") or {}).copy()
            oid = str(d.get("id") or d.get("order_id") or "")
            if not oid:
                continue
            d["ts"] = ev.get("ts")
            last[oid] = d
    out = []
    for oid, d in last.items():
        out.append({"id": oid, **d})
    # recent first
    out.sort(key=lambda x: x.get("ts") or 0, reverse=True)
    return out

