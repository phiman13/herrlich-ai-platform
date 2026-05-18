# tests/test_tasks_agent.py
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from zoneinfo import ZoneInfo

import pytest

try:
    from agents.tasks_agent import (
        get_tasks,
        get_briefing_tasks,
        add_task,
        complete_task,
        _find_list_id,
    )
except ImportError:
    from tasks_agent import (
        get_tasks,
        get_briefing_tasks,
        add_task,
        complete_task,
        _find_list_id,
    )

_LISTS = [
    {"id": "list1", "displayName": "Einkaufen"},
    {"id": "list2", "displayName": "Arbeit"},
]
_TASKS = [
    {"id": "t1", "title": "Milch", "status": "notStarted"},
    {"id": "t2", "title": "Brot", "status": "notStarted"},
]


def _mock_get(url, **kwargs):
    m = MagicMock()
    m.raise_for_status = MagicMock()
    if "lists" in url and "tasks" not in url:
        m.json.return_value = {"value": _LISTS}
    else:
        m.json.return_value = {"value": _TASKS}
    return m


def test_get_tasks_returns_items():
    with patch("httpx.get", side_effect=_mock_get), \
         patch("agents.tasks_agent.get_access_token", return_value="tok"):
        result = get_tasks("Einkaufsliste")
    assert "Milch" in result
    assert "Brot" in result


def test_get_tasks_unknown_list():
    with patch("httpx.get", side_effect=_mock_get), \
         patch("agents.tasks_agent.get_access_token", return_value="tok"):
        result = get_tasks("Nichtvorhanden")
    assert "nicht gefunden" in result.lower() or result == ""


def test_add_task_calls_post():
    with patch("httpx.get", side_effect=_mock_get), \
         patch("agents.tasks_agent.get_access_token", return_value="tok"), \
         patch("httpx.post") as mock_post:
        mock_post.return_value = MagicMock(raise_for_status=MagicMock())
        result = add_task("Einkaufsliste", "Butter")
    assert result is True
    mock_post.assert_called_once()


def test_add_task_unknown_list():
    with patch("httpx.get", side_effect=_mock_get), \
         patch("agents.tasks_agent.get_access_token", return_value="tok"):
        result = add_task("Nichtvorhanden", "Butter")
    assert result is False


def test_complete_task_patches():
    with patch("httpx.get", side_effect=_mock_get), \
         patch("agents.tasks_agent.get_access_token", return_value="tok"), \
         patch("httpx.patch") as mock_patch:
        mock_patch.return_value = MagicMock(raise_for_status=MagicMock())
        result = complete_task("Einkaufen", "Milch")
    assert result is True
    mock_patch.assert_called_once()


def test_find_list_id_fuzzy_match():
    """'Einkaufsliste' soll 'Einkaufen' matchen (substring)."""
    with patch("agents.tasks_agent._get_lists", return_value=_LISTS), \
         patch("agents.tasks_agent.get_access_token", return_value="tok"):
        result = _find_list_id("Einkaufsliste")
    assert result == "list1"


def test_find_list_id_exact_match():
    with patch("agents.tasks_agent._get_lists", return_value=_LISTS), \
         patch("agents.tasks_agent.get_access_token", return_value="tok"):
        result = _find_list_id("Arbeit")
    assert result == "list2"


def test_find_list_id_no_match():
    with patch("agents.tasks_agent._get_lists", return_value=_LISTS), \
         patch("agents.tasks_agent.get_access_token", return_value="tok"):
        result = _find_list_id("Komplett unbekannt xyz")
    assert result is None


def test_get_briefing_tasks_filters_by_due_and_reminder():
    """Briefing zeigt nur heute fällige/überfällige Tasks oder Reminder für heute."""
    today = datetime.now(ZoneInfo("Europe/Berlin")).date()
    yesterday = today - timedelta(days=1)
    tomorrow = today + timedelta(days=1)

    def _due(d):
        return {"dateTime": f"{d.isoformat()}T00:00:00.0000000", "timeZone": "Europe/Berlin"}

    def _reminder(d):
        return {"dateTime": f"{d.isoformat()}T09:00:00.0000000", "timeZone": "Europe/Berlin"}

    briefing_tasks = [
        {"title": "Heute fällig", "dueDateTime": _due(today)},
        {"title": "Überfällig", "dueDateTime": _due(yesterday)},
        {"title": "Morgen fällig", "dueDateTime": _due(tomorrow)},
        {"title": "Reminder heute", "isReminderOn": True, "reminderDateTime": _reminder(today)},
        {"title": "Reminder morgen", "isReminderOn": True, "reminderDateTime": _reminder(tomorrow)},
        {"title": "Ohne Datum"},
    ]

    def _mock(url, **kwargs):
        m = MagicMock()
        m.raise_for_status = MagicMock()
        if "lists" in url and "tasks" not in url:
            m.json.return_value = {"value": _LISTS}
        else:
            m.json.return_value = {"value": briefing_tasks}
        return m

    with patch("httpx.get", side_effect=_mock), \
         patch("agents.tasks_agent.get_access_token", return_value="tok"):
        result = get_briefing_tasks("Arbeit")

    assert "Heute fällig" in result
    assert "Überfällig" in result
    assert "Reminder heute" in result
    assert "Morgen fällig" not in result
    assert "Reminder morgen" not in result
    assert "Ohne Datum" not in result
