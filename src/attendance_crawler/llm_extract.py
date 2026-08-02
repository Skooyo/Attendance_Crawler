"""OpenRouter LLM extraction for attendance codes (supplements regex)."""

import base64
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

import httpx

from attendance_crawler.extract import (
    extract_codes_from_content,
    format_tutorial_line,
    parse_weekday_date_string,
)

_CODE_BLOCKLIST = frozenset(
    {"CODES", "CODE", "WEEK", "CLASS", "TUTOR", "EMAIL", "EDSTEM", "MALAYS", "ONLY"}
)

_ENTRIES_PROMPT_SUFFIX = (
    "Return ONLY JSON:\n"
    '{"entries": [{"type": "Tutorial", "date": "Wednesday, 29 Jul", "number": "01", '
    '"time": "8:00AM", "code": "RZL2X"}]}\n'
    "Include every row from workshop/tutorial tables. "
    "Use the exact date, 2-digit session number, and time shown for each code. "
    "If none found, return {\"entries\": []}."
)


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
    default_occurred: datetime | None = None,
) -> list[ExtractedEntry]:
    """Extract structured rows (date, number, time, code) for image-heavy emails/posts."""
    fallback_time = default_occurred or datetime.now(timezone.utc)
    codes = _filter_codes(extract_codes_from_content(text, patterns, image_blobs))
    entries: list[ExtractedEntry] = []

    if not llm_enabled:
        for c in codes:
            entries.append(
                ExtractedEntry(
                    code=c,
                    occurred_at=fallback_time,
                    context=format_tutorial_line("Tutorial", "", "", "", c),
                )
            )
        return entries

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return _codes_to_entries(codes, fallback_time)

    model = llm_model or os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")
    image_list = list(image_blobs)

    if image_list and (not codes or not llm_only_when_empty):
        entries = _extract_entries_vision(
            image_list, unit_code=unit_code, title=title, api_key=api_key, model=model
        )

    if entries:
        return entries

    if llm_only_when_empty and codes:
        return _codes_to_entries(codes, fallback_time)

    entries = _extract_entries_text(
        text=text, unit_code=unit_code, title=title, api_key=api_key, model=model
    )
    if entries:
        return entries

    return _codes_to_entries(codes, fallback_time)


def extract_codes_hybrid(
    text: str,
    patterns: Iterable[str],
    unit_code: str,
    title: str = "",
    image_blobs: Iterable[bytes] = (),
    llm_enabled: bool = False,
    llm_only_when_empty: bool = True,
    llm_model: str | None = None,
) -> list[str]:
    entries = extract_entries_hybrid(
        text=text,
        patterns=patterns,
        unit_code=unit_code,
        title=title,
        image_blobs=image_blobs,
        llm_enabled=llm_enabled,
        llm_only_when_empty=llm_only_when_empty,
        llm_model=llm_model,
    )
    return [e.code for e in entries]


def _codes_to_entries(codes: list[str], occurred: datetime) -> list[ExtractedEntry]:
    return [
        ExtractedEntry(
            code=c,
            occurred_at=occurred,
            context=format_tutorial_line("Tutorial", "", "", "", c),
        )
        for c in codes
    ]


def _extract_entries_vision(
    image_blobs: list[bytes],
    unit_code: str,
    title: str,
    api_key: str,
    model: str,
) -> list[ExtractedEntry]:
    if not image_blobs:
        return []

    prompt = (
        f"Extract attendance table rows from these images for unit {unit_code}.\n"
        f"Title: {title}\n\n"
        + _ENTRIES_PROMPT_SUFFIX
    )
    content_parts: list[dict] = [{"type": "text", "text": prompt}]
    for blob in image_blobs[:4]:
        b64 = base64.b64encode(blob).decode("ascii")
        content_parts.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64}"},
            }
        )

    content = _openrouter_chat(api_key, model, content_parts, timeout=120.0)
    return _parse_entries_json(content)


def _extract_entries_text(
    text: str,
    unit_code: str,
    title: str,
    api_key: str,
    model: str,
) -> list[ExtractedEntry]:
    body = (text or "").strip()
    if not body and not title:
        return []

    prompt = (
        f"Extract attendance rows for unit {unit_code}.\n"
        f"Title: {title}\n\n"
        f"Content:\n{body[:12000]}\n\n"
        + _ENTRIES_PROMPT_SUFFIX
    )
    content = _openrouter_chat(
        api_key, model, [{"type": "text", "text": prompt}], timeout=90.0
    )
    return _parse_entries_json(content)


def _openrouter_chat(
    api_key: str,
    model: str,
    content_parts: list[dict],
    timeout: float,
) -> str:
    try:
        resp = httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/local/attendance-crawler",
                "X-Title": "Attendance Crawler",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": content_parts}],
                "temperature": 0,
            },
            timeout=timeout,
        )
        if resp.status_code != 200:
            return ""
        return resp.json()["choices"][0]["message"]["content"]
    except Exception:
        return ""


def _parse_entries_json(content: str) -> list[ExtractedEntry]:
    if not content:
        return []
    content = content.strip()
    data = None
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\"entries\".*\}", content, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

    if not isinstance(data, dict):
        return []

    raw_entries = data.get("entries")
    if isinstance(raw_entries, list) and raw_entries:
        return _normalize_entries(raw_entries)

    # Legacy {"codes": [...]}
    raw_codes = data.get("codes")
    if isinstance(raw_codes, list):
        now = datetime.now(timezone.utc)
        return _codes_to_entries(_normalize_codes(raw_codes), now)

    return []


def _normalize_entries(raw: list) -> list[ExtractedEntry]:
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
        occurred = parse_weekday_date_string(date_str) if date_str else datetime.now(
            timezone.utc
        )
        context = format_tutorial_line(session_type, date_str, number, time_str, code)
        out.append(ExtractedEntry(code=code, occurred_at=occurred, context=context))
    return out


def _normalize_codes(raw: list) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        c = str(item).strip().upper()
        if _valid_code(c) and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _valid_code(c: str) -> bool:
    if not c or len(c) < 4 or len(c) > 16:
        return False
    return bool(re.fullmatch(r"[A-Z0-9-]+", c))
