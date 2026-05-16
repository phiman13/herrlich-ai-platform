import os
import sys
import logging
import asyncio
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import RedirectResponse, PlainTextResponse
from telegram import Update, Bot
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
)
import app_state
from chat_handler import handle_research, handle_work, handle_personal
from github_webhook import github_webhook

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from router import route_with_llm
from vps import list_projects
from voice_agent import transcribe
from mail_handler import handle_mail_intent
from calendar_handler import (
    handle_calendar_intent,
)
from callbacks import handle_callback
from intent_handlers import (
    handle_coding,
    handle_reminder_write,
    handle_news,
    handle_tasks,
    handle_weather,
    handle_briefing,
    handle_memory,
    send_briefing,
)

_scheduler = AsyncIOScheduler(timezone="Europe/Berlin")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("jarvis")

app = FastAPI()
app.post("/webhook/github")(github_webhook)
bot_app = Application.builder().token(app_state.TELEGRAM_TOKEN).build()


async def send_typing(chat_id: int):
    bot = Bot(token=app_state.TELEGRAM_TOKEN)
    await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)


async def _keep_typing(chat_id: int, stop_event: asyncio.Event):
    while not stop_event.is_set():
        await send_typing(chat_id)
        await asyncio.sleep(4)


# Conversation history for router context: each entry {"u": user_text, "j": bot_summary}
_recent_conv: dict[int, list[dict]] = {}


def _conv_append_user(chat_id: int, text: str) -> None:
    hist = _recent_conv.get(chat_id, [])
    hist.append({"u": text, "j": ""})
    _recent_conv[chat_id] = hist[-8:]


def _conv_complete(chat_id: int, summary: str) -> None:
    hist = _recent_conv.get(chat_id, [])
    if hist:
        hist[-1]["j"] = summary[:180]


def _conv_to_prev_texts(chat_id: int) -> list[str]:
    """Return interleaved Philipp/Jarvis lines for the last 3 completed turns."""
    completed = [t for t in _recent_conv.get(chat_id, []) if t["j"]][-3:]
    lines = []
    for t in completed:
        lines.append(f"Philipp: {t['u']}")
        lines.append(f"Jarvis: {t['j']}")
    return lines


_MEMORY_INTENTS = {"personal", "work", "research"}
_HISTORY_INTENTS = {"personal", "work", "research"}


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
    prev = _conv_to_prev_texts(chat_id)
    _conv_append_user(chat_id, text)
    routing = await route_with_llm(text, prev_texts=prev or None)
    intent = routing["intent"]
    params = routing["params"]

    confidence = routing["confidence"]
    if confidence < 5:
        msg = (
            "Ich bin mir nicht ganz sicher, was du meinst. "
            "Bitte präzisiere: Kalender, Mail, Task-Liste, Coding oder etwas anderes?"
        )
        await update.message.reply_text(msg)
        _conv_complete(chat_id, msg)
        return

    memory_context = ""
    if intent in _MEMORY_INTENTS:
        if app_state.profile_agent:
            try:
                profile = app_state.profile_agent.load()
                memory_context += f"=== Philipps Profil ===\n{profile}\n\n"
            except Exception as e:
                logger.warning("Profile load failed: %s", e)
        if app_state.memory_agent:
            try:
                memories = await app_state.memory_agent.retrieve()
                if memories:
                    bullet_list = "\n".join(f"• {m}" for m in memories)
                    memory_context += f"=== Erinnerungen ===\n{bullet_list}\n\n"
            except Exception as e:
                logger.warning("Memory retrieval failed: %s", e)

    logger.info(f"Intent: {intent} | Nachricht: {text}")

    answer: str = ""
    history: list[dict] = []
    if app_state.conversation_db and intent in _HISTORY_INTENTS:
        try:
            history = await app_state.conversation_db.get_recent(chat_id, n=20)
        except Exception as e:
            logger.warning("History load failed: %s", e)

    if intent == "calendar":
        await handle_calendar_intent(chat_id, text, params)
        return

    if intent == "mail":
        await handle_mail_intent(chat_id, text, params)
        return

    if intent == "research":
        answer = await handle_research(chat_id, text, memory_context, history)
    elif intent == "coding":
        await handle_coding(chat_id, text, params, update)
    elif intent == "reminder_write":
        await handle_reminder_write(chat_id, params, update)
        return
    elif intent == "work":
        answer = await handle_work(chat_id, text, memory_context, history)
    elif intent == "news":
        await handle_news(chat_id, update)
    elif intent == "tasks":
        await handle_tasks(chat_id, params, update)
    elif intent == "weather":
        await handle_weather(chat_id, params, update)
    elif intent == "briefing":
        await handle_briefing(chat_id, update)
    elif intent == "memory":
        await handle_memory(chat_id, params, update)
        return
    else:
        answer = await handle_personal(chat_id, text, memory_context, history)

    if answer and not answer.startswith("Fehler:"):
        _conv_complete(chat_id, answer[:180])

    if (
        app_state.conversation_db
        and intent in _HISTORY_INTENTS
        and answer
        and not answer.startswith("Fehler:")
    ):
        try:
            await app_state.conversation_db.save(chat_id, "user", text)
            await app_state.conversation_db.save(chat_id, "assistant", answer)
        except Exception as e:
            logger.warning("History save failed: %s", e)

    if (
        app_state.profile_agent
        and intent in _HISTORY_INTENTS
        and answer
        and not answer.startswith("Fehler:")
    ):
        conversation = f"Philipp: {text}\n\nJarvis: {answer}"
        asyncio.create_task(app_state.profile_agent.update(conversation))


async def handle_message(update, context):
    update_id = update.update_id
    if update_id in app_state.processed_updates:
        logger.info(f"Duplikat ignoriert: update_id={update_id}")
        return
    app_state.processed_updates.add(update_id)
    if len(app_state.processed_updates) > 1000:
        app_state.processed_updates.clear()

    text = update.message.text
    chat_id = update.message.chat_id
    await _process_text(text, chat_id, update)


async def handle_voice(update, context):
    update_id = update.update_id
    if update_id in app_state.processed_updates:
        logger.info(f"Duplikat ignoriert: update_id={update_id}")
        return
    app_state.processed_updates.add(update_id)
    if len(app_state.processed_updates) > 1000:
        app_state.processed_updates.clear()

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


@app.on_event("startup")
async def startup():
    from coding_agent import _ensure_init

    await _ensure_init()
    from db import MemoryDB
    from memory_agent import MemoryAgent

    _memory_db = MemoryDB()
    await _memory_db.init()
    app_state.memory_agent = MemoryAgent(_memory_db)
    logger.info("MemoryDB initialisiert")
    from db import ConversationDB

    _conv_db = ConversationDB()
    await _conv_db.init()
    app_state.conversation_db = _conv_db
    logger.info("ConversationDB initialisiert")
    from profile_agent import ProfileAgent

    app_state.profile_agent = ProfileAgent()
    app_state.profile_agent.load()  # creates profile file if it doesn't exist yet
    logger.info("ProfileAgent initialisiert")
    from db import ProactiveDB
    from proactive_agent import init_proactive

    _proactive_db = ProactiveDB()
    await _proactive_db.init()
    init_proactive(_proactive_db, _memory_db)
    task = asyncio.create_task(app_state.memory_agent.migrate_embeddings())
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

        _jarvis_dir = os.environ.get("JARVIS_DATA_DIR", "/root/.jarvis")
        _scheduler.add_jobstore(
            SQLAlchemyJobStore(url=f"sqlite:///{_jarvis_dir}/jarvis_jobs.db"), "default"
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
