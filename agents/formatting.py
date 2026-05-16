"""Pure formatting helpers — no I/O, no state, no side-effects."""

from calendar_agent import BERLIN

_WEEKDAYS_DE = [
    "Montag",
    "Dienstag",
    "Mittwoch",
    "Donnerstag",
    "Freitag",
    "Samstag",
    "Sonntag",
]


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
        time_part = (
            "ganztägig"
            if getattr(ev, "all_day", False)
            else f"um {ev.start.strftime('%H:%M')}"
        )
        line = f"Nächster Termin: {_fmt_date(ev.start)} {time_part} — {ev.title}"
        if ev.location:
            line += f" ({ev.location})"
        return line

    if not events:
        label = {"today": "heute", "tomorrow": "morgen", "week": "diese Woche"}.get(
            kind, ""
        )
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
            f"{unread_marker}{attach_marker}*{sender_clean}* — {time_str}\n  {subject}"
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


def _md_safe(s) -> str:
    """Strip Markdown-V1 control chars from user text before interpolation."""
    return (s or "").replace("*", "").replace("_", "").replace("`", "")
