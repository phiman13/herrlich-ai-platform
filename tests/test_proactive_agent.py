import asyncio
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch


def test_check_important_mails_sends_message_for_important_mail(tmp_path):
    import sys

    os.environ["TELEGRAM_BOT_TOKEN"] = "fake_token"
    sys.path.insert(0, "agents")
    from proactive_agent import check_important_mails, init_proactive
    from db import ProactiveDB, MemoryDB

    proactive_db = ProactiveDB(str(tmp_path / "proactive.db"))
    memory_db = MemoryDB(str(tmp_path / "memories.db"))
    asyncio.run(proactive_db.init())
    asyncio.run(memory_db.init())
    init_proactive(proactive_db, memory_db)

    mock_mail = MagicMock()
    mock_mail.id = "mail_abc"
    mock_mail.sender_name = "Chef"
    mock_mail.sender_email = "chef@firma.de"
    mock_mail.subject = "Dringende Deadline morgen"
    mock_mail.preview = "Bitte bis morgen 12 Uhr abliefern."

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()

    with (
        patch("proactive_agent.MailAgent") as MockMailAgent,
        patch("proactive_agent.Bot", return_value=mock_bot),
        patch(
            "proactive_agent._assess_mail_importance",
            new_callable=AsyncMock,
            return_value=[(mock_mail, "Deadline morgen 12 Uhr")],
        ),
    ):
        MockMailAgent.return_value.get_inbox_unread.return_value = [mock_mail]
        asyncio.run(check_important_mails(123))

    mock_bot.send_message.assert_called_once()
    call_kwargs = mock_bot.send_message.call_args.kwargs
    assert call_kwargs["chat_id"] == 123
    assert "Chef" in call_kwargs["text"]


def test_check_important_mails_no_ping_if_already_reported(tmp_path):
    import sys

    os.environ["TELEGRAM_BOT_TOKEN"] = "fake_token"
    sys.path.insert(0, "agents")
    from proactive_agent import check_important_mails, init_proactive
    from db import ProactiveDB, MemoryDB

    proactive_db = ProactiveDB(str(tmp_path / "proactive.db"))
    memory_db = MemoryDB(str(tmp_path / "memories.db"))
    asyncio.run(proactive_db.init())
    asyncio.run(memory_db.init())
    asyncio.run(proactive_db.mark_mails_reported(["mail_already"]))
    init_proactive(proactive_db, memory_db)

    mock_mail = MagicMock()
    mock_mail.id = "mail_already"
    mock_mail.sender_name = "Jemand"
    mock_mail.sender_email = "x@y.de"
    mock_mail.subject = "Test"
    mock_mail.preview = "Test"

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()

    with (
        patch("proactive_agent.MailAgent") as MockMailAgent,
        patch("proactive_agent.Bot", return_value=mock_bot),
    ):
        MockMailAgent.return_value.get_inbox_unread.return_value = [mock_mail]
        asyncio.run(check_important_mails(123))

    mock_bot.send_message.assert_not_called()


def test_send_task_reminder_pings_overdue_task(tmp_path):
    import sys

    os.environ["TELEGRAM_BOT_TOKEN"] = "fake_token"
    sys.path.insert(0, "agents")
    from proactive_agent import send_task_reminder, init_proactive
    from db import ProactiveDB, MemoryDB

    proactive_db = ProactiveDB(str(tmp_path / "proactive.db"))
    memory_db = MemoryDB(str(tmp_path / "memories.db"))
    asyncio.run(proactive_db.init())
    asyncio.run(memory_db.init())
    init_proactive(proactive_db, memory_db)

    overdue_reminder = {
        "uid": "apple_test_uid",
        "title": "Zahnarzt anrufen",
        "created": datetime.now(timezone.utc) - timedelta(days=3),
        "due": None,
    }

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()

    with (
        patch("proactive_agent.CalendarAgent") as MockCal,
        patch("proactive_agent.get_tasks_raw", return_value=[]),
        patch("proactive_agent.Bot", return_value=mock_bot),
    ):
        MockCal.return_value.get_all_reminders.return_value = [overdue_reminder]
        asyncio.run(send_task_reminder(123))

    mock_bot.send_message.assert_called_once()
    call_text = mock_bot.send_message.call_args.kwargs["text"]
    assert "Zahnarzt anrufen" in call_text
