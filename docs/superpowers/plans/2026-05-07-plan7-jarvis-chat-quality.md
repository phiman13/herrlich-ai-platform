# Jarvis Chat Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Jarvis bekommt Gesprächsgedächtnis (letzte 10 Turns), native Typing-Indikatoren statt Placeholder-Texten, und Sonnet für den Personal-Intent.

**Architecture:** Neue `ConversationDB`-Klasse in `db.py` speichert Turns pro `chat_id`. In `_process_text` wird History vor LLM-Calls geladen und nach LLM-Calls gespeichert. `ask_claude` bekommt einen optionalen `history`-Parameter. Typing-Indikatoren ersetzen alle `reply_text`-Placeholder für LLM-Calls.

**Tech Stack:** aiosqlite (bereits installiert), `telegram.ChatAction`, Python asyncio.Event für Typing-Loop.

---

## File Map

| File | Änderung |
|---|---|
| `agents/db.py` | Neue `ConversationDB`-Klasse |
| `agents/main.py` | `send_typing`, `_keep_typing`, Typing-Replacement in `_process_text`, `ask_claude` history-Param, Model-Upgrade, `_conversation_db` global + startup init |
| `tests/test_conversation_db.py` | Neu: 4 Tests für ConversationDB |
| `tests/test_chat_quality_main.py` | Neu: Tests für Typing + History-Wiring in main.py |

---

### Task 1: `ConversationDB` in `db.py`

**Files:**
- Modify: `agents/db.py`
- Test: `tests/test_conversation_db.py`

- [ ] **Step 1: Failing tests schreiben**

Erstelle `tests/test_conversation_db.py`:

```python
import asyncio
import pytest


def test_save_and_get_recent(tmp_path):
    from agents.db import ConversationDB
    db = ConversationDB(str(tmp_path / "conv.db"))
    asyncio.run(db.init())
    asyncio.run(db.save(123, "user", "Hallo"))
    asyncio.run(db.save(123, "assistant", "Hallo zurück"))

    rows = asyncio.run(db.get_recent(123, n=20))
    assert len(rows) == 2
    assert rows[0] == {"role": "user", "content": "Hallo"}
    assert rows[1] == {"role": "assistant", "content": "Hallo zurück"}


def test_get_recent_respects_chat_id(tmp_path):
    from agents.db import ConversationDB
    db = ConversationDB(str(tmp_path / "conv.db"))
    asyncio.run(db.init())
    asyncio.run(db.save(111, "user", "Für chat 111"))
    asyncio.run(db.save(222, "user", "Für chat 222"))

    rows = asyncio.run(db.get_recent(111, n=20))
    assert len(rows) == 1
    assert rows[0]["content"] == "Für chat 111"


def test_get_recent_limits_to_n(tmp_path):
    from agents.db import ConversationDB
    db = ConversationDB(str(tmp_path / "conv.db"))
    asyncio.run(db.init())
    for i in range(25):
        asyncio.run(db.save(123, "user", f"Nachricht {i}"))

    rows = asyncio.run(db.get_recent(123, n=20))
    assert len(rows) == 20
    assert rows[0]["content"] == "Nachricht 5"   # älteste der letzten 20
    assert rows[-1]["content"] == "Nachricht 24"  # neueste


def test_get_recent_returns_chronological_order(tmp_path):
    from agents.db import ConversationDB
    db = ConversationDB(str(tmp_path / "conv.db"))
    asyncio.run(db.init())
    asyncio.run(db.save(123, "user", "erste"))
    asyncio.run(db.save(123, "assistant", "zweite"))
    asyncio.run(db.save(123, "user", "dritte"))

    rows = asyncio.run(db.get_recent(123, n=20))
    assert [r["content"] for r in rows] == ["erste", "zweite", "dritte"]
```

- [ ] **Step 2: Tests laufen lassen — müssen FAIL**

```bash
/Users/philippherrlich/Documents/04_Sonstiges/01_Coding/herrlich-ai-platform/.worktrees/plan3-smart-routing/.venv/bin/pytest tests/test_conversation_db.py -v
```

Erwartete Ausgabe: `ImportError: cannot import name 'ConversationDB'`

- [ ] **Step 3: `ConversationDB` in `agents/db.py` implementieren**

Füge folgende Klasse ans Ende von `agents/db.py` an:

```python
class ConversationDB:
    def __init__(self, path: str = "/root/.jarvis/conversations.db"):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)

    async def init(self):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS chat_history (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id    INTEGER NOT NULL,
                    role       TEXT NOT NULL,
                    content    TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_chat_history_chat_id "
                "ON chat_history(chat_id, id)"
            )
            await db.commit()

    async def save(self, chat_id: int, role: str, content: str):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO chat_history (chat_id, role, content, created_at) "
                "VALUES (?, ?, ?, ?)",
                (chat_id, role, content, datetime.now(timezone.utc).isoformat()),
            )
            await db.commit()

    async def get_recent(self, chat_id: int, n: int = 20) -> list[dict]:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT role, content FROM ("
                "  SELECT id, role, content FROM chat_history"
                "  WHERE chat_id = ?"
                "  ORDER BY id DESC LIMIT ?"
                ") ORDER BY id ASC",
                (chat_id, n),
            ) as cursor:
                rows = await cursor.fetchall()
        return [{"role": r[0], "content": r[1]} for r in rows]
```

- [ ] **Step 4: Tests laufen lassen — müssen PASS**

```bash
/Users/philippherrlich/Documents/04_Sonstiges/01_Coding/herrlich-ai-platform/.worktrees/plan3-smart-routing/.venv/bin/pytest tests/test_conversation_db.py -v
```

Erwartete Ausgabe: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add agents/db.py tests/test_conversation_db.py
git commit -m "feat(history): ConversationDB in db.py"
```

---

### Task 2: Typing Indicator + Model-Upgrade in `main.py`

**Files:**
- Modify: `agents/main.py`
- Test: `tests/test_chat_quality_main.py` (Teil 1: Typing)

- [ ] **Step 1: Failing test schreiben**

Erstelle `tests/test_chat_quality_main.py`:

```python
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import agents.main as main_module


def test_send_typing_calls_send_chat_action():
    mock_bot = MagicMock()
    mock_bot.send_chat_action = AsyncMock()

    with patch("agents.main.Bot", return_value=mock_bot):
        asyncio.run(main_module.send_typing(chat_id=123))

    mock_bot.send_chat_action.assert_called_once()
    call_kwargs = mock_bot.send_chat_action.call_args.kwargs
    assert call_kwargs["chat_id"] == 123


def test_keep_typing_stops_on_event():
    mock_bot = MagicMock()
    mock_bot.send_chat_action = AsyncMock()

    async def run():
        stop = asyncio.Event()
        with patch("agents.main.Bot", return_value=mock_bot):
            task = asyncio.create_task(main_module._keep_typing(123, stop))
            await asyncio.sleep(0.05)
            stop.set()
            await task
        return mock_bot.send_chat_action.call_count

    count = asyncio.run(run())
    assert count >= 1


def test_personal_intent_uses_sonnet():
    with patch("agents.main.route_with_llm", return_value={
        "intent": "personal", "confidence": 9, "params": {}, "reasoning": "test"
    }):
        with patch("agents.main.ask_claude", new_callable=AsyncMock, return_value="ok") as mock_ask:
            with patch("agents.main.send_typing", new_callable=AsyncMock):
                update = MagicMock()
                update.update_id = 77771
                update.message.text = "Hallo"
                update.message.chat_id = 123
                update.message.reply_text = AsyncMock()
                asyncio.run(main_module.handle_message(update, None))

    call_kwargs = mock_ask.call_args.kwargs
    assert call_kwargs.get("model") == "claude-sonnet-4-6"
```

- [ ] **Step 2: Tests laufen lassen — müssen FAIL**

```bash
/Users/philippherrlich/Documents/04_Sonstiges/01_Coding/herrlich-ai-platform/.worktrees/plan3-smart-routing/.venv/bin/pytest tests/test_chat_quality_main.py -v
```

Erwartete Ausgabe: `AttributeError: module 'agents.main' has no attribute 'send_typing'`

- [ ] **Step 3: `ChatAction` importieren + `send_typing` + `_keep_typing` hinzufügen**

In `agents/main.py`, ergänze den Telegram-Import in Zeile 10:

```python
from telegram import Update, Bot, ChatAction
```

Füge direkt nach der Zeile `processed_updates = set()` (derzeit ca. Zeile 46) die zwei neuen Funktionen ein:

```python
async def send_typing(chat_id: int):
    bot = Bot(token=TELEGRAM_TOKEN)
    await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)


async def _keep_typing(chat_id: int, stop_event: asyncio.Event):
    while not stop_event.is_set():
        await send_typing(chat_id)
        await asyncio.sleep(4)
```

- [ ] **Step 4: Placeholder-Texte durch Typing ersetzen + Model-Upgrade**

Ersetze in `_process_text` in `agents/main.py`:

**research-Branch** — ersetze `await update.message.reply_text("Recherchiere im Web...")` durch:
```python
    if intent == "research":
        stop = asyncio.Event()
        typing_task = asyncio.create_task(_keep_typing(chat_id, stop))
        try:
            answer = await ask_claude(
                chat_id=chat_id,
                system=memory_context + "Du bist Jarvis, KI-Assistent fuer Philipp. Recherchiere im Internet und antworte praezise auf Deutsch mit Quellenangaben.",
                user=text,
                model="claude-sonnet-4-6",
                use_web_search=True
            )
        finally:
            stop.set()
            await typing_task
        if _memory_agent:
            asyncio.create_task(_memory_agent.extract(text, answer, source="research"))
```

**work-Branch** — ersetze `await update.message.reply_text("Analysiere...")` durch:
```python
    elif intent == "work":
        stop = asyncio.Event()
        typing_task = asyncio.create_task(_keep_typing(chat_id, stop))
        try:
            answer = await ask_claude(
                chat_id=chat_id,
                system=memory_context + "Du bist Jarvis, KI-Assistent fuer Philipp (Projektmanager, Strategieberatung). Antworte praezise und strukturiert auf Deutsch.",
                user=text,
                model="claude-sonnet-4-6",
                use_web_search=True
            )
        finally:
            stop.set()
            await typing_task
        if _memory_agent:
            asyncio.create_task(_memory_agent.extract(text, answer, source="work"))
```

**personal-Branch (else)** — ersetze `await update.message.reply_text("Denke nach...")` und ändere das Modell:
```python
    else:
        await send_typing(chat_id)
        personal_system = (
            "Du bist Jarvis, persönlicher KI-Assistent für Philipp. Antworte hilfreich auf Deutsch.\n\n"
            "Wichtig zu deinen Fähigkeiten:\n"
            "- Du HAST Zugriff auf Philipps Apple-Kalender (über einen eigenen Calendar-Handler). "
            "Wenn die Frage nach Kalender oder Terminen klingt, antworte: "
            "\"Diese Frage hätte eigentlich an meinen Calendar-Handler gehen sollen — das war ein "
            "Routing-Fehler. Bitte stell die Frage nochmal mit klareren Worten wie 'Termine', "
            "'Kalender' oder 'wann habe ich Zeit'.\"\n"
            "- Du KANNST im Web recherchieren (über einen Research-Handler).\n"
            "- Du KANNST Code in Philipps Projekten ändern (über einen Coding-Handler).\n"
            "- Wenn die Frage zu einem dieser Bereiche passt, sag ehrlich, dass die Anfrage falsch "
            "geroutet wurde, statt zu halluzinieren.\n"
            "- Bei echten allgemeinen Fragen (Smalltalk, Wissensfragen ohne Tool-Bezug) antworte "
            "normal und hilfreich."
        )
        answer = await ask_claude(
            chat_id=chat_id,
            system=memory_context + personal_system,
            user=text,
            model="claude-sonnet-4-6"
        )
        if _memory_agent:
            asyncio.create_task(_memory_agent.extract(text, answer, source="personal"))
```

- [ ] **Step 5: Tests laufen lassen — müssen PASS**

```bash
/Users/philippherrlich/Documents/04_Sonstiges/01_Coding/herrlich-ai-platform/.worktrees/plan3-smart-routing/.venv/bin/pytest tests/test_chat_quality_main.py tests/test_main_memory.py -v
```

Erwartete Ausgabe: mind. 8 passed, 0 failed.

- [ ] **Step 6: Commit**

```bash
git add agents/main.py tests/test_chat_quality_main.py
git commit -m "feat(ux): typing indicator + Sonnet für personal intent"
```

---

### Task 3: History-Wiring in `ask_claude` + `_process_text` + `startup()`

**Files:**
- Modify: `agents/main.py`
- Modify: `tests/test_chat_quality_main.py` (3 neue Tests ergänzen)

- [ ] **Step 1: Neue Tests schreiben**

Ergänze folgende 3 Tests **am Ende** von `tests/test_chat_quality_main.py`:

```python
def test_ask_claude_injects_history():
    history = [
        {"role": "user", "content": "Was ist Python?"},
        {"role": "assistant", "content": "Python ist eine Programmiersprache."},
    ]

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Antwort")]

    with patch("agents.main.claude") as mock_claude, \
         patch("agents.main.Bot") as mock_bot_cls:
        mock_bot_cls.return_value.send_message = AsyncMock()
        mock_claude.messages.create.return_value = mock_response
        asyncio.run(main_module.ask_claude(
            chat_id=123,
            system="system",
            user="Wie alt ist es?",
            history=history,
        ))

    call_kwargs = mock_claude.messages.create.call_args.kwargs
    messages = call_kwargs["messages"]
    assert messages[0] == {"role": "user", "content": "Was ist Python?"}
    assert messages[1] == {"role": "assistant", "content": "Python ist eine Programmiersprache."}
    assert messages[2] == {"role": "user", "content": "Wie alt ist es?"}


def test_history_saved_after_personal_intent():
    mock_db = MagicMock()
    mock_db.get_recent = AsyncMock(return_value=[])
    mock_db.save = AsyncMock()
    main_module._conversation_db = mock_db

    with patch("agents.main.route_with_llm", return_value={
        "intent": "personal", "confidence": 9, "params": {}, "reasoning": "test"
    }):
        with patch("agents.main.ask_claude", new_callable=AsyncMock, return_value="Antwort auf Hallo"):
            with patch("agents.main.send_typing", new_callable=AsyncMock):
                update = MagicMock()
                update.update_id = 77772
                update.message.text = "Hallo"
                update.message.chat_id = 123
                update.message.reply_text = AsyncMock()
                asyncio.run(main_module.handle_message(update, None))

    save_calls = mock_db.save.call_args_list
    assert any(c.args == (123, "user", "Hallo") for c in save_calls)
    assert any(c.args == (123, "assistant", "Antwort auf Hallo") for c in save_calls)

    main_module._conversation_db = None


def test_history_not_saved_for_calendar_intent():
    mock_db = MagicMock()
    mock_db.get_recent = AsyncMock(return_value=[])
    mock_db.save = AsyncMock()
    main_module._conversation_db = mock_db

    with patch("agents.main.route_with_llm", return_value={
        "intent": "calendar", "confidence": 9,
        "params": {"mode": "read", "kind": "today", "start": None, "end": None,
                   "title": None, "calendar_name": None},
        "reasoning": "test",
    }):
        with patch("agents.main.handle_calendar", new_callable=AsyncMock):
            update = MagicMock()
            update.update_id = 77773
            update.message.text = "Was habe ich heute?"
            update.message.chat_id = 123
            update.message.reply_text = AsyncMock()
            asyncio.run(main_module.handle_message(update, None))

    mock_db.save.assert_not_called()

    main_module._conversation_db = None
```

- [ ] **Step 2: Tests laufen lassen — müssen FAIL**

```bash
/Users/philippherrlich/Documents/04_Sonstiges/01_Coding/herrlich-ai-platform/.worktrees/plan3-smart-routing/.venv/bin/pytest tests/test_chat_quality_main.py -v
```

Erwartete Ausgabe: 3 neue Tests FAIL mit `AttributeError: module 'agents.main' has no attribute '_conversation_db'`.

- [ ] **Step 3: `ask_claude` — `history`-Parameter hinzufügen**

Ersetze die Signatur und den `messages`-Aufbau in `ask_claude`:

```python
async def ask_claude(chat_id, system, user, model="claude-haiku-4-5-20251001", use_web_search=False, history: list[dict] | None = None) -> str:
    bot = Bot(token=TELEGRAM_TOKEN)
    answer = ""
    try:
        kwargs = {
            "model": model,
            "max_tokens": 2048,
            "system": system,
            "messages": [*(history or []), {"role": "user", "content": user}]
        }
        if use_web_search:
            kwargs["tools"] = [{"type": "web_search_20250305", "name": "web_search"}]

        response = claude.messages.create(**kwargs)

        for block in response.content:
            if hasattr(block, "text"):
                answer += block.text

        if not answer:
            answer = "Keine Antwort erhalten."
        if len(answer) > 4000:
            answer = answer[:4000] + "\n[...]"
        await bot.send_message(chat_id=chat_id, text=answer)
    except Exception as e:
        answer = f"Fehler: {str(e)}"
        await bot.send_message(chat_id=chat_id, text=answer)
    return answer
```

- [ ] **Step 4: `_conversation_db` global + History-Laden + History-Speichern in `_process_text`**

**4a.** Füge direkt nach `_memory_agent = None` (ca. Zeile 48) hinzu:

```python
_conversation_db = None  # initialized in startup()
_HISTORY_INTENTS = {"personal", "work", "research"}
```

**4b.** Ergänze in `_process_text` direkt nach dem `memory_context`-Block (nach Zeile `logger.info(...)`) das History-Laden:

```python
    history: list[dict] = []
    if _conversation_db and intent in _HISTORY_INTENTS:
        try:
            history = await _conversation_db.get_recent(chat_id, n=20)
        except Exception as e:
            logger.warning("History load failed: %s", e)
```

**4c.** Füge History-Injection in die drei LLM-Calls ein — jeweils `history=history` als Parameter:

research-Branch:
```python
            answer = await ask_claude(
                chat_id=chat_id,
                system=memory_context + "Du bist Jarvis, KI-Assistent fuer Philipp. Recherchiere im Internet und antworte praezise auf Deutsch mit Quellenangaben.",
                user=text,
                model="claude-sonnet-4-6",
                use_web_search=True,
                history=history,
            )
```

work-Branch:
```python
            answer = await ask_claude(
                chat_id=chat_id,
                system=memory_context + "Du bist Jarvis, KI-Assistent fuer Philipp (Projektmanager, Strategieberatung). Antworte praezise und strukturiert auf Deutsch.",
                user=text,
                model="claude-sonnet-4-6",
                use_web_search=True,
                history=history,
            )
```

personal-Branch (else):
```python
        answer = await ask_claude(
            chat_id=chat_id,
            system=memory_context + personal_system,
            user=text,
            model="claude-sonnet-4-6",
            history=history,
        )
```

**4d.** Füge History-Speichern nach jedem LLM-Call (research, work, personal) ein. Platziere diesen Block **direkt nach** dem `if _memory_agent: asyncio.create_task(...)` — also nach dem Memory-Extract für jeden der drei Intents:

```python
        if _conversation_db and intent in _HISTORY_INTENTS:
            try:
                await _conversation_db.save(chat_id, "user", text)
                await _conversation_db.save(chat_id, "assistant", answer)
            except Exception as e:
                logger.warning("History save failed: %s", e)
```

**Wichtig:** Dieser Block muss **nach** den drei Intent-Branches stehen (nach dem `else:`-Block), da `intent` und `answer` dann gesetzt sind. Alternativ: am Ende von jedem Branch separat einfügen. Einfachste Option: einmalig am Ende von `_process_text`, nach allen Intent-Branches:

```python
    # History für LLM-Intents speichern
    if _conversation_db and intent in _HISTORY_INTENTS and "answer" in dir():
        try:
            await _conversation_db.save(chat_id, "user", text)
            await _conversation_db.save(chat_id, "assistant", answer)
        except Exception as e:
            logger.warning("History save failed: %s", e)
```

**Hinweis:** `"answer" in dir()` ist fragil. Besser: setze `answer = ""` am Anfang von `_process_text`, dann prüfe `if answer:`. Die Variable `answer` existiert bereits nach jedem LLM-Call. Der einfachste Ansatz: setze `answer: str = ""` als erstes in `_process_text`, und füge dann den Speicher-Block einmalig ganz am Ende ein:

```python
async def _process_text(text: str, chat_id: int, update: Update) -> None:
    answer: str = ""  # ← NEU: am Anfang der Funktion
    routing = await route_with_llm(text)
    ...
    # ganz am Ende der Funktion, nach allen if/elif/else-Branches:
    if _conversation_db and intent in _HISTORY_INTENTS and answer:
        try:
            await _conversation_db.save(chat_id, "user", text)
            await _conversation_db.save(chat_id, "assistant", answer)
        except Exception as e:
            logger.warning("History save failed: %s", e)
```

- [ ] **Step 5: `ConversationDB` in `startup()` initialisieren**

Füge in der `startup()`-Funktion direkt nach der MemoryDB-Initialisierung ein:

```python
    global _memory_agent, _conversation_db
    from db import ConversationDB
    _conv_db = ConversationDB()
    await _conv_db.init()
    _conversation_db = _conv_db
    logger.info("ConversationDB initialisiert")
```

- [ ] **Step 6: Alle Tests laufen lassen — müssen PASS**

```bash
/Users/philippherrlich/Documents/04_Sonstiges/01_Coding/herrlich-ai-platform/.worktrees/plan3-smart-routing/.venv/bin/pytest tests/test_chat_quality_main.py tests/test_conversation_db.py tests/test_main_memory.py -v
```

Erwartete Ausgabe: mind. 15 passed, 0 failed.

- [ ] **Step 7: Commit + Push**

```bash
git add agents/main.py tests/test_chat_quality_main.py
git commit -m "feat(history): conversation history in _process_text + ask_claude"
git push
```

---

### Task 4: VPS deployen und testen

- [ ] **Step 1: Deployen**

```bash
ssh root@100.115.184.3 "cd /root/agents && git pull && systemctl restart jarvis"
```

- [ ] **Step 2: Logs prüfen**

```bash
ssh root@100.115.184.3 "journalctl -u jarvis -n 20 --no-pager"
```

Erwartete Ausgabe: `ConversationDB initialisiert` + `Jarvis gestartet` ohne Fehler.

- [ ] **Step 3: Gesprächsgedächtnis testen**

Sende in Telegram:
1. *„Ich bin Software-Entwickler und arbeite hauptsächlich mit Python"*
2. *„Was sind gute Frameworks für mein Hauptwerkzeug?"*

Erwartete Antwort auf Nachricht 2: Jarvis antwortet über Python-Frameworks (weil er weiß, dass Python das Hauptwerkzeug ist).

- [ ] **Step 4: Typing-Indikator testen**

Sende: *„Was kostet Bitcoin gerade?"* → Jarvis soll die nativen Telegram-Typing-Dots zeigen (nicht mehr „Recherchiere im Web...").
