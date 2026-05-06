# tests/test_calendar_write.py
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime
from zoneinfo import ZoneInfo

BERLIN = ZoneInfo("Europe/Berlin")


def test_backend_create_event_calls_save():
    """ICloudCalDAVBackend.create_event() calls cal.save_event() on the right calendar."""
    from agents.calendar_agent import ICloudCalDAVBackend

    backend = ICloudCalDAVBackend("user@example.com", "pw", ["Privat", "Arbeit"])
    mock_cal_privat = MagicMock()
    mock_cal_privat.name = "Privat"
    mock_cal_arbeit = MagicMock()
    mock_cal_arbeit.name = "Arbeit"
    backend._calendars = [mock_cal_privat, mock_cal_arbeit]

    start = datetime(2026, 5, 10, 10, 0, tzinfo=BERLIN)
    end = datetime(2026, 5, 10, 11, 0, tzinfo=BERLIN)

    backend.create_event("Zahnarzt", start, end, calendar_name="Privat")

    mock_cal_privat.save_event.assert_called_once()
    ical_arg = mock_cal_privat.save_event.call_args[0][0]
    assert "Zahnarzt" in ical_arg
    assert "VEVENT" in ical_arg
    mock_cal_arbeit.save_event.assert_not_called()


def test_backend_create_event_defaults_to_first_calendar():
    """If calendar_name is None, use first whitelisted calendar."""
    from agents.calendar_agent import ICloudCalDAVBackend

    backend = ICloudCalDAVBackend("user@example.com", "pw", ["Privat"])
    mock_cal = MagicMock()
    mock_cal.name = "Privat"
    backend._calendars = [mock_cal]

    start = datetime(2026, 5, 10, 10, 0, tzinfo=BERLIN)
    end = datetime(2026, 5, 10, 11, 0, tzinfo=BERLIN)

    backend.create_event("Meeting", start, end, calendar_name=None)
    mock_cal.save_event.assert_called_once()


def test_agent_create_event_routes_to_backend():
    """CalendarAgent.create_event() delegates to the first backend that has create_event."""
    from agents.calendar_agent import CalendarAgent

    mock_backend = MagicMock()
    agent = CalendarAgent(backends=[mock_backend])

    start = datetime(2026, 5, 10, 10, 0, tzinfo=BERLIN)
    end = datetime(2026, 5, 10, 11, 0, tzinfo=BERLIN)

    agent.create_event("Besprechung", start, end, calendar_name="Arbeit")

    mock_backend.create_event.assert_called_once_with(
        "Besprechung", start, end, calendar_name="Arbeit"
    )


def test_agent_get_calendar_names_reads_env():
    from agents.calendar_agent import CalendarAgent
    with patch.dict("os.environ", {"CALENDAR_WHITELIST": "Privat, Arbeit"}):
        agent = CalendarAgent(backends=[])
        names = agent.get_calendar_names()
    assert "Privat" in names
    assert "Arbeit" in names
