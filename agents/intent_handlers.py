"""Lean intent handlers — briefing, memory."""

import logging
import os

from telegram import Bot

import app_state
from app_state import _conv_complete
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
