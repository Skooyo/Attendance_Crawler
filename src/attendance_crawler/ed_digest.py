"""EdStem daily digest: collect/rank dump for Hermes; confirm watermark + mark-read."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from attendance_crawler.config import AppConfig, UnitConfig
from attendance_crawler.extract import strip_html
from attendance_crawler.paths import ED_DIGEST_PENDING_PATH
from attendance_crawler.store import get_ed_digest_watermarks, upsert_ed_digest_watermarks

STAFF_ROLES = frozenset({"admin", "staff", "tutor", "mentor"})


@dataclass
class DigestPost:
    unit_code: str
    course_id: int
    thread_id: int
    thread_number: int | None
    title: str
    type: str
    role: str
    matched_keywords: list[str]
    link: str
    body: str
    important: bool
    last_activity_at: str
    created_at: str


def _parse_ed_time(value: Any) -> datetime:
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


def _activity_iso(thread: dict) -> str:
    for key in ("updated_at", "last_activity_at", "created_at", "created"):
        if thread.get(key) is not None:
            return _parse_ed_time(thread.get(key)).isoformat()
    return datetime.now(timezone.utc).isoformat()


def _is_staff_side(role: str | None) -> bool:
    if not role:
        return False
    return role.lower() in STAFF_ROLES


def _match_keywords(text: str, keywords: list[str]) -> list[str]:
    hits: list[str] = []
    for kw in keywords:
        if re.search(re.escape(kw), text, re.I):
            hits.append(kw)
    return hits


def _tier(post: DigestPost) -> int:
    # Sort A: lower tier number = higher priority
    if _is_staff_side(post.role) or post.type == "announcement":
        return 0
    if post.matched_keywords:
        return 1
    return 2


def rank_posts(posts: list[DigestPost]) -> list[DigestPost]:
    return sorted(
        posts,
        key=lambda p: (_tier(p), -_parse_ed_time(p.created_at).timestamp()),
    )


def _units_for_digest(config: AppConfig) -> list[UnitConfig]:
    wanted = {c.upper() for c in config.ed_digest.unit_codes} if config.ed_digest.unit_codes else None
    out: list[UnitConfig] = []
    for u in config.units:
        if u.ed_course_id is None:
            continue
        if wanted is not None and u.code.upper() not in wanted:
            continue
        out.append(u)
    return out


def _extract_thread_list(data: Any) -> list[dict]:
    if isinstance(data, list):
        return [t for t in data if isinstance(t, dict)]
    if not isinstance(data, dict):
        return []
    threads = data.get("threads")
    if isinstance(threads, list):
        return [t for t in threads if isinstance(t, dict)]
    if isinstance(threads, dict):
        return [t for t in threads.values() if isinstance(t, dict)]
    return []


def _needs_digest(thread: dict, watermarks: dict[int, str]) -> bool:
    tid = thread.get("id")
    if tid is None:
        return False
    tid = int(tid)
    activity = _activity_iso(thread)
    prev = watermarks.get(tid)
    if prev is None:
        return True
    return _parse_ed_time(activity) > _parse_ed_time(prev)


def _role_from_thread(thread: dict) -> str:
    user = thread.get("user")
    if isinstance(user, dict):
        role = user.get("course_role")
        if role:
            return str(role)
    return ""


def _normalize_detail(envelope: Any, fallback: dict) -> dict:
    if not isinstance(envelope, dict):
        return fallback
    detail = envelope.get("thread", envelope)
    return detail if isinstance(detail, dict) else fallback


def _body_text(detail: dict, limit: int) -> str:
    content = detail.get("content") or ""
    if isinstance(content, list):
        content = " ".join(str(x) for x in content)
    document = detail.get("document") or ""
    text = strip_html(str(content))
    if not text.strip() and document:
        text = strip_html(str(document))
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        return text[: limit - 1] + "..."
    return text


def collect_ed_digest(config: AppConfig) -> tuple[list[DigestPost], list[str]]:
    errors: list[str] = []
    posts: list[DigestPost] = []

    if not config.ed_api_token:
        errors.append("Ed digest: ED_API_TOKEN not set")
        return posts, errors

    headers = {
        "Authorization": f"Bearer {config.ed_api_token}",
        "Content-Type": "application/json",
    }
    base = config.ed_base_url.rstrip("/")
    region = config.ed_region
    keywords = config.ed_digest.keywords
    body_chars = config.ed_digest.body_chars
    max_threads = config.ed_digest.max_threads

    units = _units_for_digest(config)
    if not units:
        errors.append("Ed digest: no units with ed_course_id selected")
        return posts, errors

    with httpx.Client(headers=headers, timeout=60.0) as client:
        for unit in units:
            course_id = int(unit.ed_course_id)  # type: ignore[arg-type]
            try:
                resp = client.get(
                    f"{base}/courses/{course_id}/threads",
                    params={"limit": 100, "sort": "new"},
                )
                resp.raise_for_status()
                threads = _extract_thread_list(resp.json())
                watermarks = get_ed_digest_watermarks(course_id)
                candidates = [t for t in threads if _needs_digest(t, watermarks)]
                # ponytail: cap per course to avoid rate limits after long gaps
                candidates = candidates[:max_threads]

                for thread in candidates:
                    tid = int(thread["id"])
                    detail = thread
                    try:
                        r = client.get(
                            f"{base}/threads/{tid}",
                            params={"mark_as_read": "false"},
                        )
                        if r.status_code == 200:
                            detail = _normalize_detail(r.json(), thread)
                    except Exception as e:
                        errors.append(f"Ed digest {unit.code} thread {tid}: body fetch {e}")

                    title = str(detail.get("title") or thread.get("title") or "").strip()
                    role = _role_from_thread(detail) or _role_from_thread(thread)
                    ttype = str(detail.get("type") or thread.get("type") or "post")
                    body = _body_text(detail, body_chars)
                    hay = f"{title}\n{body}"
                    matched = _match_keywords(hay, keywords)
                    important = _is_staff_side(role) or ttype == "announcement" or bool(matched)
                    number = detail.get("number")
                    if number is not None:
                        try:
                            number = int(number)
                        except (TypeError, ValueError):
                            number = None
                    posts.append(
                        DigestPost(
                            unit_code=unit.code,
                            course_id=course_id,
                            thread_id=tid,
                            thread_number=number,
                            title=title,
                            type=ttype,
                            role=role or "unknown",
                            matched_keywords=matched,
                            link=f"https://edstem.org/{region}/discussion/{tid}",
                            body=body,
                            important=important,
                            last_activity_at=_activity_iso(detail),
                            created_at=_activity_iso(
                                {"created_at": detail.get("created_at") or thread.get("created_at")}
                            ),
                        )
                    )
            except Exception as e:
                errors.append(f"Ed digest unit {unit.code}: {e}")

    posts = rank_posts(posts)
    return posts, errors


def write_pending(posts: list[DigestPost], path: Path | None = None) -> Path:
    out = path or ED_DIGEST_PENDING_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "posts": [asdict(p) for p in posts],
    }
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out


def load_pending(path: Path | None = None) -> list[DigestPost]:
    p = path or ED_DIGEST_PENDING_PATH
    if not p.exists():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    raw_posts = data.get("posts") if isinstance(data, dict) else data
    if not isinstance(raw_posts, list):
        return []
    out: list[DigestPost] = []
    for item in raw_posts:
        if not isinstance(item, dict):
            continue
        out.append(
            DigestPost(
                unit_code=str(item.get("unit_code") or ""),
                course_id=int(item["course_id"]),
                thread_id=int(item["thread_id"]),
                thread_number=item.get("thread_number"),
                title=str(item.get("title") or ""),
                type=str(item.get("type") or "post"),
                role=str(item.get("role") or ""),
                matched_keywords=list(item.get("matched_keywords") or []),
                link=str(item.get("link") or ""),
                body=str(item.get("body") or ""),
                important=bool(item.get("important")),
                last_activity_at=str(item.get("last_activity_at") or ""),
                created_at=str(item.get("created_at") or ""),
            )
        )
    return out


AGENT_INSTRUCTIONS = """\
# EdStem daily digest - agent instructions

You write the Discord message for this digest.

Rules:
1. Staff/announcement and keyword hits are **important**: explain in greater detail.
2. Other posts: title + one short summary sentence + link only.
3. Group by unit when helpful. Keep the message scannable.
4. If the dump says Nothing new, reply exactly: Nothing new
5. After you post to Discord, run: python -m attendance_crawler ed-digest confirm
   (or the Hermes confirm script) so watermarks and Ed read state update.
"""


def format_dump(posts: list[DigestPost]) -> str:
    if not posts:
        return "Nothing new\n"
    lines = [AGENT_INSTRUCTIONS, "", f"Posts ({len(posts)}):", ""]
    for i, p in enumerate(posts, 1):
        kw = ", ".join(p.matched_keywords) if p.matched_keywords else "(none)"
        lines.extend(
            [
                f"## {i}. [{p.unit_code}] {p.title}",
                f"- type: {p.type}",
                f"- role: {p.role}",
                f"- important: {p.important}",
                f"- keywords: {kw}",
                f"- link: {p.link}",
                f"- body: {p.body or '(empty)'}",
                "",
            ]
        )
    return "\n".join(lines)


def mark_threads_read(config: AppConfig, posts: list[DigestPost]) -> list[str]:
    errors: list[str] = []
    if not posts:
        return errors
    if not config.ed_api_token:
        errors.append("Ed digest confirm: ED_API_TOKEN not set")
        return errors
    headers = {
        "Authorization": f"Bearer {config.ed_api_token}",
        "Content-Type": "application/json",
    }
    base = config.ed_base_url.rstrip("/")
    with httpx.Client(headers=headers, timeout=60.0) as client:
        for p in posts:
            try:
                # default GET marks seen (mcp-ed)
                r = client.get(f"{base}/threads/{p.thread_id}")
                if r.status_code >= 400:
                    errors.append(f"mark-read {p.thread_id}: HTTP {r.status_code}")
            except Exception as e:
                errors.append(f"mark-read {p.thread_id}: {e}")
    return errors


def confirm_digest(config: AppConfig, path: Path | None = None) -> tuple[int, list[str]]:
    posts = load_pending(path)
    errors = mark_threads_read(config, posts)
    rows = [
        (p.course_id, p.thread_id, p.thread_number, p.last_activity_at or p.created_at)
        for p in posts
    ]
    n = upsert_ed_digest_watermarks(rows) if rows else 0
    pending = path or ED_DIGEST_PENDING_PATH
    if pending.exists():
        pending.unlink()
    return n, errors