import json
import logging
import asyncio
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import anthropic
import httpx

BERLIN = ZoneInfo("Europe/Berlin")

try:
    from agents.vps import list_projects as _list_projects
except ImportError:
    from vps import list_projects as _list_projects

logger = logging.getLogger("jarvis")
_claude = anthropic.Anthropic()

_project_list_cache: list[str] = []

# Context cache: (value, fetched_at_timestamp)
_todo_lists_cache: tuple[list[str], float] = ([], 0.0)
_TODO_CACHE_TTL = 1800  # 30 min

# calendar names come from env — no network call needed
_calendar_names_cache: list[str] = []

# mail folder names cache: (value, fetched_at)
_mail_folders_cache: tuple[list[str], float] = ([], 0.0)
_MAIL_FOLDER_CACHE_TTL = 1800  # 30 min


async def _get_project_list() -> list[str]:
    global _project_list_cache
    if not _project_list_cache:
        _project_list_cache = await _list_projects()
    return _project_list_cache


async def _get_todo_list_names() -> list[str]:
    global _todo_lists_cache
    names, fetched_at = _todo_lists_cache
    if names and (time.time() - fetched_at) < _TODO_CACHE_TTL:
        return names
    try:

        def _fetch():
            try:
                from microsoft_auth import get_access_token
            except ImportError:
                from agents.microsoft_auth import get_access_token
            token = get_access_token()
            resp = httpx.get(
                "https://graph.microsoft.com/v1.0/me/todo/lists",
                headers={"Authorization": f"Bearer {token}"},
                timeout=5,
            )
            resp.raise_for_status()
            return [lst["displayName"] for lst in resp.json().get("value", [])]

        names = await asyncio.to_thread(_fetch)
        _todo_lists_cache = (names, time.time())
    except Exception as e:
        logger.debug(f"To-Do-Listen nicht abrufbar: {e}")
    return names


async def _get_calendar_names() -> list[str]:
    global _calendar_names_cache
    if not _calendar_names_cache:
        import os as _os

        raw = _os.environ.get("CALENDAR_WHITELIST", "")
        _calendar_names_cache = [w.strip() for w in raw.split(",") if w.strip()]
    return _calendar_names_cache


async def _get_mail_folder_names() -> list[str]:
    global _mail_folders_cache
    names, fetched_at = _mail_folders_cache
    if names and (time.time() - fetched_at) < _MAIL_FOLDER_CACHE_TTL:
        return names
    try:

        def _fetch():
            try:
                from microsoft_auth import get_access_token
            except ImportError:
                from agents.microsoft_auth import get_access_token
            token = get_access_token()
            resp = httpx.get(
                "https://graph.microsoft.com/v1.0/me/mailFolders",
                headers={"Authorization": f"Bearer {token}"},
                params={"$top": 50, "$select": "displayName"},
                timeout=5,
            )
            resp.raise_for_status()
            return [f["displayName"] for f in resp.json().get("value", [])]

        names = await asyncio.to_thread(_fetch)
        _mail_folders_cache = (names, time.time())
    except Exception as e:
        logger.debug(f"Mail-Ordner nicht abrufbar: {e}")
    return names


_SYSTEM_TEMPLATE = """Du bist der Intent-Router von Jarvis, einem persönlichen KI-Assistenten von Philipp. Klassifiziere die User-Nachricht in genau einen der folgenden Intents und extrahiere relevante Parameter. Antworte AUSSCHLIESSLICH mit einem JSON-Objekt, ohne Markdown-Codeblock, ohne erklärenden Text.

## Verfügbare Intents

1. "calendar" — Fragen zum Kalender (Apple Calendar via CalDAV).
   Verfügbare Kalender: {CALENDAR_NAMES}

   Beispiele:
   - "Was habe ich heute?" → mode=read, kind=today
   - "Erstelle Termin Zahnarzt morgen 10 Uhr" → mode=write

   Parameter:
   - mode: "read" | "write"
   - kind: "today" | "tomorrow" | "week" | "next" | "range" | "specific_day" (nur bei mode=read)
   - start: ISO-8601 datetime oder null
   - end: ISO-8601 datetime oder null (bei mode=write und null → start + 1 Stunde)
   - label: deutsche Beschreibung des Zeitfensters (nur bei mode=read)
   - title: string (Termin-Titel, nur bei mode=write)
   - calendar_name: string oder null (Ziel-Kalender, einer aus: {CALENDAR_NAMES}, nur bei mode=write)

   WICHTIG: Heute ist {HEUTE_ISO}. Bei mode=read: Berechne start/end relativ zu diesem Datum, in Europe/Berlin Zeitzone. Bei "today" / "tomorrow" / "week" / "next" können start/end null sein. Bei "range" oder "specific_day" MUSS start/end gesetzt sein. Bei mode=write: start MUSS gesetzt sein. end=null bedeutet start+1h.

2. "coding" — Aufgaben oder Fragen zu Code-Projekten.
   Verfügbare Projekte: {PROJECT_LIST}

   Beispiele:
   - "Backlog von recipe-app?" → query, backlog
   - "Was hat sich zuletzt in immo-radar geändert?" → query, git_log
   - "Fixe den Login-Bug in recipe-app" → action
   - "Füge 'Dark Mode' zum Backlog von recipe-app hinzu" → backlog_write
   - "Schreibe Feature X in immo-radar" → action

   Parameter:
   - project: string (Projektname, einer aus: {PROJECT_LIST}) oder null
   - mode: "query" | "action" | "backlog_write"
   - query_type: "backlog" | "git_log" | "readme" | "claude_md" (nur bei mode=query)
   - backlog_item: string (der neue Eintrag, nur bei mode=backlog_write)
   - backlog_priority: "P1" | "P2" | "P3" (default: "P1", nur bei mode=backlog_write)

3. "research" — Web-Recherche-Anfragen.
   Beispiele: "Recherchiere ESG-Pflichten 2026", "Was sind die aktuellen Entwicklungen bei...", "Suche im Internet nach..."

   Parameter: keine

4. "work" — Strategieberatungs- / PM-Aufgaben (Meeting-Zusammenfassungen, Analysen, Executive Summaries).
   Beispiele: "Fass diese E-Mail-Kette zusammen", "Analysiere den Markt für...", "Erstelle ein Meeting-Protokoll aus..."

   Parameter: keine

5. "mail" — Anfragen zu Outlook-Mails: lesen, suchen und schreiben.
   Verfügbare Ordner: {MAIL_FOLDERS}

   Beispiele:
   - "Was Wichtiges im Posteingang?" → quick_scan
   - "Was hab ich verpasst?" / "Ungelesene Mails" → unread
   - "Hat mir Anna geschrieben?" → search
   - "Mails von letzter Woche zum Thema X" → search
   - "Was steht im Ordner 'Steuern'?" → quick_scan mit folder_name
   - "Welche Ordner gibt es?" → list_folders
   - "Schreibe eine Mail an anna@beispiel.de ..." → compose
   - "Markiere die Mail von Sparkasse als gelesen" → mark_read
   - "Markiere als ungelesen" → mark_unread
   - "Archiviere die letzte Mail von Anna" → archive
   - "Verschiebe die Mail über Rechnung in den Ordner Steuern" → move
   - "Lösche die Mail von Newsletter XY" → delete
   - "Antworte auf die Mail von Anna mit: Passt mir gut" → reply
   - "Leite die Rechnung von Müller weiter an chef@firma.de" → forward

   Parameter:
   - mode: "quick_scan" | "unread" | "search" | "list_folders" | "compose" | "mark_read" | "mark_unread" | "archive" | "move" | "delete" | "reply" | "forward"
   - count: integer oder null (Anzahl Mails, default je nach mode)
   - sender: string oder null (Filter nach Absender, falls genannt)
   - subject_contains: string oder null (Filter nach Betreff)
   - since_iso: ISO-8601 datetime oder null (nur Mails ab diesem Zeitpunkt, relativ zu {HEUTE_ISO})
   - folder_name: string oder null (spezifischer Ordner, einer aus: {MAIL_FOLDERS})
   - to_email: string oder null (Empfänger-Adresse, nur bei mode=compose)
   - subject: string oder null (Betreff, nur bei mode=compose)
   - body: string oder null (Mail-Text auf Deutsch, nur bei mode=compose)
   - mail_query: string oder null (Freitext-Beschreibung der Zielmail, z.B. "letzte Mail von Sparkasse" — MUSS gesetzt sein bei mode=mark_read/unread/archive/move/delete/reply/forward)
   - reply_text: string oder null (Antworttext, nur bei mode=reply)
   - forward_to: string oder null (Empfänger-E-Mail, nur bei mode=forward)
   - forward_text: string oder null (optionaler Begleittext, nur bei mode=forward)
   - destination_folder: string oder null (Zielordner-Name, nur bei mode=move)

   Mode-Bestimmung:
   - "Posteingang" / "Was Neues" / "Aktuelle Mails" → quick_scan
   - "Ungelesene" / "Was hab ich verpasst" / "Was ist neu" → unread
   - "Hat mir X geschrieben" / "Mails von X" / "zum Thema Y" → search
   - "Welche Ordner" / "Liste meiner Ordner" → list_folders
   - Ordnerangaben wie "im Ordner X" setzen folder_name, mode bleibt je nach Hauptfrage
   - "Schreibe/Sende eine Mail an ..." → compose (extrahiere to_email, subject, body aus dem Text)
   - "Als gelesen/ungelesen markieren" → mark_read/mark_unread (mail_query = Beschreibung der Zielmail)
   - "Archivieren / Verschieben / Löschen" → archive/move/delete (mail_query = Beschreibung der Zielmail)
   - "Antworte auf ... mit ..." → reply (mail_query = Zielmail-Beschreibung, reply_text = Antworttext)
   - "Leite ... weiter an ..." → forward (mail_query = Zielmail-Beschreibung, forward_to = Empfänger-E-Mail)
   - Bei Write-Modes: mail_query MUSS gesetzt sein — alles was die Zielmail identifiziert (Absender, Betreff, Zeit)

6. "personal" — Allgemeine Fragen, Smalltalk, alles andere.
   Beispiele: "Wie geht's dir?", "Erklär mir Photosynthese", "Was hältst du von..."

   Parameter: keine

7. "news" — KI-News und Technologie-Neuigkeiten abrufen.
   Beispiele: "Was gibt's Neues in AI?", "Neueste KI-Entwicklungen?", "AI News"

   Parameter: keine

8. "tasks" — MS To Do Tasks lesen oder schreiben.
   Beispiele: "Was steht auf meiner Einkaufsliste?", "Füge Milch zur Einkaufsliste hinzu", "Erledigte Tasks anzeigen", "Zeig mir alle To Do Listen"

   Echte MS To Do Listennamen (verwende diese exakten Namen als list_name): {TODO_LISTS}

   Parameter:
   - mode: "read" | "write" | "complete" | "create_list" | "delete_list" | "rename_list"
   - list_name: string oder null — bei read/write/complete/delete_list/rename_list: MUSS einem der echten Listennamen oben entsprechen; bei create_list: der gewünschte neue Name (frei wählbar)
   - item: string oder null (Task-Text, nur bei mode=write)
   - new_name: string oder null (neuer Listenname, nur bei mode=rename_list)

   Mode-Bestimmung:
   - "Neue Liste anlegen / erstellen" → create_list (list_name = gewünschter Name)
   - "Liste löschen / entfernen" → delete_list
   - "Liste umbenennen / in X umbenennen" → rename_list (list_name = alter Name, new_name = neuer Name)

9. "briefing" — Morning Briefing abrufen: Kalender, Wetter, Mail, News, Tasks, GitHub.
   Beispiele: "Briefing", "Gib mir mein Briefing", "Morning Briefing", "Was liegt heute an?"

   Parameter: keine

10. "memory" — Jarvis-Erinnerungen abrufen oder löschen.
   Beispiele:
   - "Was weißt du über mich?" → mode=list
   - "Was hast du dir gemerkt?" → mode=list
   - "Zeig mir deine Erinnerungen" → mode=list
   - "Vergiss was ich über Siemens gesagt habe" → mode=delete, query="Siemens"
   - "Vergiss das" → mode=delete, query=null (löscht die neueste Erinnerung)

   Parameter:
   - mode: "list" | "delete"
   - query: string oder null (was gelöscht werden soll; null = neueste Erinnerung)

11. "reminder_write" — Apple Reminder / Erinnerung erstellen.
   Beispiele: "Erinnere mich morgen an den Anruf", "Erstelle eine Erinnerung: Paket abholen am Freitag"

   Parameter:
   - title: string (Titel der Erinnerung, Pflichtfeld)
   - due_date: ISO-Datum (YYYY-MM-DD) oder null (falls kein Datum genannt)
   - list_name: string oder null (falls eine bestimmte Reminder-Liste genannt)

12. "weather" — Wetterabfragen für die aktuelle Region (Tutzing / München).
   Beispiele: "Wie wird das Wetter morgen?", "Wetter heute", "Wettervorhersage diese Woche", "Regnet es morgen?", "Wie wird es heute Nachmittag?"

   Parameter:
   - period: "today" | "tomorrow" | "week"
   - time_of_day: "morning" | "noon" | "afternoon" | "evening" | "night" | null (nur wenn explizit genannt)
   - location: string oder null (Stadtname, nur wenn explizit genannt — sonst null für Standardort Tutzing)

## Output-Format

{{
  "intent": "calendar" | "coding" | "research" | "work" | "mail" | "personal" | "news" | "tasks" | "briefing" | "memory" | "reminder_write" | "weather",
  "confidence": 1-10,
  "params": {{ ... intent-spezifische Parameter ... }},
  "reasoning": "kurze Erklärung in einem Satz, warum dieser Intent"
}}

Confidence 10 = absolut sicher, 1 = totale Vermutung. Confidence < 7 zeigt an, dass die Klassifikation unsicher ist.

NIEMALS andere Felder hinzufügen. NIEMALS Markdown verwenden. NIEMALS erklärenden Text vor oder nach dem JSON."""


_FALLBACK = {
    "intent": "personal",
    "confidence": 0,
    "params": {},
    "reasoning": "parse_error",
}


async def _build_system_prompt() -> str:
    heute = datetime.now(BERLIN).strftime("%Y-%m-%d")
    project_list, todo_names, calendar_names, mail_folders = await asyncio.gather(
        _get_project_list(),
        _get_todo_list_names(),
        _get_calendar_names(),
        _get_mail_folder_names(),
    )
    projects_str = ", ".join(project_list) if project_list else "recipe-app"
    todo_str = ", ".join(todo_names) if todo_names else "(nicht verfügbar)"
    calendar_str = ", ".join(calendar_names) if calendar_names else "(nicht verfügbar)"
    mail_str = ", ".join(mail_folders) if mail_folders else "(nicht verfügbar)"
    return (
        _SYSTEM_TEMPLATE.replace("{HEUTE_ISO}", heute)
        .replace("{PROJECT_LIST}", projects_str)
        .replace("{TODO_LISTS}", todo_str)
        .replace("{CALENDAR_NAMES}", calendar_str)
        .replace("{MAIL_FOLDERS}", mail_str)
    )


def _call_claude_sync(system: str, user: str) -> str:
    response = _claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        temperature=0,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return response.content[0].text


async def route_with_llm(text: str) -> dict:
    logger.info(f"Router input: {text!r}")
    system = await _build_system_prompt()
    try:
        raw = await asyncio.to_thread(_call_claude_sync, system, text)
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```\s*$", "", cleaned)
        parsed = json.loads(cleaned)
        for field in ("intent", "confidence", "params", "reasoning"):
            if field not in parsed:
                raise ValueError(f"missing field: {field}")
        if parsed["intent"] not in {
            "calendar",
            "coding",
            "research",
            "work",
            "mail",
            "personal",
            "news",
            "tasks",
            "briefing",
            "memory",
            "reminder_write",
            "weather",
        }:
            raise ValueError(f"invalid intent: {parsed['intent']}")
        result = parsed
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(f"Router parse error: {e}")
        result = dict(_FALLBACK)
    except Exception as e:
        logger.warning(f"Router API error: {e}")
        result = dict(_FALLBACK, reasoning="api_error")

    logger.info(
        f"Router output: intent={result['intent']} "
        f"confidence={result['confidence']} "
        f"reasoning={result['reasoning']!r} "
        f"params={result['params']}"
    )
    return result
