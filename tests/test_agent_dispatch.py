"""Tests für die Intent-Verdrahtung in dispatch._process_text."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app_state
import dispatch


def _routing(intent):
    return {"intent": intent, "params": {}, "confidence": 8, "reasoning": ""}


@pytest.mark.asyncio
async def test_personal_routed_to_agent():
    app_state.conversation_db = None
    app_state.profile_agent = None
    app_state.memory_agent = None
    update = MagicMock()
    with (
        patch(
            "dispatch.route_with_llm", new=AsyncMock(return_value=_routing("personal"))
        ),
        patch(
            "dispatch.run_agent", new=AsyncMock(return_value="Agent-Antwort")
        ) as mock_run,
    ):
        await dispatch._process_text("Hallo", 123, update)
    mock_run.assert_awaited_once()


@pytest.mark.asyncio
async def test_weather_routed_to_agent():
    app_state.conversation_db = None
    app_state.profile_agent = None
    app_state.memory_agent = None
    update = MagicMock()
    with (
        patch(
            "dispatch.route_with_llm", new=AsyncMock(return_value=_routing("weather"))
        ),
        patch(
            "dispatch.run_agent", new=AsyncMock(return_value="Wetter-Antwort")
        ) as mock_run,
    ):
        await dispatch._process_text("Wetter morgen?", 123, update)
    mock_run.assert_awaited_once()


@pytest.mark.asyncio
async def test_agent_answer_persisted_to_conversation_db():
    app_state.profile_agent = None
    app_state.memory_agent = None
    mock_conv_db = MagicMock()
    mock_conv_db.get_recent = AsyncMock(return_value=[])
    mock_conv_db.save = AsyncMock()
    app_state.conversation_db = mock_conv_db
    update = MagicMock()
    try:
        with (
            patch(
                "dispatch.route_with_llm",
                new=AsyncMock(return_value=_routing("personal")),
            ),
            patch("dispatch.run_agent", new=AsyncMock(return_value="Agent-Antwort")),
        ):
            await dispatch._process_text("Frage", 123, update)
    finally:
        app_state.conversation_db = None
    assert mock_conv_db.save.await_count == 2
    saved_roles = [call.args[1] for call in mock_conv_db.save.await_args_list]
    assert saved_roles == ["user", "assistant"]
