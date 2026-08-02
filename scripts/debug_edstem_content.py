import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

from attendance_crawler.config import load_config
from attendance_crawler.collectors.edstem import (
    _author_name_from_thread,
    _normalize_thread_detail,
    _thread_matches_filters,
)
from attendance_crawler.extract import strip_html

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
config = load_config()
unit = [u for u in config.units if u.code == "FIT2102"][0]
h = {"Authorization": f"Bearer {os.getenv('ED_API_TOKEN')}"}
base = config.ed_base_url.rstrip("/")
with httpx.Client(headers=h, timeout=60) as c:
    threads = c.get(f"{base}/courses/36340/threads", params={"limit": 80}).json().get("threads")
    t = next(x for x in threads if x.get("title") == "Week 1 Attendance Codes")
    env = c.get(f"{base}/threads/{t['id']}").json()
    detail = _normalize_thread_detail(env, t)
    title = detail.get("title")
    author = _author_name_from_thread(detail, env)
    print("title", title)
    print("author", author)
    print("match", _thread_matches_filters(unit, title, author))
    content = detail.get("content") or ""
    text = strip_html(str(content))
    print("content len", len(text))
    print(text[:800])
