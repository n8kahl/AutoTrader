from __future__ import annotations
import os
from typing import Dict, Any, List, Tuple
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

from ..config import settings
from .. import session as session_cfg
from ..providers import tradier as t
from ..providers.tradier import TradierHTTPError


def _time_in_window(now_et: datetime, start_str: str, end_str: str) -> bool:
    def _parse(s: str) -> dtime:
        hh, mm = [int(x) for x in (s or "").split(":", 1)]
        return dtime(hour=hh, minute=mm)
    start = _parse(start_str)
    end = _parse(end_str)
    return start <= now_et.time() <= end


async def portfolio_snapshot() -> Dict[str, Any]:
    cfg = settings()
    acct = cfg.tradier_account_id
    out: Dict[str, Any] = {"positions": [], "open_orders": []}
    if not acct:
        return out
    try:
        pos = await t.list_positions(acct)
        raw = (pos.get("positions") or {}).get("position")
        if isinstance(raw, list):
            out["positions"] = raw
        elif isinstance(raw, dict):
            out["positions"] = [raw]
        else:
            out["positions"] = []
    except Exception:
        out["positions"] = []
    try:
        oo = await t.list_orders(acct, status="open")
        raw = (oo.get("orders") or {}).get("order") or []
        out["open_orders"] = raw if isinstance(raw, list) else [raw]
    except Exception:
        pass
    return out


async def evaluate(signal: Dict[str, Any]) -> Tuple[bool, List[str]]:
    cfg = settings()
    reasons: List[str] = []

    sym = (signal.get("symbol") or "").upper()

    # Trading window (America/New_York)
    now_et = datetime.now(ZoneInfo("America/New_York"))
    # Allow per-symbol window override via WINDOW_<SYM>=HH:MM-HH:MM
    win_start, win_end = cfg.trading_window_start, cfg.trading_window_end
    current_session = None
    try:
        ses_cfg = session_cfg.load_session_config()
        current_session = ses_cfg.current(now_et)
        if current_session:
            win_start = current_session.start.strftime("%H:%M")
            win_end = current_session.end.strftime("%H:%M")
    except FileNotFoundError:
        current_session = None
    except Exception:
        current_session = None
    try:
        w = os.getenv(f"WINDOW_{sym}") or None
        if w and "-" in w:
            a, b = w.split("-", 1)
            win_start, win_end = a.strip(), b.strip()
    except Exception:
        pass
    if not _time_in_window(now_et, win_start, win_end):
        reasons.append(f"Outside trading window {win_start}-{win_end} ET")

    # Symbols allow/deny
    if cfg.symbol_blacklist:
        bl = {s.strip().upper() for s in cfg.symbol_blacklist.split(",") if s.strip()}
        if sym in bl:
            reasons.append("Symbol blacklisted")
    if cfg.symbol_whitelist:
        wl = {s.strip().upper() for s in cfg.symbol_whitelist.split(",") if s.strip()}
        if sym not in wl:
            reasons.append("Symbol not in whitelist")

    snap = await portfolio_snapshot()
    open_pos = [p for p in (snap.get("positions") or []) if float(p.get("quantity") or 0) != 0]
    open_orders = (snap.get("open_orders") or [])

    # Concurrency limits
    if len(open_pos) >= cfg.risk_max_concurrent:
        reasons.append(f"Max concurrent positions reached: {cfg.risk_max_concurrent}")
    if len(open_orders) >= cfg.risk_max_open_orders:
        reasons.append(f"Max open orders reached: {cfg.risk_max_open_orders}")

    # Per-symbol limits
    same_sym_pos = [x for x in open_pos if (x.get("symbol") or "").upper() == sym]
    max_per_symbol = cfg.risk_max_positions_per_symbol
    if max_per_symbol is not None and max_per_symbol > 0:
        if len(same_sym_pos) >= max_per_symbol:
            reasons.append(f"Max positions for {sym} reached: {max_per_symbol}")

    # Notional cap
    # Notional cap (symbol override NOTIONAL_<SYM> takes precedence)
    sym_cap = None
    try:
        v = os.getenv(f"NOTIONAL_{sym}")
        if v is not None and str(v).strip() != "":
            sym_cap = float(v)
    except Exception:
        sym_cap = None
    cap = sym_cap if sym_cap is not None else cfg.risk_max_order_notional_usd
    if cap is not None:
        try:
            price = await t.last_trade_price(sym)
        except TradierHTTPError:
            price = None
        if price is None:
            try:
                quote = await t.get_quote(sym)
                qq = (quote.get("quotes") or {}).get("quote")
                if isinstance(qq, list):
                    qq = qq[0] if qq else {}
                price = float((qq or {}).get("last") or 0) or None
            except Exception:
                price = None
        if price:
            qty = int(signal.get("qty") or 0)
            notional = price * qty
            if notional > float(cap):
                reasons.append(f"Order notional ${notional:.2f} exceeds cap ${cap}")

    # Optional: min cash
    if cfg.min_cash_usd is not None and cfg.tradier_account_id:
        try:
            bal = await t.get_balances(cfg.tradier_account_id)
            cash = ((bal.get("balances") or {}).get("cash") or {}).get("cash_available")
            if cash is not None and float(cash) < float(cfg.min_cash_usd):
                reasons.append(f"Cash below minimum ${cfg.min_cash_usd}")
        except Exception:
            pass

    return (len(reasons) == 0), reasons
