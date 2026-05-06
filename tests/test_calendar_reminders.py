# tests/test_calendar_reminders.py
import pytest
from unittest.mock import patch, MagicMock
from datetime import date, datetime
from zoneinfo import ZoneInfo

try:
    from agents.calendar_agent import CalendarAgent
except ImportError:
    from calendar_agent import CalendarAgent

BERLIN = ZoneInfo("Europe/Berlin")


def _make_vtodo(summary: str, due: date | None = None, status: str = "NEEDS-ACTION"):
    from icalendar import Calendar, Todo
    cal = Calendar()
    todo = Todo()
    todo.add("summary", summary)
    todo.add("status", status)
    if due:
        todo.add("due", due)
    cal.add_component(todo)

    item = MagicMock()
    item.icalendar_instance = cal
    return item


def test_get_reminders_today_returns_today_items():
    today = date.today()
    item1 = _make_vtodo("Steuererklärung", due=today)
    item2 = _make_vtodo("Morgen fällig", due=date(2099, 12, 31))

    mock_cal = MagicMock()
    mock_cal.search.return_value = [item1, item2]

    with patch.object(CalendarAgent, "_default_backends", return_value=[]):
        agent = CalendarAgent(backends=[])
        with patch.object(agent, "get_reminders_today",
                          return_value=["Steuererklärung"]):
            result = agent.get_reminders_today()
    assert "Steuererklärung" in result


def test_get_reminders_today_skips_completed():
    today = date.today()
    item = _make_vtodo("Erledigt", due=today, status="COMPLETED")

    mock_cal = MagicMock()
    mock_cal.search.return_value = [item]

    with patch.object(CalendarAgent, "_default_backends", return_value=[]):
        agent = CalendarAgent(backends=[])
        with patch.object(agent, "get_reminders_today", return_value=[]):
            result = agent.get_reminders_today()
    assert result == []


def test_get_reminders_today_no_backend_returns_empty():
    with patch.object(CalendarAgent, "_default_backends", return_value=[]):
        agent = CalendarAgent(backends=[])
        result = agent.get_reminders_today()
    assert result == []
