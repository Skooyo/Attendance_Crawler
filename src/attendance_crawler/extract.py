import re
from datetime import datetime, timedelta, timezone
from html import unescape
from typing import Iterable

from bs4 import BeautifulSoup


def strip_html(html: str) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator=" ", strip=True)
    return unescape(re.sub(r"\s+", " ", text))


def extract_codes_from_text(text: str, patterns: Iterable[str]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for pattern in patterns:
        try:
            for match in re.finditer(pattern, text):
                code = match.group(1).strip()
                if code and code not in seen:
                    seen.add(code)
                    found.append(code)
        except re.error:
            continue
    return found


_DATE_RE = re.compile(
    r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s*(\d{1,2})\s+"
    r"(January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)",
    re.I,
)


def format_tutorial_line(
    session_type: str,
    date_str: str,
    number: str,
    time_str: str,
    code: str,
) -> str:
    # Always emit 5 pipe-separated fields so downstream parsers can rely on
    # fixed column positions (index 2 = session number) regardless of which
    # metadata the extractor managed to capture.
    return " | ".join([
        session_type.strip() or "Tutorial",
        date_str.strip() if date_str else "",
        number.strip() if number else "",
        time_str.strip() if time_str else "",
        code.strip(),
    ])


def parse_weekday_date_string(date_str: str) -> datetime:
    match = _DATE_RE.search(date_str)
    if not match:
        return datetime.now(timezone.utc)
    month_map = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
        "january": 1, "february": 2, "march": 3, "april": 4, "june": 6,
        "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
        "december": 12,
    }
    day = int(match.group(2))
    month_key = match.group(3).lower()
    month = month_map.get(month_key) or month_map.get(month_key[:3], 1)
    year = datetime.now(timezone.utc).year
    try:
        dt = datetime(year, month, day, tzinfo=timezone.utc)
    except ValueError:
        return datetime.now(timezone.utc)
    now = datetime.now(timezone.utc)
    if dt > now + timedelta(days=14):
        try:
            dt = dt.replace(year=year - 1)
        except ValueError:
            pass
    return dt


def session_number_before_time(text: str, time_start: int) -> str:
    before = text[:time_start]
    nums = re.findall(r"\b(\d{2})\b", before)
    return nums[-1] if nums else ""
