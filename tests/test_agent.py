"""Tests für agents/agent.py."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

import agent
import app_state


def test_system_prompt_includes_memory_context():
    prompt = agent.build_system_prompt("=== Erinnerungen ===\nPhilipp mag Tee\n\n")
    assert "Philipp mag Tee" in prompt
    assert "workspace" in prompt


def test_system_prompt_empty_memory():
    prompt = agent.build_system_prompt("")
    assert prompt.startswith("Du bist Jarvis")
    assert "- weather:" in prompt
    assert "- news:" in prompt


def test_format_history_interleaves_roles():
    history = [
        {"role": "user", "content": "Frage 1"},
        {"role": "assistant", "content": "Antwort 1"},
    ]
    text = agent.format_history(history)
    assert "Philipp: Frage 1" in text
    assert "Jarvis: Antwort 1" in text


def test_format_history_empty():
    assert agent.format_history([]) == ""


def test_format_history_caps_turns():
    history = [{"role": "user", "content": f"m{i}"} for i in range(100)]
    text = agent.format_history(history)
    # 100 Einträge -> auf _HISTORY_TURNS*2 (=30) gekappt -> 29 Zeilenumbrüche
    assert text.count("\n") == (agent._HISTORY_TURNS * 2) - 1


def test_build_user_prompt_with_history():
    history = [{"role": "user", "content": "alt"}]
    prompt = agent.build_user_prompt(history, "neue Frage")
    assert "[Bisheriger Gesprächsverlauf]" in prompt
    assert "[Aktuelle Nachricht]" in prompt
    assert "neue Frage" in prompt


def test_build_user_prompt_no_history():
    assert agent.build_user_prompt([], "nur die Frage") == "nur die Frage"


def test_get_agent_lock_returns_same_lock_per_chat():
    app_state.agent_run_locks.clear()
    lock_a1 = app_state.get_agent_lock(111)
    lock_a2 = app_state.get_agent_lock(111)
    lock_b = app_state.get_agent_lock(222)
    assert lock_a1 is lock_a2
    assert lock_a1 is not lock_b
    assert isinstance(lock_a1, asyncio.Lock)


def _fake_assistant(text):
    msg = MagicMock(spec=AssistantMessage)
    block = MagicMock(spec=TextBlock)
    block.text = text
    msg.content = [block]
    return msg


def _fake_result(result_text, is_error=False):
    msg = MagicMock(spec=ResultMessage)
    msg.result = result_text
    msg.is_error = is_error
    return msg


@pytest.mark.asyncio
async def test_run_agent_returns_result_text():
    async def fake_query(*, prompt, options=None, transport=None):
        yield _fake_assistant("Zwischentext")
        yield _fake_result("Die finale Antwort.")

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()
    app_state.agent_run_locks.clear()
    with (
        patch("agent.query", fake_query),
        patch("agent.Bot", return_value=mock_bot),
        patch("agent._keep_typing", new=AsyncMock()),
    ):
        answer = await agent.run_agent(555, "Hallo", [], "")

    assert answer == "Die finale Antwort."
    mock_bot.send_message.assert_awaited_once()
    assert mock_bot.send_message.call_args.kwargs["text"] == "Die finale Antwort."


@pytest.mark.asyncio
async def test_run_agent_handles_query_exception():
    async def boom(*, prompt, options=None, transport=None):
        raise RuntimeError("CLI weg")
        yield  # pragma: no cover

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()
    mock_keep_typing = AsyncMock()
    app_state.agent_run_locks.clear()
    with (
        patch("agent.query", boom),
        patch("agent.Bot", return_value=mock_bot),
        patch("agent._keep_typing", mock_keep_typing),
    ):
        answer = await agent.run_agent(555, "Hallo", [], "")

    assert answer.startswith("Fehler:")
    mock_bot.send_message.assert_awaited_once()
    # finally-Block muss den Typing-Task auch im Fehlerfall sauber beenden
    mock_keep_typing.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_agent_serializes_per_chat():
    order = []

    async def slow_query(*, prompt, options=None, transport=None):
        order.append("start")
        await asyncio.sleep(0.05)
        order.append("end")
        yield _fake_result("ok")

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()
    app_state.agent_run_locks.clear()
    with (
        patch("agent.query", slow_query),
        patch("agent.Bot", return_value=mock_bot),
        patch("agent._keep_typing", new=AsyncMock()),
    ):
        await asyncio.gather(
            agent.run_agent(777, "A", [], ""),
            agent.run_agent(777, "B", [], ""),
        )

    # Serialisiert: erst beide Schritte von Lauf 1, dann Lauf 2 — kein Interleaving.
    assert order == ["start", "end", "start", "end"]


@pytest.mark.asyncio
async def test_run_agent_uses_assistant_text_without_result():
    async def fake_query(*, prompt, options=None, transport=None):
        yield _fake_assistant("Nur Assistant-Text")

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()
    app_state.agent_run_locks.clear()
    with (
        patch("agent.query", fake_query),
        patch("agent.Bot", return_value=mock_bot),
        patch("agent._keep_typing", new=AsyncMock()),
    ):
        answer = await agent.run_agent(556, "Hallo", [], "")

    assert answer == "Nur Assistant-Text"


@pytest.mark.asyncio
async def test_run_agent_forces_subscription_billing():
    """run_agent klemmt ANTHROPIC_API_KEY für den CLI-Subprozess ab → Abo-Billing."""
    captured = {}

    async def fake_query(*, prompt, options=None, transport=None):
        captured["options"] = options
        yield _fake_result("ok")

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()
    app_state.agent_run_locks.clear()
    with (
        patch("agent.query", fake_query),
        patch("agent.Bot", return_value=mock_bot),
        patch("agent._keep_typing", new=AsyncMock()),
    ):
        await agent.run_agent(558, "Hallo", [], "")

    assert captured["options"].env.get("ANTHROPIC_API_KEY") == ""
