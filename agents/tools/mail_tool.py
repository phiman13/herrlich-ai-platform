"""mail-Tool — Mails suchen, lesen und schreiben.

Read-Aktionen (search/list_unread/list_inbox/list_folders/get_body) laufen
sofort. Write-Aktionen werden via app_state.stage_agent_action vorgemerkt
und erst nach Philipps Bestätigung durch execute_write ausgeführt.
"""

import asyncio

from claude_agent_sdk import tool

import app_state
from mail_agent import MailAgent

_WRITE_ACTIONS = {
    "compose",
    "reply",
    "forward",
    "archive",
    "move",
    "delete",
    "mark_read",
    "mark_unread",
}


def _label(action: str, params: dict) -> str:
    subj = (params.get("subject") or "")[:60]
    to = params.get("to_email", "")
    dest = params.get("destination_folder", "?")
    if action == "compose":
        return f"Mail an '{to}' senden: {subj}"
    if action == "reply":
        return f"Auf Mail '{subj}' antworten"
    if action == "forward":
        return f"Mail '{subj}' weiterleiten an '{to}'"
    if action == "archive":
        return f"Mail '{subj}' archivieren"
    if action == "move":
        return f"Mail '{subj}' nach '{dest}' verschieben"
    if action == "delete":
        return f"Mail '{subj}' löschen"
    if action == "mark_read":
        return f"Mail '{subj}' als gelesen markieren"
    if action == "mark_unread":
        return f"Mail '{subj}' als ungelesen markieren"
    return action


def _missing_fields(action: str, params: dict) -> str:
    required = {
        "compose": ("to_email", "subject", "body"),
        "reply": ("mail_id", "comment"),
        "forward": ("mail_id", "to_email"),
        "archive": ("mail_id",),
        "move": ("mail_id", "destination_folder"),
        "delete": ("mail_id",),
        "mark_read": ("mail_id",),
        "mark_unread": ("mail_id",),
    }[action]
    return ", ".join(f for f in required if not params.get(f))


def _format_mails(mails) -> str:
    if not mails:
        return "Keine Mails gefunden."
    from zoneinfo import ZoneInfo

    berlin = ZoneInfo("Europe/Berlin")
    parts = [f"📬 {len(mails)} Mail(s):\n"]
    for m in mails:
        unread = "🔵 " if not m.is_read else ""
        date_str = m.received.astimezone(berlin).strftime("%d.%m. %H:%M")
        sender = (m.sender_name or m.sender_email or "?")[:40]
        parts.append(
            f"{unread}ID: {m.id}\n"
            f"Von: {sender} | {date_str}\n"
            f"Betreff: {m.subject[:80]}\n"
            f"Vorschau: {m.preview[:120]}"
        )
    return "\n\n".join(parts)


def _text(msg: str) -> dict:
    return {"content": [{"type": "text", "text": msg}]}


def make_mail_tool(chat_id: int):
    """Baut das mail-Tool für einen Lauf — chat_id für das Vormerken."""

    @tool(
        "mail",
        "E-Mails suchen, lesen und schreiben. "
        "action='search' (query, count=20): Mails suchen — Ergebnis enthält IDs. "
        "action='list_unread' (count=20, folder_name optional): Ungelesene Mails. "
        "action='list_inbox' (count=10): Neueste Inbox-Mails. "
        "action='list_folders': Alle Mail-Ordner. "
        "action='get_body' (mail_id): Volltext einer Mail. "
        "action='compose' (to_email, subject, body): Neue Mail senden. "
        "action='reply' (mail_id, comment, subject): Mail beantworten. "
        "action='forward' (mail_id, to_email, comment, subject): Weiterleiten. "
        "action='archive' (mail_id, subject): Archivieren. "
        "action='move' (mail_id, destination_folder, subject): Verschieben. "
        "action='delete' (mail_id, subject): Löschen. "
        "action='mark_read' (mail_id, subject): Als gelesen markieren. "
        "action='mark_unread' (mail_id, subject): Als ungelesen markieren. "
        "Bei Write-Aktionen: subject = Mail-Betreff (nur für den Confirm-Dialog). "
        "Write-Aktionen werden vorgemerkt und erst nach Philipps Bestätigung "
        "ausgeführt — sag ihm, was du vorbereitet hast.",
        {
            "action": str,
            "query": str,
            "count": int,
            "folder_name": str,
            "mail_id": str,
            "to_email": str,
            "subject": str,
            "body": str,
            "comment": str,
            "destination_folder": str,
        },
    )
    async def mail_tool(args: dict) -> dict:
        action = (args.get("action") or "").strip()

        if action == "search":
            query = (args.get("query") or "").strip()
            if not query:
                return _text("FEHLER: action='search' braucht: query.")
            count = int(args.get("count") or 20)
            agent = MailAgent()
            mails = await asyncio.to_thread(agent.smart_search, query, count)
            return _text(_format_mails(mails))

        if action == "list_unread":
            count = int(args.get("count") or 20)
            folder_name = (args.get("folder_name") or "").strip() or None
            agent = MailAgent()
            if folder_name:
                folder = await asyncio.to_thread(agent.find_folder_by_name, folder_name)
                if folder is None:
                    return _text(f"FEHLER: Ordner '{folder_name}' nicht gefunden.")
                mails = await asyncio.to_thread(agent.get_unread, count, folder.id)
            else:
                mails = await asyncio.to_thread(agent.get_inbox_unread, count)
            return _text(_format_mails(mails))

        if action == "list_inbox":
            count = int(args.get("count") or 10)
            agent = MailAgent()
            mails = await asyncio.to_thread(agent.quick_scan, count)
            return _text(_format_mails(mails))

        if action == "list_folders":
            agent = MailAgent()
            folders = await asyncio.to_thread(agent.list_folders)
            if not folders:
                return _text("Keine Ordner gefunden.")
            lines = ["📁 Mail-Ordner:\n"]
            for f in folders:
                unread = f" ({f.unread_count} ungelesen)" if f.unread_count else ""
                lines.append(f"• {f.name}{unread}")
            return _text("\n".join(lines))

        if action == "get_body":
            mail_id = (args.get("mail_id") or "").strip()
            if not mail_id:
                return _text("FEHLER: action='get_body' braucht: mail_id.")
            agent = MailAgent()
            data = await asyncio.to_thread(agent.get_mail_body, mail_id)
            text = (
                f"Von: {data['sender_name']} <{data['sender_email']}>\n"
                f"Betreff: {data['subject']}\n"
                f"Datum: {data['received']}\n\n"
                f"{data['body_text']}"
            )
            return _text(text)

        if action not in _WRITE_ACTIONS:
            return _text(
                f"FEHLER: Unbekannte action '{action}'. Erlaubt: search, "
                "list_unread, list_inbox, list_folders, get_body, compose, reply, "
                "forward, archive, move, delete, mark_read, mark_unread."
            )

        params = {
            "mail_id": (args.get("mail_id") or "").strip(),
            "to_email": (args.get("to_email") or "").strip(),
            "subject": (args.get("subject") or "").strip(),
            "body": (args.get("body") or "").strip(),
            "comment": (args.get("comment") or "").strip(),
            "destination_folder": (args.get("destination_folder") or "").strip(),
        }
        missing = _missing_fields(action, params)
        if missing:
            return _text(f"FEHLER: action='{action}' braucht: {missing}.")
        label = _label(action, params)
        app_state.stage_agent_action(chat_id, "mail", action, label, params)
        return _text(
            f"✅ Vorgemerkt: {label}. Wird nach Philipps Bestätigung ausgeführt "
            "— du musst nicht warten."
        )

    return mail_tool


async def execute_write(action: str, params: dict) -> str:
    """Eine vorgemerkte mail-Schreibaktion ausführen."""
    agent = MailAgent()

    if action == "compose":
        ok = await asyncio.to_thread(
            agent.send_mail, params["to_email"], params["subject"], params["body"]
        )
        return (
            f"✅ Mail an '{params['to_email']}' gesendet."
            if ok
            else f"❌ Mail an '{params['to_email']}' konnte nicht gesendet werden."
        )

    if action == "reply":
        ok = await asyncio.to_thread(agent.reply, params["mail_id"], params["comment"])
        return "✅ Antwort gesendet." if ok else "❌ Antwort fehlgeschlagen."

    if action == "forward":
        to_emails = [e.strip() for e in params["to_email"].split(",") if "@" in e]
        if not to_emails:
            return f"❌ Keine gültige E-Mail-Adresse in '{params['to_email']}'."
        comment = params.get("comment", "")
        ok = await asyncio.to_thread(
            agent.forward, params["mail_id"], to_emails, comment
        )
        return (
            f"✅ Mail weitergeleitet an '{params['to_email']}'."
            if ok
            else "❌ Weiterleiten fehlgeschlagen."
        )

    if action == "archive":
        ok = await asyncio.to_thread(agent.archive, params["mail_id"])
        return "✅ Mail archiviert." if ok else "❌ Archivieren fehlgeschlagen."

    if action == "move":
        folder = await asyncio.to_thread(
            agent.find_folder_by_name, params["destination_folder"]
        )
        if folder is None:
            return f"❌ Ordner '{params['destination_folder']}' nicht gefunden."
        ok = await asyncio.to_thread(agent.move, params["mail_id"], folder.id)
        return (
            f"✅ Mail nach '{params['destination_folder']}' verschoben."
            if ok
            else "❌ Verschieben fehlgeschlagen."
        )

    if action == "delete":
        ok = await asyncio.to_thread(agent.delete, params["mail_id"])
        return "✅ Mail gelöscht." if ok else "❌ Löschen fehlgeschlagen."

    if action == "mark_read":
        ok = await asyncio.to_thread(agent.mark_read, params["mail_id"], True)
        return "✅ Als gelesen markiert." if ok else "❌ Fehlgeschlagen."

    if action == "mark_unread":
        ok = await asyncio.to_thread(agent.mark_read, params["mail_id"], False)
        return "✅ Als ungelesen markiert." if ok else "❌ Fehlgeschlagen."

    return f"❌ Unbekannte mail-Aktion '{action}'."
