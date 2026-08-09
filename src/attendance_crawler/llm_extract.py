"""OpenRouter LLM extraction for attendance codes (supplements regex)."""

import base64
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

import httpx

from attendance_crawler.extract import (
    extract_codes_from_content,
    format_tutorial_line,
    ocr_blobs_to_text,
    parse_weekday_date_string,
)

logger = logging.getLogger(__name__)

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

# Set by last OpenRouter call (for debug scripts)
last_openrouter_error: str | None = None


@dataclass
class ExtractedEntry:
    code: str
    occurred_at: datetime
    context: str


def _filter_codes(codes: list[str]) -> list[str]:
    return [c for c in codes if c.upper() not in _CODE_BLOCKLIST]


_TIME_CODE_RE = re.compile(
    r"(?i)(\d{1,2}:\d{2}\s*(?:AM|PM)|\d{1,2}:\d{2}\s+(?:AM|PM))\s+([A-Z0-9]{5})\b"
)


def _entries_from_ocr_text(
    ocr_text: str,
    patterns: Iterable[str],
    fallback_time: datetime,
) -> list[ExtractedEntry]:
    """Parse attendance rows from Tesseract output; empty list if nothing useful."""
    if not (ocr_text or "").strip():
        return []

    entries: list[ExtractedEntry] = []
    seen: set[str] = set()
    for line in ocr_text.splitlines():
        match = _TIME_CODE_RE.search(line)
        if not match:
            continue
        code = match.group(2).upper()
        if not _valid_code(code) or code in seen or code in _CODE_BLOCKLIST:
            continue
        seen.add(code)
        entries.append(
            ExtractedEntry(
                code=code,
                occurred_at=fallback_time,
                context=format_tutorial_line(
                    "Tutorial", "", "", match.group(1), code
                ),
            )
        )
    if entries:
        return entries

    codes = _filter_codes(extract_codes_from_content(ocr_text, patterns, ()))
    if codes:
        return _codes_to_entries(codes, fallback_time)
    return []


def extract_entries_hybrid(
    text: str,
    patterns: Iterable[str],
    unit_code: str,
    title: str = "",
    image_blobs: Iterable[bytes] = (),
    llm_enabled: bool = False,
    llm_only_when_empty: bool = True,
    llm_model: str | None = None,
    llm_max_tokens: int = 2048,
    default_occurred: datetime | None = None,
) -> list[ExtractedEntry]:
    """Extract structured rows. Image posts: OCR first; LLM only if OCR finds nothing."""
    global last_openrouter_error
    last_openrouter_error = None

    fallback_time = default_occurred or datetime.now(timezone.utc)
    image_list = list(image_blobs)
    has_images = bool(image_list)

    body_codes = _filter_codes(
        extract_codes_from_content(text, patterns, () if has_images else image_list)
    )

    if not llm_enabled:
        ocr_only = image_list if has_images else ()
        codes = _filter_codes(
            extract_codes_from_content(text, patterns, ocr_only)
        )
        return _codes_to_entries(codes, fallback_time)

    api_key = os.getenv("OPENROUTER_API_KEY")
    model = llm_model or os.getenv("OPENROUTER_MODEL", "openrouter/free")

    if has_images:
        ocr_text = ocr_blobs_to_text(image_list)
        ocr_entries = _entries_from_ocr_text(ocr_text, patterns, fallback_time)
        if ocr_entries:
            logger.debug(
                "OCR extracted %s code(s) for %s — skipping LLM",
                len(ocr_entries),
                unit_code,
            )
            return ocr_entries

        if api_key:
            entries = _extract_entries_vision(
                image_list,
                unit_code=unit_code,
                title=title,
                api_key=api_key,
                model=model,
                max_tokens=llm_max_tokens,
            )
            if entries:
                return entries
            logger.warning(
                "Vision extraction returned no entries for %s (%s). Last API: %s",
                unit_code,
                title,
                last_openrouter_error or "unknown",
            )
            if ocr_text.strip():
                entries = _extract_entries_text(
                    text=ocr_text,
                    unit_code=unit_code,
                    title=title,
                    api_key=api_key,
                    model=model,
                    max_tokens=llm_max_tokens,
                )
                if entries:
                    return entries
        else:
            last_openrouter_error = "OPENROUTER_API_KEY not set"

        return _codes_to_entries(body_codes, fallback_time)

    # No images: regex then optional text LLM
    if llm_only_when_empty and body_codes:
        return _codes_to_entries(body_codes, fallback_time)

    if api_key:
        entries = _extract_entries_text(
            text=text,
            unit_code=unit_code,
            title=title,
            api_key=api_key,
            model=model,
            max_tokens=llm_max_tokens,
        )
        if entries:
            return entries

    return _codes_to_entries(body_codes, fallback_time)


def extract_codes_hybrid(
    text: str,
    patterns: Iterable[str],
    unit_code: str,
    title: str = "",
    image_blobs: Iterable[bytes] = (),
    llm_enabled: bool = False,
    llm_only_when_empty: bool = True,
    llm_model: str | None = None,
    llm_max_tokens: int = 2048,
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
        llm_max_tokens=llm_max_tokens,
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


def _guess_image_mime(blob: bytes) -> str:
    if blob[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if blob[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if blob[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if len(blob) >= 12 and blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def _extract_entries_vision(
    image_blobs: list[bytes],
    unit_code: str,
    title: str,
    api_key: str,
    model: str,
    max_tokens: int,
) -> list[ExtractedEntry]:
    if not image_blobs:
        return []

    prompt = (
        f"These images are attendance code tables (tutorial/workshop) for {unit_code}.\n"
        f"Title: {title}\n"
        "Read every row from the table images.\n\n"
        + _ENTRIES_PROMPT_SUFFIX
    )
    content_parts: list[dict] = [{"type": "text", "text": prompt}]
    for blob in image_blobs[:4]:
        mime = _guess_image_mime(blob)
        b64 = base64.b64encode(blob).decode("ascii")
        content_parts.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"},
            }
        )

    content = _openrouter_chat(api_key, model, content_parts, timeout=120.0, max_tokens=max_tokens)
    return _parse_entries_json(content)


def _extract_entries_text(
    text: str,
    unit_code: str,
    title: str,
    api_key: str,
    model: str,
    max_tokens: int,
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
        api_key,
        model,
        [{"type": "text", "text": prompt}],
        timeout=90.0,
        max_tokens=max_tokens,
    )
    return _parse_entries_json(content)


def _openrouter_chat(
    api_key: str,
    model: str,
    content_parts: list[dict],
    timeout: float,
    max_tokens: int = 2048,
) -> str:
    global last_openrouter_error
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
                "max_tokens": max_tokens,
            },
            timeout=timeout,
        )
        if resp.status_code != 200:
            last_openrouter_error = f"HTTP {resp.status_code}: {resp.text[:300]}"
            logger.warning("OpenRouter error: %s", last_openrouter_error)
            return ""
        last_openrouter_error = None
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        last_openrouter_error = str(e)
        logger.warning("OpenRouter request failed: %s", e)
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
