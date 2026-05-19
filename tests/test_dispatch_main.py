# tests/test_dispatch_main.py
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import dispatch as main
import app_state


@pytest.fixture(autouse=True)
def clear_processed_updates():
    """Prevent dedup logic from skipping tests that share the same update_id."""
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


def _route(intent, params=None):
    return {"intent": intent, "confidence": 9, "params": params or {}, "reasoning": "t"}


def test_mail_intent_dispatches_to_run_agent():
    """mail-Intent läuft jetzt durch run_agent (nicht mehr handle_mail_intent)."""
    import dispatch as dispatch_mod

    assert not hasattr(dispatch_mod, "handle_mail_intent")
    assert not hasattr(dispatch_mod, "handle_calendar_intent")
    with (
        patch(
            "dispatch.route_with_llm",
            new_callable=AsyncMock,
            return_value=_route("mail", {"mode": "quick_scan"}),
        ),
        patch(
            "dispatch.run_agent", new_callable=AsyncMock, return_value="Mail-Antwort"
        ) as mock_agent,
    ):
        asyncio.run(
            main.handle_message(_make_update("Was Wichtiges im Posteingang?"), None)
        )
    mock_agent.assert_awaited_once()


def test_briefing_intent_calls_build_briefing():
    with (
        patch(
            "dispatch.route_with_llm",
            new_callable=AsyncMock,
            return_value=_route("briefing"),
        ),
        patch(
            "intent_handlers.build_briefing",
            new_callable=AsyncMock,
            return_value="briefing",
        ) as mock_b,
    ):
        asyncio.run(main.handle_message(_make_update("Mein Briefing bitte"), None))
    mock_b.assert_awaited_once()


def test_coding_query_intent_calls_handle_coding_query():
    with (
        patch(
            "dispatch.route_with_llm",
            new_callable=AsyncMock,
            return_value=_route(
                "coding",
                {"mode": "query", "project": "recipe-app", "query_type": "backlog"},
            ),
        ),
        patch(
            "intent_handlers.handle_coding_query",
            new_callable=AsyncMock,
            return_value="backlog",
        ) as mock_q,
    ):
        asyncio.run(main.handle_message(_make_update("Backlog von recipe-app?"), None))
    mock_q.assert_awaited_once()


def test_low_confidence_asks_for_clarification():
    routing = {"intent": "mail", "confidence": 2, "params": {}, "reasoning": "t"}
    update = _make_update("hm")
    with patch("dispatch.route_with_llm", new_callable=AsyncMock, return_value=routing):
        asyncio.run(main.handle_message(update, None))
    assert "nicht ganz sicher" in update.message.reply_text.call_args[0][0]
