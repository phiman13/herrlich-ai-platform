import os
import sys
import logging
import asyncio
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import RedirectResponse, PlainTextResponse
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
)
import app_state
from github_webhook import github_webhook
from dispatch import handle_message, handle_voice, start

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from vps import list_projects
from callbacks import handle_callback
from intent_handlers import (
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
        from coding_agent import sync_workspace

        _scheduler.add_job(
            sync_workspace,
            CronTrigger(minute=0, timezone="Europe/Berlin"),
            args=[_chat_id],
            id="workspace_sync",
            replace_existing=True,
        )
        logger.info(
            "Proaktive Jobs registriert: mail_check x2, task_reminder, "
            "weekly_review, workspace_sync (stündlich)"
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
