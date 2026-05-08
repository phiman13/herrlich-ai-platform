import os
import re
import sys
import logging
import asyncio
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import RedirectResponse, PlainTextResponse
from telegram import Update, Bot
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
import anthropic

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from calendar_agent import CalendarAgent, BERLIN
from router import route_with_llm
import router
from coding_agent import handle_coding_query, run_coding_action, add_backlog_item
from vps import list_projects
from briefing_agent import build_briefing
from news_agent import get_ai_news
from tasks_agent import (
    get_tasks,
    add_task,
    complete_task,
    create_list,
    delete_list,
    rename_list,
)
from voice_agent import transcribe
from weather_agent import get_weather

_scheduler = AsyncIOScheduler(timezone="Europe/Berlin")

calendar_agent = CalendarAgent()

_WEEKDAYS_DE = [
    "Montag",
    "Dienstag",
    "Mittwoch",
    "Donnerstag",
    "Freitag",
    "Samstag",
    "Sonntag",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("jarvis")

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
claude = anthropic.Anthropic()

app = FastAPI()
bot_app = Application.builder().token(TELEGRAM_TOKEN).build()

processed_updates = set()


async def send_typing(chat_id: int):
    bot = Bot(token=TELEGRAM_TOKEN)
    await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)


async def _keep_typing(chat_id: int, stop_event: asyncio.Event):
    while not stop_event.is_set():
        await send_typing(chat_id)
        await asyncio.sleep(4)


_pending_mail_ops: dict[int, dict] = {}
_last_mail_search: dict[int, dict] = {}
_memory_agent = None  # initialized in startup()
_MEMORY_INTENTS = {"personal", "work", "research"}
_conversation_db = None  # initialized in startup()
_HISTORY_INTENTS = {"personal", "work", "research"}
_profile_agent = None  # initialized in startup()


def detect_calendar_window(text):
    """Return (kind, start, end) or None. kind is 'today'/'tomorrow'/'week'/'next'.

    Order matters:
      1. "nächster termin"  -> next
      2. "diese woche"      -> week (from now until Sunday 23:59:59)
      3. "heute"            -> today (word boundary, wins over "morgen")
      4. "morgen"           -> tomorrow (word boundary, avoids "Guten Morgen")
    """
    t = text.lower()
    now = datetime.now(BERLIN)

    if (
        "nächster termin" in t
        or "naechster termin" in t
        or "wann ist mein nächster" in t
        or "wann ist mein naechster" in t
    ):
        return ("next", None, None)
    if "diese woche" in t or "woche kalender" in t or "termine woche" in t:
        start = now
        days_until_sunday = 6 - now.weekday()  # 0=Mo, 6=So
        sunday = (now + timedelta(days=days_until_sunday)).replace(
            hour=23, minute=59, second=59, microsecond=999999
        )
        return ("week", start, sunday)
    if re.search(r"\bheute\b", t) and (
        "was habe ich" in t or "termine" in t or "kalender" in t
    ):
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        return ("today", start, end)
    if re.search(r"\bmorgen\b", t) and (
        "was habe ich" in t or "termine" in t or "kalender" in t
    ):
        start = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        end = start + timedelta(days=1)
        return ("tomorrow", start, end)
    return None


def _fmt_time(dt):
    return dt.strftime("%H:%M")


def _fmt_date(dt):
    return f"{_WEEKDAYS_DE[dt.weekday()]} {dt.strftime('%d.%m.')}"


def _fmt_time_or_allday(ev):
    if getattr(ev, "all_day", False):
        return "ganztägig"
    return ev.start.strftime("%H:%M")


def format_calendar_response(kind, events, query_start=None):
    if kind == "next":
        ev = events  # single event or None
        if ev is None:
            return "Kein kommender Termin gefunden."
        time_part = (
            "ganztägig"
            if getattr(ev, "all_day", False)
            else f"um {ev.start.strftime('%H:%M')}"
        )
        line = f"Nächster Termin: {_fmt_date(ev.start)} {time_part} — {ev.title}"
        if ev.location:
            line += f" ({ev.location})"
        return line

    if not events:
        label = {"today": "heute", "tomorrow": "morgen", "week": "diese Woche"}.get(
            kind, ""
        )
        return f"Keine Termine {label}.".strip()

    if kind in ("today", "tomorrow"):
        lines = [f"{_fmt_time_or_allday(ev)} — {ev.title}" for ev in events]
        return "\n".join(lines)

    # week: group by effective start day (clamped to query_start for
    # multi-day events that began before the window)
    lines = []
    current_day = None
    for ev in events:
        effective_start = max(ev.start, query_start) if query_start else ev.start
        day_key = effective_start.date()
        if day_key != current_day:
            if lines:
                lines.append("")
            lines.append(_fmt_date(effective_start))
            current_day = day_key
        lines.append(f"  {_fmt_time_or_allday(ev)} — {ev.title}")
    return "\n".join(lines)


def format_mail_list(mails, header):
    if not mails:
        return f"{header}\n\nKeine Mails gefunden."
    lines = [f"*{header}*\n"]
    for m in mails:
        time_str = m.received.astimezone(BERLIN).strftime("%d.%m. %H:%M")
        unread_marker = "🔵 " if not m.is_read else ""
        attach_marker = "📎 " if m.has_attachments else ""
        sender = m.sender_name or m.sender_email or "(unbekannt)"
        subject = m.subject.replace("*", "").replace("_", "").replace("`", "")[:80]
        sender_clean = sender.replace("*", "").replace("_", "").replace("`", "")[:40]
        lines.append(
            f"{unread_marker}{attach_marker}*{sender_clean}* — {time_str}\n  {subject}"
        )
    return "\n\n".join(lines)


def format_folder_list(folders):
    if not folders:
        return "Keine Ordner gefunden."
    lines = ["*📁 Mail-Ordner*\n"]
    for f in folders:
        unread = f" ({f.unread_count} ungelesen)" if f.unread_count else ""
        lines.append(f"• {f.name}{unread}")
    return "\n".join(lines)


async def handle_mail(chat_id, text, params):
    bot = Bot(token=TELEGRAM_TOKEN)
    from mail_agent import MailAgent

    mode = params.get("mode", "quick_scan")

    if mode == "compose":
        to_email = params.get("to_email", "")
        subject = params.get("subject", "(kein Betreff)")
        body = params.get("body", "")

        if not to_email or "@" not in to_email:
            await bot.send_message(
                chat_id=chat_id,
                text="Empfänger-Adresse fehlt oder ist ungültig. Bitte nochmal mit vollständiger E-Mail-Adresse.",
            )
            return

        _pending_mail_ops[chat_id] = {
            "type": "compose",
            "to_email": to_email,
            "subject": subject,
            "body": body,
        }

        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        keyboard = [
            [
                InlineKeyboardButton("📤 Senden", callback_data="mail:send"),
                InlineKeyboardButton("❌ Abbrechen", callback_data="mail:cancel"),
            ]
        ]

        preview = f"📝 *Entwurf*\n\n*An:* {to_email}\n*Betreff:* {subject}\n\n{body}"
        await bot.send_message(
            chat_id=chat_id,
            text=preview,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    agent = MailAgent()
    count = params.get("count")
    sender = params.get("sender")
    subject_contains = params.get("subject_contains")
    since_iso = params.get("since_iso")
    folder_name = params.get("folder_name")

    folder_id = None
    if folder_name:
        try:
            folder = await asyncio.to_thread(agent.find_folder_by_name, folder_name)
            if folder is None:
                await bot.send_message(
                    chat_id=chat_id,
                    text=f"Ordner '{folder_name}' nicht gefunden.",
                )
                return
            folder_id = folder.id
        except Exception as e:
            logger.exception("Folder lookup failed")
            await bot.send_message(
                chat_id=chat_id,
                text=f"Konnte Ordner nicht abrufen: {e}",
            )
            return

    try:
        if mode == "list_folders":
            folders = await asyncio.to_thread(agent.list_folders)
            response = format_folder_list(folders)
        elif mode == "unread":
            n = count or 20
            mails = await asyncio.to_thread(agent.get_unread, n, folder_id)
            response = format_mail_list(mails, header=f"📬 Ungelesen ({len(mails)})")
        elif mode == "search":
            since = datetime.fromisoformat(since_iso) if since_iso else None
            query_parts = [p for p in [sender, subject_contains, text] if p]
            query = " ".join(query_parts) if query_parts else text
            mails = await asyncio.to_thread(agent.smart_search, query, 150, since)
            response = format_mail_list(mails, header=f"🔍 Suche ({len(mails)})")
        else:
            n = count or 10
            mails = await asyncio.to_thread(agent.quick_scan, n, folder_id)
            header = f"📥 Neueste {len(mails)}"
            if folder_name:
                header += f" in '{folder_name}'"
            response = format_mail_list(mails, header=header)
    except Exception as e:
        logger.exception("Mail handler failed")
        await bot.send_message(chat_id=chat_id, text=f"Mail-Fehler: {e}")
        return

    await bot.send_message(chat_id=chat_id, text=response, parse_mode="Markdown")


async def handle_calendar(
    chat_id,
    text,
    kind=None,
    start=None,
    end=None,
    mode="read",
    title=None,
    calendar_name=None,
):
    bot = Bot(token=TELEGRAM_TOKEN)

    if mode == "write":
        if not title or not start:
            await bot.send_message(
                chat_id=chat_id, text="Bitte Titel und Startzeit angeben."
            )
            return
        if end is None:
            end = start + timedelta(hours=1)
        try:
            await asyncio.to_thread(
                calendar_agent.create_event, title, start, end, calendar_name
            )
            cal_note = f" in '{calendar_name}'" if calendar_name else ""
            await bot.send_message(
                chat_id=chat_id,
                text=f"✅ Termin erstellt{cal_note}: *{title}*\n{start.strftime('%d.%m.%Y %H:%M')} – {end.strftime('%H:%M')}",
                parse_mode="Markdown",
            )
        except Exception as e:
            await bot.send_message(
                chat_id=chat_id, text=f"❌ Termin konnte nicht erstellt werden: {e}"
            )
        return

    if start is None or end is None:
        if kind != "next":
            window = detect_calendar_window(text)
            if window is None:
                await bot.send_message(
                    chat_id=chat_id,
                    text="Konnte das Zeitfenster nicht bestimmen. Bitte konkreter fragen (z.B. 'heute', 'morgen', 'diese Woche', 'nächster Termin').",
                )
                return
            kind, start, end = window
    try:
        if kind == "next":
            ev = await asyncio.to_thread(calendar_agent.get_next_event)
            msg = format_calendar_response("next", ev)
        else:
            events = await asyncio.to_thread(calendar_agent.get_events, start, end)
            msg = format_calendar_response(kind, events, query_start=start)
        await bot.send_message(chat_id=chat_id, text=msg)
    except Exception as e:
        await bot.send_message(chat_id=chat_id, text=f"Kalender-Fehler: {str(e)}")


async def ask_claude(
    chat_id,
    system,
    user,
    model="claude-haiku-4-5-20251001",
    use_web_search=False,
    history: list[dict] | None = None,
) -> str:
    bot = Bot(token=TELEGRAM_TOKEN)
    answer = ""
    try:
        kwargs = {
            "model": model,
            "max_tokens": 2048,
            "system": system,
            "messages": [*(history or []), {"role": "user", "content": user}],
        }
        if use_web_search:
            kwargs["tools"] = [{"type": "web_search_20250305", "name": "web_search"}]

        response = claude.messages.create(**kwargs)

        for block in response.content:
            if hasattr(block, "text"):
                answer += block.text

        if not answer:
            answer = "Keine Antwort erhalten."
        if len(answer) > 4000:
            answer = answer[:4000] + "\n[...]"
        await bot.send_message(chat_id=chat_id, text=answer)
    except Exception as e:
        answer = f"Fehler: {str(e)}"
        await bot.send_message(chat_id=chat_id, text=answer)
    return answer


async def send_briefing():
    chat_id_str = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not chat_id_str:
        logger.warning("TELEGRAM_CHAT_ID nicht gesetzt — Briefing übersprungen")
        return
    bot = Bot(token=os.environ["TELEGRAM_BOT_TOKEN"])
    try:
        msg = await build_briefing()
        await bot.send_message(
            chat_id=int(chat_id_str), text=msg, parse_mode="Markdown"
        )
    except Exception as e:
        logger.exception(f"Briefing-Fehler: {e}")


async def start(update, context):
    await update.message.reply_text(
        "Hallo Philipp! Ich bin Jarvis.\n\n"
        "Coding (Frage): 'Was sind die Todos in recipe-app?'\n"
        "Coding (Aktion): 'Fixe den Login-Bug in recipe-app'\n"
        "Research: 'Recherchiere: ESG Pflichten 2026'\n"
        "Work: 'Fass mir diesen Text zusammen'\n"
        "Personal: 'Was sind gute Laufschuhe?'"
    )


async def _process_text(text: str, chat_id: int, update: Update) -> None:
    routing = await route_with_llm(text)
    intent = routing["intent"]
    params = routing["params"]

    confidence = routing["confidence"]
    if confidence < 5:
        await update.message.reply_text(
            "Ich bin mir nicht ganz sicher, was du meinst. "
            "Bitte präzisiere: Kalender, Mail, Task-Liste, Coding oder etwas anderes?"
        )
        return

    memory_context = ""
    if intent in _MEMORY_INTENTS:
        if _profile_agent:
            try:
                profile = _profile_agent.load()
                memory_context += f"=== Philipps Profil ===\n{profile}\n\n"
            except Exception as e:
                logger.warning("Profile load failed: %s", e)
        if _memory_agent:
            try:
                memories = await _memory_agent.retrieve()
                if memories:
                    bullet_list = "\n".join(f"• {m}" for m in memories)
                    memory_context += f"=== Erinnerungen ===\n{bullet_list}\n\n"
            except Exception as e:
                logger.warning("Memory retrieval failed: %s", e)

    logger.info(f"Intent: {intent} | Nachricht: {text}")

    answer: str = ""
    history: list[dict] = []
    if _conversation_db and intent in _HISTORY_INTENTS:
        try:
            history = await _conversation_db.get_recent(chat_id, n=20)
        except Exception as e:
            logger.warning("History load failed: %s", e)

    if intent == "calendar":
        mode = params.get("mode", "read")
        kind = params.get("kind")
        start_str = params.get("start")
        end_str = params.get("end")
        start = datetime.fromisoformat(start_str) if start_str else None
        end = datetime.fromisoformat(end_str) if end_str else None
        title = params.get("title")
        calendar_name = params.get("calendar_name")
        await handle_calendar(
            chat_id=chat_id,
            text=text,
            kind=kind,
            start=start,
            end=end,
            mode=mode,
            title=title,
            calendar_name=calendar_name,
        )
        return

    if intent == "mail":
        await handle_mail(chat_id=chat_id, text=text, params=params)
        return

    if intent == "research":
        stop = asyncio.Event()
        typing_task = asyncio.create_task(_keep_typing(chat_id, stop))
        try:
            answer = await ask_claude(
                chat_id=chat_id,
                system=memory_context
                + "Du bist Jarvis, KI-Assistent fuer Philipp. Recherchiere im Internet und antworte praezise auf Deutsch mit Quellenangaben.",
                user=text,
                model="claude-sonnet-4-6",
                use_web_search=True,
                history=history,
            )
        finally:
            stop.set()
            await typing_task
        if _memory_agent:
            asyncio.create_task(_memory_agent.extract(text, answer, source="research"))

    elif intent == "coding":
        mode = params.get("mode", "action")
        project = params.get("project")

        if not project:
            projects = await list_projects()
            project = projects[0] if projects else "recipe-app"

        if mode == "query":
            query_type = params.get("query_type", "backlog")
            await update.message.reply_text("🔍 Lese...")
            query_result = await handle_coding_query(project, query_type)
            await update.message.reply_text(
                f"📁 *{project}* — {query_type}\n\n{query_result[:4000]}",
                parse_mode="Markdown",
            )

        elif mode == "backlog_write":
            item = params.get("backlog_item", text)
            priority = params.get("backlog_priority", "P1")
            success = await add_backlog_item(project, item, priority)
            if success:
                await update.message.reply_text(
                    f"✅ Backlog-Item hinzugefügt in *{project}*:\n_{item}_",
                    parse_mode="Markdown",
                )
            else:
                await update.message.reply_text(
                    "❌ Konnte Backlog nicht aktualisieren."
                )

        else:  # action
            asyncio.create_task(run_coding_action(text, project, chat_id))

    elif intent == "reminder_write":
        title = params.get("title", "")
        due_date_str = params.get("due_date")
        list_name = params.get("list_name") or os.environ.get(
            "REMINDER_TODO_LIST", "Tasks"
        )
        if not title:
            await update.message.reply_text("Kein Titel angegeben.")
            return
        try:
            ok = await asyncio.to_thread(add_task, list_name, title, due_date_str)
            if ok:
                due_str = f" (fällig: {due_date_str})" if due_date_str else ""
                await update.message.reply_text(
                    f"✅ Erinnerung '{title}'{due_str} in To-Do gespeichert."
                )
            else:
                await update.message.reply_text(
                    f"❌ Liste '{list_name}' nicht gefunden. Verfügbare Listen mit 'Zeig mir alle To-Do-Listen'."
                )
        except Exception as e:
            logger.exception("reminder_write fehlgeschlagen")
            await update.message.reply_text(
                f"❌ Erinnerung konnte nicht erstellt werden: {e}"
            )
        return

    elif intent == "work":
        stop = asyncio.Event()
        typing_task = asyncio.create_task(_keep_typing(chat_id, stop))
        try:
            answer = await ask_claude(
                chat_id=chat_id,
                system=memory_context
                + "Du bist Jarvis, KI-Assistent fuer Philipp (Projektmanager, Strategieberatung). Antworte praezise und strukturiert auf Deutsch.",
                user=text,
                model="claude-sonnet-4-6",
                use_web_search=True,
                history=history,
            )
        finally:
            stop.set()
            await typing_task
        if _memory_agent:
            asyncio.create_task(_memory_agent.extract(text, answer, source="work"))

    elif intent == "news":
        await update.message.reply_text("📰 Lade AI-News...")
        news = await asyncio.to_thread(get_ai_news, 48, 10)
        await update.message.reply_text(
            f"📰 *AI NEWS — letzte 48h*\n\n{news or 'Keine News gefunden.'}",
            parse_mode="Markdown",
        )

    elif intent == "tasks":
        mode = params.get("mode", "read")
        list_name = params.get("list_name")
        item = params.get("item")

        if mode == "read":
            task_result = await asyncio.to_thread(get_tasks, list_name)
            await update.message.reply_text(
                task_result or "Keine offenen Tasks.", parse_mode="Markdown"
            )

        elif mode == "write" and item:
            if not list_name:
                await update.message.reply_text("Welche Liste? (z.B. 'Einkaufsliste')")
            else:
                success = await asyncio.to_thread(add_task, list_name, item)
                if success:
                    await update.message.reply_text(
                        f"✅ '{item}' zu *{list_name}* hinzugefügt.",
                        parse_mode="Markdown",
                    )
                else:
                    await update.message.reply_text("❌ Konnte Task nicht hinzufügen.")

        elif mode == "complete" and item:
            if not list_name:
                await update.message.reply_text("Welche Liste?")
            else:
                success = await asyncio.to_thread(complete_task, list_name, item)
                if success:
                    await update.message.reply_text(
                        f"✅ '{item}' in *{list_name}* als erledigt markiert.",
                        parse_mode="Markdown",
                    )
                else:
                    await update.message.reply_text(
                        "❌ Task nicht gefunden oder bereits erledigt."
                    )

        elif mode == "create_list" and list_name:
            success = await asyncio.to_thread(create_list, list_name)
            if success:
                router._todo_lists_cache = ([], 0.0)
                await update.message.reply_text(
                    f"✅ Liste *{list_name}* angelegt.", parse_mode="Markdown"
                )
            else:
                await update.message.reply_text(
                    "❌ Liste konnte nicht angelegt werden."
                )

        elif mode == "delete_list" and list_name:
            success = await asyncio.to_thread(delete_list, list_name)
            if success:
                router._todo_lists_cache = ([], 0.0)
                await update.message.reply_text(
                    f"✅ Liste *{list_name}* gelöscht.", parse_mode="Markdown"
                )
            else:
                await update.message.reply_text(
                    f"❌ Liste '{list_name}' nicht gefunden oder konnte nicht gelöscht werden."
                )

        elif mode == "rename_list":
            new_name = params.get("new_name")
            if not list_name or not new_name:
                await update.message.reply_text(
                    "Bitte alter und neuer Listenname angeben."
                )
            else:
                success = await asyncio.to_thread(rename_list, list_name, new_name)
                if success:
                    router._todo_lists_cache = ([], 0.0)
                    await update.message.reply_text(
                        f"✅ Liste *{list_name}* → *{new_name}* umbenannt.",
                        parse_mode="Markdown",
                    )
                else:
                    await update.message.reply_text(
                        f"❌ Liste '{list_name}' nicht gefunden oder Umbenennung fehlgeschlagen."
                    )

    elif intent == "weather":
        period = params.get("period", "today")
        time_of_day = params.get("time_of_day")
        location = params.get("location")
        period_label = {
            "today": "heute",
            "tomorrow": "morgen",
            "week": "diese Woche",
        }.get(period, period)
        weather = await asyncio.to_thread(get_weather, period, time_of_day, location)
        await update.message.reply_text(
            f"🌤️ *Wetter {period_label}:*\n{weather}", parse_mode="Markdown"
        )

    elif intent == "briefing":
        await update.message.reply_text("⏳ Briefing wird erstellt...")
        msg = await build_briefing()
        await update.message.reply_text(msg, parse_mode="Markdown")

    elif intent == "memory":
        mode = params.get("mode", "list")
        query = params.get("query")
        if not _memory_agent:
            await update.message.reply_text("Memory-System nicht initialisiert.")
            return
        if mode == "delete":
            msg = await _memory_agent.delete_memory(query)
        else:
            msg = await _memory_agent.list_memories()
        await update.message.reply_text(msg, parse_mode="Markdown")

    else:
        personal_system = (
            "Du bist Jarvis, persönlicher KI-Assistent für Philipp. Antworte hilfreich auf Deutsch.\n\n"
            "Deine tatsächlichen Fähigkeiten:\n"
            "- Kalender: Apple Calendar lesen und Termine erstellen (CalDAV)\n"
            "- Apple Reminders: lesen und erstellen\n"
            "- Mail: MS365-Posteingang lesen, durchsuchen, Mails schreiben\n"
            "- Tasks: MS To Do Listen lesen und verwalten\n"
            "- Wetter: aktuelle Wetterdaten und Vorhersage für Tutzing/München\n"
            "- KI-News: aktuelle Nachrichten aus der AI-Welt\n"
            "- Web-Recherche: aktuelle Informationen aus dem Internet\n"
            "- Coding: Claude Code auf VPS-Projekten ausführen (recipe-app, immo-radar etc.)\n"
            "- Morning Briefing: tägliche Zusammenfassung\n"
            "- Erinnerungen: persönliche Fakten und Präferenzen speichern/abrufen\n\n"
            "Wenn eine Frage zu einem dieser Bereiche gehört aber hierher geroutet wurde, sag das ehrlich "
            "('Das war ein Routing-Fehler — frag nochmal klarer') statt zu halluzinieren. "
            "Bei echten allgemeinen Fragen (Smalltalk, Wissensfragen ohne Tool-Bezug) antworte normal."
        )
        stop = asyncio.Event()
        typing_task = asyncio.create_task(_keep_typing(chat_id, stop))
        try:
            answer = await ask_claude(
                chat_id=chat_id,
                system=memory_context + personal_system,
                user=text,
                model="claude-sonnet-4-6",
                history=history,
            )
        finally:
            stop.set()
            await typing_task
        if _memory_agent:
            asyncio.create_task(_memory_agent.extract(text, answer, source="personal"))

    if (
        _conversation_db
        and intent in _HISTORY_INTENTS
        and answer
        and not answer.startswith("Fehler:")
    ):
        try:
            await _conversation_db.save(chat_id, "user", text)
            await _conversation_db.save(chat_id, "assistant", answer)
        except Exception as e:
            logger.warning("History save failed: %s", e)

    if (
        _profile_agent
        and intent in _HISTORY_INTENTS
        and answer
        and not answer.startswith("Fehler:")
    ):
        conversation = f"Philipp: {text}\n\nJarvis: {answer}"
        asyncio.create_task(_profile_agent.update(conversation))


async def handle_message(update, context):
    update_id = update.update_id
    if update_id in processed_updates:
        logger.info(f"Duplikat ignoriert: update_id={update_id}")
        return
    processed_updates.add(update_id)
    if len(processed_updates) > 1000:
        processed_updates.clear()

    text = update.message.text
    chat_id = update.message.chat_id
    await _process_text(text, chat_id, update)


async def handle_voice(update, context):
    update_id = update.update_id
    if update_id in processed_updates:
        logger.info(f"Duplikat ignoriert: update_id={update_id}")
        return
    processed_updates.add(update_id)
    if len(processed_updates) > 1000:
        processed_updates.clear()

    chat_id = update.message.chat_id
    try:
        voice_file = await update.message.voice.get_file()
        ogg_bytes = bytes(await voice_file.download_as_bytearray())
        text = await transcribe(ogg_bytes)
    except Exception as e:
        logger.warning("Voice transcription failed: %s", e)
        await update.message.reply_text(
            "❌ Sprachnachricht konnte nicht transkribiert werden."
        )
        return

    await _process_text(text, chat_id, update)


@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, bot_app.bot)
    await bot_app.process_update(update)
    return {"ok": True}


@app.get("/health")
async def health():
    return {"status": "ok", "service": "jarvis-gateway"}


@app.get("/oauth/microsoft/login")
async def microsoft_login(secret: str = ""):
    if secret != os.environ.get("OAUTH_LOGIN_SECRET", ""):
        raise HTTPException(status_code=403, detail="Forbidden")
    from microsoft_auth import get_login_url
    import secrets as _secrets

    state = _secrets.token_urlsafe(16)
    url = get_login_url(state)
    return RedirectResponse(url=url, status_code=302)


@app.get("/oauth/microsoft/callback")
async def microsoft_callback(
    code: str = "", error: str = "", error_description: str = ""
):
    if error:
        return PlainTextResponse(
            f"OAuth-Fehler: {error}\n{error_description}",
            status_code=400,
        )
    if not code:
        return PlainTextResponse("Kein code-Parameter", status_code=400)

    from microsoft_auth import handle_callback

    try:
        result = handle_callback(code)
        if "access_token" in result:
            return PlainTextResponse(
                "✅ Microsoft-Login erfolgreich. Token gespeichert. "
                "Du kannst dieses Fenster schließen."
            )
        return PlainTextResponse(
            f"⚠️ Token konnte nicht abgerufen werden: "
            f"{result.get('error_description', 'unbekannter Fehler')}",
            status_code=500,
        )
    except Exception as e:
        logger.exception("OAuth-Callback fehlgeschlagen")
        return PlainTextResponse(f"❌ Callback-Fehler: {e}", status_code=500)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from vps import git_push

    query = update.callback_query
    await query.answer()
    data = query.data or ""

    if data.startswith("push:"):
        project = data[5:]
        await query.edit_message_reply_markup(reply_markup=None)
        success = await git_push(project)
        if success:
            await query.message.reply_text(
                f"✅ *{project}* gepusht.", parse_mode="Markdown"
            )
        else:
            await query.message.reply_text(f"❌ Push fehlgeschlagen für {project}.")
    elif data == "dismiss":
        await query.edit_message_reply_markup(reply_markup=None)

    elif data == "mail:send":
        chat_id = query.message.chat_id
        draft = _pending_mail_ops.pop(chat_id, None)
        if draft is None:
            await query.edit_message_text("⚠️ Kein Entwurf mehr vorhanden.")
            return
        from mail_agent import MailAgent

        agent = MailAgent()
        success = await asyncio.to_thread(
            agent.send_mail, draft["to_email"], draft["subject"], draft["body"]
        )
        if success:
            await query.edit_message_text(
                f"✅ Mail gesendet an *{draft['to_email']}*.",
                parse_mode="Markdown",
            )
        else:
            await query.edit_message_text("❌ Mail konnte nicht gesendet werden.")

    elif data == "mail:cancel":
        chat_id = query.message.chat_id
        _pending_mail_ops.pop(chat_id, None)
        await query.edit_message_text("❌ Entwurf verworfen.")


@app.on_event("startup")
async def startup():
    from coding_agent import _ensure_init

    await _ensure_init()
    global _memory_agent, _conversation_db, _profile_agent
    from db import MemoryDB
    from memory_agent import MemoryAgent

    _memory_db = MemoryDB()
    await _memory_db.init()
    _memory_agent = MemoryAgent(_memory_db)
    logger.info("MemoryDB initialisiert")
    from db import ConversationDB

    _conv_db = ConversationDB()
    await _conv_db.init()
    _conversation_db = _conv_db
    logger.info("ConversationDB initialisiert")
    from profile_agent import ProfileAgent

    _profile_agent = ProfileAgent()
    _profile_agent.load()  # creates profile file if it doesn't exist yet
    logger.info("ProfileAgent initialisiert")
    from db import ProactiveDB
    from proactive_agent import init_proactive

    _proactive_db = ProactiveDB()
    await _proactive_db.init()
    init_proactive(_proactive_db, _memory_db)
    task = asyncio.create_task(_memory_agent.migrate_embeddings())
    task.add_done_callback(
        lambda t: (
            logger.error("Migration failed: %s", t.exception())
            if t.exception()
            else None
        )
    )
    projects = await list_projects()
    logger.info(f"Workspace projects: {projects}")
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    bot_app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    from telegram.ext import CallbackQueryHandler

    bot_app.add_handler(CallbackQueryHandler(handle_callback))
    try:
        from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

        _scheduler.add_jobstore(
            SQLAlchemyJobStore(url="sqlite:////root/.jarvis/jarvis_jobs.db"), "default"
        )
        logger.info("APScheduler SQLite-Jobstore konfiguriert")
    except Exception as e:
        logger.warning("SQLite-Jobstore nicht verfügbar: %s — läuft ohne Persistenz", e)
    _scheduler.add_job(
        send_briefing,
        CronTrigger(hour=7, minute=0, timezone="Europe/Berlin"),
        id="morning_briefing",
        replace_existing=True,
    )
    _chat_id_str = os.environ.get("TELEGRAM_CHAT_ID", "")
    if _chat_id_str:
        _chat_id = int(_chat_id_str)
        from proactive_agent import (
            check_important_mails,
            send_task_reminder,
            send_weekly_review,
        )

        _scheduler.add_job(
            check_important_mails,
            CronTrigger(hour=9, minute=0, timezone="Europe/Berlin"),
            args=[_chat_id],
            id="mail_check_morning",
            replace_existing=True,
        )
        _scheduler.add_job(
            check_important_mails,
            CronTrigger(hour=14, minute=0, timezone="Europe/Berlin"),
            args=[_chat_id],
            id="mail_check_afternoon",
            replace_existing=True,
        )
        _scheduler.add_job(
            send_task_reminder,
            CronTrigger(hour=10, minute=0, timezone="Europe/Berlin"),
            args=[_chat_id],
            id="task_reminder_daily",
            replace_existing=True,
        )
        _scheduler.add_job(
            send_weekly_review,
            CronTrigger(day_of_week="fri", hour=17, minute=0, timezone="Europe/Berlin"),
            args=[_chat_id],
            id="weekly_review_friday",
            replace_existing=True,
        )
        logger.info(
            "Proaktive Jobs registriert: mail_check x2, task_reminder, weekly_review"
        )
    else:
        logger.warning("TELEGRAM_CHAT_ID nicht gesetzt — proaktive Jobs deaktiviert")
    _scheduler.start()
    logger.info("APScheduler gestartet — Briefing täglich 07:00 Berlin")
    await bot_app.initialize()
    await bot_app.start()
    logger.info("Jarvis gestartet")


@app.on_event("shutdown")
async def shutdown():
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
    await bot_app.stop()
