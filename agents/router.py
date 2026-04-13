import json
import logging
import asyncio
import re
from datetime import datetime

import anthropic

from calendar_agent import BERLIN

logger = logging.getLogger("jarvis")
_claude = anthropic.Anthropic()

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
   Beispiele: "Fixe den Login-Bug in recipe-app", "Was steht im Backlog?", "Erstelle einen neuen Branch", "Erkläre mir wie die Auth funktioniert"

   Parameter:
   - project: string oder null (Projektname, falls erwähnt)
   - mode: "action" | "question" — "action" wenn Code geändert werden soll, "question" wenn nur informiert/erklärt werden soll

3. "research" — Web-Recherche-Anfragen.
   Beispiele: "Recherchiere ESG-Pflichten 2026", "Was sind die aktuellen Entwicklungen bei...", "Suche im Internet nach..."

   Parameter: keine

4. "work" — Strategieberatungs- / PM-Aufgaben (Meeting-Zusammenfassungen, Analysen, Executive Summaries).
   Beispiele: "Fass diese E-Mail-Kette zusammen", "Analysiere den Markt für...", "Erstelle ein Meeting-Protokoll aus..."

   Parameter: keine

5. "personal" — Allgemeine Fragen, Smalltalk, alles andere.
   Beispiele: "Wie geht's dir?", "Erklär mir Photosynthese", "Was hältst du von..."

   Parameter: keine

## Output-Format

{{
  "intent": "calendar" | "coding" | "research" | "work" | "personal",
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


def _build_system_prompt() -> str:
    heute = datetime.now(BERLIN).strftime("%Y-%m-%d")
    return _SYSTEM_TEMPLATE.replace("{HEUTE_ISO}", heute)


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
    system = _build_system_prompt()
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
        if parsed["intent"] not in {"calendar", "coding", "research", "work", "personal"}:
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
