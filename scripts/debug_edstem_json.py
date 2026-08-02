import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
h = {"Authorization": f"Bearer {os.getenv('ED_API_TOKEN')}"}
base = os.getenv("ED_BASE_URL", "https://edstem.org/api").rstrip("/")
with httpx.Client(headers=h, timeout=60) as c:
    threads = c.get(f"{base}/courses/36340/threads", params={"limit": 80}).json().get("threads")
    t = next(x for x in threads if x.get("title") == "Week 1 Attendance Codes")
    env = c.get(f"{base}/threads/{t['id']}").json()
    print(json.dumps(env, indent=2)[:4000])
