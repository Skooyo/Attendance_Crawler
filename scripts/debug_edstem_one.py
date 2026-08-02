import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

from attendance_crawler.config import load_config
from attendance_crawler.collectors.edstem import _list_threads, _thread_to_records

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
config = load_config()
unit = [u for u in config.units if u.code == "FIT2102"][0]
h = {"Authorization": f"Bearer {os.getenv('ED_API_TOKEN')}"}
base = config.ed_base_url.rstrip("/")
with httpx.Client(headers=h, timeout=60) as client:
    threads = _list_threads(client, base, unit.ed_course_id)
    for t in threads:
        if t.get("title") == "Week 1 Attendance Codes":
            recs = _thread_to_records(client, base, config.ed_region, unit, t, config)
            print("recs", len(recs), [r.code for r in recs])
            r = client.get(f"{base}/threads/{t['id']}")
            print("detail keys", r.json().keys() if isinstance(r.json(), dict) else type(r.json()))
