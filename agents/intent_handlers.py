"""Lean intent handlers — send_briefing für APScheduler-Proaktiv-Job."""

import logging
import os

from telegram import Bot

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
