# tests/test_calendar_write.py
from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import httpx
import pytest

BERLIN = ZoneInfo("Europe/Berlin")


def _resp(status=201):
    m = MagicMock()
    m.status_code = status
    m.raise_for_status.return_value = None
    return m


def test_create_event_posts_to_graph():
    from agents.calendar_agent import CalendarAgent

    start = datetime(2026, 5, 17, 10, 0, tzinfo=BERLIN)
    end = datetime(2026, 5, 17, 11, 0, tzinfo=BERLIN)
    with (
        patch("agents.calendar_agent.get_access_token", return_value="tok"),
        patch("httpx.post", return_value=_resp(201)) as mock_post,
    ):
        CalendarAgent().create_event("Zahnarzt", start, end)

    mock_post.assert_called_once()
    url = mock_post.call_args[0][0]
    assert url.endswith("/me/events")
    body = mock_post.call_args[1]["json"]
    assert body["subject"] == "Zahnarzt"
    assert body["start"]["dateTime"] == "2026-05-17T10:00:00"
    assert body["start"]["timeZone"] == "Europe/Berlin"
    assert body["end"]["dateTime"] == "2026-05-17T11:00:00"


def test_create_event_raises_on_http_error():
    from agents.calendar_agent import CalendarAgent

    start = datetime(2026, 5, 17, 10, 0, tzinfo=BERLIN)
    end = datetime(2026, 5, 17, 11, 0, tzinfo=BERLIN)
    with (
        patch("agents.calendar_agent.get_access_token", return_value="tok"),
        patch("httpx.post", side_effect=httpx.HTTPError("403")),
    ):
        with pytest.raises(httpx.HTTPError):
            CalendarAgent().create_event("X", start, end)
