"""Telegram InlineKeyboard callback router."""

import logging

from telegram import Update
from telegram.ext import ContextTypes

import app_state

logger = logging.getLogger("jarvis.callbacks")


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

    elif data.startswith("agent:confirm:"):
        chat_id = query.message.chat_id
        try:
            expected_id = int(data.split(":")[2])
        except (ValueError, IndexError):
            await query.edit_message_text("❌ Ungültiger Confirm.")
            return
        actions = app_state.take_pending_actions(chat_id, expected_id)
        if not actions:
            await query.edit_message_text(
                "⏱️ Diese Vormerkung ist abgelaufen oder überholt — bitte nochmal."
            )
            return
        from tools import execute_pending_action

        results = []
        for action in actions:
            try:
                results.append(await execute_pending_action(action))
            except Exception as e:
                logger.exception("agent:confirm — Aktion fehlgeschlagen")
                results.append(f"❌ {action['label']}: Fehler — {e}")
        await query.edit_message_text("\n".join(results))

    elif data.startswith("agent:cancel:"):
        chat_id = query.message.chat_id
        try:
            expected_id = int(data.split(":")[2])
        except (ValueError, IndexError):
            await query.edit_message_text("❌ Ungültiger Abbruch.")
            return
        cancelled = app_state.take_pending_actions(chat_id, expected_id)
        if cancelled:
            await query.edit_message_text("❌ Abgebrochen.")
        else:
            await query.edit_message_text("⏱️ Diese Vormerkung ist bereits überholt.")
