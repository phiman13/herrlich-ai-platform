# tests/test_callback_main.py
import asyncio
import time
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import agents.main as main


def _make_cbq(data, chat_id=123):
    """Build a mock Telegram callback-query Update for handle_callback."""
    query = MagicMock()
    query.data = data
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.edit_message_reply_markup = AsyncMock()
    query.message = MagicMock()
    query.message.chat_id = chat_id
    query.message.reply_text = AsyncMock()
    update = MagicMock()
    update.callback_query = query
    return update


def _edited(update):
    """Return the text passed to edit_message_text."""
    return update.callback_query.edit_message_text.call_args[0][0]


@pytest.fixture(autouse=True)
def _clear_state():
    _dicts = (
        main._pending_mail_ops,
        main._pending_calendar_ops,
        main._last_mail_search,
        main._last_calendar_search,
    )
    for d in _dicts:
        d.clear()
    yield
    for d in _dicts:
        d.clear()


# --- TTL: expired pending ops must NOT execute ---


def test_mail_send_expired_op_is_rejected():
    main._pending_mail_ops[123] = {
        "type": "compose",
        "to_email": "a@b.de",
        "subject": "S",
        "body": "B",
        "staged_at": time.time() - 700,
    }
    update = _make_cbq("mail:send")
    with patch("mail_agent.MailAgent") as MockAgent:
        asyncio.run(main.handle_callback(update, None))
    MockAgent.assert_not_called()
    assert "Abgelaufen" in _edited(update)


def test_mail_action_confirm_expired_op_is_rejected():
    main._pending_mail_ops[123] = {
        "type": "archive",
        "mail_id": "m1",
        "subject": "S",
        "sender": "X",
        "staged_at": time.time() - 700,
    }
    update = _make_cbq("mail:action:confirm")
    with patch("mail_agent.MailAgent") as MockAgent:
        asyncio.run(main.handle_callback(update, None))
    MockAgent.assert_not_called()
    assert "Abgelaufen" in _edited(update)


def test_cal_action_confirm_expired_op_is_rejected():
    main._pending_calendar_ops[123] = {
        "type": "create",
        "title": "T",
        "start": datetime(2026, 6, 1, 10, 0),
        "end": datetime(2026, 6, 1, 11, 0),
        "staged_at": time.time() - 700,
    }
    update = _make_cbq("cal:action:confirm")
    with patch("agents.main.calendar_agent") as mock_cal:
        asyncio.run(main.handle_callback(update, None))
    mock_cal.create_event.assert_not_called()
    assert "Abgelaufen" in _edited(update)


# --- TTL: fresh pending ops DO execute ---


def test_mail_send_fresh_op_is_sent():
    main._pending_mail_ops[123] = {
        "type": "compose",
        "to_email": "a@b.de",
        "subject": "S",
        "body": "B",
        "staged_at": time.time(),
    }
    update = _make_cbq("mail:send")
    with patch("mail_agent.MailAgent") as MockAgent:
        MockAgent.return_value.send_mail.return_value = True
        asyncio.run(main.handle_callback(update, None))
    MockAgent.return_value.send_mail.assert_called_once()
    assert "gesendet" in _edited(update)


def test_mail_action_confirm_fresh_op_executes():
    main._pending_mail_ops[123] = {
        "type": "archive",
        "mail_id": "m1",
        "subject": "S",
        "sender": "X",
        "staged_at": time.time(),
    }
    update = _make_cbq("mail:action:confirm")
    with patch("mail_agent.MailAgent") as MockAgent:
        MockAgent.return_value.archive.return_value = True
        asyncio.run(main.handle_callback(update, None))
    MockAgent.return_value.archive.assert_called_once_with("m1")
    assert "archiviert" in _edited(update)


def test_cal_action_confirm_fresh_op_executes():
    main._pending_calendar_ops[123] = {
        "type": "delete",
        "event_id": "e1",
        "title": "Zahnarzt",
        "staged_at": time.time(),
    }
    update = _make_cbq("cal:action:confirm")
    with patch("agents.main.calendar_agent") as mock_cal:
        asyncio.run(main.handle_callback(update, None))
    mock_cal.delete_event.assert_called_once_with("e1")
    assert "abgesagt" in _edited(update)
