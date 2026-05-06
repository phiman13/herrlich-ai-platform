import asyncio
import pytest
from unittest.mock import patch, AsyncMock
from agents.vps import read_file, list_projects, git_log, git_pull, write_file_and_commit


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


def test_git_log_returns_commits():
    with patch("agents.vps.run_as_claude", new_callable=AsyncMock) as mock:
        mock.return_value = (0, "abc1234 Fix auth\ndef5678 Add tests\n", "")
        result = asyncio.run(git_log("recipe-app", n=5))
    assert "abc1234" in result
    assert "Fix auth" in result


def test_git_log_fallback_on_error():
    with patch("agents.vps.run_as_claude", new_callable=AsyncMock) as mock:
        mock.return_value = (1, "", "not a git repo")
        result = asyncio.run(git_log("recipe-app"))
    assert result == "git log failed"


def test_git_pull_returns_true_on_success():
    with patch("agents.vps.run_as_claude", new_callable=AsyncMock) as mock:
        mock.return_value = (0, "", "")
        result = asyncio.run(git_pull("recipe-app"))
    assert result is True


def test_git_pull_returns_false_on_failure():
    with patch("agents.vps.run_as_claude", new_callable=AsyncMock) as mock:
        mock.return_value = (1, "", "error")
        result = asyncio.run(git_pull("recipe-app"))
    assert result is False


def test_write_file_and_commit_success():
    with patch("agents.vps.run_as_claude", new_callable=AsyncMock) as mock_run, \
         patch("builtins.open", create=True) as mock_open, \
         patch("agents.vps.os.chown") as mock_chown, \
         patch("agents.vps.pwd.getpwnam") as mock_pwd:
        mock_run.return_value = (0, "", "")
        mock_open.return_value.__enter__ = lambda s: s
        mock_open.return_value.__exit__ = lambda s, *a: None
        mock_open.return_value.write = lambda c: None
        mock_pwd.return_value.pw_uid = 1000
        mock_pwd.return_value.pw_gid = 1000
        result = asyncio.run(
            write_file_and_commit("recipe-app", "BACKLOG.md", "content", "msg")
        )
    assert result is True
