# tests/test_calendar_read.py
from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import httpx

BERLIN = ZoneInfo("Europe/Berlin")

_CALENDAR_VIEW_JSON = {
    "value": [
        {
            "subject": "Zahnarzt",
            "start": {
                "dateTime": "2026-05-16T10:00:00.0000000",
                "timeZone": "Europe/Berlin",
            },
            "end": {
                "dateTime": "2026-05-16T11:00:00.0000000",
                "timeZone": "Europe/Berlin",
            },
            "isAllDay": False,
            "location": {"displayName": "Praxis Dr. Müller"},
        },
        {
            "subject": "Urlaub",
            "start": {
                "dateTime": "2026-05-16T00:00:00.0000000",
                "timeZone": "Europe/Berlin",
            },
            "end": {
                "dateTime": "2026-05-17T00:00:00.0000000",
                "timeZone": "Europe/Berlin",
            },
            "isAllDay": True,
            "location": {"displayName": ""},
        },
    ]
}


def _resp(json_data, status=200):
    m = MagicMock()
    m.status_code = status
    m.json.return_value = json_data
    m.raise_for_status.return_value = None
    return m


def test_get_events_maps_graph_payload():
    from agents.calendar_agent import CalendarAgent

    start = datetime(2026, 5, 16, 0, 0, tzinfo=BERLIN)
    end = datetime(2026, 5, 17, 0, 0, tzinfo=BERLIN)
    with (
        patch("agents.calendar_agent.get_access_token", return_value="tok"),
        patch("httpx.get", return_value=_resp(_CALENDAR_VIEW_JSON)) as mock_get,
    ):
        events = CalendarAgent().get_events(start, end)

    assert len(events) == 2
    ev = events[1]  # sorted by start: Urlaub 00:00 < Zahnarzt 10:00
    assert ev.title == "Zahnarzt"
    assert ev.start == datetime(2026, 5, 16, 10, 0, tzinfo=BERLIN)
    assert ev.end == datetime(2026, 5, 16, 11, 0, tzinfo=BERLIN)
    assert ev.location == "Praxis Dr. Müller"
    assert ev.all_day is False
    assert ev.source == "outlook"
    assert "calendarView" in mock_get.call_args[0][0]


def test_get_events_marks_all_day_and_empty_location():
    from agents.calendar_agent import CalendarAgent

    start = datetime(2026, 5, 16, 0, 0, tzinfo=BERLIN)
    end = datetime(2026, 5, 17, 0, 0, tzinfo=BERLIN)
    with (
        patch("agents.calendar_agent.get_access_token", return_value="tok"),
        patch("httpx.get", return_value=_resp(_CALENDAR_VIEW_JSON)),
    ):
        events = CalendarAgent().get_events(start, end)

    urlaub = [e for e in events if e.title == "Urlaub"][0]
    assert urlaub.all_day is True
    assert urlaub.location is None


def test_get_events_returns_empty_on_error():
    from agents.calendar_agent import CalendarAgent

    start = datetime(2026, 5, 16, 0, 0, tzinfo=BERLIN)
    end = datetime(2026, 5, 17, 0, 0, tzinfo=BERLIN)
    with (
        patch("agents.calendar_agent.get_access_token", return_value="tok"),
        patch("httpx.get", side_effect=httpx.HTTPError("boom")),
    ):
        events = CalendarAgent().get_events(start, end)
    assert events == []
