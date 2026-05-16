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


# --- Mail callback branches (characterization) ---


def test_mail_cancel_discards_draft():
    main._pending_mail_ops[123] = {"type": "compose", "staged_at": time.time()}
    update = _make_cbq("mail:cancel")
    asyncio.run(main.handle_callback(update, None))
    assert 123 not in main._pending_mail_ops
    assert "verworfen" in _edited(update)


def test_mail_send_no_draft_warns():
    update = _make_cbq("mail:send")
    asyncio.run(main.handle_callback(update, None))
    assert "Kein Entwurf" in _edited(update)


def test_mail_action_confirm_no_op_warns():
    update = _make_cbq("mail:action:confirm")
    asyncio.run(main.handle_callback(update, None))
    assert "Keine ausstehende Aktion" in _edited(update)


@pytest.mark.parametrize(
    "op_type,method,extra,expected_args,expect",
    [
        ("delete", "delete", {}, ("m1",), "gelöscht"),
        ("reply", "reply", {"reply_text": "ok"}, ("m1", "ok"), "Antwort gesendet"),
        (
            "forward",
            "forward",
            {"forward_to": "x@y.de"},
            ("m1", ["x@y.de"], ""),
            "weitergeleitet",
        ),
    ],
)
def test_mail_action_confirm_executes(op_type, method, extra, expected_args, expect):
    main._pending_mail_ops[123] = {
        "type": op_type,
        "mail_id": "m1",
        "subject": "S",
        "sender": "X",
        "staged_at": time.time(),
        **extra,
    }
    update = _make_cbq("mail:action:confirm")
    with patch("mail_agent.MailAgent") as MockAgent:
        getattr(MockAgent.return_value, method).return_value = True
        asyncio.run(main.handle_callback(update, None))
    getattr(MockAgent.return_value, method).assert_called_once_with(*expected_args)
    assert expect in _edited(update)


def test_mail_action_confirm_move():
    main._pending_mail_ops[123] = {
        "type": "move",
        "mail_id": "m1",
        "subject": "S",
        "sender": "X",
        "destination_folder": "Steuern",
        "staged_at": time.time(),
    }
    update = _make_cbq("mail:action:confirm")
    with patch("mail_agent.MailAgent") as MockAgent:
        folder = MagicMock()
        folder.id = "f1"
        MockAgent.return_value.find_folder_by_name.return_value = folder
        MockAgent.return_value.move.return_value = True
        asyncio.run(main.handle_callback(update, None))
    MockAgent.return_value.move.assert_called_once_with("m1", "f1")
    assert "verschoben" in _edited(update)


def test_mail_action_cancel_clears_state():
    main._pending_mail_ops[123] = {"type": "archive", "staged_at": time.time()}
    main._last_mail_search[123] = {"mails": [], "timestamp": time.time()}
    update = _make_cbq("mail:action:cancel")
    asyncio.run(main.handle_callback(update, None))
    assert 123 not in main._pending_mail_ops
    assert 123 not in main._last_mail_search
    assert "Abgebrochen" in _edited(update)


def test_mail_select_expired_search_warns():
    main._last_mail_search[123] = {
        "mails": [MagicMock()],
        "mode": "archive",
        "params": {},
        "timestamp": time.time() - 300,
    }
    update = _make_cbq("mail:select:0")
    asyncio.run(main.handle_callback(update, None))
    assert "abgelaufen" in _edited(update).lower()


def test_mail_select_picks_mail_and_shows_confirm():
    mail = MagicMock()
    mail.id = "m1"
    mail.subject = "S"
    mail.sender_name = "X"
    mail.sender_email = "x@y.de"
    main._last_mail_search[123] = {
        "mails": [mail],
        "mode": "archive",
        "params": {},
        "timestamp": time.time(),
    }
    update = _make_cbq("mail:select:0")
    with patch(
        "agents.main._show_mail_action_confirm", new_callable=AsyncMock
    ) as mock_show:
        asyncio.run(main.handle_callback(update, None))
    mock_show.assert_awaited_once()
    assert mock_show.await_args[0][1] is mail
    assert 123 not in main._last_mail_search


def test_mail_action_roundtrip_archive():
    """Stage via _show_mail_action_confirm → confirm via handle_callback."""
    from zoneinfo import ZoneInfo

    mail = MagicMock()
    mail.id = "m99"
    mail.subject = "Rechnung"
    mail.sender_name = "Stadtwerke"
    mail.sender_email = "sw@x.de"
    mail.received = datetime(2026, 5, 1, 9, 0, tzinfo=ZoneInfo("Europe/Berlin"))
    with patch("agents.main.Bot") as MockBot:
        MockBot.return_value.send_message = AsyncMock()
        asyncio.run(main._show_mail_action_confirm(123, mail, "archive", {}))
    assert main._pending_mail_ops[123]["type"] == "archive"
    assert main._pending_mail_ops[123]["mail_id"] == "m99"
    assert "staged_at" in main._pending_mail_ops[123]

    update = _make_cbq("mail:action:confirm")
    with patch("mail_agent.MailAgent") as MockAgent:
        MockAgent.return_value.archive.return_value = True
        asyncio.run(main.handle_callback(update, None))
    MockAgent.return_value.archive.assert_called_once_with("m99")


# --- push / dismiss / calendar callback branches (characterization) ---


def test_push_triggers_git_push():
    update = _make_cbq("push:immo-radar")
    with patch("vps.git_push", new_callable=AsyncMock, return_value=True) as mock_push:
        asyncio.run(main.handle_callback(update, None))
    mock_push.assert_awaited_once_with("immo-radar")
    update.callback_query.message.reply_text.assert_awaited()


def test_dismiss_removes_keyboard():
    update = _make_cbq("dismiss")
    asyncio.run(main.handle_callback(update, None))
    update.callback_query.edit_message_reply_markup.assert_awaited_once()


def test_cal_action_confirm_create_executes():
    main._pending_calendar_ops[123] = {
        "type": "create",
        "title": "Zahnarzt",
        "start": datetime(2026, 6, 1, 10, 0),
        "end": datetime(2026, 6, 1, 11, 0),
        "staged_at": time.time(),
    }
    update = _make_cbq("cal:action:confirm")
    with patch("agents.main.calendar_agent") as mock_cal:
        asyncio.run(main.handle_callback(update, None))
    mock_cal.create_event.assert_called_once()
    assert "erstellt" in _edited(update)


def test_cal_action_confirm_update_executes():
    main._pending_calendar_ops[123] = {
        "type": "update",
        "event_id": "e1",
        "title": "Zahnarzt",
        "new_start": datetime(2026, 6, 1, 15, 0),
        "new_end": datetime(2026, 6, 1, 16, 0),
        "new_title": None,
        "new_location": None,
        "staged_at": time.time(),
    }
    update = _make_cbq("cal:action:confirm")
    with patch("agents.main.calendar_agent") as mock_cal:
        asyncio.run(main.handle_callback(update, None))
    mock_cal.update_event.assert_called_once()
    assert "geändert" in _edited(update)


def test_cal_action_confirm_no_op_warns():
    update = _make_cbq("cal:action:confirm")
    asyncio.run(main.handle_callback(update, None))
    assert "Keine ausstehende Aktion" in _edited(update)


def test_cal_action_cancel_clears_state():
    main._pending_calendar_ops[123] = {"type": "create", "staged_at": time.time()}
    main._last_calendar_search[123] = {"events": [], "timestamp": time.time()}
    update = _make_cbq("cal:action:cancel")
    asyncio.run(main.handle_callback(update, None))
    assert 123 not in main._pending_calendar_ops
    assert 123 not in main._last_calendar_search
    assert "Abgebrochen" in _edited(update)


def test_cal_select_expired_search_warns():
    main._last_calendar_search[123] = {
        "events": [MagicMock()],
        "mode": "delete",
        "params": {},
        "timestamp": time.time() - 300,  # > 180s TTL
    }
    update = _make_cbq("cal:select:0")
    asyncio.run(main.handle_callback(update, None))
    assert "abgelaufen" in _edited(update).lower()


def test_cal_select_picks_event_and_shows_confirm():
    event = MagicMock()
    main._last_calendar_search[123] = {
        "events": [event],
        "mode": "delete",
        "params": {},
        "timestamp": time.time(),
    }
    update = _make_cbq("cal:select:0")
    with patch(
        "agents.main._show_calendar_action_confirm", new_callable=AsyncMock
    ) as mock_show:
        asyncio.run(main.handle_callback(update, None))
    mock_show.assert_awaited_once()
    assert mock_show.await_args[0][1] is event
    assert 123 not in main._last_calendar_search


def test_calendar_create_roundtrip():
    """Stage via handle_calendar write → confirm via handle_callback."""
    start = datetime(2026, 6, 1, 10, 0)
    with patch("agents.main.Bot") as MockBot:
        MockBot.return_value.send_message = AsyncMock()
        asyncio.run(
            main.handle_calendar(123, "x", mode="write", title="Zahnarzt", start=start)
        )
    assert main._pending_calendar_ops[123]["type"] == "create"
    assert "staged_at" in main._pending_calendar_ops[123]

    update = _make_cbq("cal:action:confirm")
    with patch("agents.main.calendar_agent") as mock_cal:
        asyncio.run(main.handle_callback(update, None))
    mock_cal.create_event.assert_called_once()
