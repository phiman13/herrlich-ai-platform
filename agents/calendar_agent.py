"""
Calendar Agent for Jarvis.

Reads and writes events on the user's default Outlook calendar via
Microsoft Graph. Auth is shared with the mail/tasks agents through
microsoft_auth.get_access_token().
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import httpx

try:
    from microsoft_auth import get_access_token
except ImportError:
    from agents.microsoft_auth import get_access_token  # type: ignore

logger = logging.getLogger("jarvis.calendar")

BERLIN = ZoneInfo("Europe/Berlin")
UTC = ZoneInfo("UTC")

_GRAPH = "https://graph.microsoft.com/v1.0"


@dataclass
class Event:
    id: str
    title: str
    start: datetime
    end: datetime
    location: Optional[str]
    calendar_name: str
    source: str  # "outlook"
    all_day: bool = False
    recurring: bool = False


def _to_berlin(dt: datetime) -> datetime:
    """Normalize a naive-or-aware datetime to Europe/Berlin."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=BERLIN)
    return dt.astimezone(BERLIN)


def _parse_graph_dt(value: dict) -> datetime:
    """Parse a Graph dateTimeTimeZone object into an aware Berlin datetime.

    With the `Prefer: outlook.timezone` header Graph returns local times
    without an offset (e.g. "2026-05-16T10:00:00.0000000"). Parse them
    naively and attach Europe/Berlin. Graph sends 7 fractional digits;
    datetime.fromisoformat accepts at most 6, so trim.
    """
    raw = value["dateTime"]
    if "." in raw:
        head, frac = raw.split(".", 1)
        raw = f"{head}.{frac[:6]}"
    return _to_berlin(datetime.fromisoformat(raw))


class CalendarAgent:
    """Reads and writes the user's default Outlook calendar via MS Graph."""

    DEFAULT_CALENDAR_NAME = "Outlook"

    def _headers(self, prefer_berlin: bool = False) -> dict:
        headers = {
            "Authorization": f"Bearer {get_access_token()}",
            "Content-Type": "application/json",
        }
        if prefer_berlin:
            headers["Prefer"] = 'outlook.timezone="Europe/Berlin"'
        return headers

    def get_events(self, start: datetime, end: datetime) -> list[Event]:
        if start.tzinfo is None:
            start = start.replace(tzinfo=BERLIN)
        if end.tzinfo is None:
            end = end.replace(tzinfo=BERLIN)
        try:
            events = self._fetch_calendar_view(start, end)
        except Exception as e:
            logger.error("get_events failed: %s", e)
            return []
        events.sort(key=lambda ev: ev.start)
        logger.info(
            "get_events: %s..%s -> %d events",
            start.isoformat(),
            end.isoformat(),
            len(events),
        )
        return events

    def _fetch_calendar_view(self, start: datetime, end: datetime) -> list[Event]:
        url: Optional[str] = f"{_GRAPH}/me/calendarView"
        params: Optional[dict] = {
            "startDateTime": start.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
            "endDateTime": end.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
            "$orderby": "start/dateTime",
            "$top": 100,
            "$select": "id,subject,start,end,isAllDay,location,type",
        }
        headers = self._headers(prefer_berlin=True)
        events: list[Event] = []
        while url:
            resp = httpx.get(url, headers=headers, params=params, timeout=15)
            resp.raise_for_status()
            payload = resp.json()
            for item in payload.get("value", []):
                events.append(self._to_event(item))
            url = payload.get("@odata.nextLink")
            params = None  # nextLink already carries the query string
        return events

    @classmethod
    def _to_event(cls, item: dict) -> Event:
        location = (item.get("location") or {}).get("displayName") or None
        return Event(
            id=item["id"],
            title=item.get("subject") or "(ohne Titel)",
            start=_parse_graph_dt(item["start"]),
            end=_parse_graph_dt(item["end"]),
            location=location,
            calendar_name=cls.DEFAULT_CALENDAR_NAME,
            source="outlook",
            all_day=bool(item.get("isAllDay")),
            recurring=item.get("type") not in (None, "singleInstance"),
        )

    def get_next_event(self) -> Optional[Event]:
        now = datetime.now(BERLIN)
        events = self.get_events(now, now + timedelta(days=60))
        for ev in events:
            if ev.start >= now:
                return ev
        return None

    def create_event(self, title: str, start_dt: datetime, end_dt: datetime) -> None:
        """Create an event on the default Outlook calendar. Raises on failure."""
        body = {
            "subject": title,
            "start": {
                "dateTime": _to_berlin(start_dt).strftime("%Y-%m-%dT%H:%M:%S"),
                "timeZone": "Europe/Berlin",
            },
            "end": {
                "dateTime": _to_berlin(end_dt).strftime("%Y-%m-%dT%H:%M:%S"),
                "timeZone": "Europe/Berlin",
            },
        }
        resp = httpx.post(
            f"{_GRAPH}/me/events",
            headers=self._headers(),
            json=body,
            timeout=15,
        )
        resp.raise_for_status()
        logger.info("Termin erstellt: '%s' (%s)", title, start_dt.isoformat())

    def search_events(self, query: str, start: datetime, end: datetime) -> list[Event]:
        """Return events in [start, end] whose title matches `query`.

        Match rule: every word in `query` with length >= 3 must appear as a
        case-insensitive substring of the title. If `query` has no such word,
        the whole (stripped, lowercased) query must be a substring.
        """
        events = self.get_events(start, end)
        words = [w for w in query.lower().split() if len(w) >= 3]
        if not words:
            words = [query.lower().strip()]
        return [ev for ev in events if all(w in ev.title.lower() for w in words)]

    def update_event(
        self,
        event_id: str,
        new_start: Optional[datetime] = None,
        new_end: Optional[datetime] = None,
        new_title: Optional[str] = None,
        new_location: Optional[str] = None,
    ) -> None:
        """Patch an event — only the provided fields change. Raises on failure."""
        body: dict = {}
        if new_title is not None:
            body["subject"] = new_title
        if new_start is not None:
            body["start"] = {
                "dateTime": _to_berlin(new_start).strftime("%Y-%m-%dT%H:%M:%S"),
                "timeZone": "Europe/Berlin",
            }
        if new_end is not None:
            body["end"] = {
                "dateTime": _to_berlin(new_end).strftime("%Y-%m-%dT%H:%M:%S"),
                "timeZone": "Europe/Berlin",
            }
        if new_location is not None:
            body["location"] = {"displayName": new_location}
        if not body:
            raise ValueError("update_event: keine Änderung angegeben")
        resp = httpx.patch(
            f"{_GRAPH}/me/events/{event_id}",
            headers=self._headers(),
            json=body,
            timeout=15,
        )
        resp.raise_for_status()
        logger.info("Termin geändert: %s", event_id)

    def delete_event(self, event_id: str) -> None:
        """Delete an event. Raises on failure."""
        resp = httpx.delete(
            f"{_GRAPH}/me/events/{event_id}",
            headers=self._headers(),
            timeout=15,
        )
        resp.raise_for_status()
        logger.info("Termin abgesagt: %s", event_id)
