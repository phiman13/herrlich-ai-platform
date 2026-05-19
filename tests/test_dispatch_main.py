# tests/test_dispatch_main.py
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import dispatch as main
import app_state


@pytest.fixture(autouse=True)
def clear_processed_updates():
    app_state.processed_updates.clear()
    yield
    app_state.processed_updates.clear()


def _make_update(text, chat_id=123, update_id=90001):
    update = MagicMock()
    update.update_id = update_id
    update.message.text = text
    update.message.chat_id = chat_id
    update.message.reply_text = AsyncMock()
    return update


def test_any_message_dispatches_to_run_agent():
    """Ohne Router läuft jede Nachricht direkt durch run_agent."""
    app_state.conversation_db = None
    app_state.profile_agent = None
    app_state.memory_agent = None
    with patch(
        "dispatch.run_agent", new_callable=AsyncMock, return_value="Antwort"
    ) as mock_agent:
        asyncio.run(main.handle_message(_make_update("Hallo"), None))
    mock_agent.assert_awaited_once()


def test_no_router_import():
    """Router-Import ist weg."""
    import dispatch as dispatch_mod

    assert not hasattr(dispatch_mod, "route_with_llm")


def test_no_direct_handler_imports():
    """handle_briefing und handle_memory sind nicht mehr in dispatch."""
    import dispatch as dispatch_mod

    assert not hasattr(dispatch_mod, "handle_briefing")
    assert not hasattr(dispatch_mod, "handle_memory")
