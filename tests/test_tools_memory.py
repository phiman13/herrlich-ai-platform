"""Tests für agents/tools/memory_tool.py."""

import pytest
import app_state
import tools.memory_tool as memory_tool_mod


class _MockMemoryAgent:
    def __init__(self, list_result="Liste", delete_result="✅ Gelöscht"):
        self._list_result = list_result
        self._delete_result = delete_result
        self.delete_calls = []

    async def list_memories(self):
        return self._list_result

    async def delete_memory(self, query):
        self.delete_calls.append(query)
        return self._delete_result


@pytest.mark.asyncio
async def test_list_reads_immediately():
    app_state.pending_agent_actions.clear()
    agent = _MockMemoryAgent(list_result="🧠 *Erinnerungen:*\n• Mag Kaffee")
    app_state.memory_agent = agent
    try:
        tool = memory_tool_mod.make_memory_tool(7)
        result = await tool.handler({"action": "list"})
        assert "Erinnerungen" in result["content"][0]["text"]
        assert app_state.peek_pending(7) is None
    finally:
        app_state.memory_agent = None


@pytest.mark.asyncio
async def test_list_no_memory_agent():
    app_state.pending_agent_actions.clear()
    app_state.memory_agent = None
    tool = memory_tool_mod.make_memory_tool(7)
    result = await tool.handler({"action": "list"})
    text = result["content"][0]["text"]
    assert "FEHLER" in text or "nicht" in text.lower()
    assert app_state.peek_pending(7) is None


@pytest.mark.asyncio
async def test_delete_stages_not_executes():
    app_state.pending_agent_actions.clear()
    agent = _MockMemoryAgent()
    app_state.memory_agent = agent
    try:
        tool = memory_tool_mod.make_memory_tool(7)
        result = await tool.handler({"action": "delete", "query": "Kaffee"})
        assert agent.delete_calls == []
        assert "vorgemerkt" in result["content"][0]["text"].lower()
        entry = app_state.peek_pending(7)
        assert entry is not None
        a = entry["actions"][0]
        assert a["tool"] == "memory"
        assert a["action"] == "delete"
        assert a["params"]["query"] == "Kaffee"
    finally:
        app_state.memory_agent = None
        app_state.pending_agent_actions.clear()


@pytest.mark.asyncio
async def test_delete_without_query_stages_last():
    app_state.pending_agent_actions.clear()
    agent = _MockMemoryAgent()
    app_state.memory_agent = agent
    try:
        tool = memory_tool_mod.make_memory_tool(7)
        result = await tool.handler({"action": "delete"})
        assert agent.delete_calls == []
        assert "vorgemerkt" in result["content"][0]["text"].lower()
        entry = app_state.peek_pending(7)
        assert entry is not None
        a = entry["actions"][0]
        assert a["params"]["query"] is None
    finally:
        app_state.memory_agent = None
        app_state.pending_agent_actions.clear()


@pytest.mark.asyncio
async def test_unknown_action_is_error():
    app_state.memory_agent = None
    tool = memory_tool_mod.make_memory_tool(7)
    result = await tool.handler({"action": "frobnicate"})
    assert result["content"][0]["text"].startswith("FEHLER")


@pytest.mark.asyncio
async def test_execute_write_delete_with_query():
    agent = _MockMemoryAgent(delete_result="✅ Erinnerung gelöscht: _Mag Kaffee_")
    app_state.memory_agent = agent
    try:
        msg = await memory_tool_mod.execute_write("delete", {"query": "Kaffee"})
        assert agent.delete_calls == ["Kaffee"]
        assert "✅" in msg
    finally:
        app_state.memory_agent = None


@pytest.mark.asyncio
async def test_execute_write_delete_without_query():
    agent = _MockMemoryAgent(delete_result="✅ Letzte Erinnerung gelöscht.")
    app_state.memory_agent = agent
    try:
        msg = await memory_tool_mod.execute_write("delete", {"query": None})
        assert agent.delete_calls == [None]
        assert "✅" in msg
    finally:
        app_state.memory_agent = None


@pytest.mark.asyncio
async def test_execute_write_no_memory_agent():
    app_state.memory_agent = None
    msg = await memory_tool_mod.execute_write("delete", {"query": None})
    assert "❌" in msg


@pytest.mark.asyncio
async def test_execute_write_unknown_action():
    msg = await memory_tool_mod.execute_write("frobnicate", {})
    assert "❌" in msg or "Unbekannte" in msg
