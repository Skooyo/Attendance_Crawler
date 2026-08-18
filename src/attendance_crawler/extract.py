import os
import re
from datetime import datetime, timedelta, timezone
from html import unescape
from io import BytesIO
from pathlib import Path
from typing import Iterable

from bs4 import BeautifulSoup
from PIL import Image, ImageEnhance, ImageOps

try:
    import pytesseract
except ImportError:
    pytesseract = None  # type: ignore

_tesseract_warned = False
_tesseract_cmd_ready = False


def _configure_tesseract_cmd() -> None:
    """Use TESSERACT_CMD or the default Windows install path if PATH has no tesseract."""
    global _tesseract_cmd_ready
    if _tesseract_cmd_ready or pytesseract is None:
        return
    _tesseract_cmd_ready = True
    candidates = [
        os.getenv("TESSERACT_CMD"),
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        str(Path.home() / "AppData/Local/Programs/Tesseract-OCR/tesseract.exe"),
    ]
    for path in candidates:
        if path and Path(path).is_file():
            pytesseract.pytesseract.tesseract_cmd = path
            return


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


def ocr_image_bytes(data: bytes) -> str:
    global _tesseract_warned
    if pytesseract is None:
        return ""
    _configure_tesseract_cmd()
    try:
        img = Image.open(BytesIO(data))
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGBA")
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[-1])
            img = bg
        img = ImageOps.grayscale(img)
        img = ImageEnhance.Contrast(img).enhance(2.0)
        return pytesseract.image_to_string(img).strip()
    except Exception as e:
        if not _tesseract_warned:
            _tesseract_warned = True
            import logging

            logging.getLogger(__name__).warning(
                "Tesseract OCR skipped: %s (install Tesseract and add it to PATH)",
                e,
            )
        return ""


def ocr_blobs_to_text(image_blobs: Iterable[bytes]) -> str:
    parts: list[str] = []
    for blob in image_blobs:
        text = ocr_image_bytes(blob)
        if text:
            parts.append(text)
    return "\n\n".join(parts)


def extract_codes_from_content(
    text: str,
    patterns: Iterable[str],
    image_blobs: Iterable[bytes] = (),
) -> list[str]:
    codes = extract_codes_from_text(text, patterns)
    seen = set(codes)
    for blob in image_blobs:
        ocr_text = ocr_image_bytes(blob)
        for c in extract_codes_from_text(ocr_text, patterns):
            if c not in seen:
                seen.add(c)
                codes.append(c)
    return codes


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
    parts = [session_type.strip() or "Tutorial"]
    if date_str:
        parts.append(date_str.strip())
    if number:
        parts.append(number.strip())
    if time_str:
        parts.append(time_str.strip())
    parts.append(code.strip())
    return " | ".join(parts)


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
