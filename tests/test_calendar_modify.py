# tests/test_calendar_modify.py
from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import httpx
import pytest

BERLIN = ZoneInfo("Europe/Berlin")

_SEARCH_JSON = {
    "value": [
        {
            "id": "evt-zahnarzt",
            "subject": "Zahnarzt Dr. Müller",
            "start": {
                "dateTime": "2026-05-20T10:00:00.0000000",
                "timeZone": "Europe/Berlin",
            },
            "end": {
                "dateTime": "2026-05-20T11:00:00.0000000",
                "timeZone": "Europe/Berlin",
            },
            "isAllDay": False,
            "location": {"displayName": ""},
            "type": "singleInstance",
        },
        {
            "id": "evt-standup",
            "subject": "Standup Team Backend",
            "start": {
                "dateTime": "2026-05-21T09:00:00.0000000",
                "timeZone": "Europe/Berlin",
            },
            "end": {
                "dateTime": "2026-05-21T09:15:00.0000000",
                "timeZone": "Europe/Berlin",
            },
            "isAllDay": False,
            "location": {"displayName": ""},
            "type": "occurrence",
        },
        {
            "id": "evt-lunch",
            "subject": "Lunch mit Anna",
            "start": {
                "dateTime": "2026-05-22T12:00:00.0000000",
                "timeZone": "Europe/Berlin",
            },
            "end": {
                "dateTime": "2026-05-22T13:00:00.0000000",
                "timeZone": "Europe/Berlin",
            },
            "isAllDay": False,
            "location": {"displayName": ""},
            "type": "singleInstance",
        },
    ]
}


def _resp(json_data=None, status=200):
    m = MagicMock()
    m.status_code = status
    m.json.return_value = json_data or {}
    m.raise_for_status.return_value = None
    return m


def _win():
    return (
        datetime(2026, 5, 19, 0, 0, tzinfo=BERLIN),
        datetime(2026, 6, 19, 0, 0, tzinfo=BERLIN),
    )


def test_search_events_matches_single_word():
    from agents.calendar_agent import CalendarAgent

    start, end = _win()
    with (
        patch("agents.calendar_agent.get_access_token", return_value="tok"),
        patch("httpx.get", return_value=_resp(_SEARCH_JSON)),
    ):
        hits = CalendarAgent().search_events("Zahnarzt", start, end)

    assert len(hits) == 1
    assert hits[0].id == "evt-zahnarzt"


def test_search_events_requires_all_words():
    from agents.calendar_agent import CalendarAgent

    start, end = _win()
    with (
        patch("agents.calendar_agent.get_access_token", return_value="tok"),
        patch("httpx.get", return_value=_resp(_SEARCH_JSON)),
    ):
        hits = CalendarAgent().search_events("Standup Backend", start, end)

    assert len(hits) == 1
    assert hits[0].id == "evt-standup"


def test_search_events_no_match_returns_empty():
    from agents.calendar_agent import CalendarAgent

    start, end = _win()
    with (
        patch("agents.calendar_agent.get_access_token", return_value="tok"),
        patch("httpx.get", return_value=_resp(_SEARCH_JSON)),
    ):
        hits = CalendarAgent().search_events("Friseur", start, end)

    assert hits == []


def test_update_event_patches_only_changed_fields():
    from agents.calendar_agent import CalendarAgent

    new_start = datetime(2026, 5, 20, 15, 0, tzinfo=BERLIN)
    new_end = datetime(2026, 5, 20, 16, 0, tzinfo=BERLIN)
    with (
        patch("agents.calendar_agent.get_access_token", return_value="tok"),
        patch("httpx.patch", return_value=_resp(status=200)) as mock_patch,
    ):
        CalendarAgent().update_event(
            "evt-zahnarzt", new_start=new_start, new_end=new_end
        )

    mock_patch.assert_called_once()
    assert mock_patch.call_args[0][0].endswith("/me/events/evt-zahnarzt")
    body = mock_patch.call_args[1]["json"]
    assert body["start"]["dateTime"] == "2026-05-20T15:00:00"
    assert body["end"]["dateTime"] == "2026-05-20T16:00:00"
    assert "subject" not in body
    assert "location" not in body


def test_update_event_changes_title_and_location():
    from agents.calendar_agent import CalendarAgent

    with (
        patch("agents.calendar_agent.get_access_token", return_value="tok"),
        patch("httpx.patch", return_value=_resp(status=200)) as mock_patch,
    ):
        CalendarAgent().update_event(
            "evt-x", new_title="Strategie-Call", new_location="Raum 3"
        )

    body = mock_patch.call_args[1]["json"]
    assert body["subject"] == "Strategie-Call"
    assert body["location"] == {"displayName": "Raum 3"}
    assert "start" not in body


def test_update_event_raises_without_changes():
    from agents.calendar_agent import CalendarAgent

    with patch("agents.calendar_agent.get_access_token", return_value="tok"):
        with pytest.raises(ValueError):
            CalendarAgent().update_event("evt-x")


def test_delete_event_calls_graph_delete():
    from agents.calendar_agent import CalendarAgent

    with (
        patch("agents.calendar_agent.get_access_token", return_value="tok"),
        patch("httpx.delete", return_value=_resp(status=204)) as mock_delete,
    ):
        CalendarAgent().delete_event("evt-zahnarzt")

    mock_delete.assert_called_once()
    assert mock_delete.call_args[0][0].endswith("/me/events/evt-zahnarzt")


def test_delete_event_raises_on_http_error():
    from agents.calendar_agent import CalendarAgent

    with (
        patch("agents.calendar_agent.get_access_token", return_value="tok"),
        patch("httpx.delete", side_effect=httpx.HTTPError("boom")),
    ):
        with pytest.raises(httpx.HTTPError):
            CalendarAgent().delete_event("evt-x")
