"""Tests für dispatch._process_text — ohne Router, run_agent immer."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app_state
import dispatch


@pytest.mark.asyncio
async def test_any_message_calls_run_agent():
    app_state.conversation_db = None
    app_state.profile_agent = None
    app_state.memory_agent = None
    with patch("dispatch.run_agent", new=AsyncMock(return_value="Antwort")) as mock_run:
        await dispatch._process_text("Hallo", 123)
    mock_run.assert_awaited_once()


@pytest.mark.asyncio
async def test_profile_updated_after_any_message():
    """Profil-Update läuft jetzt für alle Nachrichten, nicht nur MEMORY_INTENTS."""
    app_state.conversation_db = None
    app_state.memory_agent = None
    mock_profile = MagicMock()
    mock_profile.load.return_value = ""
    mock_profile.update = AsyncMock()
    app_state.profile_agent = mock_profile
    try:
        with patch("dispatch.run_agent", new=AsyncMock(return_value="Wetter-Antwort")):
            await dispatch._process_text("Wetter morgen?", 123)
    finally:
        app_state.profile_agent = None
    mock_profile.update.assert_called_once()


@pytest.mark.asyncio
async def test_answer_persisted_to_conversation_db():
    app_state.profile_agent = None
    app_state.memory_agent = None
    mock_conv_db = MagicMock()
    mock_conv_db.get_recent = AsyncMock(return_value=[])
    mock_conv_db.save = AsyncMock()
    app_state.conversation_db = mock_conv_db
    try:
        with patch("dispatch.run_agent", new=AsyncMock(return_value="Agent-Antwort")):
            await dispatch._process_text("Frage", 123)
    finally:
        app_state.conversation_db = None
    assert mock_conv_db.save.await_count == 2
    saved_roles = [call.args[1] for call in mock_conv_db.save.await_args_list]
    assert saved_roles == ["user", "assistant"]


@pytest.mark.asyncio
async def test_no_router_in_dispatch():
    import dispatch as dispatch_mod

    assert not hasattr(dispatch_mod, "route_with_llm")
