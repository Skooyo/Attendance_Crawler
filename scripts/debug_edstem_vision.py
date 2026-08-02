import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

from attendance_crawler.collectors.edstem import _download_ed_images
from attendance_crawler.llm_extract import _extract_via_openrouter_vision

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
h = {"Authorization": f"Bearer {os.getenv('ED_API_TOKEN')}"}
base = os.getenv("ED_BASE_URL", "https://edstem.org/api").rstrip("/")
with httpx.Client(headers=h, timeout=60) as c:
    threads = c.get(f"{base}/courses/36340/threads", params={"limit": 80}).json().get("threads")
    t = next(x for x in threads if x.get("title") == "Week 1 Attendance Codes")
    env = c.get(f"{base}/threads/{t['id']}").json()
    content = env["thread"]["content"]
    blobs = _download_ed_images(c, content)
    codes = _extract_via_openrouter_vision(
        blobs,
        unit_code="FIT2102",
        title="Week 1 Attendance Codes",
        api_key=os.getenv("OPENROUTER_API_KEY"),
        model=os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini"),
    )
    print("codes", codes)
