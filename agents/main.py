import os
import re
import sys
import json
import logging
import asyncio
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import RedirectResponse, PlainTextResponse
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import anthropic

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from calendar_agent import CalendarAgent, BERLIN
from router import route_with_llm
from coding_agent import handle_coding_query, run_coding_action, add_backlog_item
from vps import list_projects
from briefing_agent import build_briefing
from news_agent import get_ai_news
from tasks_agent import get_tasks, add_task, complete_task

_scheduler = AsyncIOScheduler(timezone="Europe/Berlin")

calendar_agent = CalendarAgent()

_WEEKDAYS_DE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("jarvis")

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
claude = anthropic.Anthropic()

app = FastAPI()
bot_app = Application.builder().token(TELEGRAM_TOKEN).build()

processed_updates = set()
_pending_mail_drafts: dict[int, dict] = {}

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

    if "nächster termin" in t or "naechster termin" in t or "wann ist mein nächster" in t or "wann ist mein naechster" in t:
        return ("next", None, None)
    if "diese woche" in t or "woche kalender" in t or "termine woche" in t:
        start = now
        days_until_sunday = 6 - now.weekday()  # 0=Mo, 6=So
        sunday = (now + timedelta(days=days_until_sunday)).replace(
            hour=23, minute=59, second=59, microsecond=999999
        )
        return ("week", start, sunday)
    if re.search(r'\bheute\b', t) and ("was habe ich" in t or "termine" in t or "kalender" in t):
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        return ("today", start, end)
    if re.search(r'\bmorgen\b', t) and ("was habe ich" in t or "termine" in t or "kalender" in t):
        start = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
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
        time_part = "ganztägig" if getattr(ev, "all_day", False) else f"um {ev.start.strftime('%H:%M')}"
        line = f"Nächster Termin: {_fmt_date(ev.start)} {time_part} — {ev.title}"
        if ev.location:
            line += f" ({ev.location})"
        return line

    if not events:
        label = {"today": "heute", "tomorrow": "morgen", "week": "diese Woche"}.get(kind, "")
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
            f"{unread_marker}{attach_marker}*{sender_clean}* — {time_str}\n"
            f"  {subject}"
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

        _pending_mail_drafts[chat_id] = {
            "to_email": to_email,
            "subject": subject,
            "body": body,
        }

        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        keyboard = [[
            InlineKeyboardButton("📤 Senden", callback_data="mail:send"),
            InlineKeyboardButton("❌ Abbrechen", callback_data="mail:cancel"),
        ]]

        preview = (
            f"📝 *Entwurf*\n\n"
            f"*An:* {to_email}\n"
            f"*Betreff:* {subject}\n\n"
            f"{body}"
        )
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
            n = count or 25
            since = datetime.fromisoformat(since_iso) if since_iso else None
            mails = await asyncio.to_thread(
                agent.search, sender, subject_contains, since, folder_id, n
            )
            header_parts = ["🔍 Suche"]
            if sender:
                header_parts.append(f"Absender: {sender}")
            if subject_contains:
                header_parts.append(f"Betreff: {subject_contains}")
            if folder_name:
                header_parts.append(f"Ordner: {folder_name}")
            response = format_mail_list(
                mails, header=" — ".join(header_parts) + f" ({len(mails)})"
            )
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


async def handle_calendar(chat_id, text, kind=None, start=None, end=None, mode="read", title=None, calendar_name=None):
    bot = Bot(token=TELEGRAM_TOKEN)

    if mode == "write":
        if not title or not start:
            await bot.send_message(chat_id=chat_id, text="Bitte Titel und Startzeit angeben.")
            return
        if end is None:
            end = start + timedelta(hours=1)
        try:
            await asyncio.to_thread(calendar_agent.create_event, title, start, end, calendar_name)
            cal_note = f" in '{calendar_name}'" if calendar_name else ""
            await bot.send_message(
                chat_id=chat_id,
                text=f"✅ Termin erstellt{cal_note}: *{title}*\n{start.strftime('%d.%m.%Y %H:%M')} – {end.strftime('%H:%M')}",
                parse_mode="Markdown",
            )
        except Exception as e:
            await bot.send_message(chat_id=chat_id, text=f"❌ Termin konnte nicht erstellt werden: {e}")
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


async def ask_claude(chat_id, system, user, model="claude-haiku-4-5-20251001", use_web_search=False):
    bot = Bot(token=TELEGRAM_TOKEN)
    try:
        kwargs = {
            "model": model,
            "max_tokens": 2048,
            "system": system,
            "messages": [{"role": "user", "content": user}]
        }
        if use_web_search:
            kwargs["tools"] = [{"type": "web_search_20250305", "name": "web_search"}]

        response = claude.messages.create(**kwargs)

        answer = ""
        for block in response.content:
            if hasattr(block, "text"):
                answer += block.text

        if not answer:
            answer = "Keine Antwort erhalten."
        if len(answer) > 4000:
            answer = answer[:4000] + "\n[...]"
        await bot.send_message(chat_id=chat_id, text=answer)
    except Exception as e:
        await bot.send_message(chat_id=chat_id, text=f"Fehler: {str(e)}")

async def send_briefing():
    chat_id_str = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not chat_id_str:
        logger.warning("TELEGRAM_CHAT_ID nicht gesetzt — Briefing übersprungen")
        return
    bot = Bot(token=os.environ["TELEGRAM_BOT_TOKEN"])
    try:
        msg = await build_briefing()
        await bot.send_message(chat_id=int(chat_id_str), text=msg, parse_mode="Markdown")
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

    result = await route_with_llm(text)
    intent = result["intent"]
    params = result["params"]

    confidence = result["confidence"]
    if confidence < 5:
        await update.message.reply_text(
            "Ich bin mir nicht ganz sicher, was du meinst. "
            "Bitte präzisiere: Kalender, Mail, Task-Liste, Coding oder etwas anderes?"
        )
        return

    logger.info(f"Intent: {intent} | Nachricht: {text}")

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
            chat_id=chat_id, text=text, kind=kind, start=start, end=end,
            mode=mode, title=title, calendar_name=calendar_name,
        )
        return

    if intent == "mail":
        await handle_mail(chat_id=chat_id, text=text, params=params)
        return

    if intent == "research":
        await update.message.reply_text("Recherchiere im Web...")
        await ask_claude(
            chat_id=chat_id,
            system="Du bist Jarvis, KI-Assistent fuer Philipp. Recherchiere im Internet und antworte praezise auf Deutsch mit Quellenangaben.",
            user=text,
            model="claude-sonnet-4-6",
            use_web_search=True
        )

    elif intent == "coding":
        mode = params.get("mode", "action")
        project = params.get("project")

        if not project:
            projects = await list_projects()
            project = projects[0] if projects else "recipe-app"

        if mode == "query":
            query_type = params.get("query_type", "backlog")
            await update.message.reply_text("🔍 Lese...")
            result = await handle_coding_query(project, query_type)
            await update.message.reply_text(
                f"📁 *{project}* — {query_type}\n\n{result[:4000]}",
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
                await update.message.reply_text("❌ Konnte Backlog nicht aktualisieren.")

        else:  # action
            asyncio.create_task(run_coding_action(text, project, chat_id))

    elif intent == "work":
        await update.message.reply_text("Analysiere...")
        await ask_claude(
            chat_id=chat_id,
            system="Du bist Jarvis, KI-Assistent fuer Philipp (Projektmanager, Strategieberatung). Antworte praezise und strukturiert auf Deutsch.",
            user=text,
            model="claude-sonnet-4-6",
            use_web_search=True
        )

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
            result = await asyncio.to_thread(get_tasks, list_name)
            await update.message.reply_text(result or "Keine offenen Tasks.", parse_mode="Markdown")

        elif mode == "write" and item:
            if not list_name:
                await update.message.reply_text("Welche Liste? (z.B. 'Einkaufsliste')")
            else:
                success = await asyncio.to_thread(add_task, list_name, item)
                if success:
                    await update.message.reply_text(
                        f"✅ '{item}' zu *{list_name}* hinzugefügt.", parse_mode="Markdown"
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
                        f"✅ '{item}' in *{list_name}* als erledigt markiert.", parse_mode="Markdown"
                    )
                else:
                    await update.message.reply_text("❌ Task nicht gefunden oder bereits erledigt.")

    elif intent == "briefing":
        await update.message.reply_text("⏳ Briefing wird erstellt...")
        msg = await build_briefing()
        await update.message.reply_text(msg, parse_mode="Markdown")

    else:
        await update.message.reply_text("Denke nach...")
        personal_system = (
            "Du bist Jarvis, persönlicher KI-Assistent für Philipp. Antworte hilfreich auf Deutsch.\n\n"
            "Wichtig zu deinen Fähigkeiten:\n"
            "- Du HAST Zugriff auf Philipps Apple-Kalender (über einen eigenen Calendar-Handler). "
            "Wenn die Frage nach Kalender oder Terminen klingt, antworte: "
            "\"Diese Frage hätte eigentlich an meinen Calendar-Handler gehen sollen — das war ein "
            "Routing-Fehler. Bitte stell die Frage nochmal mit klareren Worten wie 'Termine', "
            "'Kalender' oder 'wann habe ich Zeit'.\"\n"
            "- Du KANNST im Web recherchieren (über einen Research-Handler).\n"
            "- Du KANNST Code in Philipps Projekten ändern (über einen Coding-Handler).\n"
            "- Wenn die Frage zu einem dieser Bereiche passt, sag ehrlich, dass die Anfrage falsch "
            "geroutet wurde, statt zu halluzinieren.\n"
            "- Bei echten allgemeinen Fragen (Smalltalk, Wissensfragen ohne Tool-Bezug) antworte "
            "normal und hilfreich."
        )
        await ask_claude(
            chat_id=chat_id,
            system=personal_system,
            user=text,
            model="claude-haiku-4-5-20251001"
        )

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
async def microsoft_callback(code: str = "", error: str = "", error_description: str = ""):
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
            await query.message.reply_text(f"✅ *{project}* gepusht.", parse_mode="Markdown")
        else:
            await query.message.reply_text(f"❌ Push fehlgeschlagen für {project}.")
    elif data == "dismiss":
        await query.edit_message_reply_markup(reply_markup=None)

    elif data == "mail:send":
        chat_id = query.message.chat_id
        draft = _pending_mail_drafts.pop(chat_id, None)
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
        _pending_mail_drafts.pop(chat_id, None)
        await query.edit_message_text("❌ Entwurf verworfen.")


@app.on_event("startup")
async def startup():
    from coding_agent import _ensure_init
    await _ensure_init()
    projects = await list_projects()
    logger.info(f"Workspace projects: {projects}")
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    from telegram.ext import CallbackQueryHandler
    bot_app.add_handler(CallbackQueryHandler(handle_callback))
    _scheduler.add_job(
        send_briefing,
        CronTrigger(hour=7, minute=0, timezone="Europe/Berlin"),
        id="morning_briefing",
        replace_existing=True,
    )
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
