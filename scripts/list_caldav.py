#!/usr/bin/env python3
# ruff: noqa: E402
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)) + "/agents")

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "agents", ".env"))
load_dotenv("/root/agents/.env")

import caldav

url = os.environ.get("CALDAV_URL", "https://caldav.icloud.com")
user = os.environ.get("CALDAV_USERNAME")
pw = os.environ.get("CALDAV_PASSWORD")

print(f"Connecting as {user}...")
client = caldav.DAVClient(url=url, username=user, password=pw)
principal = client.principal()
cals = principal.calendars()

print(f"\n{len(cals)} Kollektionen:\n")
for c in cals:
    print(f"  Name: {c.name!r}")
    print(f"  URL:  {c.url}")
    print()
