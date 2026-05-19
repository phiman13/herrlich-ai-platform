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
async def test_news_routed_to_agent():
    app_state.conversation_db = None
    app_state.profile_agent = None
    app_state.memory_agent = None
    update = MagicMock()
    with (
        patch("dispatch.route_with_llm", new=AsyncMock(return_value=_routing("news"))),
        patch(
            "dispatch.run_agent", new=AsyncMock(return_value="News-Antwort")
        ) as mock_run,
    ):
        await dispatch._process_text("Was gibt es Neues in AI?", 123, update)
    mock_run.assert_awaited_once()


@pytest.mark.asyncio
async def test_tasks_routed_to_agent():
    app_state.conversation_db = None
    app_state.profile_agent = None
    app_state.memory_agent = None
    update = MagicMock()
    with (
        patch("dispatch.route_with_llm", new=AsyncMock(return_value=_routing("tasks"))),
        patch(
            "dispatch.run_agent", new=AsyncMock(return_value="Tasks-Antwort")
        ) as mock_run,
    ):
        await dispatch._process_text("Zeig meine Tasks", 123, update)
    mock_run.assert_awaited_once()


@pytest.mark.asyncio
async def test_reminder_write_routed_to_agent():
    app_state.conversation_db = None
    app_state.profile_agent = None
    app_state.memory_agent = None
    update = MagicMock()
    with (
        patch(
            "dispatch.route_with_llm",
            new=AsyncMock(return_value=_routing("reminder_write")),
        ),
        patch(
            "dispatch.run_agent", new=AsyncMock(return_value="Erinnerung-Antwort")
        ) as mock_run,
    ):
        await dispatch._process_text("Erinnere mich an den Anruf", 123, update)
    mock_run.assert_awaited_once()


@pytest.mark.asyncio
async def test_weather_does_not_trigger_profile_update():
    """Triviale Intents (weather/news) lösen kein Profil-Update aus — nur
    Gesprächs-Intents (_MEMORY_INTENTS) lernen ins Profil."""
    app_state.conversation_db = None
    app_state.memory_agent = None
    mock_profile = MagicMock()
    mock_profile.load.return_value = ""
    mock_profile.update = AsyncMock()
    app_state.profile_agent = mock_profile
    update = MagicMock()
    try:
        with (
            patch(
                "dispatch.route_with_llm",
                new=AsyncMock(return_value=_routing("weather")),
            ),
            patch("dispatch.run_agent", new=AsyncMock(return_value="Wetter-Antwort")),
        ):
            await dispatch._process_text("Wetter morgen?", 123, update)
    finally:
        app_state.profile_agent = None
    mock_profile.update.assert_not_called()


@pytest.mark.asyncio
async def test_mail_routed_to_agent():
    app_state.conversation_db = None
    app_state.profile_agent = None
    app_state.memory_agent = None
    update = MagicMock()
    with (
        patch("dispatch.route_with_llm", new=AsyncMock(return_value=_routing("mail"))),
        patch(
            "dispatch.run_agent", new=AsyncMock(return_value="Mail-Antwort")
        ) as mock_run,
    ):
        await dispatch._process_text("Was Wichtiges im Posteingang?", 123, update)
    mock_run.assert_awaited_once()


@pytest.mark.asyncio
async def test_calendar_routed_to_agent():
    app_state.conversation_db = None
    app_state.profile_agent = None
    app_state.memory_agent = None
    update = MagicMock()
    with (
        patch(
            "dispatch.route_with_llm", new=AsyncMock(return_value=_routing("calendar"))
        ),
        patch(
            "dispatch.run_agent", new=AsyncMock(return_value="Kalender-Antwort")
        ) as mock_run,
    ):
        await dispatch._process_text("Nächster Termin?", 123, update)
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
