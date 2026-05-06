import asyncio
import pytest
from unittest.mock import patch, AsyncMock
from agents.vps import read_file, list_projects, git_log


def test_list_projects_parses_output():
    with patch("agents.vps.run_as_claude", new_callable=AsyncMock) as mock:
        mock.return_value = (0, "recipe-app\nimmo-radar\nrefurbish-business\n", "")
        result = asyncio.run(list_projects())
    assert result == ["immo-radar", "recipe-app", "refurbish-business"]


def test_list_projects_filters_hidden():
    with patch("agents.vps.run_as_claude", new_callable=AsyncMock) as mock:
        mock.return_value = (0, "recipe-app\n.cache\nimmo-radar\n", "")
        result = asyncio.run(list_projects())
    assert ".cache" not in result


def test_read_file_returns_content():
    with patch("agents.vps.run_as_claude", new_callable=AsyncMock) as mock:
        mock.return_value = (0, "# Backlog\n- item 1\n", "")
        result = asyncio.run(read_file("recipe-app", "BACKLOG.md"))
    assert "item 1" in result


def test_read_file_not_found():
    with patch("agents.vps.run_as_claude", new_callable=AsyncMock) as mock:
        mock.return_value = (1, "", "No such file")
        result = asyncio.run(read_file("recipe-app", "NONEXISTENT.md"))
    assert result is None
