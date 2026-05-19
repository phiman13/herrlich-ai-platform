"""Tests für agents/tools/coding_tool.py."""

import asyncio
import pytest
from unittest.mock import AsyncMock

import app_state
import tools.coding_tool as coding_tool_mod


# ── Helpers ──────────────────────────────────────────────────────────────────


def _text_of(result):
    return result["content"][0]["text"]


# ── Read-only: sofort ausführen ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_projects_reads_immediately(monkeypatch):
    monkeypatch.setattr(
        coding_tool_mod,
        "_list_projects",
        AsyncMock(return_value=["recipe-app", "immo-radar"]),
    )
    tool = coding_tool_mod.make_coding_tool(7)
    result = await tool.handler({"action": "list_projects"})
    text = _text_of(result)
    assert "recipe-app" in text
    assert "immo-radar" in text
    assert app_state.peek_pending(7) is None


@pytest.mark.asyncio
async def test_query_reads_immediately(monkeypatch):
    monkeypatch.setattr(
        coding_tool_mod,
        "handle_coding_query",
        AsyncMock(return_value="# Backlog\n- [ ] Fix login"),
    )
    tool = coding_tool_mod.make_coding_tool(7)
    result = await tool.handler(
        {"action": "query", "project": "recipe-app", "query_type": "backlog"}
    )
    text = _text_of(result)
    assert "Fix login" in text
    assert app_state.peek_pending(7) is None


@pytest.mark.asyncio
async def test_query_requires_project_and_query_type():
    tool = coding_tool_mod.make_coding_tool(7)
    result = await tool.handler({"action": "query", "project": "recipe-app"})
    assert _text_of(result).startswith("FEHLER")


# ── run: sofort feuern, NICHT vormerken ──────────────────────────────────────


@pytest.mark.asyncio
async def test_run_fires_background_task(monkeypatch):
    app_state.pending_agent_actions.clear()
    ran = []

    async def _fake_run(task, project, chat_id):
        ran.append((task, project, chat_id))

    monkeypatch.setattr(coding_tool_mod, "run_coding_action", _fake_run)
    tool = coding_tool_mod.make_coding_tool(7)
    result = await tool.handler(
        {"action": "run", "project": "recipe-app", "task": "Fix the login bug"}
    )
    await asyncio.sleep(0)  # ein Event-Loop-Tick — Background-Task läuft
    assert ran == [("Fix the login bug", "recipe-app", 7)]
    assert "Hintergrund" in _text_of(result)
    assert app_state.peek_pending(7) is None  # explizit: NICHT staged
    app_state.pending_agent_actions.clear()


@pytest.mark.asyncio
async def test_run_requires_project_and_task(monkeypatch):
    monkeypatch.setattr(coding_tool_mod, "run_coding_action", AsyncMock())
    tool = coding_tool_mod.make_coding_tool(7)
    result = await tool.handler({"action": "run", "task": "Fix bug"})
    assert _text_of(result).startswith("FEHLER")


# ── backlog_write: vormerken, nicht ausführen ─────────────────────────────────


@pytest.mark.asyncio
async def test_backlog_write_stages_not_executes(monkeypatch):
    app_state.pending_agent_actions.clear()
    called = []
    monkeypatch.setattr(
        coding_tool_mod,
        "add_backlog_item",
        AsyncMock(side_effect=lambda *a: called.append(a) or True),
    )
    tool = coding_tool_mod.make_coding_tool(7)
    result = await tool.handler(
        {
            "action": "backlog_write",
            "project": "recipe-app",
            "item": "Dark mode implementieren",
            "priority": "P1",
        }
    )
    assert called == []
    assert "vorgemerkt" in _text_of(result).lower()
    entry = app_state.peek_pending(7)
    assert entry is not None
    a = entry["actions"][0]
    assert a["tool"] == "coding"
    assert a["action"] == "backlog_write"
    assert a["params"]["item"] == "Dark mode implementieren"
    assert a["params"]["project"] == "recipe-app"
    app_state.pending_agent_actions.clear()


@pytest.mark.asyncio
async def test_backlog_write_requires_project_and_item():
    app_state.pending_agent_actions.clear()
    tool = coding_tool_mod.make_coding_tool(7)
    result = await tool.handler({"action": "backlog_write", "item": "Fix bug"})
    assert _text_of(result).startswith("FEHLER")
    assert app_state.peek_pending(7) is None


@pytest.mark.asyncio
async def test_backlog_write_default_priority(monkeypatch):
    """Kein priority-Argument → Default 'P1' im gestagten params."""
    app_state.pending_agent_actions.clear()
    tool = coding_tool_mod.make_coding_tool(7)
    await tool.handler(
        {"action": "backlog_write", "project": "recipe-app", "item": "Neues Feature"}
    )
    entry = app_state.peek_pending(7)
    assert entry["actions"][0]["params"]["priority"] == "P1"
    app_state.pending_agent_actions.clear()


@pytest.mark.asyncio
async def test_unknown_action_is_error():
    tool = coding_tool_mod.make_coding_tool(7)
    result = await tool.handler({"action": "frobnicate"})
    assert _text_of(result).startswith("FEHLER")


# ── execute_write ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_write_backlog_write_success(monkeypatch):
    calls = []
    monkeypatch.setattr(
        coding_tool_mod,
        "add_backlog_item",
        AsyncMock(side_effect=lambda p, i, prio: calls.append((p, i, prio)) or True),
    )
    msg = await coding_tool_mod.execute_write(
        "backlog_write",
        {"project": "recipe-app", "item": "Dark mode", "priority": "P2"},
    )
    assert calls == [("recipe-app", "Dark mode", "P2")]
    assert "✅" in msg
    assert "recipe-app" in msg


@pytest.mark.asyncio
async def test_execute_write_backlog_write_failure(monkeypatch):
    monkeypatch.setattr(
        coding_tool_mod, "add_backlog_item", AsyncMock(return_value=False)
    )
    msg = await coding_tool_mod.execute_write(
        "backlog_write",
        {"project": "recipe-app", "item": "Dark mode", "priority": "P1"},
    )
    assert "❌" in msg
    assert "recipe-app" in msg


@pytest.mark.asyncio
async def test_execute_write_unknown_action():
    msg = await coding_tool_mod.execute_write("frobnicate", {})
    assert "Unbekannte" in msg
