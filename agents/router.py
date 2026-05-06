import json
import logging
import asyncio
import re
from datetime import datetime

import anthropic

from calendar_agent import BERLIN
try:
    from agents.vps import list_projects as _list_projects
except ImportError:
    from vps import list_projects as _list_projects

logger = logging.getLogger("jarvis")
_claude = anthropic.Anthropic()

_project_list_cache: list[str] = []

async def _get_project_list() -> list[str]:
    global _project_list_cache
    if not _project_list_cache:
        _project_list_cache = await _list_projects()
    return _project_list_cache

_SYSTEM_TEMPLATE = """Du bist der Intent-Router von Jarvis, einem persönlichen KI-Assistenten von Philipp. Klassifiziere die User-Nachricht in genau einen der folgenden Intents und extrahiere relevante Parameter. Antworte AUSSCHLIESSLICH mit einem JSON-Objekt, ohne Markdown-Codeblock, ohne erklärenden Text.

## Verfügbare Intents

1. "calendar" — Fragen zum Kalender (Apple Calendar via CalDAV).
   Beispiele: "Was habe ich heute?", "Habe ich nächste Woche Termine?", "Wann ist mein nächster Termin?", "Bin ich Mittwoch frei?", "Was steht morgen an?"

   Parameter:
   - kind: "today" | "tomorrow" | "week" | "next" | "range" | "specific_day"
   - start: ISO-8601 datetime oder null (nur bei "range" / "specific_day")
   - end: ISO-8601 datetime oder null (nur bei "range" / "specific_day")
   - label: deutsche Beschreibung des Zeitfensters für die spätere Antwortformatierung (z.B. "die nächsten zwei Tage")

   WICHTIG: Heute ist {HEUTE_ISO}. Berechne start/end immer relativ zu diesem Datum, in Europe/Berlin Zeitzone. Bei "today" / "tomorrow" / "week" / "next" können start/end null sein, weil der bestehende Calendar-Handler die Berechnung übernimmt. Bei "range" oder "specific_day" MUSS start/end gesetzt sein.

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

5. "mail" — Anfragen zu Outlook-Mails (Posteingang, Ordner, Suche). NUR LESEN, keine Aktionen wie verschieben oder löschen.

   Beispiele:
   - "Was Wichtiges im Posteingang?"
   - "Was hab ich verpasst?" / "Ungelesene Mails"
   - "Hat mir Anna geschrieben?"
   - "Mails von letzter Woche zum Thema X"
   - "Was steht im Ordner 'Steuern'?"
   - "Welche Ordner gibt es?"

   Parameter:
   - mode: "quick_scan" | "unread" | "search" | "list_folders"
   - count: integer oder null (Anzahl Mails, default je nach mode)
   - sender: string oder null (Filter nach Absender, falls genannt)
   - subject_contains: string oder null (Filter nach Betreff)
   - since_iso: ISO-8601 datetime oder null (nur Mails ab diesem Zeitpunkt, relativ zu {HEUTE_ISO})
   - folder_name: string oder null (spezifischer Ordner, falls genannt)

   Mode-Bestimmung:
   - "Posteingang" / "Was Neues" / "Aktuelle Mails" → quick_scan
   - "Ungelesene" / "Was hab ich verpasst" / "Was ist neu" → unread
   - "Hat mir X geschrieben" / "Mails von X" / "zum Thema Y" → search
   - "Welche Ordner" / "Liste meiner Ordner" → list_folders
   - Ordnerangaben wie "im Ordner X" setzen folder_name, mode bleibt je nach Hauptfrage

6. "personal" — Allgemeine Fragen, Smalltalk, alles andere.
   Beispiele: "Wie geht's dir?", "Erklär mir Photosynthese", "Was hältst du von..."

   Parameter: keine

7. "news" — KI-News und Technologie-Neuigkeiten abrufen.
   Beispiele: "Was gibt's Neues in AI?", "Neueste KI-Entwicklungen?", "AI News"

   Parameter: keine

8. "tasks" — MS To Do Tasks lesen oder schreiben.
   Beispiele: "Was steht auf meiner Einkaufsliste?", "Füge Milch zur Einkaufsliste hinzu", "Erledigte Tasks anzeigen", "Zeig mir alle To Do Listen"

   Parameter:
   - mode: "read" | "write" | "complete"
   - list_name: string oder null (Listenname, z.B. "Einkaufsliste")
   - item: string oder null (Task-Text, nur bei mode=write)

9. "briefing" — Morning Briefing abrufen: Kalender, Wetter, Mail, News, Tasks, GitHub.
   Beispiele: "Briefing", "Gib mir mein Briefing", "Morning Briefing", "Was liegt heute an?"

   Parameter: keine

## Output-Format

{{
  "intent": "calendar" | "coding" | "research" | "work" | "mail" | "personal" | "news" | "tasks" | "briefing",
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
    project_list = await _get_project_list()
    projects_str = ", ".join(project_list) if project_list else "recipe-app"
    return (
        _SYSTEM_TEMPLATE
        .replace("{HEUTE_ISO}", heute)
        .replace("{PROJECT_LIST}", projects_str)
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
        if parsed["intent"] not in {"calendar", "coding", "research", "work", "mail", "personal", "news", "tasks", "briefing"}:
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
