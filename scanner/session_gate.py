from __future__ import annotations

import os
from datetime import datetime, time
from zoneinfo import ZoneInfo

# GitHub cron is UTC; New York is DST-aware.
ET = ZoneInfo("America/New_York")
now = datetime.now(ET)
in_session = now.weekday() < 5 and time(9, 30) <= now.time() <= time(16, 0)

print(f"New York time: {now.isoformat()}")
print(f"Regular session: {in_session}")

out = os.getenv("GITHUB_OUTPUT")
if out:
    with open(out, "a", encoding="utf-8") as f:
        f.write("in_session=" + ("true" if in_session else "false") + "\n")
