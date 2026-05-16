"""Mail intent handlers — read, search, compose, write-actions."""

import asyncio
import logging
import time
from datetime import datetime

from telegram import Bot

import app_state
from calendar_agent import BERLIN
from formatting import format_mail_list, format_folder_list

logger = logging.getLogger("jarvis.mail_handler")

_WRITE_MODES = {
    "mark_read",
    "mark_unread",
    "archive",
    "move",
    "delete",
    "reply",
    "forward",
}


async def handle_mail(chat_id, text, params):
    bot = Bot(token=app_state.TELEGRAM_TOKEN)
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

        app_state.pending_mail_ops[chat_id] = {
            "type": "compose",
            "to_email": to_email,
            "subject": subject,
            "body": body,
            "staged_at": time.time(),
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

    if mode in _WRITE_MODES:
        await _handle_mail_write(chat_id, mode, params)
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


async def _handle_mail_write(chat_id: int, mode: str, params: dict) -> None:
    bot = Bot(token=app_state.TELEGRAM_TOKEN)
    from mail_agent import MailAgent

    mail_query = (
        params.get("mail_query")
        or params.get("sender")
        or params.get("subject_contains")
        or ""
    )
    if not mail_query:
        await bot.send_message(
            chat_id=chat_id,
            text="Welche Mail meinst du? Bitte beschreibe sie genauer (z.B. 'letzte Mail von X').",
        )
        return

    agent = MailAgent()
    try:
        mails = await asyncio.to_thread(agent.smart_search, mail_query, 50)
    except Exception as e:
        logger.exception("_handle_mail_write: smart_search fehlgeschlagen")
        await bot.send_message(chat_id=chat_id, text=f"❌ Suche fehlgeschlagen: {e}")
        return

    if not mails:
        await bot.send_message(
            chat_id=chat_id,
            text=f"Keine passende Mail gefunden für '{mail_query}'.",
        )
        return

    if len(mails) > 5:
        await bot.send_message(
            chat_id=chat_id,
            text="Zu viele Treffer — bitte genauer beschreiben (Absender, Betreff oder Datum nennen).",
        )
        return

    if len(mails) == 1:
        await _show_mail_action_confirm(chat_id, mails[0], mode, params)
        return

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    lines = ["🔍 *Welche Mail?*\n"]
    keyboard = []
    for i, m in enumerate(mails):
        date_str = m.received.astimezone(BERLIN).strftime("%d.%m %H:%M")
        sender = (m.sender_name or m.sender_email or "?")[:30]
        subject = m.subject[:60]
        lines.append(f"{i + 1}. *{sender}* — {date_str}\n   _{subject}_")
        keyboard.append(
            [InlineKeyboardButton(str(i + 1), callback_data=f"mail:select:{i}")]
        )

    app_state.last_mail_search[chat_id] = {
        "mails": mails,
        "mode": mode,
        "params": params,
        "timestamp": time.time(),
    }
    await bot.send_message(
        chat_id=chat_id,
        text="\n\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def _show_mail_action_confirm(
    chat_id: int, mail, mode: str, params: dict
) -> None:
    bot = Bot(token=app_state.TELEGRAM_TOKEN)
    from mail_agent import MailAgent
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    date_str = mail.received.astimezone(BERLIN).strftime("%d.%m.%Y %H:%M")
    sender = mail.sender_name or mail.sender_email or "?"
    subject_clean = mail.subject.replace("*", "").replace("_", "")[:80]

    if mode == "mark_read":
        agent = MailAgent()
        ok = await asyncio.to_thread(agent.mark_read, mail.id, True)
        await bot.send_message(
            chat_id=chat_id,
            text="✅ Als gelesen markiert." if ok else "❌ Fehlgeschlagen.",
        )
        return

    if mode == "mark_unread":
        agent = MailAgent()
        ok = await asyncio.to_thread(agent.mark_read, mail.id, False)
        await bot.send_message(
            chat_id=chat_id,
            text="✅ Als ungelesen markiert." if ok else "❌ Fehlgeschlagen.",
        )
        return

    action_labels = {
        "archive": "📦 Archivieren?",
        "move": "📁 Verschieben?",
        "delete": "🗑️ Löschen?",
        "reply": "↩️ Antworten?",
        "forward": "↪️ Weiterleiten?",
    }
    confirm_labels = {
        "archive": "✅ Archivieren",
        "move": "✅ Verschieben",
        "delete": "✅ Löschen",
        "reply": "✅ Senden",
        "forward": "✅ Senden",
    }
    title = action_labels.get(mode, "❓ Ausführen?")
    confirm_label = confirm_labels.get(mode, "✅ Ja")

    body_preview = ""
    if mode in ("reply", "forward"):
        try:
            agent = MailAgent()
            full = await asyncio.to_thread(agent.get_mail_body, mail.id)
            if full.get("body_text"):
                body_preview = f"\n\n📄 _{full['body_text'][:200]}_"
        except Exception:
            pass

    if mode == "reply":
        reply_text = params.get("reply_text", "")
        text = (
            f"↩️ *Antwort auf:*\nVon: {sender}\nBetreff: {subject_clean}\nDatum: {date_str}"
            f"{body_preview}\n\n*Deine Antwort:*\n_{reply_text}_"
        )
    elif mode == "forward":
        forward_to = params.get("forward_to", "")
        forward_text = params.get("forward_text", "")
        text = (
            f"↪️ *Weiterleiten an:* {forward_to}\nBetreff: {subject_clean}\nVon: {sender}"
            f"{body_preview}" + (f"\n\n_{forward_text}_" if forward_text else "")
        )
    elif mode == "move":
        dest = params.get("destination_folder", "?")
        text = f"📁 *Verschieben nach '{dest}'?*\n\nVon: {sender}\nBetreff: {subject_clean}\nDatum: {date_str}"
    else:
        text = f"{title}\n\nVon: {sender}\nBetreff: {subject_clean}\nDatum: {date_str}"

    app_state.pending_mail_ops[chat_id] = {
        "type": mode,
        "mail_id": mail.id,
        "subject": mail.subject,
        "sender": sender,
        "staged_at": time.time(),
        **{
            k: params[k]
            for k in ("reply_text", "forward_to", "forward_text", "destination_folder")
            if k in params
        },
    }

    keyboard = [
        [
            InlineKeyboardButton(confirm_label, callback_data="mail:action:confirm"),
            InlineKeyboardButton("❌ Abbrechen", callback_data="mail:action:cancel"),
        ]
    ]
    await bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def handle_mail_intent(chat_id: int, text: str, params: dict) -> None:
    from dispatch import _conv_complete

    await handle_mail(chat_id=chat_id, text=text, params=params)
    mail_mode = params.get("mode", "")
    _conv_complete(chat_id, f"Mail {mail_mode} ausgeführt")
