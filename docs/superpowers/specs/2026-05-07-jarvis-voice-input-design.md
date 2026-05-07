# Jarvis Voice Input — Design Spec

**Date:** 2026-05-07
**Status:** Approved

## Goal

Jarvis akzeptiert Sprachnachrichten in Telegram. Der Nutzer spricht, Groq Whisper transkribiert, und der transkribierte Text läuft durch die bestehende Intent-Pipeline — für Jarvis ist es eine normale Textnachricht.

## Architecture

```
Telegram Voice Message (OGG)
        ↓
handle_voice() in main.py
        ↓
voice_agent.transcribe(ogg_bytes) → str
        ↓  [Groq Whisper API]
Transkribierter Text
        ↓
route_with_llm() → Intent
        ↓
Bestehende Handler (calendar, research, personal, …)
        ↓
Antwort an Telegram
```

Kein neuer Intent. Kein neuer Router-Eintrag. Voice ist ein Eingabe-Layer, kein eigener Intent.

## Components

### `agents/voice_agent.py` (neu)

Einzige Funktion: `async def transcribe(ogg_bytes: bytes) -> str`

- Ruft Groq Whisper API auf (`whisper-large-v3-turbo`, Sprache: `de`)
- Schreibt OGG-Bytes in eine temporäre Datei (`tempfile.NamedTemporaryFile`), übergibt sie an den Groq-Client, löscht sie danach
- Gibt den transkribierten Text zurück
- Wirft `RuntimeError` bei leerem Transkript oder API-Fehler

### `agents/main.py` (Änderungen)

**Import:** `from voice_agent import transcribe`

**Neuer Handler `handle_voice(update, context)`:**
- Gleiche Deduplizierung wie `handle_message` (via `processed_updates`)
- Lädt die Telegram-Voice-Datei herunter: `await update.message.voice.get_file()` → `await file.download_as_bytearray()`
- Ruft `transcribe(ogg_bytes)` auf
- Bei Fehler: sendet `"❌ Sprachnachricht konnte nicht transkribiert werden."` und returnt
- Bei Erfolg: ruft intern `_process_text(text, update, context)` auf

**Refactoring:** Die Kernlogik von `handle_message` (ab `route_with_llm`) wird in `_process_text(text, update, context)` ausgelagert, sodass beide Handler sie teilen.

**Registrierung in `startup()`:**
```python
bot_app.add_handler(MessageHandler(filters.VOICE, handle_voice))
```

## Dependencies

| Package | Version | Zweck |
|---|---|---|
| `groq` | `>=0.7.0` | Whisper-Transkription |

Neue Env-Var auf VPS: `GROQ_API_KEY`

## Error Handling

| Fehler | Verhalten |
|---|---|
| Groq API nicht erreichbar | `RuntimeError` → Fehlernachricht an User |
| Leeres Transkript | `RuntimeError` → Fehlernachricht an User |
| Datei-Download fehlgeschlagen | Exception propagiert → Fehlernachricht an User |

Fehler werden geloggt (`logger.warning`), nie still geschluckt.

## File Map

| File | Änderung |
|---|---|
| `agents/voice_agent.py` | Neu: `transcribe()` |
| `agents/main.py` | `handle_voice()` + `_process_text()` Refactoring + Handler-Registrierung |
| `agents/requirements.txt` | `groq>=0.7.0` hinzu |

## Out of Scope

- Sprachausgabe (Text-to-Speech) — Jarvis antwortet weiterhin als Text
- Sprachen außer Deutsch
- Transkriptions-Feedback (z.B. „Ich habe verstanden: …") — der transkribierte Text wird nicht zurückgespiegelt
