"""List Ed thread titles (local debug)."""
import os
import re
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
h = {"Authorization": f"Bearer {os.getenv('ED_API_TOKEN')}"}
base = os.getenv("ED_BASE_URL", "https://edstem.org/api").rstrip("/")
cid = 36340
r = httpx.get(f"{base}/courses/{cid}/threads", headers=h, params={"limit": 80}, timeout=60)
data = r.json()
threads = data.get("threads", data if isinstance(data, list) else [])
for t in threads:
    if not isinstance(t, dict):
        continue
    title = t.get("title", "")
    if re.search(r"attendance", title, re.I):
        user = t.get("user")
        print(repr(title), "| user=", user)
