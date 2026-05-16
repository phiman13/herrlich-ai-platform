import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import dispatch as main_module
import chat_handler
import app_state


def test_send_typing_calls_send_chat_action():
    mock_bot = MagicMock()
    mock_bot.send_chat_action = AsyncMock()

    with patch("dispatch.Bot", return_value=mock_bot):
        asyncio.run(main_module.send_typing(chat_id=123))

    mock_bot.send_chat_action.assert_called_once()
    call_kwargs = mock_bot.send_chat_action.call_args.kwargs
    assert call_kwargs["chat_id"] == 123
    from telegram.constants import ChatAction

    assert call_kwargs["action"] == ChatAction.TYPING


def test_keep_typing_stops_on_event():
    mock_bot = MagicMock()
    mock_bot.send_chat_action = AsyncMock()

    async def run():
        stop = asyncio.Event()
        with patch("dispatch.Bot", return_value=mock_bot):
            task = asyncio.create_task(main_module._keep_typing(123, stop))
            await asyncio.sleep(0.05)
            stop.set()
            await task
        return mock_bot.send_chat_action.call_count

    count = asyncio.run(run())
    assert count >= 1


def test_personal_intent_uses_sonnet():
    with patch(
        "dispatch.route_with_llm",
        return_value={
            "intent": "personal",
            "confidence": 9,
            "params": {},
            "reasoning": "test",
        },
    ):
        with patch(
            "chat_handler.ask_claude", new_callable=AsyncMock, return_value="ok"
        ) as mock_ask:
            with patch("dispatch.send_typing", new_callable=AsyncMock):
                update = MagicMock()
                update.update_id = 77771
                update.message.text = "Hallo"
                update.message.chat_id = 123
                update.message.reply_text = AsyncMock()
                asyncio.run(main_module.handle_message(update, None))

    call_kwargs = mock_ask.call_args.kwargs
    assert call_kwargs.get("model") == "claude-sonnet-4-6"


def test_ask_claude_injects_history():
    history = [
        {"role": "user", "content": "Was ist Python?"},
        {"role": "assistant", "content": "Python ist eine Programmiersprache."},
    ]

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Antwort")]

    with (
        patch("chat_handler.claude") as mock_claude,
        patch("chat_handler.Bot") as mock_bot_cls,
    ):
        mock_bot_cls.return_value.send_message = AsyncMock()
        mock_claude.messages.create.return_value = mock_response
        asyncio.run(
            chat_handler.ask_claude(
                chat_id=123,
                system="system",
                user="Wie alt ist es?",
                history=history,
            )
        )

    call_kwargs = mock_claude.messages.create.call_args.kwargs
    messages = call_kwargs["messages"]
    assert messages[0] == {"role": "user", "content": "Was ist Python?"}
    assert messages[1] == {
        "role": "assistant",
        "content": "Python ist eine Programmiersprache.",
    }
    assert messages[2] == {"role": "user", "content": "Wie alt ist es?"}


def test_history_saved_after_personal_intent():
    mock_db = MagicMock()
    mock_db.get_recent = AsyncMock(return_value=[])
    mock_db.save = AsyncMock()
    app_state.conversation_db = mock_db

    with patch(
        "dispatch.route_with_llm",
        return_value={
            "intent": "personal",
            "confidence": 9,
            "params": {},
            "reasoning": "test",
        },
    ):
        with patch(
            "chat_handler.ask_claude",
            new_callable=AsyncMock,
            return_value="Antwort auf Hallo",
        ):
            with patch("dispatch.send_typing", new_callable=AsyncMock):
                update = MagicMock()
                update.update_id = 77772
                update.message.text = "Hallo"
                update.message.chat_id = 123
                update.message.reply_text = AsyncMock()
                asyncio.run(main_module.handle_message(update, None))

    save_calls = mock_db.save.call_args_list
    assert any(c.args == (123, "user", "Hallo") for c in save_calls)
    assert any(c.args == (123, "assistant", "Antwort auf Hallo") for c in save_calls)

    app_state.conversation_db = None


def test_history_not_saved_for_calendar_intent():
    mock_db = MagicMock()
    mock_db.get_recent = AsyncMock(return_value=[])
    mock_db.save = AsyncMock()
    app_state.conversation_db = mock_db

    with patch(
        "dispatch.route_with_llm",
        return_value={
            "intent": "calendar",
            "confidence": 9,
            "params": {
                "mode": "read",
                "kind": "today",
                "start": None,
                "end": None,
                "title": None,
                "calendar_name": None,
            },
            "reasoning": "test",
        },
    ):
        with patch("calendar_handler.handle_calendar", new_callable=AsyncMock):
            update = MagicMock()
            update.update_id = 77773
            update.message.text = "Was habe ich heute?"
            update.message.chat_id = 123
            update.message.reply_text = AsyncMock()
            asyncio.run(main_module.handle_message(update, None))

    mock_db.save.assert_not_called()
    mock_db.get_recent.assert_not_called()

    app_state.conversation_db = None


def test_profile_content_injected_for_personal_intent():
    mock_profile = MagicMock()
    mock_profile.load.return_value = "## Beruf & Rolle\nStrategischer Berater\n"
    mock_profile.update = AsyncMock()
    app_state.profile_agent = mock_profile

    with patch(
        "dispatch.route_with_llm",
        return_value={
            "intent": "personal",
            "confidence": 9,
            "params": {},
            "reasoning": "test",
        },
    ):
        with patch(
            "chat_handler.ask_claude", new_callable=AsyncMock, return_value="ok"
        ) as mock_ask:
            with patch("dispatch.send_typing", new_callable=AsyncMock):
                update = MagicMock()
                update.update_id = 88881
                update.message.text = "Was soll ich tun?"
                update.message.chat_id = 456
                update.message.reply_text = AsyncMock()
                asyncio.run(main_module.handle_message(update, None))

    app_state.profile_agent = None
    system_arg = mock_ask.call_args.kwargs.get("system", "")
    assert "Strategischer Berater" in system_arg
