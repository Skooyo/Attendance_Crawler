from datetime import datetime

from attendance_crawler.store import AttendanceRecord


def format_markdown(records: list[AttendanceRecord], days: int) -> str:
    if not records:
        return f"# Attendance codes (last {days} days)\n\nNo codes found.\n"

    lines = [f"# Attendance codes (last {days} days)", ""]
    by_unit: dict[str, list[AttendanceRecord]] = {}
    for r in records:
        by_unit.setdefault(r.unit_code, []).append(r)

    for unit in sorted(by_unit.keys()):
        lines.append(f"## {unit}")
        for r in by_unit[unit]:
            lines.append(f"- {_display_line(r)}")
        lines.append("")

    lines.append(f"**Total:** {len(records)} codes")
    return "\n".join(lines)


def format_hermes(records: list[AttendanceRecord], days: int, silent_when_empty: bool) -> str:
    if not records:
        if silent_when_empty:
            return "[SILENT]"
        return f"Attendance codes (last {days} days)\n\nNo codes found."

    lines = [f"Attendance codes (last {days} days)", ""]
    by_unit: dict[str, list[AttendanceRecord]] = {}
    for r in records:
        by_unit.setdefault(r.unit_code, []).append(r)

    for unit in sorted(by_unit.keys()):
        lines.append(unit)
        for r in by_unit[unit]:
            lines.append(f"- {_display_line(r)}")
        lines.append("")

    lines.append(f"Total: {len(records)} codes")
    return "\n".join(lines)


def _display_line(r: AttendanceRecord) -> str:
    ctx = (r.context or "").replace("\n", " ").strip()
    if ctx and "|" in ctx:
        return ctx
    dt = r.occurred_at.strftime("%a %d %b")
    return f"{r.code} — {dt} — {r.source} — {ctx}"

