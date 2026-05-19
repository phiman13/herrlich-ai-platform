"""calendar-Tool — Termine lesen und schreiben.

Read-Aktionen laufen sofort via asyncio.to_thread. Write-Aktionen (create/
update/delete) werden via app_state.stage_agent_action vorgemerkt und erst
nach Philipps Bestätigung durch execute_write ausgeführt.
"""

import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from claude_agent_sdk import tool

import app_state
from calendar_agent import CalendarAgent

BERLIN = ZoneInfo("Europe/Berlin")

_WRITE_ACTIONS = {"create", "update", "delete"}


def _parse_iso(s) -> datetime | None:
    """ISO-String → timezone-aware Berlin-datetime. None wenn leer/None."""
    if not s:
        return None
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=BERLIN)
    return dt


def _label(action: str, params: dict) -> str:
    title = (params.get("title") or "")[:60]
    if action == "create":
        start = (params.get("start_iso") or "")[:16].replace("T", " ")
        return f"Termin '{title}' anlegen ({start})"
    if action == "update":
        return f"Termin '{title}' ändern"
    if action == "delete":
        return f"Termin '{title}' absagen"
    return action


def _missing_fields(action: str, params: dict) -> str:
    required = {
        "create": ("title", "start_iso"),
        "update": ("event_id", "title"),
        "delete": ("event_id", "title"),
    }[action]
    return ", ".join(f for f in required if not params.get(f))


def _format_events(events) -> str:
    if not events:
        return "Keine Termine gefunden."
    parts = [f"📅 {len(events)} Termin(e):\n"]
    for ev in events:
        start = ev.start.strftime("%d.%m.%Y %H:%M")
        end = ev.end.strftime("%H:%M")
        location = f" ({ev.location})" if ev.location else ""
        parts.append(f"ID: {ev.id}\n{start}–{end} — {ev.title}{location}")
    return "\n\n".join(parts)


def _text(msg: str) -> dict:
    return {"content": [{"type": "text", "text": msg}]}


def make_calendar_tool(chat_id: int):
    """Baut das calendar-Tool für einen Lauf."""

    @tool(
        "calendar",
        "Outlook-Kalender lesen und schreiben. "
        "action='list' (start_iso, end_iso): Termine in einem Zeitfenster — gibt IDs zurück. "
        "action='search' (query, start_iso, end_iso): Termine nach Stichwort suchen. "
        "action='get_next': Nächster anstehender Termin. "
        "action='create' (title, start_iso, end_iso optional, location optional): "
        "Termin anlegen (end_iso-Default: start + 1 Stunde). "
        "action='update' (event_id, title, new_title optional, new_start_iso optional, "
        "new_end_iso optional, new_location optional): Termin ändern. "
        "action='delete' (event_id, title): Termin absagen. "
        "Alle start/end-Parameter als ISO 8601 (z.B. '2026-05-20T10:00:00'). "
        "title bei update/delete ist der aktuelle Titel (nur für den Confirm-Dialog). "
        "Write-Aktionen werden vorgemerkt und erst nach Philipps Bestätigung ausgeführt "
        "— sag ihm, was du vorbereitet hast.",
        {
            "action": str,
            "query": str,
            "start_iso": str,
            "end_iso": str,
            "event_id": str,
            "title": str,
            "location": str,
            "new_title": str,
            "new_start_iso": str,
            "new_end_iso": str,
            "new_location": str,
        },
    )
    async def calendar_tool(args: dict) -> dict:
        action = (args.get("action") or "").strip()
        agent = CalendarAgent()

        if action == "list":
            start = _parse_iso(args.get("start_iso"))
            end = _parse_iso(args.get("end_iso"))
            if not start or not end:
                return _text("FEHLER: action='list' braucht: start_iso, end_iso.")
            events = await asyncio.to_thread(agent.get_events, start, end)
            return _text(_format_events(events))

        if action == "search":
            query = (args.get("query") or "").strip()
            start = _parse_iso(args.get("start_iso"))
            end = _parse_iso(args.get("end_iso"))
            if not query or not start or not end:
                return _text(
                    "FEHLER: action='search' braucht: query, start_iso, end_iso."
                )
            events = await asyncio.to_thread(agent.search_events, query, start, end)
            return _text(_format_events(events))

        if action == "get_next":
            event = await asyncio.to_thread(agent.get_next_event)
            if event is None:
                return _text("Kein kommender Termin gefunden.")
            start = event.start.strftime("%d.%m.%Y %H:%M")
            end = event.end.strftime("%H:%M")
            location = f" ({event.location})" if event.location else ""
            return _text(f"ID: {event.id}\n{start}–{end} — {event.title}{location}")

        if action not in _WRITE_ACTIONS:
            return _text(
                f"FEHLER: Unbekannte action '{action}'. Erlaubt: list, search, "
                "get_next, create, update, delete."
            )

        params = {
            "title": (args.get("title") or "").strip(),
            "start_iso": (args.get("start_iso") or "").strip(),
            "end_iso": (args.get("end_iso") or "").strip() or None,
            "location": (args.get("location") or "").strip() or None,
            "event_id": (args.get("event_id") or "").strip(),
            "new_title": (args.get("new_title") or "").strip() or None,
            "new_start_iso": (args.get("new_start_iso") or "").strip() or None,
            "new_end_iso": (args.get("new_end_iso") or "").strip() or None,
            "new_location": (args.get("new_location") or "").strip() or None,
        }
        missing = _missing_fields(action, params)
        if missing:
            return _text(f"FEHLER: action='{action}' braucht: {missing}.")

        # Validate update action: must have at least one change field
        if action == "update":
            has_change = any(
                params.get(f)
                for f in ("new_title", "new_start_iso", "new_end_iso", "new_location")
            )
            if not has_change:
                return _text(
                    "FEHLER: action='update' braucht mindestens ein neues Feld (new_title, new_start_iso, new_end_iso oder new_location)."
                )
        label = _label(action, params)
        app_state.stage_agent_action(chat_id, "calendar", action, label, params)
        return _text(
            f"✅ Vorgemerkt: {label}. Wird nach Philipps Bestätigung ausgeführt "
            "— du musst nicht warten."
        )

    return calendar_tool


async def execute_write(action: str, params: dict) -> str:
    """Eine vorgemerkte calendar-Schreibaktion ausführen."""
    agent = CalendarAgent()

    if action == "create":
        start = _parse_iso(params["start_iso"])
        end = _parse_iso(params.get("end_iso")) or (start + timedelta(hours=1))
        try:
            await asyncio.to_thread(agent.create_event, params["title"], start, end)
            return f"✅ Termin '{params['title']}' angelegt ({start.strftime('%d.%m.%Y %H:%M')})."
        except Exception as e:
            return f"❌ Termin konnte nicht angelegt werden: {e}"

    if action == "update":
        new_start = _parse_iso(params.get("new_start_iso"))
        new_end = _parse_iso(params.get("new_end_iso"))
        try:
            await asyncio.to_thread(
                agent.update_event,
                params["event_id"],
                new_start,
                new_end,
                params.get("new_title"),
                params.get("new_location"),
            )
            return f"✅ Termin '{params['title']}' geändert."
        except Exception as e:
            return f"❌ Termin konnte nicht geändert werden: {e}"

    if action == "delete":
        try:
            await asyncio.to_thread(agent.delete_event, params["event_id"])
            return f"✅ Termin '{params['title']}' abgesagt."
        except Exception as e:
            return f"❌ Termin konnte nicht abgesagt werden: {e}"

    return f"❌ Unbekannte calendar-Aktion '{action}'."
