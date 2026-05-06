# tests/test_tasks_agent.py
import pytest
from unittest.mock import patch, MagicMock

try:
    from agents.tasks_agent import get_tasks, add_task, complete_task, _find_list_id
except ImportError:
    from tasks_agent import get_tasks, add_task, complete_task, _find_list_id

_LISTS = [
    {"id": "list1", "displayName": "Einkaufsliste"},
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
        result = complete_task("Einkaufsliste", "Milch")
    assert result is True
    mock_patch.assert_called_once()
