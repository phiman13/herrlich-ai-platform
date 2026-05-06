# tests/test_coding_agent.py
import asyncio
import pytest
from unittest.mock import patch, AsyncMock
from agents.coding_agent import handle_coding_query, _run_claude_action


@pytest.mark.asyncio
async def test_query_backlog():
    with patch("agents.coding_agent.read_file", new_callable=AsyncMock) as mock_read, \
         patch("agents.coding_agent.git_pull", new_callable=AsyncMock) as mock_pull, \
         patch("agents.coding_agent.list_projects", new_callable=AsyncMock) as mock_list:
        mock_pull.return_value = True
        mock_list.return_value = ["recipe-app", "immo-radar"]
        mock_read.return_value = "# Backlog\n- [ ] Fix login\n- [ ] Add tests\n"
        result = await handle_coding_query("recipe-app", "backlog")
    assert "Fix login" in result
    assert "Add tests" in result


@pytest.mark.asyncio
async def test_query_git_log():
    with patch("agents.coding_agent.git_log", new_callable=AsyncMock) as mock_log, \
         patch("agents.coding_agent.git_pull", new_callable=AsyncMock) as mock_pull, \
         patch("agents.coding_agent.list_projects", new_callable=AsyncMock) as mock_list:
        mock_pull.return_value = True
        mock_list.return_value = ["recipe-app"]
        mock_log.return_value = "abc1234 Fix auth\ndef5678 Add tests\n"
        result = await handle_coding_query("recipe-app", "git_log")
    assert "abc1234" in result


@pytest.mark.asyncio
async def test_query_unknown_project():
    with patch("agents.coding_agent.list_projects", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = ["recipe-app", "immo-radar"]
        result = await handle_coding_query("nonexistent-project", "backlog")
    assert "nicht gefunden" in result.lower() or "verfügbare" in result.lower()


@pytest.mark.asyncio
async def test_query_backlog_falls_back_to_todo():
    """Wenn kein BACKLOG.md, fällt zurück auf TODO.md"""
    with patch("agents.coding_agent.read_file", new_callable=AsyncMock) as mock_read, \
         patch("agents.coding_agent.git_pull", new_callable=AsyncMock), \
         patch("agents.coding_agent.list_projects", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = ["recipe-app"]
        # BACKLOG.md fehlt, TODO.md vorhanden
        mock_read.side_effect = [None, "- [ ] Todo item\n"]
        result = await handle_coding_query("recipe-app", "backlog")
    assert "Todo item" in result


@pytest.mark.asyncio
async def test_action_parses_session_id():
    """Claude Code stream-json output enthält session_id im result-Event."""
    fake_output = (
        '{"type":"system","subtype":"init","session_id":"sess_abc123"}\n'
        '{"type":"assistant","message":{"content":[{"type":"text","text":"Done."}]}}\n'
        '{"type":"result","subtype":"success","session_id":"sess_abc123","result":"Fixed."}\n'
    )
    with patch("agents.coding_agent.run_as_claude", new_callable=AsyncMock) as mock_run, \
         patch("agents.coding_agent._db") as mock_db:
        mock_run.return_value = (0, fake_output, "")
        mock_db.upsert_session = AsyncMock()
        session_id, output = await _run_claude_action(
            project="recipe-app",
            task="Fix the login bug",
            existing_session=None,
        )
    assert session_id == "sess_abc123"
    assert "Fixed." in output or "Done." in output


@pytest.mark.asyncio
async def test_action_uses_resume_when_session_exists():
    with patch("agents.coding_agent.run_as_claude", new_callable=AsyncMock) as mock_run, \
         patch("agents.coding_agent._db") as mock_db:
        mock_run.return_value = (0, '{"type":"result","session_id":"sess_xyz","result":"ok"}\n', "")
        mock_db.upsert_session = AsyncMock()
        await _run_claude_action(
            project="recipe-app",
            task="Also add tests",
            existing_session="sess_existing",
        )
    call_args = mock_run.call_args[0][0]  # cmd list
    assert "--resume" in call_args
    assert "sess_existing" in call_args
