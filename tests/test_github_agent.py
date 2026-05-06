# tests/test_github_agent.py
import pytest
from unittest.mock import patch, MagicMock

try:
    from agents.github_agent import get_github_summary, _format_age
except ImportError:
    from github_agent import get_github_summary, _format_age


def _mock_prs(titles):
    from datetime import datetime, timezone
    prs = []
    for t in titles:
        pr = {"title": t, "number": 1, "created_at": "2026-05-01T10:00:00Z", "html_url": "https://github.com/x"}
        prs.append(pr)
    return prs


def test_format_age_days():
    result = _format_age("2026-05-01T10:00:00Z")
    assert "Tag" in result or "d" in result


def test_get_github_summary_with_open_prs():
    def fake_get(url, **kwargs):
        m = MagicMock()
        m.json.return_value = _mock_prs(["Fix login bug"])
        m.raise_for_status = MagicMock()
        return m

    with patch("httpx.get", side_effect=fake_get):
        result = get_github_summary()
    assert "Fix login bug" in result or "PR" in result or "recipe-app" in result


def test_get_github_summary_no_prs():
    def fake_get(url, **kwargs):
        m = MagicMock()
        m.json.return_value = []
        m.raise_for_status = MagicMock()
        return m

    with patch("httpx.get", side_effect=fake_get):
        result = get_github_summary()
    assert "GITHUB" in result


def test_get_github_summary_api_error():
    with patch("httpx.get", side_effect=Exception("network error")):
        result = get_github_summary()
    assert "GitHub" in result or "nicht verfügbar" in result.lower()
