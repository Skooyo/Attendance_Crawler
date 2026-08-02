import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

from attendance_crawler.collectors.edstem import _download_ed_images, _image_urls_from_ed_content

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
h = {"Authorization": f"Bearer {os.getenv('ED_API_TOKEN')}"}
base = os.getenv("ED_BASE_URL", "https://edstem.org/api").rstrip("/")
with httpx.Client(headers=h, timeout=60) as c:
    threads = c.get(f"{base}/courses/36340/threads", params={"limit": 80}).json().get("threads")
    t = next(x for x in threads if x.get("title") == "Week 1 Attendance Codes")
    env = c.get(f"{base}/threads/{t['id']}").json()
    content = env["thread"]["content"]
    urls = _image_urls_from_ed_content(content)
    print("urls", urls)
    blobs = _download_ed_images(c, content)
    print("blobs", len(blobs), [len(b) for b in blobs])
    from attendance_crawler.extract import ocr_image_bytes
    for i, b in enumerate(blobs):
        print("ocr", i, ocr_image_bytes(b)[:200])
