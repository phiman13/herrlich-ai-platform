import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone

import anthropic
from telegram import Bot

try:
    from calendar_agent import CalendarAgent, BERLIN
    from db import ProactiveDB, MemoryDB
    from mail_agent import MailAgent
    from tasks_agent import get_tasks_raw, get_completed_tasks_this_week
except ImportError:
    from agents.calendar_agent import CalendarAgent, BERLIN
    from agents.db import ProactiveDB, MemoryDB
    from agents.mail_agent import MailAgent
    from agents.tasks_agent import get_tasks_raw, get_completed_tasks_this_week

logger = logging.getLogger("jarvis.proactive")

_proactive_db: ProactiveDB | None = None
_memory_db: MemoryDB | None = None

_MAIL_IMPORTANCE_SYSTEM = (
    "Du analysierst E-Mails für Philipp und entscheidest ob sie wichtig sind.\n"
    "Wichtig bedeutet: konkrete Deadlines, direkte Anfragen/Fragen an Philipp, "
    "finanzielle Themen (Rechnungen, Zahlungen, Angebote), zeitkritische Informationen.\n"
    "NICHT wichtig: Newsletter, Werbung, automatische Benachrichtigungen, FYI-Mails.\n"
    'Antworte NUR mit JSON: [{"id": "...", "reason": "..."}] für wichtige Mails. '
    "Leeres Array [] wenn keine wichtig. KEIN erklärender Text."
)

_WEEKLY_REVIEW_SYSTEM = (
    "Du bist Jarvis, KI-Assistent für Philipp. Erstelle einen wöchentlichen Review auf Deutsch. "
    "Schreibe einen narrativen, kurzen Text (kein reines Bullet-Listing). "
    "Rückblick: Was war bedeutsam diese Woche? Vorausschau: Worauf sollte Philipp sich vorbereiten? "
    "Halte es kompakt — max. 300 Wörter."
)

_WEEKDAYS_DE = [
    "Montag",
    "Dienstag",
    "Mittwoch",
    "Donnerstag",
    "Freitag",
    "Samstag",
    "Sonntag",
]


async def init_proactive(proactive_db: ProactiveDB, memory_db: MemoryDB) -> None:
    global _proactive_db, _memory_db
    _proactive_db = proactive_db
    _memory_db = memory_db
    logger.info("ProactiveAgent initialisiert")


async def _assess_mail_importance(mails: list) -> list:
    """Call Haiku to assess mail importance. Returns list of (Mail, reason) tuples."""
    mail_list = [
        {
            "id": m.id,
            "from": f"{m.sender_name} <{m.sender_email}>",
            "subject": m.subject,
            "preview": m.preview,
        }
        for m in mails
    ]
    prompt = f"Mails:\n{json.dumps(mail_list, ensure_ascii=False)}"
    try:
        client = anthropic.Anthropic()
        resp = await asyncio.to_thread(
            client.messages.create,
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            temperature=0,
            system=_MAIL_IMPORTANCE_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        important_map = {
            item["id"]: item["reason"]
            for item in json.loads(resp.content[0].text.strip())
        }
    except Exception as e:
        logger.warning("Haiku importance check failed: %s", e)
        return []

    mail_by_id = {m.id: m for m in mails}
    return [
        (mail_by_id[mid], reason)
        for mid, reason in important_map.items()
        if mid in mail_by_id
    ]


async def check_important_mails(chat_id: int) -> None:
    """Fetch unread inbox mails, filter reported, assess via Haiku, send digest if important."""
    try:
        mails = await asyncio.to_thread(MailAgent().get_inbox_unread, 30)
    except Exception as e:
        logger.warning("Mail fetch failed: %s", e)
        return

    if not mails:
        return

    reported = await _proactive_db.get_reported_mail_ids()
    new_mails = [m for m in mails if m.id not in reported]

    if not new_mails:
        return

    important = await _assess_mail_importance(new_mails)

    await _proactive_db.mark_mails_reported([m.id for m in new_mails])

    if not important:
        return

    lines = ["📬 *Wichtige neue Mails:*\n"]
    for mail, reason in important:
        sender = mail.sender_name or mail.sender_email
        subject = mail.subject.replace("*", "").replace("_", "")[:80]
        lines.append(f"*{sender}*")
        lines.append(f"_{subject}_")
        lines.append(f"→ {reason}\n")

    bot = Bot(token=os.environ["TELEGRAM_BOT_TOKEN"])
    await bot.send_message(
        chat_id=chat_id, text="\n".join(lines), parse_mode="Markdown"
    )


async def send_task_reminder(chat_id: int) -> None:
    """Check for tasks open > 2 days and not reminded in last 2 days. Send reminder if found."""
    now = datetime.now(timezone.utc)
    two_days_ago = now - timedelta(days=2)
    overdue = []

    try:
        reminders = await asyncio.to_thread(CalendarAgent().get_all_reminders)
        for r in reminders:
            created = r.get("created")
            if created is None:
                continue
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if created > two_days_ago:
                continue
            last = await _proactive_db.get_last_reminded(r["uid"])
            if last and (now - last) < timedelta(days=2):
                continue
            overdue.append(r)
    except Exception as e:
        logger.warning("Apple Reminders fetch failed: %s", e)

    try:
        todos = await asyncio.to_thread(get_tasks_raw)
        for t in todos:
            created_str = t.get("created_at")
            if not created_str:
                continue
            created = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
            if created > two_days_ago:
                continue
            last = await _proactive_db.get_last_reminded(t["id"])
            if last and (now - last) < timedelta(days=2):
                continue
            overdue.append({"uid": t["id"], "title": t["title"]})
    except Exception as e:
        logger.warning("MS To Do fetch failed: %s", e)

    if not overdue:
        return

    await _proactive_db.mark_tasks_reminded([t["uid"] for t in overdue])

    lines = [f"⏰ *{len(overdue)} überfällige Tasks:*\n"]
    for t in overdue:
        icon = "📝" if t["uid"].startswith("apple_") else "✅"
        lines.append(f"{icon} {t['title']}")

    bot = Bot(token=os.environ["TELEGRAM_BOT_TOKEN"])
    await bot.send_message(
        chat_id=chat_id, text="\n".join(lines), parse_mode="Markdown"
    )


async def send_weekly_review(chat_id: int) -> None:
    """Build and send narrative weekly review: Rückblick (this week) + Vorausschau (next week)."""
    now = datetime.now(BERLIN)
    monday = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    friday = monday + timedelta(days=4, hours=23, minutes=59, seconds=59)
    next_monday = monday + timedelta(weeks=1)
    next_sunday = next_monday + timedelta(days=6, hours=23, minutes=59, seconds=59)

    cal = CalendarAgent()

    def fmt_event(ev):
        day = _WEEKDAYS_DE[ev.start.weekday()]
        time_str = "ganztägig" if ev.all_day else ev.start.strftime("%H:%M")
        return f"{day} {time_str}: {ev.title}"

    try:
        this_week_events = await asyncio.to_thread(cal.get_events, monday, friday)
    except Exception as e:
        logger.warning("this_week_events failed: %s", e)
        this_week_events = []

    try:
        completed_reminders = await asyncio.to_thread(
            cal.get_completed_reminders_this_week
        )
    except Exception as e:
        logger.warning("completed_reminders failed: %s", e)
        completed_reminders = []

    try:
        completed_todos = await asyncio.to_thread(get_completed_tasks_this_week)
    except Exception as e:
        logger.warning("completed_todos failed: %s", e)
        completed_todos = []

    memories = await _memory_db.load_since(7)

    try:
        next_week_events = await asyncio.to_thread(
            cal.get_events, next_monday, next_sunday
        )
    except Exception as e:
        logger.warning("next_week_events failed: %s", e)
        next_week_events = []

    try:
        open_reminders = await asyncio.to_thread(cal.get_all_reminders)
    except Exception as e:
        logger.warning("open_reminders failed: %s", e)
        open_reminders = []

    try:
        open_todos = await asyncio.to_thread(get_tasks_raw)
    except Exception as e:
        logger.warning("open_todos failed: %s", e)
        open_todos = []

    rueckblick = (
        f"DIESE WOCHE (Rückblick):\n"
        f"Termine: {chr(10).join(fmt_event(e) for e in this_week_events) or 'keine'}\n"
        f"Erledigte Apple Reminders: {', '.join(completed_reminders) or 'keine'}\n"
        f"Erledigte MS To Do: {', '.join(completed_todos) or 'keine'}\n"
        f"Neue Erkenntnisse (Memory): {', '.join(m['content'] for m in memories) or 'keine'}"
    )
    vorausschau = (
        f"NÄCHSTE WOCHE (Vorausschau):\n"
        f"Termine: {chr(10).join(fmt_event(e) for e in next_week_events) or 'keine'}\n"
        f"Offene Reminders: {', '.join(r['title'] for r in open_reminders) or 'keine'}\n"
        f"Offene MS To Do: {', '.join(t['title'] for t in open_todos) or 'keine'}"
    )

    try:
        client = anthropic.Anthropic()
        resp = await asyncio.to_thread(
            client.messages.create,
            model="claude-sonnet-4-6",
            max_tokens=1000,
            temperature=0,
            system=_WEEKLY_REVIEW_SYSTEM,
            messages=[{"role": "user", "content": f"{rueckblick}\n\n{vorausschau}"}],
        )
        summary = resp.content[0].text.strip()
    except Exception as e:
        logger.warning("Weekly review Sonnet call failed: %s", e)
        return

    bot = Bot(token=os.environ["TELEGRAM_BOT_TOKEN"])
    await bot.send_message(
        chat_id=chat_id,
        text=f"📊 *Wöchentlicher Review*\n\n{summary}",
        parse_mode="Markdown",
    )
