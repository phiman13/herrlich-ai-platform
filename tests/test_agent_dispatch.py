"""Tests für die Feature-Flag-Verdrahtung in dispatch._process_text."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app_state
import dispatch


def _routing(intent):
    return {"intent": intent, "params": {}, "confidence": 8, "reasoning": ""}


@pytest.mark.asyncio
async def test_personal_routed_to_agent_when_flag_on():
    app_state.conversation_db = None
    app_state.profile_agent = None
    app_state.memory_agent = None
    update = MagicMock()
    with (
        patch(
            "dispatch.route_with_llm", new=AsyncMock(return_value=_routing("personal"))
        ),
        patch("dispatch.agent_enabled", return_value=True),
        patch(
            "dispatch.run_agent", new=AsyncMock(return_value="Agent-Antwort")
        ) as mock_run,
        patch("dispatch.handle_personal", new=AsyncMock()) as mock_personal,
    ):
        await dispatch._process_text("Hallo", 123, update)
    mock_run.assert_awaited_once()
    mock_personal.assert_not_awaited()


@pytest.mark.asyncio
async def test_personal_routed_to_legacy_handler_when_flag_off():
    app_state.conversation_db = None
    app_state.profile_agent = None
    app_state.memory_agent = None
    update = MagicMock()
    with (
        patch(
            "dispatch.route_with_llm", new=AsyncMock(return_value=_routing("personal"))
        ),
        patch("dispatch.agent_enabled", return_value=False),
        patch("dispatch.run_agent", new=AsyncMock()) as mock_run,
        patch(
            "dispatch.handle_personal", new=AsyncMock(return_value="Klassik")
        ) as mock_personal,
    ):
        await dispatch._process_text("Hallo", 123, update)
    mock_personal.assert_awaited_once()
    mock_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_weather_never_routed_to_agent():
    app_state.conversation_db = None
    app_state.profile_agent = None
    app_state.memory_agent = None
    update = MagicMock()
    with (
        patch(
            "dispatch.route_with_llm", new=AsyncMock(return_value=_routing("weather"))
        ),
        patch("dispatch.agent_enabled", return_value=True),
        patch("dispatch.run_agent", new=AsyncMock()) as mock_run,
        patch("dispatch.handle_weather", new=AsyncMock()) as mock_weather,
    ):
        await dispatch._process_text("Wetter morgen?", 123, update)
    mock_weather.assert_awaited_once()
    mock_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_work_routed_to_legacy_handler_when_flag_off():
    app_state.conversation_db = None
    app_state.profile_agent = None
    app_state.memory_agent = None
    update = MagicMock()
    with (
        patch("dispatch.route_with_llm", new=AsyncMock(return_value=_routing("work"))),
        patch("dispatch.agent_enabled", return_value=False),
        patch("dispatch.run_agent", new=AsyncMock()) as mock_run,
        patch(
            "dispatch.handle_work", new=AsyncMock(return_value="Klassik")
        ) as mock_work,
    ):
        await dispatch._process_text("Arbeit", 123, update)
    mock_work.assert_awaited_once()
    mock_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_research_routed_to_legacy_handler_when_flag_off():
    app_state.conversation_db = None
    app_state.profile_agent = None
    app_state.memory_agent = None
    update = MagicMock()
    with (
        patch(
            "dispatch.route_with_llm", new=AsyncMock(return_value=_routing("research"))
        ),
        patch("dispatch.agent_enabled", return_value=False),
        patch("dispatch.run_agent", new=AsyncMock()) as mock_run,
        patch(
            "dispatch.handle_research", new=AsyncMock(return_value="Klassik")
        ) as mock_research,
    ):
        await dispatch._process_text("Recherche", 123, update)
    mock_research.assert_awaited_once()
    mock_run.assert_not_awaited()


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
            patch("dispatch.agent_enabled", return_value=True),
            patch("dispatch.run_agent", new=AsyncMock(return_value="Agent-Antwort")),
        ):
            await dispatch._process_text("Frage", 123, update)
    finally:
        app_state.conversation_db = None
    assert mock_conv_db.save.await_count == 2
    saved_roles = [call.args[1] for call in mock_conv_db.save.await_args_list]
    assert saved_roles == ["user", "assistant"]
