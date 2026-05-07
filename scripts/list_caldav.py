#!/usr/bin/env python3
import os
import caldav

url = "https://caldav.icloud.com"
user = os.environ.get("CALDAV_USERNAME")
pw = os.environ.get("CALDAV_PASSWORD")

if not user or not pw:
    print("CALDAV_USERNAME oder CALDAV_PASSWORD nicht gesetzt.")
    print("Bitte zuerst: source /root/.env")
    raise SystemExit(1)

print(f"Connecting as {user} ...")
client = caldav.DAVClient(url=url, username=user, password=pw)
cals = client.principal().calendars()

print(f"\n{len(cals)} Kollektionen:\n")
for c in cals:
    print(f"  Name: {c.name!r}")
    print(f"  URL:  {c.url}")
    print()
