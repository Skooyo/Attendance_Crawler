"""EdStem API collector."""

import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from attendance_crawler.config import AppConfig, UnitConfig
from attendance_crawler.extract import strip_html
from attendance_crawler.llm_extract import extract_entries_hybrid
from attendance_crawler.store import AttendanceRecord


def collect_edstem(config: AppConfig) -> tuple[list[AttendanceRecord], list[str]]:
    errors: list[str] = []
    records: list[AttendanceRecord] = []

    if not config.ed_api_token:
        errors.append("EdStem: ED_API_TOKEN not set")
        return records, errors

    headers = {
        "Authorization": f"Bearer {config.ed_api_token}",
        "Content-Type": "application/json",
    }
    base = config.ed_base_url.rstrip("/")
    cutoff = datetime.now(timezone.utc) - timedelta(days=config.edstem_lookback_days)

    with httpx.Client(headers=headers, timeout=60.0) as client:
        for unit in config.units:
            if unit.ed_course_id is None:
                continue
            course_id = unit.ed_course_id
            try:
                threads = _list_threads(client, base, course_id)
                matched = 0
                considered = 0
                for thread in threads:
                    if not isinstance(thread, dict):
                        continue
                    if not _thread_within_lookback(thread, cutoff):
                        continue
                    considered += 1
                    recs = _thread_to_records(
                        client,
                        base,
                        config.ed_region,
                        unit,
                        thread,
                        config,
                        lookback_cutoff=cutoff,
                    )
                    if recs:
                        matched += 1
                    records.extend(recs)
                if unit.ed_thread_title_pattern and matched == 0 and considered == 0 and threads:
                    errors.append(
                        f"EdStem {unit.code}: no threads in last "
                        f"{config.edstem_lookback_days:g} days "
                        f"(listed {len(threads)}; check lookback or filters)"
                    )
                elif unit.ed_thread_title_pattern and matched == 0 and considered > 0:
                    errors.append(
                        f"EdStem {unit.code}: {considered} recent thread(s) but 0 codes "
                        f"(title/author match or extraction failed)"
                    )
            except Exception as e:
                errors.append(f"EdStem unit {unit.code}: {e}")

    return records, errors


def _list_threads(client: httpx.Client, base: str, course_id: int) -> list[dict]:
    """Recent threads first (Ed API has no created_after param)."""
    resp = client.get(
        f"{base}/courses/{course_id}/threads",
        params={"limit": 100, "sort": "new"},
    )
    resp.raise_for_status()
    data = resp.json()
    threads = _extract_thread_list(data)
    return [t for t in threads if isinstance(t, dict)]


def _thread_created_at(thread: dict) -> datetime:
    for key in ("created_at", "created", "last_activity_at", "updated_at"):
        if thread.get(key) is not None:
            return _parse_ed_time(thread.get(key))
    return datetime.now(timezone.utc)


def _thread_within_lookback(thread: dict, cutoff: datetime) -> bool:
    return _thread_created_at(thread) >= cutoff


def _extract_thread_list(data: Any) -> list[Any]:
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    threads = data.get("threads")
    if isinstance(threads, list):
        return threads
    if isinstance(threads, dict):
        return list(threads.values())
    return []


def _author_needles(unit: UnitConfig) -> list[str]:
    raw = unit.ed_author_name
    if not raw:
        return []
    if isinstance(raw, str):
        return [raw] if raw.strip() else []
    return [str(x).strip() for x in raw if str(x).strip()]


def _author_matches(unit: UnitConfig, author_name: str) -> bool:
    needles = _author_needles(unit)
    if not needles or not author_name:
        return True
    author = author_name.lower()
    return any(n.lower() in author for n in needles)


def _thread_matches_filters(unit: UnitConfig, title: str, author_name: str) -> bool:
    if unit.ed_thread_title_pattern:
        if not re.search(unit.ed_thread_title_pattern, title, re.I):
            return False
    if not _author_matches(unit, author_name):
        return False
    return True


def _author_name_from_thread(thread: dict, envelope: Any = None) -> str:
    for key in ("user", "creator", "author"):
        obj = thread.get(key)
        if isinstance(obj, dict):
            name = obj.get("name") or obj.get("full_name") or ""
            if name:
                return str(name)

    user_id = thread.get("user_id") or thread.get("creator_id")
    if user_id is None:
        return ""

    user = _resolve_user(envelope, user_id)
    if isinstance(user, dict):
        name = user.get("name") or user.get("full_name") or ""
        if name:
            return str(name)
    return ""


def _resolve_user(envelope: Any, user_id: Any) -> dict | None:
    if envelope is None:
        return None
    users_raw: Any = None
    if isinstance(envelope, dict):
        users_raw = envelope.get("users")
    if users_raw is None:
        return None

    uid = str(user_id)
    if isinstance(users_raw, dict):
        u = users_raw.get(uid) or users_raw.get(user_id)
        return u if isinstance(u, dict) else None
    if isinstance(users_raw, list):
        for u in users_raw:
            if not isinstance(u, dict):
                continue
            if str(u.get("id")) == uid:
                return u
    return None


def _normalize_thread_detail(envelope: Any, fallback: dict) -> dict:
    if isinstance(envelope, list):
        for item in envelope:
            if isinstance(item, dict) and item.get("title"):
                return item
        return fallback
    if not isinstance(envelope, dict):
        return fallback

    detail = envelope.get("thread", envelope)
    if isinstance(detail, list):
        for item in detail:
            if isinstance(item, dict):
                return item
        return fallback
    if isinstance(detail, dict):
        return detail
    return fallback


def _thread_to_records(
    client: httpx.Client,
    base: str,
    region: str,
    unit: UnitConfig,
    thread: dict,
    config: AppConfig,
    *,
    lookback_cutoff: datetime | None = None,
) -> list[AttendanceRecord]:
    thread_id = thread.get("id")
    if thread_id is None:
        return []

    if lookback_cutoff is not None and not _thread_within_lookback(thread, lookback_cutoff):
        return []

    title_stub = str(thread.get("title") or "").strip()
    if unit.ed_thread_title_pattern and title_stub:
        if not re.search(unit.ed_thread_title_pattern, title_stub, re.I):
            return []

    envelope: Any = {}
    detail = thread
    try:
        r = client.get(f"{base}/threads/{thread_id}")
        if r.status_code == 200:
            envelope = r.json()
            detail = _normalize_thread_detail(envelope, thread)
    except Exception:
        pass

    title = str(detail.get("title") or thread.get("title") or "").strip()
    author_name = _author_name_from_thread(detail, envelope)

    if unit.ed_thread_title_pattern or unit.ed_author_name:
        if not _thread_matches_filters(unit, title, author_name):
            return []

    content = detail.get("content") or ""
    if isinstance(content, list):
        content = " ".join(str(x) for x in content)
    document = detail.get("document") or ""
    text = f"{title}\n{strip_html(str(content))}\n{document}"

    image_blobs = _download_ed_images(client, str(content))

    occurred = _thread_created_at(detail)

    entries = extract_entries_hybrid(
        text=text,
        patterns=config.code_patterns,
        unit_code=unit.code,
        title=title,
        image_blobs=image_blobs,
        llm_enabled=config.llm_enabled,
        llm_only_when_empty=config.llm_only_when_empty,
        llm_model=config.llm_model,
        llm_effort=config.llm_effort,
        default_occurred=occurred,
    )

    source_url = f"https://edstem.org/{region}/discussion/{thread_id}"

    return [
        AttendanceRecord(
            unit_code=unit.code,
            code=e.code,
            source="edstem",
            occurred_at=e.occurred_at,
            context=e.context,
            source_url=source_url,
        )
        for e in entries
    ]


def _image_urls_from_ed_content(content: str) -> list[str]:
    urls = re.findall(r"src=[\"'](https://[^\"']+)[\"']", content)
    if not urls:
        urls = re.findall(r"https://static\.[^\"'\\s>]+", content)
    seen: set[str] = set()
    out: list[str] = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def _download_ed_images(client: httpx.Client, content: str) -> list[bytes]:
    blobs: list[bytes] = []
    for url in _image_urls_from_ed_content(content):
        try:
            resp = client.get(url, timeout=60.0, follow_redirects=True)
            if resp.status_code == 200 and resp.content:
                blobs.append(resp.content)
        except Exception:
            continue
    return blobs


def _parse_ed_time(value) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, (int, float)):
        ts = value / 1000 if value > 1e12 else value
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(timezone.utc)
