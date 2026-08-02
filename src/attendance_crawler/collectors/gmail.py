"""Gmail API collector for attendance-related emails."""

import base64
import re
from datetime import datetime, timezone
from urllib.parse import unquote

import httpx

from attendance_crawler.config import AppConfig, UnitConfig
from attendance_crawler.extract import (
    format_tutorial_line,
    parse_weekday_date_string,
    session_number_before_time,
    strip_html,
)
from attendance_crawler.llm_extract import extract_entries_hybrid
from attendance_crawler.paths import GMAIL_CREDENTIALS_PATH, GMAIL_TOKEN_PATH
from attendance_crawler.store import AttendanceRecord

_IMG_SRC_RE = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", re.I)


def collect_gmail(config: AppConfig) -> tuple[list[AttendanceRecord], list[str]]:
    errors: list[str] = []
    records: list[AttendanceRecord] = []

    if not GMAIL_CREDENTIALS_PATH.exists():
        errors.append("Gmail: credentials.json not found at project root")
        return records, errors

    try:
        service = _get_gmail_service()
    except Exception as e:
        errors.append(f"Gmail auth failed: {e}")
        return records, errors

    for unit in config.units:
        if not unit.gmail_query:
            continue
        query = unit.gmail_query
        if "newer_than" not in query:
            query = f"newer_than:{config.collect_lookback_days}d {query}"
        try:
            messages = _list_messages(service, query)
            for msg_id in messages:
                recs = _process_message(service, msg_id, unit, config)
                records.extend(recs)
        except Exception as e:
            errors.append(f"Gmail unit {unit.code}: {e}")

    return records, errors


def _get_gmail_service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
    creds = None
    if GMAIL_TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(GMAIL_TOKEN_PATH), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(GMAIL_CREDENTIALS_PATH), SCOPES
            )
            creds = flow.run_local_server(port=0, prompt="select_account")
        with open(GMAIL_TOKEN_PATH, "w") as token:
            token.write(creds.to_json())
    return build("gmail", "v1", credentials=creds)


def _list_messages(service, query: str, max_results: int = 50) -> list[str]:
    result = service.users().messages().list(
        userId="me", q=query, maxResults=max_results
    ).execute()
    return [m["id"] for m in result.get("messages", [])]


def _process_message(
    service, msg_id: str, unit: UnitConfig, config: AppConfig
) -> list[AttendanceRecord]:
    msg = service.users().messages().get(
        userId="me", id=msg_id, format="full"
    ).execute()
    headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
    subject = headers.get("subject", "")
    if unit.gmail_subject_pattern:
        if not re.search(unit.gmail_subject_pattern, subject, re.I):
            return []

    internal_date = int(msg.get("internalDate", 0))
    occurred = datetime.fromtimestamp(internal_date / 1000, tz=timezone.utc)

    body_text, image_blobs, html_raw = _extract_parts(service, msg_id, msg.get("payload", {}))
    image_blobs.extend(_download_images_from_html(html_raw))

    # Regex on body only — subject phrases like "Attendance code" cause false matches
    entries = extract_entries_hybrid(
        text=body_text,
        patterns=config.code_patterns,
        unit_code=unit.code,
        title=subject,
        image_blobs=image_blobs,
        llm_enabled=config.llm_enabled,
        llm_only_when_empty=config.llm_only_when_empty,
        llm_model=config.llm_model,
        default_occurred=occurred,
    )
    source_url = f"https://mail.google.com/mail/u/0/#inbox/{msg_id}"

    return [
        AttendanceRecord(
            unit_code=unit.code,
            code=e.code,
            source="gmail",
            occurred_at=e.occurred_at,
            context=e.context,
            source_url=source_url,
        )
        for e in entries
    ]


def _extract_parts(
    service, msg_id: str, payload: dict
) -> tuple[str, list[bytes], str]:
    texts: list[str] = []
    images: list[bytes] = []
    html_chunks: list[str] = []

    def walk(part: dict):
        mime = part.get("mimeType", "")
        body = part.get("body", {})
        data = body.get("data")
        if data:
            raw = base64.urlsafe_b64decode(data)
            if mime == "text/plain":
                texts.append(raw.decode("utf-8", errors="replace"))
            elif mime == "text/html":
                html = raw.decode("utf-8", errors="replace")
                html_chunks.append(html)
                texts.append(strip_html(html))
            elif mime.startswith("image/"):
                images.append(raw)

        if mime.startswith("image/") and body.get("attachmentId"):
            att = service.users().messages().attachments().get(
                userId="me", messageId=msg_id, id=body["attachmentId"]
            ).execute()
            images.append(base64.urlsafe_b64decode(att["data"]))

        for child in part.get("parts", []):
            walk(child)

    walk(payload)
    return "\n".join(texts), images, "\n".join(html_chunks)


def _download_images_from_html(html: str) -> list[bytes]:
    if not html:
        return []
    blobs: list[bytes] = []
    seen: set[str] = set()
    for match in _IMG_SRC_RE.finditer(html):
        url = unquote(match.group(1).strip())
        if not url.startswith("http://") and not url.startswith("https://"):
            continue
        if url in seen:
            continue
        seen.add(url)
        try:
            resp = httpx.get(url, timeout=60.0, follow_redirects=True)
            if resp.status_code == 200 and len(resp.content) > 100:
                blobs.append(resp.content)
        except Exception:
            continue
    return blobs
