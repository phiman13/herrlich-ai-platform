"""
Calendar Agent for Jarvis.

Stage 1: Read-only access to iCloud calendars via CalDAV.
Architecture is open for additional backends (e.g. Microsoft Graph / Outlook)
without changing the public API.
"""

from __future__ import annotations

import logging
import os
import traceback
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger("jarvis.calendar")

BERLIN = ZoneInfo("Europe/Berlin")
UTC = ZoneInfo("UTC")

# Broaden the server-side CalDAV search window backwards so that multi-day
# events that started before our query window are still returned by iCloud.
# Python-side overlap filter below narrows it back to the exact window.
_MULTIDAY_LOOKBACK_DAYS = 30


@dataclass
class Event:
    title: str
    start: datetime
    end: datetime
    location: Optional[str]
    calendar_name: str
    source: str  # "icloud", later also "outlook"
    all_day: bool = False


def _to_berlin(dt) -> datetime:
    """Normalize any date/datetime to an aware datetime in Europe/Berlin."""
    # All-day events come as `date`, not `datetime`
    if not isinstance(dt, datetime):
        dt = datetime(dt.year, dt.month, dt.day, tzinfo=BERLIN)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=BERLIN)
    return dt.astimezone(BERLIN)


class CalendarBackend:
    """Abstract backend. Implementations must provide fetch_events()."""

    name: str = "base"

    def fetch_events(self, start: datetime, end: datetime) -> list[Event]:
        raise NotImplementedError


class ICloudCalDAVBackend(CalendarBackend):
    name = "icloud"

    CALDAV_URL = "https://caldav.icloud.com/"

    def __init__(self, username: str, password: str, whitelist: list[str]):
        self.username = username
        self.password = password
        self.whitelist = [w.strip() for w in whitelist if w.strip()]
        self._client = None
        self._calendars = None

    def _connect(self):
        if self._calendars is not None:
            return
        import caldav

        logger.info("CalDAV connect: user=%s url=%s", self.username, self.CALDAV_URL)
        self._client = caldav.DAVClient(
            url=self.CALDAV_URL,
            username=self.username,
            password=self.password,
        )
        principal = self._client.principal()
        all_cals = principal.calendars()
        self._calendars = [
            c for c in all_cals
            if (c.name or "").strip() in self.whitelist
        ]
        logger.info(
            "CalDAV connected: %d/%d calendars whitelisted (%s)",
            len(self._calendars), len(all_cals),
            [c.name for c in self._calendars],
        )

    def fetch_events(self, start: datetime, end: datetime) -> list[Event]:
        try:
            self._connect()
        except Exception as e:
            logger.error("iCloud connect failed: %s\n%s", e, traceback.format_exc())
            return []

        # Widen the server-side query backwards so multi-day events that
        # started before `start` are still returned; Python filter below
        # narrows the result back to exact overlap semantics.
        query_start = (start - timedelta(days=_MULTIDAY_LOOKBACK_DAYS)).astimezone(UTC)
        query_end = end.astimezone(UTC)

        events: list[Event] = []
        for cal in self._calendars or []:
            cal_name = (cal.name or "").strip()
            try:
                results = cal.search(
                    start=query_start,
                    end=query_end,
                    event=True,
                    expand=True,
                )
            except Exception as e:
                logger.error("search failed for '%s': %s\n%s", cal_name, e, traceback.format_exc())
                continue

            for item in results:
                try:
                    ical = item.icalendar_instance
                except Exception as e:
                    logger.warning("parse failed: %s", e)
                    continue

                for component in ical.walk("VEVENT"):
                    try:
                        dtstart_prop = component.get("dtstart")
                        dtstart = dtstart_prop.dt
                        dtend_prop = component.get("dtend")
                        if dtend_prop is not None:
                            dtend = dtend_prop.dt
                        else:
                            dtend = dtstart

                        # Detect all-day events: icalendar returns `date`
                        # (not `datetime`) for VALUE=DATE properties.
                        # datetime is a subclass of date, so check both.
                        is_all_day = (
                            isinstance(dtstart, date)
                            and not isinstance(dtstart, datetime)
                        )

                        s = _to_berlin(dtstart)
                        e = _to_berlin(dtend)

                        # Overlap filter: keep if event.end > query.start
                        # AND event.start < query.end (RFC 4791 semantics).
                        if e <= start.astimezone(BERLIN):
                            continue
                        if s >= end.astimezone(BERLIN):
                            continue

                        title = str(component.get("summary") or "(ohne Titel)")
                        location = component.get("location")
                        location = str(location) if location else None

                        events.append(Event(
                            title=title,
                            start=s,
                            end=e,
                            location=location,
                            calendar_name=cal_name,
                            source=self.name,
                            all_day=is_all_day,
                        ))
                    except Exception as ex:
                        logger.warning("event parse failed: %s", ex)
                        continue

        logger.info(
            "fetch_events: window=%s..%s calendars=%d events=%d",
            start.isoformat(), end.isoformat(),
            len(self._calendars or []), len(events),
        )
        return events


class CalendarAgent:
    """Aggregates events from multiple backends and exposes a stable API."""

    def __init__(self, backends: Optional[list[CalendarBackend]] = None):
        if backends is None:
            backends = self._default_backends()
        self.backends = backends

    @staticmethod
    def _default_backends() -> list[CalendarBackend]:
        backends: list[CalendarBackend] = []

        icloud_user = os.environ.get("ICLOUD_USER")
        icloud_pw = os.environ.get("ICLOUD_APP_PASSWORD")
        whitelist_raw = os.environ.get("CALENDAR_WHITELIST", "")
        whitelist = [w.strip() for w in whitelist_raw.split(",") if w.strip()]

        if icloud_user and icloud_pw and whitelist:
            backends.append(ICloudCalDAVBackend(
                username=icloud_user,
                password=icloud_pw,
                whitelist=whitelist,
            ))
        else:
            logger.warning("iCloud backend disabled (missing env vars)")

        return backends

    def _deduplicate(self, events: list[Event]) -> list[Event]:
        """Placeholder for multi-backend dedup.
        Stage 1: single backend -> passthrough.
        Later: merge events with same title + overlapping time window.
        """
        return events

    def get_events(self, start: datetime, end: datetime) -> list[Event]:
        if start.tzinfo is None:
            start = start.replace(tzinfo=BERLIN)
        if end.tzinfo is None:
            end = end.replace(tzinfo=BERLIN)

        all_events: list[Event] = []
        for backend in self.backends:
            try:
                all_events.extend(backend.fetch_events(start, end))
            except Exception as e:
                logger.error("backend '%s' failed: %s\n%s", backend.name, e, traceback.format_exc())

        all_events = self._deduplicate(all_events)
        all_events.sort(key=lambda ev: ev.start)
        logger.info(
            "get_events: %s..%s -> %d events from %d backends",
            start.isoformat(), end.isoformat(), len(all_events), len(self.backends),
        )
        return all_events

    def get_next_event(self) -> Optional[Event]:
        now = datetime.now(BERLIN)
        # Look up to 60 days ahead
        events = self.get_events(now, now + timedelta(days=60))
        for ev in events:
            if ev.start >= now:
                return ev
        return None
