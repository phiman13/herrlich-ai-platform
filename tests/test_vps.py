import asyncio
import pytest
from unittest.mock import patch, AsyncMock
from agents.vps import (
    read_file,
    list_projects,
    git_log,
    git_pull,
    git_commit_all,
    write_file_and_commit,
    git_push,
    _safe_cwd,
)


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


@pytest.mark.asyncio
async def test_git_push_success():
    with patch("agents.vps.run_as_claude", new_callable=AsyncMock) as mock:
        mock.return_value = (0, "", "")
        result = await git_push("recipe-app")
    assert result is True


@pytest.mark.asyncio
async def test_git_push_failure():
    with patch("agents.vps.run_as_claude", new_callable=AsyncMock) as mock:
        mock.return_value = (1, "", "rejected")
        result = await git_push("recipe-app")
    assert result is False


def test_write_file_and_commit_success():
    # New impl: stage content in a temp file, then `cp` it into the workspace
    # AS claude via run_as_claude, then git add + commit. tempfile runs for
    # real; only run_as_claude (the privileged bridge) is mocked.
    with patch("agents.vps.run_as_claude", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = (0, "", "")
        result = asyncio.run(
            write_file_and_commit("recipe-app", "BACKLOG.md", "content", "msg")
        )
    assert result is True
    calls = [c.args[0] for c in mock_run.call_args_list]
    cwd = _safe_cwd("recipe-app")
    assert any(c[0] == "cp" for c in calls)
    assert ["git", "-C", cwd, "add", "BACKLOG.md"] in calls
    assert calls[-1] == ["git", "-C", cwd, "commit", "-m", "msg"]


@pytest.mark.asyncio
async def test_git_commit_all_commits_when_dirty():
    with patch("agents.vps.run_as_claude", new_callable=AsyncMock) as mock:
        mock.side_effect = [
            (0, " M file.py\n", ""),  # status --porcelain: dirty
            (0, "", ""),  # add -A
            (0, "", ""),  # commit
        ]
        result = await git_commit_all("recipe-app", "msg")
    assert result is True
    calls = [c.args[0] for c in mock.call_args_list]
    cwd = _safe_cwd("recipe-app")
    assert ["git", "-C", cwd, "add", "-A"] in calls
    assert calls[-1] == ["git", "-C", cwd, "commit", "-m", "msg"]


@pytest.mark.asyncio
async def test_git_commit_all_noop_when_clean():
    with patch("agents.vps.run_as_claude", new_callable=AsyncMock) as mock:
        mock.return_value = (0, "", "")  # status --porcelain: leer
        result = await git_commit_all("recipe-app", "msg")
    assert result is False
    calls = [c.args[0] for c in mock.call_args_list]
    assert len(calls) == 1  # nur status, kein add/commit
    assert all("commit" not in c for c in calls)
