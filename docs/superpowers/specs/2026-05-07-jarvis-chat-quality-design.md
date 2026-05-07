# Jarvis Chat Quality — Design Spec

**Date:** 2026-05-07
**Status:** Approved

## Goal

Jarvis soll sich wie ein echter LLM-Chat anfühlen: Gesprächsgedächtnis innerhalb einer Session, native Typing-Indikatoren statt Placeholder-Texten, und ein stärkeres Modell für offene Gespräche.

## Features

### 1. Conversation History

Jarvis speichert die letzten 10 Gesprächsrunden pro User und injiziert sie in jeden Claude-Call. Der Nutzer kann Follow-up-Fragen stellen, auf "das" und "es" referenzieren, und Jarvis baut Antworten aufeinander auf.

**Scope:** Nur LLM-Intents — `personal`, `work`, `research`, `coding`. Deterministische Intents (`calendar`, `tasks`, `mail`, `news`, `briefing`, `memory`) bleiben stateless und werden nicht in der History gespeichert.

**Storage:** Neue `ConversationDB`-Klasse in `agents/db.py`, SQLite-Datei `/root/.jarvis/conversations.db`.

```sql
CREATE TABLE IF NOT EXISTS chat_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id    INTEGER NOT NULL,
    role       TEXT NOT NULL,      -- "user" | "assistant"
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL       -- ISO-8601
);
CREATE INDEX IF NOT EXISTS idx_chat_history_chat_id ON chat_history(chat_id, id);
```

**API:**
- `async def save(self, chat_id: int, role: str, content: str)` — speichert eine Nachricht
- `async def get_recent(self, chat_id: int, n: int = 20) -> list[dict]` — gibt die letzten n Rows zurück (keys: `role`, `content`), chronologisch sortiert (älteste zuerst)

**Retrieval:** Vor jedem LLM-Call lädt `_process_text` die letzten 20 Rows für `chat_id` (= 10 User + 10 Assistant Turns). Diese werden als `history`-Parameter an `ask_claude` übergeben.

**Injection:** In `ask_claude`:
```python
messages = []
if history:
    messages.extend(history)  # [{"role": "user", "content": "..."}, ...]
messages.append({"role": "user", "content": user})
```

**Speichern:** Nach jedem LLM-Call speichert `_process_text`:
1. User-Nachricht: `save(chat_id, "user", text)`
2. Assistant-Antwort: `save(chat_id, "assistant", answer)`

### 2. Typing Indicator

Alle Placeholder-Texte (`reply_text("Denke nach...")`, `reply_text("Analysiere...")`, `reply_text("Recherchiere im Web...")`) werden durch den nativen Telegram Typing-Indikator ersetzt.

**Implementierung:** Neue Hilfsfunktion `send_typing(context, chat_id)`:
```python
async def send_typing(context, chat_id: int):
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
```

Für LLM-Calls die >5 Sekunden dauern können (research mit Web-Suche, coding): ein Background-Task wiederholt `send_typing` alle 4 Sekunden, bis die Antwort vorliegt:
```python
async def _keep_typing(context, chat_id: int, stop_event: asyncio.Event):
    while not stop_event.is_set():
        await send_typing(context, chat_id)
        await asyncio.sleep(4)
```

Für schnelle LLM-Calls (personal, work): einmaliges `send_typing` reicht.

**Import:** `from telegram import ChatAction`

**Scope:** Nur LLM-Intents. Deterministische Handlers (calendar, tasks) sind so schnell, dass kein Typing-Indikator nötig ist.

### 3. Model-Upgrade Personal-Intent

Zeile in `main.py` wo `personal`-Intent Claude aufruft:

```python
# Vorher:
model="claude-haiku-4-5-20251001"

# Nachher:
model="claude-sonnet-4-6"
```

Kein weiterer Code nötig.

## File Map

| File | Änderung |
|---|---|
| `agents/db.py` | Neue `ConversationDB`-Klasse (save, get_recent) |
| `agents/main.py` | ConversationDB init in startup(), history-Laden + Speichern in `_process_text`, `ask_claude` bekommt `history`-Parameter, Typing-Indicator für LLM-Intents, model-Upgrade personal |

## Data Flow

```
User schickt Nachricht
        ↓
_process_text()
        ↓
[intent = personal/work/research/coding]
        ↓
ConversationDB.get_recent(chat_id, n=20)  ← lädt History
        ↓
send_typing() + ggf. _keep_typing() Task starten
        ↓
ask_claude(..., history=history)
        ↓
Stop typing task
        ↓
ConversationDB.save(chat_id, "user", text)
ConversationDB.save(chat_id, "assistant", answer)
```

## Out of Scope

- Token-Counting für History-Trimming (YAGNI bei Privat-Bot)
- History-Clearing-Kommando ("Vergiss das Gespräch") — kann später kommen
- History für deterministische Intents
- Zusammenfassung alter Turns (Summarization)
- Streaming-Antworten in Telegram
