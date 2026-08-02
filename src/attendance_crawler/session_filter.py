"""Filter stored codes to the tutorial/workshop session numbers you attend."""

from attendance_crawler.config import UnitConfig
from attendance_crawler.store import AttendanceRecord

_SESSION_TYPES = frozenset({"tutorial", "workshop"})


def _normalize_session_number(value: str) -> str:
    s = (value or "").strip()
    if s.isdigit():
        return f"{int(s):02d}"
    return s


def parse_session_from_context(context: str) -> tuple[str, str] | None:
    """Parse ``Tutorial | date | 03 | 10:00 AM | CODE`` into (type, number)."""
    if not context or "|" not in context:
        return None
    parts = [p.strip() for p in context.split("|")]
    if len(parts) < 3:
        return None
    session_type = parts[0].strip().lower()
    if session_type not in _SESSION_TYPES:
        return None
    number = parts[2].strip()
    if not number:
        return None
    return session_type, number


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
