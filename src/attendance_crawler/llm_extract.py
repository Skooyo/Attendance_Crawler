"""Attendance code extraction: regex for text posts, `claude -p` for image tables."""

import json
import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Iterable

from PIL import Image

from attendance_crawler.extract import (
    extract_codes_from_text,
    format_tutorial_line,
    parse_weekday_date_string,
)

logger = logging.getLogger(__name__)

_CODE_BLOCKLIST = frozenset(
    {"CODES", "CODE", "WEEK", "CLASS", "TUTOR", "EMAIL", "EDSTEM", "MALAYS", "ONLY"}
)

_ENTRIES_SCHEMA = {
    "type": "object",
    "properties": {
        "entries": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["Tutorial", "Workshop"]},
                    "date": {"type": "string"},
                    "number": {"type": "string"},
                    "time": {"type": "string"},
                    "code": {"type": "string"},
                },
                "required": ["type", "date", "number", "time", "code"],
            },
        }
    },
    "required": ["entries"],
}

_PROMPT = """Extract attendance codes for unit {unit_code}.
Post title: {title}

{images_line}
Return one entry per table row (Tutorial or Workshop). Ignore logos and headers.
- date: as shown, e.g. "Wednesday, 29 Jul"
- number: session number exactly as shown, e.g. "01" or "03_OnlineRealTime"
- time: as shown, e.g. "8:00AM"
- code: copy character by character; do not guess similar-looking characters
Use "" for a field the post does not show. If there are no codes, return no entries.

Post text:
{text}
"""

# Set by the last claude call (for debug scripts)
last_llm_error: str | None = None


@dataclass
class ExtractedEntry:
    code: str
    occurred_at: datetime
    context: str


def _filter_codes(codes: list[str]) -> list[str]:
    return [c for c in codes if c.upper() not in _CODE_BLOCKLIST]


def extract_entries_hybrid(
    text: str,
    patterns: Iterable[str],
    unit_code: str,
    title: str = "",
    image_blobs: Iterable[bytes] = (),
    llm_enabled: bool = False,
    llm_only_when_empty: bool = True,
    llm_model: str | None = None,
    llm_effort: str | None = None,
    default_occurred: datetime | None = None,
) -> list[ExtractedEntry]:
    """Image posts go to Claude; text posts use regex, then Claude if regex is empty."""
    global last_llm_error
    last_llm_error = None

    fallback_time = default_occurred or datetime.now(timezone.utc)
    images = _images_as_png(image_blobs)
    body_codes = _filter_codes(extract_codes_from_text(text, patterns))

    if not llm_enabled:
        if images:
            last_llm_error = "llm.enabled is false; image codes skipped"
        return _codes_to_entries(body_codes, fallback_time)
    if not images and llm_only_when_empty and body_codes:
        return _codes_to_entries(body_codes, fallback_time)

    entries = _claude_extract(
        text,
        title,
        unit_code,
        images,
        llm_model or "claude-sonnet-5-5",
        llm_effort or "medium",
        fallback_time,
    )
    if entries is None:
        logger.warning("Claude extraction failed for %s (%s): %s", unit_code, title, last_llm_error)
    return entries or _codes_to_entries(body_codes, fallback_time)


def _codes_to_entries(codes: list[str], occurred: datetime) -> list[ExtractedEntry]:
    return [
        ExtractedEntry(
            code=c,
            occurred_at=occurred,
            context=format_tutorial_line("Tutorial", "", "", "", c),
        )
        for c in codes
    ]


def _images_as_png(blobs: Iterable[bytes]) -> list[bytes]:
    """Decode every image to PNG; drop tiny logos and blobs that are not images."""
    out: list[bytes] = []
    for blob in blobs:
        try:
            img = Image.open(BytesIO(blob))
            if img.width < 120 and img.height < 40:
                continue
            buf = BytesIO()
            img.save(buf, format="PNG")
            out.append(buf.getvalue())
        except Exception:
            continue
    return out


def _claude_extract(
    text: str,
    title: str,
    unit_code: str,
    images: list[bytes],
    model: str,
    effort: str,
    fallback_time: datetime,
) -> list[ExtractedEntry] | None:
    """Run `claude -p` on the post; None on failure, [] when Claude finds no codes."""
    global last_llm_error
    exe = shutil.which("claude")
    if not exe:
        last_llm_error = "claude CLI not found on PATH"
        return None

    names = [f"image_{i + 1}.png" for i in range(len(images))]
    images_line = (
        f"Use the Read tool to open these image files in the current directory: {', '.join(names)}"
        if images
        else "The post has no images."
    )
    prompt = _PROMPT.format(
        unit_code=unit_code,
        title=title,
        images_line=images_line,
        text=(text or "").strip()[:12000],
    )

    with tempfile.TemporaryDirectory(prefix="attendance_") as tmp:
        for name, png in zip(names, images):
            (Path(tmp) / name).write_bytes(png)
        try:
            proc = subprocess.run(
                [
                    exe, "-p",
                    "--model", model,
                    "--effort", effort,
                    "--tools", "Read",
                    "--allowedTools", "Read",
                    "--json-schema", json.dumps(_ENTRIES_SCHEMA),
                    "--output-format", "json",
                    "--no-session-persistence",
                ],
                input=prompt,
                cwd=tmp,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=300,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            last_llm_error = f"claude -p failed: {e}"
            return None

    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError:
        last_llm_error = f"claude -p exit {proc.returncode}: {(proc.stderr or proc.stdout)[:300]}"
        return None
    if result.get("is_error") or not isinstance(result.get("structured_output"), dict):
        last_llm_error = f"claude -p: {str(result.get('result'))[:300]}"
        return None
    return _normalize_entries(result["structured_output"].get("entries") or [], fallback_time)


def _normalize_entries(raw: list, fallback_time: datetime) -> list[ExtractedEntry]:
    out: list[ExtractedEntry] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code", "")).strip().upper()
        if not _valid_code(code) or code in seen or code in _CODE_BLOCKLIST:
            continue
        seen.add(code)
        session_type = str(item.get("type") or "Tutorial")
        date_str = str(item.get("date") or "")
        number = str(item.get("number") or "")
        time_str = str(item.get("time") or "")
        occurred = parse_weekday_date_string(date_str) if date_str else fallback_time
        context = format_tutorial_line(session_type, date_str, number, time_str, code)
        out.append(ExtractedEntry(code=code, occurred_at=occurred, context=context))
    return out


def _valid_code(c: str) -> bool:
    if not c or len(c) < 4 or len(c) > 16:
        return False
    return bool(re.fullmatch(r"[A-Z0-9-]+", c))
