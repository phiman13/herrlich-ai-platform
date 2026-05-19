"""Tests für die agent:confirm / agent:cancel Callbacks."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app_state
import callbacks


def _query(data: str):
    q = MagicMock()
    q.data = data
    q.answer = AsyncMock()
    q.edit_message_text = AsyncMock()
    q.message.chat_id = 42
    update = MagicMock()
    update.callback_query = q
    return update, q


@pytest.mark.asyncio
async def test_agent_confirm_executes_pending():
    app_state.pending_agent_actions.clear()
    app_state.stage_agent_action(42, "tasks", "add", "Task A anlegen", {"x": 1})
    pid = app_state.peek_pending(42)["id"]
    update, q = _query(f"agent:confirm:{pid}")

    async def fake_exec(action):
        return f"✅ {action['label']}"

    with patch("tools.execute_pending_action", side_effect=fake_exec):
        await callbacks.handle_callback(update, None)
    q.edit_message_text.assert_awaited_once()
    assert "✅ Task A anlegen" in q.edit_message_text.call_args.args[0]
    assert app_state.peek_pending(42) is None


@pytest.mark.asyncio
async def test_agent_confirm_executes_all_bundled():
    app_state.pending_agent_actions.clear()
    app_state.stage_agent_action(42, "tasks", "add", "Task A", {})
    app_state.stage_agent_action(42, "tasks", "complete", "Task B abhaken", {})
    pid = app_state.peek_pending(42)["id"]
    update, q = _query(f"agent:confirm:{pid}")

    async def fake_exec(action):
        return f"✅ {action['label']}"

    with patch("tools.execute_pending_action", side_effect=fake_exec):
        await callbacks.handle_callback(update, None)
    msg = q.edit_message_text.call_args.args[0]
    assert "Task A" in msg and "Task B abhaken" in msg
    assert app_state.peek_pending(42) is None


@pytest.mark.asyncio
async def test_agent_confirm_stale_id_rejected():
    app_state.pending_agent_actions.clear()
    app_state.stage_agent_action(42, "tasks", "add", "Task A", {})
    pid = app_state.peek_pending(42)["id"]
    update, q = _query(f"agent:confirm:{pid + 999}")  # veraltete/falsche ID
    await callbacks.handle_callback(update, None)
    assert "überholt" in q.edit_message_text.call_args.args[0].lower()
    # falsche ID -> Pending bleibt unangetastet
    assert app_state.peek_pending(42) is not None
    app_state.pending_agent_actions.clear()


@pytest.mark.asyncio
async def test_agent_confirm_nothing_pending():
    app_state.pending_agent_actions.clear()
    update, q = _query("agent:confirm:1")
    await callbacks.handle_callback(update, None)
    assert "abgelaufen" in q.edit_message_text.call_args.args[0].lower()


@pytest.mark.asyncio
async def test_agent_cancel_discards():
    app_state.pending_agent_actions.clear()
    app_state.stage_agent_action(42, "tasks", "add", "Task A", {})
    pid = app_state.peek_pending(42)["id"]
    update, q = _query(f"agent:cancel:{pid}")
    await callbacks.handle_callback(update, None)
    assert app_state.peek_pending(42) is None
    assert "Abgebrochen" in q.edit_message_text.call_args.args[0]
