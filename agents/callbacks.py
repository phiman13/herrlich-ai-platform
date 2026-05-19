"""Telegram InlineKeyboard callback router."""

import asyncio
import logging
import time

from telegram import Update
from telegram.ext import ContextTypes

import app_state
from calendar_handler import calendar_agent, _show_calendar_action_confirm
from mail_handler import _show_mail_action_confirm
from formatting import _md_safe

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

    elif data == "mail:send":
        chat_id = query.message.chat_id
        draft = app_state.pending_mail_ops.pop(chat_id, None)
        if draft is None:
            await query.edit_message_text("⚠️ Kein Entwurf mehr vorhanden.")
            return
        if app_state._pending_op_expired(draft):
            await query.edit_message_text("⏱️ Abgelaufen — bitte nochmal.")
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
        app_state.pending_mail_ops.pop(chat_id, None)
        await query.edit_message_text("❌ Entwurf verworfen.")

    elif data == "mail:action:confirm":
        chat_id = query.message.chat_id
        op = app_state.pending_mail_ops.pop(chat_id, None)
        if op is None:
            await query.edit_message_text("⚠️ Keine ausstehende Aktion gefunden.")
            return
        if app_state._pending_op_expired(op):
            await query.edit_message_text("⏱️ Abgelaufen — bitte nochmal.")
            return
        from mail_agent import MailAgent

        agent = MailAgent()
        op_type = op["type"]
        mail_id = op["mail_id"]
        try:
            if op_type == "archive":
                ok = await asyncio.to_thread(agent.archive, mail_id)
                msg = "✅ Mail archiviert." if ok else "❌ Archivieren fehlgeschlagen."
            elif op_type == "delete":
                ok = await asyncio.to_thread(agent.delete, mail_id)
                msg = "✅ Mail gelöscht." if ok else "❌ Löschen fehlgeschlagen."
            elif op_type == "move":
                folder_name = op.get("destination_folder", "")
                folder = await asyncio.to_thread(agent.find_folder_by_name, folder_name)
                if folder is None:
                    await query.edit_message_text(
                        f"❌ Ordner '{folder_name}' nicht gefunden."
                    )
                    return
                ok = await asyncio.to_thread(agent.move, mail_id, folder.id)
                msg = (
                    f"✅ Mail verschoben nach '{folder_name}'."
                    if ok
                    else "❌ Verschieben fehlgeschlagen."
                )
            elif op_type == "reply":
                comment = op.get("reply_text", "")
                ok = await asyncio.to_thread(agent.reply, mail_id, comment)
                msg = "✅ Antwort gesendet." if ok else "❌ Antwort fehlgeschlagen."
            elif op_type == "forward":
                to_raw = op.get("forward_to", "")
                to_emails = [e.strip() for e in to_raw.split(",") if "@" in e]
                comment = op.get("forward_text", "")
                ok = await asyncio.to_thread(agent.forward, mail_id, to_emails, comment)
                msg = (
                    f"✅ Mail weitergeleitet an {to_raw}."
                    if ok
                    else "❌ Weiterleiten fehlgeschlagen."
                )
            else:
                msg = "❌ Unbekannte Aktion."
        except Exception as e:
            logger.exception("mail:action:confirm fehlgeschlagen")
            msg = f"❌ Fehler: {e}"
        await query.edit_message_text(msg)

    elif data == "mail:action:cancel":
        chat_id = query.message.chat_id
        app_state.pending_mail_ops.pop(chat_id, None)
        app_state.last_mail_search.pop(chat_id, None)
        await query.edit_message_text("❌ Abgebrochen.")

    elif data.startswith("mail:select:"):
        chat_id = query.message.chat_id
        entry = app_state.last_mail_search.get(chat_id)
        if entry is None or (time.time() - entry["timestamp"]) > 180:
            app_state.last_mail_search.pop(chat_id, None)
            await query.edit_message_text("⏱️ Auswahl abgelaufen — bitte nochmal.")
            return
        try:
            idx = int(data.split(":")[-1])
            mails = entry["mails"]
            if idx >= len(mails):
                await query.edit_message_text("❌ Ungültige Auswahl.")
                return
        except (ValueError, IndexError):
            await query.edit_message_text("❌ Ungültige Auswahl.")
            return
        mail = mails[idx]
        mode = entry["mode"]
        params = entry["params"]
        app_state.last_mail_search.pop(chat_id, None)
        await query.edit_message_reply_markup(reply_markup=None)
        await _show_mail_action_confirm(chat_id, mail, mode, params)

    elif data == "cal:action:confirm":
        chat_id = query.message.chat_id
        op = app_state.pending_calendar_ops.pop(chat_id, None)
        if op is None:
            await query.edit_message_text("⚠️ Keine ausstehende Aktion gefunden.")
            return
        if app_state._pending_op_expired(op):
            await query.edit_message_text("⏱️ Abgelaufen — bitte nochmal.")
            return
        try:
            if op["type"] == "create":
                await asyncio.to_thread(
                    calendar_agent.create_event,
                    op["title"],
                    op["start"],
                    op["end"],
                )
                msg = (
                    f"✅ Termin erstellt: *{_md_safe(op['title'])}*\n"
                    f"{op['start'].strftime('%d.%m.%Y %H:%M')} – "
                    f"{op['end'].strftime('%H:%M')}"
                )
            elif op["type"] == "update":
                await asyncio.to_thread(
                    calendar_agent.update_event,
                    op["event_id"],
                    op["new_start"],
                    op["new_end"],
                    op["new_title"],
                    op["new_location"],
                )
                msg = f"✅ Termin geändert: *{_md_safe(op['title'])}*"
            elif op["type"] == "delete":
                await asyncio.to_thread(calendar_agent.delete_event, op["event_id"])
                msg = f"✅ Termin abgesagt: *{_md_safe(op['title'])}*"
            else:
                msg = "❌ Unbekannte Aktion."
            await query.edit_message_text(msg, parse_mode="Markdown")
        except Exception as e:
            logger.exception("cal:action:confirm fehlgeschlagen")
            await query.edit_message_text(f"❌ Aktion fehlgeschlagen: {e}")

    elif data == "cal:action:cancel":
        chat_id = query.message.chat_id
        app_state.pending_calendar_ops.pop(chat_id, None)
        app_state.last_calendar_search.pop(chat_id, None)
        await query.edit_message_text("❌ Abgebrochen.")

    elif data.startswith("cal:select:"):
        chat_id = query.message.chat_id
        entry = app_state.last_calendar_search.get(chat_id)
        if entry is None or (time.time() - entry["timestamp"]) > 180:
            app_state.last_calendar_search.pop(chat_id, None)
            await query.edit_message_text("⏱️ Auswahl abgelaufen — bitte nochmal.")
            return
        try:
            idx = int(data.split(":")[-1])
            events = entry["events"]
            if idx >= len(events):
                await query.edit_message_text("❌ Ungültige Auswahl.")
                return
        except (ValueError, IndexError):
            await query.edit_message_text("❌ Ungültige Auswahl.")
            return
        event = events[idx]
        mode = entry["mode"]
        params = entry["params"]
        app_state.last_calendar_search.pop(chat_id, None)
        await query.edit_message_reply_markup(reply_markup=None)
        await _show_calendar_action_confirm(chat_id, event, mode, params)
