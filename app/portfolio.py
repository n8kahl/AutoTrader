from __future__ import annotations
import os, json, time
from typing import Dict, Any, List, Tuple

from .providers import polygon as poly
from .providers import tradier as t

STATE_DIR = os.getenv("STATE_DIR", "/srv/state")
POS_PATH = os.path.join(STATE_DIR, "positions.json")
PNL_LOG = os.path.join(STATE_DIR, "pnl.jsonl")


def _load_positions() -> Dict[str, Any]:
    try:
        with open(POS_PATH, "r") as f:
            d = json.load(f) or {}
            return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save_positions(d: Dict[str, Any]) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = POS_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f)
    os.replace(tmp, POS_PATH)


def apply_fill(symbol: str, side: str, qty: float, price: float) -> Dict[str, Any]:
    """Update positions with a filled trade and return new position record."""
    s = symbol.upper()
    d = _load_positions()
    p = d.get(s) or {"qty": 0.0, "avg_price": 0.0, "realized_pnl": 0.0}
    q_old = float(p.get("qty") or 0.0)
    avg = float(p.get("avg_price") or 0.0)
    rpnl = float(p.get("realized_pnl") or 0.0)
    q = float(qty)
    px = float(price)
    if side.lower().startswith("buy"):
        q_new = q_old + q
        if q_new > 0:
            avg = (q_old * avg + q * px) / q_new if (q_old + q) else px
        p.update({"qty": q_new, "avg_price": round(avg, 4), "realized_pnl": round(rpnl, 2)})
    else:  # sell or buy_to_cover
        q_new = q_old - q
        rpnl += (px - avg) * q
        p.update({"qty": q_new, "avg_price": round(avg if q_new != 0 else avg, 4), "realized_pnl": round(rpnl, 2)})
        if q_new == 0:
            p["avg_price"] = 0.0
    d[s] = p
    _save_positions(d)
    return p


def positions() -> Dict[str, Any]:
    return _load_positions()


async def _price(symbol: str) -> float | None:
    try:
        lt = await poly.last_trade(symbol)
        px = float(lt.get("price") or 0) or None
        if px:
            return px
    except Exception:
        pass
    try:
        q = await t.get_quote(symbol)
        qq = (q.get("quotes") or {}).get("quote")
        if isinstance(qq, list):
            qq = qq[0] if qq else {}
        px = float((qq or {}).get("last") or 0) or None
        return px
    except Exception:
        return None


async def compute_pnl() -> Dict[str, Any]:
    d = _load_positions()
    out: List[Dict[str, Any]] = []
    total_unreal = 0.0
    total_real = 0.0
    for s, p in d.items():
        qty = float(p.get("qty") or 0)
        avg = float(p.get("avg_price") or 0)
        rpnl = float(p.get("realized_pnl") or 0)
        px = await _price(s)
        unreal = ((px or 0) - avg) * qty if px is not None else None
        out.append({
            "symbol": s,
            "qty": qty,
            "avg_price": avg,
            "last": px,
            "unrealized": round(unreal, 2) if unreal is not None else None,
            "realized": round(rpnl, 2),
        })
        total_real += rpnl
        if unreal is not None:
            total_unreal += unreal
    snap = {
        "ts": time.time(),
        "positions": out,
        "totals": {"realized": round(total_real, 2), "unrealized": round(total_unreal, 2)},
    }
    try:
        with open(PNL_LOG, "a") as f:
            f.write(json.dumps(snap) + "\n")
    except Exception:
        pass
    return snap

