"""Filter stored codes to the tutorial/workshop session numbers you attend."""

import re

from attendance_crawler.config import UnitConfig
from attendance_crawler.store import AttendanceRecord

_SESSION_TYPES = frozenset({"tutorial", "workshop"})


def _normalize_session_number(value: str) -> str:
    s = (value or "").strip()
    if s.isdigit():
        return f"{int(s):02d}"
    return s


def _looks_like_session_number(value: str) -> bool:
    """Return True if *value* looks like a real session number (2-digit or
    OnlineRealTime token) rather than a time string or a code that landed in
    the wrong column because an older extract used a non-canonical context layout."""
    v = value.strip()
    if not v:
        return False
    if re.match(r"^\d{2}$", v):
        return True
    if re.match(r"^\d{2}_OnlineRealTime$", v, re.I):
        return True
    return False


def parse_session_from_context(context: str) -> tuple[str, str] | None:
    """Parse ``Tutorial | date | 03 | 10:00 AM | CODE`` into (type, number).

    In the canonical 5-column layout the session number is at column index 2.
    For legacy contexts that used fewer/fragmented columns, the value at index 2
    may be a time or the code itself — in that case the session number is unknown
    and we return ``None`` so callers can decide how to handle it.
    """
    if not context or "|" not in context:
        return None
    parts = [p.strip() for p in context.split("|")]
    if len(parts) < 2:
        return None
    session_type = parts[0].strip().lower()
    if session_type not in _SESSION_TYPES:
        return None
    # Prefer the canonical column-2 value when it looks like a real session
    # number; otherwise the layout is too degenerate to trust index 2.
    if len(parts) >= 3 and _looks_like_session_number(parts[2]):
        number = parts[2].strip()
        if not number:
            return None
        return session_type, number
    return None


def filter_records_for_my_sessions(
    records: list[AttendanceRecord],
    units: list[UnitConfig],
) -> list[AttendanceRecord]:
    """Keep only rows matching each unit's ``my_sessions`` map (if configured)."""
    by_code = {u.code.upper(): u for u in units}
    out: list[AttendanceRecord] = []
    for r in records:
        unit = by_code.get(r.unit_code.upper())
        if not unit or not unit.my_sessions:
            out.append(r)
            continue
        parsed = parse_session_from_context(r.context or "")
        if not parsed:
            continue
        session_type, number = parsed
        allowed = unit.my_sessions.get(session_type)
        if allowed is None:
            out.append(r)
            continue
        allowed_norm = {_normalize_session_number(x) for x in allowed}
        if _normalize_session_number(number) in allowed_norm:
            out.append(r)
    return out
