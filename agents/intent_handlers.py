"""Lean intent handlers — coding, briefing, memory."""

import logging
import os
import asyncio

from telegram import Bot

import app_state
from app_state import _conv_complete
from coding_agent import handle_coding_query, run_coding_action, add_backlog_item
from vps import list_projects
from briefing_agent import build_briefing

logger = logging.getLogger("jarvis.intent_handlers")


async def send_briefing():
    chat_id_str = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not chat_id_str:
        logger.warning("TELEGRAM_CHAT_ID nicht gesetzt — Briefing übersprungen")
        return
    bot = Bot(token=os.environ["TELEGRAM_BOT_TOKEN"])
    try:
        msg = await build_briefing()
        try:
            await bot.send_message(
                chat_id=int(chat_id_str), text=msg, parse_mode="Markdown"
            )
        except Exception:
            await bot.send_message(chat_id=int(chat_id_str), text=msg)
    except Exception as e:
        logger.exception(f"Briefing-Fehler: {e}")


async def handle_coding(chat_id: int, text: str, params: dict, update) -> None:
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
            await update.message.reply_text("❌ Konnte Backlog nicht aktualisieren.")

    else:  # action
        asyncio.create_task(run_coding_action(text, project, chat_id))
    _conv_complete(chat_id, f"Coding {mode} ({project})")


async def handle_briefing(chat_id: int, update) -> None:
    await update.message.reply_text("⏳ Briefing wird erstellt...")
    msg = await build_briefing()
    await update.message.reply_text(msg, parse_mode="Markdown")
    _conv_complete(chat_id, "Morgenbriefing angezeigt")


async def handle_memory(chat_id: int, params: dict, update) -> None:
    mode = params.get("mode", "list")
    query = params.get("query")
    if not app_state.memory_agent:
        await update.message.reply_text("Memory-System nicht initialisiert.")
        return
    if mode == "delete":
        msg = await app_state.memory_agent.delete_memory(query)
    else:
        msg = await app_state.memory_agent.list_memories()
    await update.message.reply_text(msg, parse_mode="Markdown")
    _conv_complete(chat_id, f"Erinnerungen {mode}")
