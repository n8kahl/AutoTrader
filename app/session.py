from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time as dtime
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import yaml
from zoneinfo import ZoneInfo

from .config import settings


@dataclass(frozen=True)
class SessionPolicy:
    """Normalized policy rules for a named trading session."""

    name: str
    start: dtime
    end: dtime
    allow_setups: frozenset[str] = field(default_factory=frozenset)
    ban_setups: frozenset[str] = field(default_factory=frozenset)
    rvol_min: Optional[float] = None
    ema20_slope_min: Optional[float] = None
    ema20_slope_max: Optional[float] = None
    time_stop_sec: Optional[int] = None
    max_trades: Optional[int] = None
    etf_only: bool = False

    def allows_setup(self, setup: str) -> bool:
        setup_norm = (setup or "").strip().upper()
        if not setup_norm:
            return False
        if setup_norm in self.ban_setups:
            return False
        if self.allow_setups and setup_norm not in self.allow_setups:
            return False
        return True

    def contains(self, moment: datetime, tz: ZoneInfo) -> bool:
        local = moment.astimezone(tz)
        now_t = local.time()
        return self.start <= now_t <= self.end


@dataclass(frozen=True)
class SessionConfig:
    """Container for multiple trading sessions."""

    sessions: Tuple[SessionPolicy, ...]
    timezone: ZoneInfo = ZoneInfo("America/New_York")

    def current(self, moment: Optional[datetime] = None) -> Optional[SessionPolicy]:
        moment = moment or datetime.now(self.timezone)
        for policy in self.sessions:
            if policy.contains(moment, self.timezone):
                return policy
        return None


def _parse_time(label: str, raw: str) -> dtime:
    try:
        hour, minute = [int(x) for x in (raw or "").split(":", 1)]
        return dtime(hour=hour, minute=minute)
    except Exception as exc:  # pragma: no cover - defensive guard
        raise ValueError(f"Invalid time for {label}: {raw!r}") from exc


def _normalize_set(items: Iterable[str]) -> frozenset[str]:
    return frozenset({(s or "").strip().upper() for s in items if (s or "").strip()})


def _load_yaml(path: Path) -> Dict[str, object]:
    if not path.exists():
        raise FileNotFoundError(f"Session policy file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
        if not isinstance(data, dict):
            raise ValueError("Session policy YAML must be a mapping at the top level")
        return data


def _build_session(name: str, payload: Dict[str, object]) -> SessionPolicy:
    if not isinstance(payload, dict):
        raise ValueError(f"Session {name} must map to a dictionary of settings")
    window = payload.get("time_window") or []
    if not (isinstance(window, (list, tuple)) and len(window) == 2):
        raise ValueError(f"Session {name} requires a time_window with [start, end]")
    start = _parse_time(f"{name}.time_window[0]", window[0])
    end = _parse_time(f"{name}.time_window[1]", window[1])

    allow = payload.get("allow_setups") or []
    ban = payload.get("ban_setups") or []
    allow_set = _normalize_set(allow)
    ban_set = _normalize_set(ban)

    return SessionPolicy(
        name=name.upper(),
        start=start,
        end=end,
        allow_setups=allow_set,
        ban_setups=ban_set,
        rvol_min=_maybe_float(payload.get("rvol_min")),
        ema20_slope_min=_maybe_float(payload.get("ema20_slope_min")),
        ema20_slope_max=_maybe_float(payload.get("ema20_slope_max")),
        time_stop_sec=_maybe_int(payload.get("time_stop_sec")),
        max_trades=_maybe_int(payload.get("max_trades")),
        etf_only=bool(payload.get("etf_only", False)),
    )


def _maybe_float(value: object) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _maybe_int(value: object) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


@lru_cache(maxsize=1)
def load_session_config(path_override: Optional[str] = None) -> SessionConfig:
    """Load and cache session configuration from YAML."""

    cfg = settings()
    path = Path(path_override or cfg.session_policy_file).expanduser()
    data = _load_yaml(path)
    sessions_payload = data.get("sessions") or {}
    if not isinstance(sessions_payload, dict) or not sessions_payload:
        raise ValueError("Session policy file must contain a 'sessions' mapping")

    policies: List[SessionPolicy] = []
    for name, payload in sessions_payload.items():
        policies.append(_build_session(str(name), payload))

    timezone_str = data.get("timezone") or "America/New_York"
    try:
        tz = ZoneInfo(timezone_str)
    except Exception as exc:  # pragma: no cover - misconfiguration guard
        raise ValueError(f"Invalid timezone in session policy file: {timezone_str}") from exc

    policies.sort(key=lambda s: (s.start, s.end))
    return SessionConfig(sessions=tuple(policies), timezone=tz)


def reset_session_cache() -> None:
    """Clear the cached session configuration (used in tests / reloads)."""

    load_session_config.cache_clear()

