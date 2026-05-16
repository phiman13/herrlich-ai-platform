"""Calendar intent handlers — read, create, update, delete events."""

import logging
import asyncio
import time
import re
from datetime import datetime, timedelta
from telegram import Bot
from calendar_agent import CalendarAgent, BERLIN
import app_state
from formatting import format_calendar_response, _md_safe

logger = logging.getLogger("jarvis.calendar_handler")

calendar_agent = CalendarAgent()


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


async def handle_calendar(
    chat_id,
    text,
    kind=None,
    start=None,
    end=None,
    mode="read",
    title=None,
):
    bot = Bot(token=app_state.TELEGRAM_TOKEN)

    if mode == "write":
        if not title or not start:
            await bot.send_message(
                chat_id=chat_id, text="Bitte Titel und Startzeit angeben."
            )
            return
        if end is None:
            end = start + timedelta(hours=1)
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        app_state.pending_calendar_ops[chat_id] = {
            "type": "create",
            "title": title,
            "start": start,
            "end": end,
            "staged_at": time.time(),
        }
        keyboard = [
            [
                InlineKeyboardButton(
                    "✅ Erstellen", callback_data="cal:action:confirm"
                ),
                InlineKeyboardButton("❌ Abbrechen", callback_data="cal:action:cancel"),
            ]
        ]
        await bot.send_message(
            chat_id=chat_id,
            text=(
                f"📅 *Termin erstellen?*\n\n*{title}*\n"
                f"{start.strftime('%d.%m.%Y %H:%M')} – {end.strftime('%H:%M')}"
            ),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
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


async def handle_calendar_modify(chat_id, mode, params):
    """Find a target event from a description, then show an update/delete confirm."""
    bot = Bot(token=app_state.TELEGRAM_TOKEN)
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    query = params.get("query")
    if not query:
        await bot.send_message(
            chat_id=chat_id,
            text="Welchen Termin meinst du? Bitte mit einem Stichwort beschreiben.",
        )
        return

    if mode == "update" and not any(
        params.get(k) for k in ("new_start", "new_end", "new_title", "new_location")
    ):
        await bot.send_message(
            chat_id=chat_id, text="Was soll an dem Termin geändert werden?"
        )
        return

    now = datetime.now(BERLIN)
    search_start_str = params.get("search_start")
    search_end_str = params.get("search_end")
    search_start = datetime.fromisoformat(search_start_str) if search_start_str else now
    search_end = (
        datetime.fromisoformat(search_end_str)
        if search_end_str
        else now + timedelta(days=30)
    )

    events = await asyncio.to_thread(
        calendar_agent.search_events, query, search_start, search_end
    )
    if not events:
        await bot.send_message(
            chat_id=chat_id, text=f"Keinen Termin gefunden, der zu '{query}' passt."
        )
        return
    if len(events) > 5:
        await bot.send_message(
            chat_id=chat_id,
            text=f"Mehr als 5 Treffer für '{query}' — bitte präziser beschreiben.",
        )
        return
    if len(events) == 1:
        await _show_calendar_action_confirm(chat_id, events[0], mode, params)
        return

    app_state.last_calendar_search[chat_id] = {
        "events": events,
        "mode": mode,
        "params": params,
        "timestamp": time.time(),
    }
    keyboard = [
        [
            InlineKeyboardButton(
                f"{i + 1}. {ev.title} ({ev.start.strftime('%d.%m. %H:%M')})",
                callback_data=f"cal:select:{i}",
            )
        ]
        for i, ev in enumerate(events)
    ]
    await bot.send_message(
        chat_id=chat_id,
        text=f"Mehrere Termine passen zu '{query}' — welchen meinst du?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def _show_calendar_action_confirm(chat_id, event, mode, params):
    """Stage an update/delete op in app_state.pending_calendar_ops and send the confirm dialog."""
    bot = Bot(token=app_state.TELEGRAM_TOKEN)
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    recurring_note = (
        "\n_(nur dieser Termin — die Serie bleibt)_" if event.recurring else ""
    )
    title_safe = _md_safe(event.title)

    if mode == "delete":
        app_state.pending_calendar_ops[chat_id] = {
            "type": "delete",
            "event_id": event.id,
            "title": event.title,
            "staged_at": time.time(),
        }
        text = (
            f"🗑️ *Termin absagen?*\n\n*{title_safe}*\n"
            f"{event.start.strftime('%d.%m.%Y %H:%M')} – "
            f"{event.end.strftime('%H:%M')}{recurring_note}"
        )
        confirm_label = "✅ Absagen"
    else:  # update
        new_start_str = params.get("new_start")
        new_end_str = params.get("new_end")
        new_start = datetime.fromisoformat(new_start_str) if new_start_str else None
        new_end = datetime.fromisoformat(new_end_str) if new_end_str else None
        new_title = params.get("new_title")
        new_location = params.get("new_location")
        if new_start and not new_end:
            new_end = new_start + (event.end - event.start)

        app_state.pending_calendar_ops[chat_id] = {
            "type": "update",
            "event_id": event.id,
            "title": new_title or event.title,
            "new_start": new_start,
            "new_end": new_end,
            "new_title": new_title,
            "new_location": new_location,
            "staged_at": time.time(),
        }
        lines = [f"📅 *Termin ändern?*\n\n*{title_safe}*"]
        if new_start:
            lines.append(
                f"Zeit: {event.start.strftime('%d.%m. %H:%M')}–"
                f"{event.end.strftime('%H:%M')} → "
                f"{new_start.strftime('%d.%m. %H:%M')}–{new_end.strftime('%H:%M')}"
            )
        if new_title:
            lines.append(f"Titel: {title_safe} → {_md_safe(new_title)}")
        if new_location:
            lines.append(
                f"Ort: {_md_safe(event.location) or '—'} → {_md_safe(new_location)}"
            )
        text = "\n".join(lines) + recurring_note
        confirm_label = "✅ Ändern"

    keyboard = [
        [
            InlineKeyboardButton(confirm_label, callback_data="cal:action:confirm"),
            InlineKeyboardButton("❌ Abbrechen", callback_data="cal:action:cancel"),
        ]
    ]
    await bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def handle_calendar_intent(chat_id: int, text: str, params: dict) -> None:
    from dispatch import _conv_complete

    mode = params.get("mode", "read")
    if mode in ("update", "delete"):
        await handle_calendar_modify(chat_id, mode, params)
        _conv_complete(chat_id, f"Termin-Aktion ({mode}) angefragt")
        return
    kind = params.get("kind")
    start_str = params.get("start")
    end_str = params.get("end")
    start = datetime.fromisoformat(start_str) if start_str else None
    end = datetime.fromisoformat(end_str) if end_str else None
    title = params.get("title")
    await handle_calendar(
        chat_id=chat_id,
        text=text,
        kind=kind,
        start=start,
        end=end,
        mode=mode,
        title=title,
    )
    cal_summary = (
        f"Termin-Erstellung angefragt: {title}"
        if mode == "write" and title
        else "Kalender angezeigt"
    )
    _conv_complete(chat_id, cal_summary)
