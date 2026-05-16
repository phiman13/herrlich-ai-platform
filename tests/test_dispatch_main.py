# tests/test_dispatch_main.py
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import agents.main as main
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


def test_mail_intent_dispatches_to_handle_mail():
    with (
        patch(
            "agents.main.route_with_llm",
            new_callable=AsyncMock,
            return_value=_route("mail", {"mode": "quick_scan"}),
        ),
        patch("agents.main.handle_mail_intent", new_callable=AsyncMock) as mock_mail,
    ):
        asyncio.run(
            main.handle_message(_make_update("Was Wichtiges im Posteingang?"), None)
        )
    mock_mail.assert_awaited_once()


def test_research_intent_calls_ask_claude_with_web_search():
    with (
        patch(
            "agents.main.route_with_llm",
            new_callable=AsyncMock,
            return_value=_route("research"),
        ),
        patch(
            "chat_handler.ask_claude", new_callable=AsyncMock, return_value="ok"
        ) as mock_ask,
        patch("agents.main.send_typing", new_callable=AsyncMock),
    ):
        asyncio.run(main.handle_message(_make_update("Recherchiere ESG 2026"), None))
    assert mock_ask.await_args.kwargs.get("use_web_search") is True


def test_work_intent_uses_sonnet():
    with (
        patch(
            "agents.main.route_with_llm",
            new_callable=AsyncMock,
            return_value=_route("work"),
        ),
        patch(
            "chat_handler.ask_claude", new_callable=AsyncMock, return_value="ok"
        ) as mock_ask,
        patch("agents.main.send_typing", new_callable=AsyncMock),
    ):
        asyncio.run(main.handle_message(_make_update("Fass das zusammen"), None))
    assert mock_ask.await_args.kwargs.get("model") == "claude-sonnet-4-6"


def test_news_intent_calls_get_ai_news():
    with (
        patch(
            "agents.main.route_with_llm",
            new_callable=AsyncMock,
            return_value=_route("news"),
        ),
        patch("agents.main.get_ai_news", return_value="news text") as mock_news,
    ):
        asyncio.run(main.handle_message(_make_update("Was gibt es Neues in AI?"), None))
    mock_news.assert_called_once()


def test_weather_intent_calls_get_weather():
    with (
        patch(
            "agents.main.route_with_llm",
            new_callable=AsyncMock,
            return_value=_route("weather", {"period": "today"}),
        ),
        patch("agents.main.get_weather", return_value="sonnig") as mock_weather,
    ):
        asyncio.run(main.handle_message(_make_update("Wie wird das Wetter?"), None))
    mock_weather.assert_called_once()


def test_briefing_intent_calls_build_briefing():
    with (
        patch(
            "agents.main.route_with_llm",
            new_callable=AsyncMock,
            return_value=_route("briefing"),
        ),
        patch(
            "agents.main.build_briefing",
            new_callable=AsyncMock,
            return_value="briefing",
        ) as mock_b,
    ):
        asyncio.run(main.handle_message(_make_update("Mein Briefing bitte"), None))
    mock_b.assert_awaited_once()


def test_tasks_read_intent_calls_get_tasks():
    with (
        patch(
            "agents.main.route_with_llm",
            new_callable=AsyncMock,
            return_value=_route("tasks", {"mode": "read"}),
        ),
        patch("agents.main.get_tasks", return_value="• task") as mock_tasks,
    ):
        asyncio.run(main.handle_message(_make_update("Zeig meine Tasks"), None))
    mock_tasks.assert_called_once()


def test_reminder_write_intent_calls_add_task():
    with (
        patch(
            "agents.main.route_with_llm",
            new_callable=AsyncMock,
            return_value=_route("reminder_write", {"title": "Anruf", "due_date": None}),
        ),
        patch("agents.main.add_task", return_value=True) as mock_add,
    ):
        asyncio.run(
            main.handle_message(_make_update("Erinnere mich an den Anruf"), None)
        )
    mock_add.assert_called_once()


def test_coding_query_intent_calls_handle_coding_query():
    with (
        patch(
            "agents.main.route_with_llm",
            new_callable=AsyncMock,
            return_value=_route(
                "coding",
                {"mode": "query", "project": "recipe-app", "query_type": "backlog"},
            ),
        ),
        patch(
            "agents.main.handle_coding_query",
            new_callable=AsyncMock,
            return_value="backlog",
        ) as mock_q,
    ):
        asyncio.run(main.handle_message(_make_update("Backlog von recipe-app?"), None))
    mock_q.assert_awaited_once()


def test_low_confidence_asks_for_clarification():
    routing = {"intent": "mail", "confidence": 2, "params": {}, "reasoning": "t"}
    update = _make_update("hm")
    with patch(
        "agents.main.route_with_llm", new_callable=AsyncMock, return_value=routing
    ):
        asyncio.run(main.handle_message(update, None))
    assert "nicht ganz sicher" in update.message.reply_text.call_args[0][0]
