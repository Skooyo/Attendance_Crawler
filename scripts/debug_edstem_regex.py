import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

from attendance_crawler.config import load_config
from attendance_crawler.collectors.edstem import (
    _download_ed_images,
    _normalize_thread_detail,
)
from attendance_crawler.extract import extract_codes_from_content, strip_html

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
config = load_config()
h = {"Authorization": f"Bearer {os.getenv('ED_API_TOKEN')}"}
base = config.ed_base_url.rstrip("/")
with httpx.Client(headers=h, timeout=60) as c:
    threads = c.get(f"{base}/courses/36340/threads", params={"limit": 80}).json().get("threads")
    t = next(x for x in threads if x.get("title") == "Week 1 Attendance Codes")
    env = c.get(f"{base}/threads/{t['id']}").json()
    detail = _normalize_thread_detail(env, t)
    title = detail.get("title")
    content = detail.get("content") or ""
    document = detail.get("document") or ""
    text = f"{title}\n{strip_html(str(content))}\n{document}"
    blobs = _download_ed_images(c, str(content))
    codes = extract_codes_from_content(text, config.code_patterns, blobs)
    print("regex+ocr codes", codes)
