import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import agents.main as main_module


def test_send_typing_calls_send_chat_action():
    mock_bot = MagicMock()
    mock_bot.send_chat_action = AsyncMock()

    with patch("agents.main.Bot", return_value=mock_bot):
        asyncio.run(main_module.send_typing(chat_id=123))

    mock_bot.send_chat_action.assert_called_once()
    call_kwargs = mock_bot.send_chat_action.call_args.kwargs
    assert call_kwargs["chat_id"] == 123


def test_keep_typing_stops_on_event():
    mock_bot = MagicMock()
    mock_bot.send_chat_action = AsyncMock()

    async def run():
        stop = asyncio.Event()
        with patch("agents.main.Bot", return_value=mock_bot):
            task = asyncio.create_task(main_module._keep_typing(123, stop))
            await asyncio.sleep(0.05)
            stop.set()
            await task
        return mock_bot.send_chat_action.call_count

    count = asyncio.run(run())
    assert count >= 1


def test_personal_intent_uses_sonnet():
    with patch("agents.main.route_with_llm", return_value={
        "intent": "personal", "confidence": 9, "params": {}, "reasoning": "test"
    }):
        with patch("agents.main.ask_claude", new_callable=AsyncMock, return_value="ok") as mock_ask:
            with patch("agents.main.send_typing", new_callable=AsyncMock):
                update = MagicMock()
                update.update_id = 77771
                update.message.text = "Hallo"
                update.message.chat_id = 123
                update.message.reply_text = AsyncMock()
                asyncio.run(main_module.handle_message(update, None))

    call_kwargs = mock_ask.call_args.kwargs
    assert call_kwargs.get("model") == "claude-sonnet-4-6"
