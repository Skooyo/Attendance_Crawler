import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from attendance_crawler.paths import DB_PATH, ensure_dirs


@dataclass
class AttendanceRecord:
    unit_code: str
    code: str
    source: str
    occurred_at: datetime
    context: str
    source_url: str | None = None


SCHEMA = """
CREATE TABLE IF NOT EXISTS attendance_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_code TEXT NOT NULL,
    code TEXT NOT NULL,
    source TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    context TEXT NOT NULL,
    source_url TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(unit_code, code, source, occurred_at)
);
"""


def connect() -> sqlite3.Connection:
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def insert_records(records: Iterable[AttendanceRecord]) -> int:
    conn = connect()
    inserted = 0
    now = datetime.now(timezone.utc).isoformat()
    for r in records:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO attendance_codes
            (unit_code, code, source, occurred_at, context, source_url, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                r.unit_code,
                r.code,
                r.source,
                r.occurred_at.isoformat(),
                r.context[:2000],
                r.source_url,
                now,
            ),
        )
        if cur.rowcount > 0:
            inserted += 1
    conn.commit()
    conn.close()
    return inserted


def fetch_since(days: int) -> list[AttendanceRecord]:
    conn = connect()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    rows = conn.execute(
        """
        SELECT unit_code, code, source, occurred_at, context, source_url
        FROM attendance_codes
        ORDER BY occurred_at DESC
        """
    ).fetchall()
    conn.close()
    out: list[AttendanceRecord] = []
    for row in rows:
        occurred = datetime.fromisoformat(row["occurred_at"])
        if occurred.tzinfo is None:
            occurred = occurred.replace(tzinfo=timezone.utc)
        if occurred < cutoff or occurred > now + timedelta(days=1):
            continue
        out.append(
            AttendanceRecord(
                unit_code=row["unit_code"],
                code=row["code"],
                source=row["source"],
                occurred_at=occurred,
                context=row["context"],
                source_url=row["source_url"],
            )
        )
    return out
