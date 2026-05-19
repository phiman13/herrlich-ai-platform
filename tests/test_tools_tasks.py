"""Tests für agents/tools/tasks_tool.py."""

import pytest

import app_state
import tools.tasks_tool as tasks_tool_mod


@pytest.mark.asyncio
async def test_list_action_reads_immediately(monkeypatch):
    monkeypatch.setattr(tasks_tool_mod, "get_tasks", lambda ln: "📋 Liste: A, B")
    tool = tasks_tool_mod.make_tasks_tool(7)
    result = await tool.handler({"action": "list", "list_name": "Einkaufen"})
    assert "Liste: A, B" in result["content"][0]["text"]


@pytest.mark.asyncio
async def test_add_action_stages_not_executes(monkeypatch):
    app_state.pending_agent_actions.clear()
    called = []
    monkeypatch.setattr(
        tasks_tool_mod, "add_task", lambda *a, **k: called.append(a) or True
    )
    tool = tasks_tool_mod.make_tasks_tool(7)
    result = await tool.handler(
        {"action": "add", "list_name": "Einkaufen", "title": "Milch"}
    )
    # vorgemerkt, NICHT ausgeführt
    assert called == []
    assert "vorgemerkt" in result["content"][0]["text"].lower()
    entry = app_state.peek_pending(7)
    assert entry is not None and len(entry["actions"]) == 1
    assert entry["actions"][0]["tool"] == "tasks"
    assert entry["actions"][0]["action"] == "add"
    assert entry["actions"][0]["params"]["title"] == "Milch"
    app_state.pending_agent_actions.clear()


@pytest.mark.asyncio
async def test_add_action_requires_list_and_title():
    app_state.pending_agent_actions.clear()
    tool = tasks_tool_mod.make_tasks_tool(7)
    result = await tool.handler({"action": "add", "title": "Milch"})
    assert result["content"][0]["text"].startswith("FEHLER")
    assert app_state.peek_pending(7) is None


@pytest.mark.asyncio
async def test_unknown_action_is_error():
    tool = tasks_tool_mod.make_tasks_tool(7)
    result = await tool.handler({"action": "frobnicate"})
    assert result["content"][0]["text"].startswith("FEHLER")


@pytest.mark.asyncio
async def test_execute_write_add_calls_add_task(monkeypatch):
    calls = []
    monkeypatch.setattr(tasks_tool_mod, "add_task", lambda *a: calls.append(a) or True)
    msg = await tasks_tool_mod.execute_write(
        "add",
        {
            "list_name": "Einkaufen",
            "title": "Milch",
            "due_date": None,
            "due_time": None,
        },
    )
    assert calls == [("Einkaufen", "Milch", None, None)]
    assert "✅" in msg


@pytest.mark.asyncio
async def test_execute_write_add_failure(monkeypatch):
    monkeypatch.setattr(tasks_tool_mod, "add_task", lambda *a: False)
    msg = await tasks_tool_mod.execute_write(
        "add", {"list_name": "Nope", "title": "X", "due_date": None, "due_time": None}
    )
    assert "❌" in msg


@pytest.mark.asyncio
async def test_execute_write_unknown_action_returns_error():
    msg = await tasks_tool_mod.execute_write("frobnicate", {})
    assert "Unbekannte" in msg


@pytest.mark.asyncio
async def test_stage_then_execute_via_registry(monkeypatch):
    """Integration: Tool merkt vor -> execute_pending_action führt aus."""
    import tools

    app_state.pending_agent_actions.clear()
    calls = []
    monkeypatch.setattr(tasks_tool_mod, "add_task", lambda *a: calls.append(a) or True)
    tool = tasks_tool_mod.make_tasks_tool(9)
    await tool.handler({"action": "add", "list_name": "Einkaufen", "title": "Milch"})
    entry = app_state.peek_pending(9)
    assert entry is not None and len(entry["actions"]) == 1
    msg = await tools.execute_pending_action(entry["actions"][0])
    assert calls == [("Einkaufen", "Milch", None, None)]
    assert "✅" in msg
    app_state.pending_agent_actions.clear()
