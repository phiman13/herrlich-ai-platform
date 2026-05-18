# Jarvis Voice Input Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Jarvis akzeptiert Telegram-Sprachnachrichten, transkribiert sie via Groq Whisper und schickt den Text durch die bestehende Intent-Pipeline.

**Architecture:** Ein neues `voice_agent.py` stellt `transcribe(ogg_bytes) -> str` bereit (Groq Whisper API, lazy-init). In `main.py` wird die Kernlogik von `handle_message` in `_process_text` extrahiert, sodass der neue `handle_voice`-Handler denselben Code nutzt.

**Tech Stack:** `groq>=0.7.0`, python-telegram-bot 22.7 (`filters.VOICE`), asyncio.to_thread für blockierende Groq-Calls.

---

## File Map

| File | Änderung |
|---|---|
| `agents/voice_agent.py` | Neu: `transcribe(ogg_bytes: bytes) -> str` |
| `agents/main.py` | Extrahiere `_process_text`, füge `handle_voice` hinzu, registriere Handler |
| `agents/requirements.txt` | Füge `groq>=0.7.0` hinzu |
| `tests/test_voice_agent.py` | Neu: 3 Tests für `transcribe` |
| `tests/test_voice_main.py` | Neu: 3 Tests für `handle_voice` |

---

### Task 1: `voice_agent.py` — Transkriptions-Modul

**Files:**
- Create: `agents/voice_agent.py`
- Test: `tests/test_voice_agent.py`

- [ ] **Step 1: Failing tests schreiben**

Erstelle `tests/test_voice_agent.py`:

```python
import asyncio
from unittest.mock import MagicMock, patch
import pytest


def test_transcribe_returns_text():
    mock_result = MagicMock()
    mock_result.text = "Ich möchte eine Recherche über Bitcoin"

    mock_client = MagicMock()
    mock_client.audio.transcriptions.create.return_value = mock_result

    with patch("agents.voice_agent._get_groq", return_value=mock_client):
        from agents.voice_agent import transcribe
        result = asyncio.run(transcribe(b"fake_ogg_bytes"))

    assert result == "Ich möchte eine Recherche über Bitcoin"
    call_kwargs = mock_client.audio.transcriptions.create.call_args.kwargs
    assert call_kwargs["model"] == "whisper-large-v3-turbo"
    assert call_kwargs["language"] == "de"


def test_transcribe_raises_on_empty_transcript():
    mock_result = MagicMock()
    mock_result.text = "   "

    mock_client = MagicMock()
    mock_client.audio.transcriptions.create.return_value = mock_result

    with patch("agents.voice_agent._get_groq", return_value=mock_client):
        from agents.voice_agent import transcribe
        with pytest.raises(RuntimeError, match="Leeres Transkript"):
            asyncio.run(transcribe(b"fake_ogg_bytes"))


def test_transcribe_propagates_api_error():
    mock_client = MagicMock()
    mock_client.audio.transcriptions.create.side_effect = Exception("API unavailable")

    with patch("agents.voice_agent._get_groq", return_value=mock_client):
        from agents.voice_agent import transcribe
        with pytest.raises(Exception, match="API unavailable"):
            asyncio.run(transcribe(b"fake_ogg_bytes"))
```

- [ ] **Step 2: Tests laufen lassen — müssen FAIL**

```bash
cd /Users/philippherrlich/Documents/04_Sonstiges/01_Coding/herrlich-ai-platform
pytest tests/test_voice_agent.py -v
```

Erwartete Ausgabe: `ERROR` oder `ImportError` (Modul existiert noch nicht).

- [ ] **Step 3: `voice_agent.py` implementieren**

Erstelle `agents/voice_agent.py`:

```python
import asyncio
import io
import logging
import os

logger = logging.getLogger("jarvis.voice")

_groq = None


def _get_groq():
    global _groq
    if _groq is None:
        from groq import Groq
        _groq = Groq(api_key=os.environ["GROQ_API_KEY"])
    return _groq


async def transcribe(ogg_bytes: bytes) -> str:
    client = _get_groq()
    audio_io = io.BytesIO(ogg_bytes)
    audio_io.name = "voice.ogg"
    result = await asyncio.to_thread(
        client.audio.transcriptions.create,
        model="whisper-large-v3-turbo",
        file=audio_io,
        language="de",
    )
    text = result.text.strip()
    if not text:
        raise RuntimeError("Leeres Transkript")
    return text
```

- [ ] **Step 4: Tests laufen lassen — müssen PASS**

```bash
pytest tests/test_voice_agent.py -v
```

Erwartete Ausgabe:
```
tests/test_voice_agent.py::test_transcribe_returns_text PASSED
tests/test_voice_agent.py::test_transcribe_raises_on_empty_transcript PASSED
tests/test_voice_agent.py::test_transcribe_propagates_api_error PASSED
3 passed
```

- [ ] **Step 5: Commit**

```bash
git add agents/voice_agent.py tests/test_voice_agent.py
git commit -m "feat(voice): voice_agent.py mit Groq Whisper Transkription"
```

---

### Task 2: `_process_text` in `main.py` extrahieren

**Files:**
- Modify: `agents/main.py` (Zeilen 363–589)

Der bestehende `handle_message` enthält zwei Teile: (1) Deduplizierung + Text-Extraktion, (2) alles ab `route_with_llm`. Teil (2) wird in `_process_text` ausgelagert.

- [ ] **Step 1: Bestehende Tests als Baseline laufen lassen**

```bash
pytest tests/test_main_memory.py -v
```

Alle 5 Tests müssen PASS — das ist der Ausgangszustand vor der Änderung.

- [ ] **Step 2: `_process_text` extrahieren und `handle_message` vereinfachen**

Ersetze die gesamte `handle_message`-Funktion in `agents/main.py` durch diese zwei Funktionen:

```python
async def _process_text(text: str, chat_id: int, update) -> None:
    result = await route_with_llm(text)
    intent = result["intent"]
    params = result["params"]

    confidence = result["confidence"]
    if confidence < 5:
        await update.message.reply_text(
            "Ich bin mir nicht ganz sicher, was du meinst. "
            "Bitte präzisiere: Kalender, Mail, Task-Liste, Coding oder etwas anderes?"
        )
        return

    memory_context = ""
    if _memory_agent and intent in _MEMORY_INTENTS:
        try:
            memories = await _memory_agent.retrieve(text)
            if memories:
                bullet_list = "\n".join(f"• {m}" for m in memories)
                memory_context = (
                    f"Kontext aus früheren Gesprächen mit Philipp:\n{bullet_list}\n\n"
                )
        except Exception as e:
            logger.warning("Memory retrieval failed: %s", e)

    logger.info(f"Intent: {intent} | Nachricht: {text}")

    if intent == "calendar":
        mode = params.get("mode", "read")
        kind = params.get("kind")
        start_str = params.get("start")
        end_str = params.get("end")
        start = datetime.fromisoformat(start_str) if start_str else None
        end = datetime.fromisoformat(end_str) if end_str else None
        title = params.get("title")
        calendar_name = params.get("calendar_name")
        await handle_calendar(
            chat_id=chat_id, text=text, kind=kind, start=start, end=end,
            mode=mode, title=title, calendar_name=calendar_name,
        )
        return

    if intent == "mail":
        await handle_mail(chat_id=chat_id, text=text, params=params)
        return

    if intent == "research":
        await update.message.reply_text("Recherchiere im Web...")
        answer = await ask_claude(
            chat_id=chat_id,
            system=memory_context + "Du bist Jarvis, KI-Assistent fuer Philipp. Recherchiere im Internet und antworte praezise auf Deutsch mit Quellenangaben.",
            user=text,
            model="claude-sonnet-4-6",
            use_web_search=True
        )
        if _memory_agent:
            asyncio.create_task(_memory_agent.extract(text, answer, source="research"))

    elif intent == "coding":
        mode = params.get("mode", "action")
        project = params.get("project")

        if not project:
            projects = await list_projects()
            project = projects[0] if projects else "recipe-app"

        if mode == "query":
            query_type = params.get("query_type", "backlog")
            await update.message.reply_text("🔍 Lese...")
            result = await handle_coding_query(project, query_type)
            await update.message.reply_text(
                f"📁 *{project}* — {query_type}\n\n{result[:4000]}",
                parse_mode="Markdown",
            )

        elif mode == "backlog_write":
            item = params.get("backlog_item", text)
            priority = params.get("backlog_priority", "P1")
            success = await add_backlog_item(project, item, priority)
            if success:
                await update.message.reply_text(
                    f"✅ Backlog-Item hinzugefügt in *{project}*:\n_{item}_",
                    parse_mode="Markdown",
                )
            else:
                await update.message.reply_text("❌ Konnte Backlog nicht aktualisieren.")

        else:  # action
            asyncio.create_task(run_coding_action(text, project, chat_id))

    elif intent == "work":
        await update.message.reply_text("Analysiere...")
        answer = await ask_claude(
            chat_id=chat_id,
            system=memory_context + "Du bist Jarvis, KI-Assistent fuer Philipp (Projektmanager, Strategieberatung). Antworte praezise und strukturiert auf Deutsch.",
            user=text,
            model="claude-sonnet-4-6",
            use_web_search=True
        )
        if _memory_agent:
            asyncio.create_task(_memory_agent.extract(text, answer, source="work"))

    elif intent == "news":
        await update.message.reply_text("📰 Lade AI-News...")
        news = await asyncio.to_thread(get_ai_news, 48, 10)
        await update.message.reply_text(
            f"📰 *AI NEWS — letzte 48h*\n\n{news or 'Keine News gefunden.'}",
            parse_mode="Markdown",
        )

    elif intent == "tasks":
        mode = params.get("mode", "read")
        list_name = params.get("list_name")
        item = params.get("item")

        if mode == "read":
            result = await asyncio.to_thread(get_tasks, list_name)
            await update.message.reply_text(result or "Keine offenen Tasks.", parse_mode="Markdown")

        elif mode == "write" and item:
            if not list_name:
                await update.message.reply_text("Welche Liste? (z.B. 'Einkaufsliste')")
            else:
                success = await asyncio.to_thread(add_task, list_name, item)
                if success:
                    await update.message.reply_text(
                        f"✅ '{item}' zu *{list_name}* hinzugefügt.", parse_mode="Markdown"
                    )
                else:
                    await update.message.reply_text("❌ Konnte Task nicht hinzufügen.")

        elif mode == "complete" and item:
            if not list_name:
                await update.message.reply_text("Welche Liste?")
            else:
                success = await asyncio.to_thread(complete_task, list_name, item)
                if success:
                    await update.message.reply_text(
                        f"✅ '{item}' in *{list_name}* als erledigt markiert.", parse_mode="Markdown"
                    )
                else:
                    await update.message.reply_text("❌ Task nicht gefunden oder bereits erledigt.")

        elif mode == "create_list" and list_name:
            success = await asyncio.to_thread(create_list, list_name)
            if success:
                router._todo_lists_cache = ([], 0.0)
                await update.message.reply_text(f"✅ Liste *{list_name}* angelegt.", parse_mode="Markdown")
            else:
                await update.message.reply_text("❌ Liste konnte nicht angelegt werden.")

        elif mode == "delete_list" and list_name:
            success = await asyncio.to_thread(delete_list, list_name)
            if success:
                router._todo_lists_cache = ([], 0.0)
                await update.message.reply_text(f"✅ Liste *{list_name}* gelöscht.", parse_mode="Markdown")
            else:
                await update.message.reply_text(f"❌ Liste '{list_name}' nicht gefunden oder konnte nicht gelöscht werden.")

        elif mode == "rename_list":
            new_name = params.get("new_name")
            if not list_name or not new_name:
                await update.message.reply_text("Bitte alter und neuer Listenname angeben.")
            else:
                success = await asyncio.to_thread(rename_list, list_name, new_name)
                if success:
                    router._todo_lists_cache = ([], 0.0)
                    await update.message.reply_text(
                        f"✅ Liste *{list_name}* → *{new_name}* umbenannt.", parse_mode="Markdown"
                    )
                else:
                    await update.message.reply_text(f"❌ Liste '{list_name}' nicht gefunden oder Umbenennung fehlgeschlagen.")

    elif intent == "briefing":
        await update.message.reply_text("⏳ Briefing wird erstellt...")
        msg = await build_briefing()
        await update.message.reply_text(msg, parse_mode="Markdown")

    elif intent == "memory":
        mode = params.get("mode", "list")
        query = params.get("query")
        if not _memory_agent:
            await update.message.reply_text("Memory-System nicht initialisiert.")
            return
        if mode == "delete":
            msg = await _memory_agent.delete_memory(query)
        else:
            msg = await _memory_agent.list_memories()
        await update.message.reply_text(msg, parse_mode="Markdown")

    else:
        await update.message.reply_text("Denke nach...")
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
            model="claude-haiku-4-5-20251001"
        )
        if _memory_agent:
            asyncio.create_task(_memory_agent.extract(text, answer, source="personal"))


async def handle_message(update, context):
    update_id = update.update_id
    if update_id in processed_updates:
        logger.info(f"Duplikat ignoriert: update_id={update_id}")
        return
    processed_updates.add(update_id)
    if len(processed_updates) > 1000:
        processed_updates.clear()

    text = update.message.text
    chat_id = update.message.chat_id
    await _process_text(text, chat_id, update)
```

- [ ] **Step 3: Tests laufen lassen — müssen weiterhin PASS**

```bash
pytest tests/test_main_memory.py -v
```

Alle 5 Tests müssen PASS. Wenn nicht: Refactoring hat die Signatur oder den Scope verändert — rückgängig machen und Fehler prüfen.

- [ ] **Step 4: Commit**

```bash
git add agents/main.py
git commit -m "refactor(main): extrahiere _process_text aus handle_message"
```

---

### Task 3: `handle_voice` hinzufügen und registrieren

**Files:**
- Modify: `agents/main.py`
- Test: `tests/test_voice_main.py`

- [ ] **Step 1: Failing tests schreiben**

Erstelle `tests/test_voice_main.py`:

```python
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import agents.main as main_module


def test_handle_voice_transcribes_and_calls_process_text():
    main_module.processed_updates.discard(8801)

    mock_file = MagicMock()
    mock_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"fake_ogg"))

    mock_update = MagicMock()
    mock_update.update_id = 8801
    mock_update.message.chat_id = 123
    mock_update.message.voice.get_file = AsyncMock(return_value=mock_file)

    with patch("agents.main.transcribe", new_callable=AsyncMock, return_value="Was kostet Bitcoin?") as mock_transcribe, \
         patch("agents.main._process_text", new_callable=AsyncMock) as mock_process:
        asyncio.run(main_module.handle_voice(mock_update, None))

    mock_transcribe.assert_called_once_with(bytes(b"fake_ogg"))
    mock_process.assert_called_once_with("Was kostet Bitcoin?", 123, mock_update)


def test_handle_voice_sends_error_on_transcription_failure():
    main_module.processed_updates.discard(8802)

    mock_file = MagicMock()
    mock_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"fake_ogg"))

    mock_update = MagicMock()
    mock_update.update_id = 8802
    mock_update.message.chat_id = 123
    mock_update.message.voice.get_file = AsyncMock(return_value=mock_file)
    mock_update.message.reply_text = AsyncMock()

    with patch("agents.main.transcribe", new_callable=AsyncMock, side_effect=RuntimeError("Leeres Transkript")):
        asyncio.run(main_module.handle_voice(mock_update, None))

    mock_update.message.reply_text.assert_called_once_with(
        "❌ Sprachnachricht konnte nicht transkribiert werden."
    )


def test_handle_voice_deduplicates():
    main_module.processed_updates.discard(8803)

    mock_file = MagicMock()
    mock_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"fake_ogg"))

    mock_update = MagicMock()
    mock_update.update_id = 8803
    mock_update.message.chat_id = 123
    mock_update.message.voice.get_file = AsyncMock(return_value=mock_file)

    with patch("agents.main.transcribe", new_callable=AsyncMock, return_value="Text") as mock_transcribe, \
         patch("agents.main._process_text", new_callable=AsyncMock):
        asyncio.run(main_module.handle_voice(mock_update, None))
        asyncio.run(main_module.handle_voice(mock_update, None))

    assert mock_transcribe.call_count == 1
```

- [ ] **Step 2: Tests laufen lassen — müssen FAIL**

```bash
pytest tests/test_voice_main.py -v
```

Erwartete Ausgabe: `AttributeError: module 'agents.main' has no attribute 'handle_voice'`

- [ ] **Step 3: Import + `handle_voice` in `main.py` hinzufügen**

Füge folgenden Import am Anfang von `agents/main.py` ein (nach den bestehenden lokalen Imports):

```python
from voice_agent import transcribe
```

Füge direkt nach `handle_message` folgende Funktion ein:

```python
async def handle_voice(update, context):
    update_id = update.update_id
    if update_id in processed_updates:
        logger.info(f"Duplikat ignoriert: update_id={update_id}")
        return
    processed_updates.add(update_id)
    if len(processed_updates) > 1000:
        processed_updates.clear()

    chat_id = update.message.chat_id
    try:
        voice_file = await update.message.voice.get_file()
        ogg_bytes = bytes(await voice_file.download_as_bytearray())
        text = await transcribe(ogg_bytes)
    except Exception as e:
        logger.warning("Voice transcription failed: %s", e)
        await update.message.reply_text("❌ Sprachnachricht konnte nicht transkribiert werden.")
        return

    await _process_text(text, chat_id, update)
```

- [ ] **Step 4: Handler in `startup()` registrieren**

In `agents/main.py`, in der `startup()`-Funktion, füge direkt nach der Zeile mit `filters.TEXT` ein:

```python
bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
bot_app.add_handler(MessageHandler(filters.VOICE, handle_voice))  # NEU
```

- [ ] **Step 5: Alle Tests laufen lassen — müssen PASS**

```bash
pytest tests/test_voice_main.py tests/test_voice_agent.py tests/test_main_memory.py -v
```

Erwartete Ausgabe: 11 passed, 0 failed.

- [ ] **Step 6: Commit**

```bash
git add agents/main.py tests/test_voice_main.py
git commit -m "feat(voice): handle_voice Handler in main.py + Registrierung"
```

---

### Task 4: `requirements.txt` updaten + VPS deployen

**Files:**
- Modify: `agents/requirements.txt`

- [ ] **Step 1: `groq` zur requirements.txt hinzufügen**

Füge am Ende von `agents/requirements.txt` ein:

```
groq>=0.7.0
```

- [ ] **Step 2: Commit + Push**

```bash
git add agents/requirements.txt
git commit -m "chore(deps): groq>=0.7.0 für Whisper-Transkription"
git push
```

- [ ] **Step 3: `GROQ_API_KEY` auf dem VPS setzen**

Groq-API-Key holen unter [console.groq.com](https://console.groq.com) → API Keys → Create.

Dann auf dem VPS den Key setzen. Prüfe zuerst ob eine `.env`-Datei oder systemd-Override genutzt wird:

```bash
ssh root@100.115.184.3 "cat /root/agents/.env 2>/dev/null || systemctl cat jarvis | grep Environment"
```

Wenn `.env`-Datei vorhanden:
```bash
ssh root@100.115.184.3 "echo 'GROQ_API_KEY=gsk_DEIN_KEY_HIER' >> /root/agents/.env"
```

Wenn systemd-Override:
```bash
ssh root@100.115.184.3 "systemctl edit jarvis"
# Füge hinzu: Environment=GROQ_API_KEY=gsk_DEIN_KEY_HIER
```

- [ ] **Step 4: Paket installieren + deployen**

```bash
ssh root@100.115.184.3 "
  cd /root/agents && \
  git pull && \
  venv/bin/pip install groq && \
  systemctl restart jarvis
"
```

- [ ] **Step 5: Logs prüfen**

```bash
ssh root@100.115.184.3 "journalctl -u jarvis -n 20 --no-pager"
```

Erwartete Ausgabe: `Jarvis gestartet` ohne Fehler.

- [ ] **Step 6: Testen**

Sende eine Telegram-Sprachnachricht an Jarvis, z.B.: *„Was kostet Bitcoin gerade?"*

Erwartetes Verhalten:
1. Jarvis antwortet mit einer normalen Textnachricht (keine Fehlermeldung)
2. Die Antwort behandelt die transkribierte Frage — in diesem Fall eine Research-Anfrage mit Web-Suche
3. In den Logs erscheint: `Intent: research | Nachricht: Was kostet Bitcoin gerade?`
