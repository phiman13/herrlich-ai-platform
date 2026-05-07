#!/usr/bin/env python3
import os
import caldav

url = "https://caldav.icloud.com"
user = os.environ.get("ICLOUD_USER") or os.environ.get("CALDAV_USERNAME")
pw = os.environ.get("ICLOUD_APP_PASSWORD") or os.environ.get("CALDAV_PASSWORD")

if not user or not pw:
    print("ICLOUD_USER oder ICLOUD_APP_PASSWORD nicht gesetzt.")
    raise SystemExit(1)

print(f"Connecting as {user} ...")
client = caldav.DAVClient(url=url, username=user, password=pw)
cals = client.principal().calendars()

print(f"\n{len(cals)} Kollektionen:\n")
for c in cals:
    print(f"  Name: {c.name!r}")
    print(f"  URL:  {c.url}")
    print()
