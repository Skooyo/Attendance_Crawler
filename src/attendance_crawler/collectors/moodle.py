"""Moodle announcements/forums collector via Playwright."""

import re
from datetime import datetime, timezone
from urllib.parse import urljoin

from attendance_crawler.auth_moodle import moodle_session_valid
from attendance_crawler.config import AppConfig, UnitConfig
from attendance_crawler.extract import (
    extract_codes_from_content,
    format_tutorial_line,
    parse_weekday_date_string,
    session_number_before_time,
    strip_html,
)
from attendance_crawler.paths import MOODLE_STATE_PATH
from attendance_crawler.store import AttendanceRecord

AUTH_REQUIRED = "AUTH_REQUIRED: moodle"

_ATTENDANCE_RE = re.compile(r"mod/attendance/view\.php\?[^\"']*id=(\d+)", re.I)
_DATE_RE = re.compile(
    r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s*(\d{1,2})\s+"
    r"(January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)",
    re.I,
)
_TIME_CODE_RE = re.compile(
    r"(?i)(\d{1,2}:\d{2}\s*(?:AM|PM)|\d{1,2}:\d{2}\s+(?:AM|PM))\s+([A-Z0-9]{5})\b"
)


def collect_moodle(config: AppConfig) -> tuple[list[AttendanceRecord], list[str]]:
    errors: list[str] = []
    records: list[AttendanceRecord] = []

    if not moodle_session_valid(config):
        errors.append(AUTH_REQUIRED)
        return records, errors

    base = config.moodle_base_url
    units_with_moodle = [
        u for u in config.units
        if u.moodle_paths or u.moodle_course_id is not None
    ]
    if not units_with_moodle:
        return records, errors

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        errors.append("Playwright not installed")
        return records, errors

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=str(MOODLE_STATE_PATH))
        page = context.new_page()

        page.goto(base, wait_until="domcontentloaded", timeout=60000)
        if _is_login_page(page.url):
            errors.append(AUTH_REQUIRED)
            browser.close()
            return records, errors

        for unit in units_with_moodle:
            to_visit = _build_unit_urls(base, unit)

            if unit.moodle_course_id is not None and unit.moodle_discover_sections:
                course_url = f"{base}/course/view.php?id={unit.moodle_course_id}"
                try:
                    page.goto(course_url, wait_until="domcontentloaded", timeout=60000)
                    if _is_login_page(page.url):
                        errors.append(AUTH_REQUIRED)
                    else:
                        discovered = _discover_urls_from_html(
                            page.content(), base, unit.moodle_course_id
                        )
                        for u in discovered:
                            if u not in to_visit:
                                to_visit.append(u)
                except Exception as e:
                    errors.append(f"Moodle {unit.code} discover: {e}")

            for url in to_visit:
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    if _is_login_page(page.url):
                        errors.append(AUTH_REQUIRED)
                        continue
                    recs = _extract_from_page(page, unit.code, url, config.code_patterns)
                    records.extend(recs)
                except Exception as e:
                    errors.append(f"Moodle {unit.code} {url}: {e}")

        browser.close()

    return records, errors


def _build_unit_urls(base: str, unit: UnitConfig) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()

    def add(url: str) -> None:
        if url not in seen:
            seen.add(url)
            urls.append(url)

    for path in unit.moodle_paths:
        add(path if path.startswith("http") else urljoin(base + "/", path.lstrip("/")))

    if unit.moodle_course_id is not None:
        cid = unit.moodle_course_id
        add(f"{base}/course/view.php?id={cid}")
        for section_id in unit.moodle_section_ids:
            add(f"{base}/course/view.php?id={cid}&section={section_id}")

    return urls


def _discover_urls_from_html(html: str, base: str, course_id: int) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    section_patterns = [
        re.compile(
            rf"course/view\.php\?id={course_id}&section=(\d+)",
            re.I,
        ),
        re.compile(
            rf"[?&]id={course_id}[^\"']*section=(\d+)",
            re.I,
        ),
    ]
    for pattern in section_patterns:
        for match in pattern.finditer(html):
            section = match.group(1)
            url = f"{base}/course/view.php?id={course_id}&section={section}"
            if url not in seen:
                seen.add(url)
                found.append(url)

    for match in _ATTENDANCE_RE.finditer(html):
        att_id = match.group(1)
        url = f"{base}/mod/attendance/view.php?id={att_id}"
        if url not in seen:
            seen.add(url)
            found.append(url)

    return found


def _is_login_page(url: str) -> bool:
    lower = url.lower()
    return "okta" in lower or ("login" in lower and "moodle" not in lower)


def _extract_from_page(
    page, unit_code: str, url: str, patterns: list[str]
) -> list[AttendanceRecord]:
    html = page.content()
    text = strip_html(html)

    blocks: list[str] = []
    for selector in (
        ".forum-post-content",
        ".post-content-container",
        ".contentwithoutlink",
        "article",
        ".announcement",
        "#region-main",
        ".course-content",
    ):
        for el in page.locator(selector).all()[:50]:
            try:
                blocks.append(el.inner_text())
            except Exception:
                pass

    combined = "\n".join(blocks) if blocks else text
    records = _records_from_tutorial_table(unit_code, url, combined, patterns)

    if not records:
        codes = extract_codes_from_content(combined, patterns)
        occurred = datetime.now(timezone.utc)
        context = combined[:200] if combined else url
        records = [
            AttendanceRecord(
                unit_code=unit_code,
                code=c,
                source="moodle",
                occurred_at=occurred,
                context=context,
                source_url=url,
            )
            for c in codes
        ]

    return records


def _records_from_tutorial_table(
    unit_code: str, url: str, text: str, patterns: list[str]
) -> list[AttendanceRecord]:
    """Parse Moodle tutorial rows: date, time, 5-char code on same line."""
    records: list[AttendanceRecord] = []
    seen_codes: set[str] = set()

    for line in text.splitlines():
        line = line.strip()
        if not line or "tutorial" not in line.lower():
            continue
        time_code = _TIME_CODE_RE.search(line)
        if not time_code:
            continue
        code = time_code.group(2)
        if code in seen_codes:
            continue
        seen_codes.add(code)

        date_match = _DATE_RE.search(line)
        occurred = (
            parse_weekday_date_string(date_match.group(0))
            if date_match
            else datetime.now(timezone.utc)
        )
        number = session_number_before_time(line, time_code.start())
        context = format_tutorial_line(
            "Tutorial",
            date_match.group(0) if date_match else "",
            number,
            time_code.group(1),
            code,
        )

        records.append(
            AttendanceRecord(
                unit_code=unit_code,
                code=code,
                source="moodle",
                occurred_at=occurred,
                context=context,
                source_url=url,
            )
        )

    if records:
        return records

    # Multi-row tables sometimes collapse into one block — scan per Tutorial chunk
    for chunk in re.split(r"(?i)(?=Tutorial)", text):
        if "tutorial" not in chunk.lower():
            continue
        for time_code in _TIME_CODE_RE.finditer(chunk):
            code = time_code.group(2)
            if code in seen_codes:
                continue
            seen_codes.add(code)
            date_match = _DATE_RE.search(chunk)
            occurred = (
                parse_weekday_date_string(date_match.group(0))
                if date_match
                else datetime.now(timezone.utc)
            )
            number = session_number_before_time(chunk, time_code.start())
            context = format_tutorial_line(
                "Tutorial",
                date_match.group(0) if date_match else "",
                number,
                time_code.group(1),
                code,
            )
            records.append(
                AttendanceRecord(
                    unit_code=unit_code,
                    code=code,
                    source="moodle",
                    occurred_at=occurred,
                    context=context,
                    source_url=url,
                )
            )

    if records:
        return records

    # No tutorial rows — do not scrape random 5-char tokens from the whole course page
    return []


