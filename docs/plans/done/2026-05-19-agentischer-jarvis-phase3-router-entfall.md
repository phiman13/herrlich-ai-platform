# Agentischer Jarvis Phase 3 — Router-Entfall Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Router (`route_with_llm`) und alle direkten Intent-Handler entfernen — jede Nachricht läuft direkt durch `run_agent`; Briefing und Memory werden zu Tools.

**Architecture:** `briefing_tool.py` (statisch, read-only) und `memory_tool.py` (Factory, staged delete) werden als neue MCP-Tools registriert. `dispatch._process_text` kollabiert zu einem einfachen Orchestrator: immer Kontext laden, immer `run_agent` rufen, immer speichern. `router.py` wird gelöscht.

**Tech Stack:** Python 3.11 · claude-agent-sdk (`@tool`) · pytest-asyncio

---

## File Structure

```
agents/tools/
  briefing_tool.py          NEU  — statisches @tool, action='build'
  memory_tool.py            NEU  — make_memory_tool(chat_id)-Factory, execute_write
  __init__.py               MODIFY — briefing + memory registrieren
agents/
  dispatch.py               MODIFY — Router-Import weg, _process_text kollabiert
  intent_handlers.py        MODIFY — handle_briefing + handle_memory entfernen
  agent.py                  MODIFY — Briefing + Memory in build_system_prompt
  router.py                 DELETE
  CLAUDE.md                 MODIFY — Architektur-Diagramm + Agentischer-Pfad-Abschnitt
tests/
  test_tools_briefing.py    NEU
  test_tools_memory.py      NEU
  test_tools_registry.py    MODIFY — briefing + memory prüfen
  test_agent_dispatch.py    MODIFY — router_with_llm-Patches entfernen
  test_dispatch_main.py     MODIFY — router-Patches entfernen, neue Tests
  test_router_context.py    DELETE
  test_router_memory.py     DELETE
```

---

## Task 1: `briefing_tool.py` + Tests

**Files:**
- Create: `agents/tools/briefing_tool.py`
- Create: `tests/test_tools_briefing.py`

- [ ] **Step 1: Failing test schreiben**

```python
# tests/test_tools_briefing.py
"""Tests für agents/tools/briefing_tool.py."""

import pytest
import tools.briefing_tool as briefing_tool_mod


@pytest.mark.asyncio
async def test_build_returns_briefing_text(monkeypatch):
    async def fake_briefing():
        return "Guten Morgen! Heute 22°C."

    monkeypatch.setattr(briefing_tool_mod, "_build_briefing", fake_briefing)
    result = await briefing_tool_mod.briefing_tool.handler({"action": "build"})
    assert "Guten Morgen" in result["content"][0]["text"]


@pytest.mark.asyncio
async def test_build_unknown_action_is_error(monkeypatch):
    async def fake_briefing():
        return "x"

    monkeypatch.setattr(briefing_tool_mod, "_build_briefing", fake_briefing)
    result = await briefing_tool_mod.briefing_tool.handler({"action": "frobnicate"})
    assert result["content"][0]["text"].startswith("FEHLER")


@pytest.mark.asyncio
async def test_build_empty_action_is_error(monkeypatch):
    async def fake_briefing():
        return "x"

    monkeypatch.setattr(briefing_tool_mod, "_build_briefing", fake_briefing)
    result = await briefing_tool_mod.briefing_tool.handler({})
    assert result["content"][0]["text"].startswith("FEHLER")
```

- [ ] **Step 2: Test ausführen — muss FAIL mit ImportError**

```bash
PYTHONPATH=agents pytest tests/test_tools_briefing.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'tools.briefing_tool'`

- [ ] **Step 3: `briefing_tool.py` implementieren**

```python
# agents/tools/briefing_tool.py
"""briefing-Tool — Morgenbriefing abrufen. Read-only, statisch.

Kein chat_id nötig, da keine Schreib-Aktionen.
"""

from claude_agent_sdk import tool

from briefing_agent import build_briefing as _build_briefing


@tool(
    "briefing",
    "Morgenbriefing abrufen — Wetter, Kalender, offene Tasks, wichtige Mails, "
    "GitHub-Aktivität und News. action='build': Briefing jetzt erstellen.",
    {"action": str},
)
async def briefing_tool(args: dict) -> dict:
    action = (args.get("action") or "").strip()
    if action == "build":
        result = await _build_briefing()
        return {"content": [{"type": "text", "text": result}]}
    return {
        "content": [
            {
                "type": "text",
                "text": f"FEHLER: Unbekannte action '{action}'. Erlaubt: build.",
            }
        ]
    }
```

- [ ] **Step 4: Tests ausführen — müssen PASS**

```bash
PYTHONPATH=agents pytest tests/test_tools_briefing.py -v
```

Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add agents/tools/briefing_tool.py tests/test_tools_briefing.py
git commit -m "feat(tools): briefing_tool — statisches @tool, action='build'"
```

---

## Task 2: `memory_tool.py` + Tests

**Files:**
- Create: `agents/tools/memory_tool.py`
- Create: `tests/test_tools_memory.py`

- [ ] **Step 1: Failing tests schreiben**

```python
# tests/test_tools_memory.py
"""Tests für agents/tools/memory_tool.py."""

import pytest
import app_state
import tools.memory_tool as memory_tool_mod


class _MockMemoryAgent:
    def __init__(self, list_result="Liste", delete_result="✅ Gelöscht"):
        self._list_result = list_result
        self._delete_result = delete_result
        self.delete_calls = []

    async def list_memories(self):
        return self._list_result

    async def delete_memory(self, query):
        self.delete_calls.append(query)
        return self._delete_result


@pytest.mark.asyncio
async def test_list_reads_immediately(monkeypatch):
    app_state.pending_agent_actions.clear()
    agent = _MockMemoryAgent(list_result="🧠 *Erinnerungen:*\n• Mag Kaffee")
    app_state.memory_agent = agent
    try:
        tool = memory_tool_mod.make_memory_tool(7)
        result = await tool.handler({"action": "list"})
        assert "Erinnerungen" in result["content"][0]["text"]
        assert app_state.peek_pending(7) is None
    finally:
        app_state.memory_agent = None


@pytest.mark.asyncio
async def test_list_no_memory_agent():
    app_state.pending_agent_actions.clear()
    app_state.memory_agent = None
    tool = memory_tool_mod.make_memory_tool(7)
    result = await tool.handler({"action": "list"})
    assert "FEHLER" in result["content"][0]["text"] or "nicht" in result["content"][0]["text"].lower()
    assert app_state.peek_pending(7) is None


@pytest.mark.asyncio
async def test_delete_stages_not_executes(monkeypatch):
    app_state.pending_agent_actions.clear()
    agent = _MockMemoryAgent()
    app_state.memory_agent = agent
    try:
        tool = memory_tool_mod.make_memory_tool(7)
        result = await tool.handler({"action": "delete", "query": "Kaffee"})
        assert agent.delete_calls == []
        assert "vorgemerkt" in result["content"][0]["text"].lower()
        entry = app_state.peek_pending(7)
        assert entry is not None
        a = entry["actions"][0]
        assert a["tool"] == "memory"
        assert a["action"] == "delete"
        assert a["params"]["query"] == "Kaffee"
    finally:
        app_state.memory_agent = None
        app_state.pending_agent_actions.clear()


@pytest.mark.asyncio
async def test_delete_without_query_stages_last(monkeypatch):
    app_state.pending_agent_actions.clear()
    agent = _MockMemoryAgent()
    app_state.memory_agent = agent
    try:
        tool = memory_tool_mod.make_memory_tool(7)
        result = await tool.handler({"action": "delete"})
        assert agent.delete_calls == []
        assert "vorgemerkt" in result["content"][0]["text"].lower()
        entry = app_state.peek_pending(7)
        assert entry is not None
        a = entry["actions"][0]
        assert a["params"]["query"] is None
    finally:
        app_state.memory_agent = None
        app_state.pending_agent_actions.clear()


@pytest.mark.asyncio
async def test_unknown_action_is_error():
    app_state.memory_agent = None
    tool = memory_tool_mod.make_memory_tool(7)
    result = await tool.handler({"action": "frobnicate"})
    assert result["content"][0]["text"].startswith("FEHLER")


@pytest.mark.asyncio
async def test_execute_write_delete_with_query():
    agent = _MockMemoryAgent(delete_result="✅ Erinnerung gelöscht: _Mag Kaffee_")
    app_state.memory_agent = agent
    try:
        msg = await memory_tool_mod.execute_write("delete", {"query": "Kaffee"})
        assert agent.delete_calls == ["Kaffee"]
        assert "✅" in msg
    finally:
        app_state.memory_agent = None


@pytest.mark.asyncio
async def test_execute_write_delete_without_query():
    agent = _MockMemoryAgent(delete_result="✅ Letzte Erinnerung gelöscht.")
    app_state.memory_agent = agent
    try:
        msg = await memory_tool_mod.execute_write("delete", {"query": None})
        assert agent.delete_calls == [None]
        assert "✅" in msg
    finally:
        app_state.memory_agent = None


@pytest.mark.asyncio
async def test_execute_write_no_memory_agent():
    app_state.memory_agent = None
    msg = await memory_tool_mod.execute_write("delete", {"query": None})
    assert "❌" in msg


@pytest.mark.asyncio
async def test_execute_write_unknown_action():
    msg = await memory_tool_mod.execute_write("frobnicate", {})
    assert "Unbekannte" in msg or "❌" in msg
```

- [ ] **Step 2: Tests ausführen — FAIL**

```bash
PYTHONPATH=agents pytest tests/test_tools_memory.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'tools.memory_tool'`

- [ ] **Step 3: `memory_tool.py` implementieren**

```python
# agents/tools/memory_tool.py
"""memory-Tool — Erinnerungen auflisten und löschen.

action='list' läuft sofort. action='delete' wird vorgemerkt und erst nach
Philipps Bestätigung ausgeführt.
"""

from claude_agent_sdk import tool

import app_state


_WRITE_ACTIONS = {"delete"}


def _text(msg: str) -> dict:
    return {"content": [{"type": "text", "text": msg}]}


def make_memory_tool(chat_id: int):
    """Baut das memory-Tool für einen Lauf — chat_id für das Vormerken."""

    @tool(
        "memory",
        "Erinnerungen über Philipp verwalten. "
        "action='list': Alle gespeicherten Erinnerungen anzeigen. "
        "action='delete' (query optional): Eine Erinnerung löschen — query ist die "
        "Beschreibung; leer = letzte Erinnerung löschen. "
        "delete wird vorgemerkt und erst nach Philipps Bestätigung ausgeführt "
        "— sag ihm, was du vorbereitet hast.",
        {"action": str, "query": str},
    )
    async def memory_tool(args: dict) -> dict:
        action = (args.get("action") or "").strip()

        if action == "list":
            if not app_state.memory_agent:
                return _text("FEHLER: Memory-Agent nicht verfügbar.")
            result = await app_state.memory_agent.list_memories()
            return _text(result)

        if action not in _WRITE_ACTIONS:
            return _text(
                f"FEHLER: Unbekannte action '{action}'. Erlaubt: list, delete."
            )

        # delete: staged
        query = (args.get("query") or "").strip() or None
        label = (
            f"Erinnerung löschen: {query[:60]}"
            if query
            else "Letzte Erinnerung löschen"
        )
        params = {"query": query}
        app_state.stage_agent_action(chat_id, "memory", action, label, params)
        return _text(
            f"✅ Vorgemerkt: {label}. Wird nach Philipps Bestätigung ausgeführt "
            "— du musst nicht warten."
        )

    return memory_tool


async def execute_write(action: str, params: dict) -> str:
    """Eine vorgemerkte memory-Schreibaktion ausführen."""
    if action == "delete":
        if not app_state.memory_agent:
            return "❌ Memory-Agent nicht verfügbar."
        return await app_state.memory_agent.delete_memory(params.get("query"))
    return f"❌ Unbekannte memory-Aktion '{action}'."
```

- [ ] **Step 4: Tests ausführen — PASS**

```bash
PYTHONPATH=agents pytest tests/test_tools_memory.py -v
```

Expected: 9 PASS

- [ ] **Step 5: Commit**

```bash
git add agents/tools/memory_tool.py tests/test_tools_memory.py
git commit -m "feat(tools): memory_tool — list sofort, delete staged"
```

---

## Task 3: Router-Entfall — Verdrahtung + Cleanup

**Files:**
- Modify: `agents/tools/__init__.py`
- Modify: `agents/agent.py`
- Modify: `agents/dispatch.py`
- Modify: `agents/intent_handlers.py`
- Modify: `tests/test_tools_registry.py`
- Modify: `tests/test_agent_dispatch.py`
- Modify: `tests/test_dispatch_main.py`
- Modify: `CLAUDE.md`
- Delete: `agents/router.py`
- Delete: `tests/test_router_context.py`
- Delete: `tests/test_router_memory.py`

- [ ] **Step 1: `tools/__init__.py` — briefing + memory registrieren**

In `agents/tools/__init__.py`:

1. Ergänze die Import-Zeilen nach den bestehenden Submodul-Importen:
```python
from . import briefing_tool
from . import memory_tool
```

2. Ergänze `_STATIC_TOOLS`:
```python
_STATIC_TOOLS = [_workspace_capability, _weather_capability, _news_capability, briefing_tool.briefing_tool]
```

3. Ergänze `_all_tools` um `memory_tool`:
```python
def _all_tools(chat_id: int) -> list:
    return _STATIC_TOOLS + [
        tasks_tool.make_tasks_tool(chat_id),
        mail_tool.make_mail_tool(chat_id),
        calendar_tool.make_calendar_tool(chat_id),
        coding_tool.make_coding_tool(chat_id),
        memory_tool.make_memory_tool(chat_id),
    ]
```

4. Ergänze `_WRITE_EXECUTORS`:
```python
_WRITE_EXECUTORS: dict = {
    "tasks": tasks_tool.execute_write,
    "mail": mail_tool.execute_write,
    "calendar": calendar_tool.execute_write,
    "coding": coding_tool.execute_write,
    "memory": memory_tool.execute_write,
}
```

- [ ] **Step 2: `agent.py` — build_system_prompt ergänzen**

In `agents/agent.py`, in der `build_system_prompt`-Funktion, hänge nach der `coding`-Zeile und vor dem `WebSearch`-Absatz Folgendes an:

```python
        "- briefing: Morgenbriefing abrufen (Wetter, Kalender, Tasks, Mails, GitHub, News). "
        "action='build': Briefing jetzt erstellen.\n"
        "- memory: Erinnerungen über Philipp verwalten. action='list': alle anzeigen. "
        "action='delete' (query optional): eine löschen — staged, erst nach Bestätigung.\n"
```

Die vollständige Sektion sieht danach so aus (Reihenfolge der Werkzeuge):
workspace → weather → news → tasks → mail → calendar → coding → briefing → memory → WebSearch/WebFetch

- [ ] **Step 3: `test_tools_registry.py` — briefing + memory prüfen**

Ergänze in `tests/test_tools_registry.py` in `test_build_mcp_server_registers_tools`:

```python
    assert "mcp__jarvis__briefing" in tools._ALLOWED_TOOL_NAMES
    assert "mcp__jarvis__memory" in tools._ALLOWED_TOOL_NAMES
```

Ergänze einen weiteren Test:

```python
def test_memory_in_write_executors():
    assert "memory" in tools._WRITE_EXECUTORS


def test_briefing_not_in_write_executors():
    assert "briefing" not in tools._WRITE_EXECUTORS
```

- [ ] **Step 4: Registry-Tests ausführen**

```bash
PYTHONPATH=agents pytest tests/test_tools_registry.py -v
```

Expected: alle grün

- [ ] **Step 5: `dispatch.py` kollabieren**

Ersetze `agents/dispatch.py` vollständig mit:

```python
"""Telegram message dispatch — routing-free orchestrator."""

import asyncio
import logging

from telegram import Update

import app_state
from voice_agent import transcribe
from agent import run_agent

logger = logging.getLogger("jarvis.dispatch")


async def start(update, context):
    await update.message.reply_text(
        "Hallo Philipp! Ich bin Jarvis.\n\n"
        "Coding (Frage): 'Was sind die Todos in recipe-app?'\n"
        "Coding (Aktion): 'Fixe den Login-Bug in recipe-app'\n"
        "Research: 'Recherchiere: ESG Pflichten 2026'\n"
        "Work: 'Fass mir diesen Text zusammen'\n"
        "Personal: 'Was sind gute Laufschuhe?'"
    )


async def _process_text(text: str, chat_id: int, update: Update) -> None:
    memory_context = ""
    if app_state.profile_agent:
        try:
            profile = app_state.profile_agent.load()
            memory_context += f"=== Philipps Profil ===\n{profile}\n\n"
        except Exception as e:
            logger.warning("Profile load failed: %s", e)
    if app_state.memory_agent:
        try:
            memories = await app_state.memory_agent.retrieve()
            if memories:
                bullet_list = "\n".join(f"• {m}" for m in memories)
                memory_context += f"=== Erinnerungen ===\n{bullet_list}\n\n"
        except Exception as e:
            logger.warning("Memory retrieval failed: %s", e)

    history: list[dict] = []
    if app_state.conversation_db:
        try:
            history = await app_state.conversation_db.get_recent(chat_id, n=20)
        except Exception as e:
            logger.warning("History load failed: %s", e)

    answer = await run_agent(chat_id, text, history, memory_context)

    if app_state.conversation_db and answer and not answer.startswith("Fehler:"):
        try:
            await app_state.conversation_db.save(chat_id, "user", text)
            await app_state.conversation_db.save(chat_id, "assistant", answer)
        except Exception as e:
            logger.warning("History save failed: %s", e)

    if app_state.profile_agent and answer and not answer.startswith("Fehler:"):
        conversation = f"Philipp: {text}\n\nJarvis: {answer}"
        asyncio.create_task(app_state.profile_agent.update(conversation))


async def handle_message(update, context):
    update_id = update.update_id
    if update_id in app_state.processed_updates:
        logger.info(f"Duplikat ignoriert: update_id={update_id}")
        return
    app_state.processed_updates.add(update_id)
    if len(app_state.processed_updates) > 1000:
        app_state.processed_updates.clear()

    text = update.message.text
    chat_id = update.message.chat_id
    await _process_text(text, chat_id, update)


async def handle_voice(update, context):
    update_id = update.update_id
    if update_id in app_state.processed_updates:
        logger.info(f"Duplikat ignoriert: update_id={update_id}")
        return
    app_state.processed_updates.add(update_id)
    if len(app_state.processed_updates) > 1000:
        app_state.processed_updates.clear()

    chat_id = update.message.chat_id
    try:
        voice_file = await update.message.voice.get_file()
        ogg_bytes = bytes(await voice_file.download_as_bytearray())
        text = await transcribe(ogg_bytes)
    except Exception as e:
        logger.warning("Voice transcription failed: %s", e)
        await update.message.reply_text(
            "❌ Sprachnachricht konnte nicht transkribiert werden."
        )
        return

    await _process_text(text, chat_id, update)
```

- [ ] **Step 6: `intent_handlers.py` — handle_briefing + handle_memory entfernen**

Ersetze `agents/intent_handlers.py` vollständig mit:

```python
"""Lean intent handlers — send_briefing für APScheduler-Proaktiv-Job."""

import logging
import os

from telegram import Bot

from briefing_agent import build_briefing

logger = logging.getLogger("jarvis.intent_handlers")


async def send_briefing():
    chat_id_str = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not chat_id_str:
        logger.warning("TELEGRAM_CHAT_ID nicht gesetzt — Briefing übersprungen")
        return
    bot = Bot(token=os.environ["TELEGRAM_BOT_TOKEN"])
    try:
        msg = await build_briefing()
        try:
            await bot.send_message(
                chat_id=int(chat_id_str), text=msg, parse_mode="Markdown"
            )
        except Exception:
            await bot.send_message(chat_id=int(chat_id_str), text=msg)
    except Exception as e:
        logger.exception(f"Briefing-Fehler: {e}")
```

- [ ] **Step 7: `router.py` und Router-Tests löschen**

```bash
rm agents/router.py tests/test_router_context.py tests/test_router_memory.py
```

- [ ] **Step 8: `test_agent_dispatch.py` ersetzen**

Ersetze `tests/test_agent_dispatch.py` vollständig mit:

```python
"""Tests für dispatch._process_text — ohne Router, run_agent immer."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app_state
import dispatch


@pytest.mark.asyncio
async def test_any_message_calls_run_agent():
    app_state.conversation_db = None
    app_state.profile_agent = None
    app_state.memory_agent = None
    update = MagicMock()
    with patch("dispatch.run_agent", new=AsyncMock(return_value="Antwort")) as mock_run:
        await dispatch._process_text("Hallo", 123, update)
    mock_run.assert_awaited_once()


@pytest.mark.asyncio
async def test_profile_updated_after_any_message():
    """Profil-Update läuft jetzt für alle Nachrichten, nicht nur MEMORY_INTENTS."""
    app_state.conversation_db = None
    app_state.memory_agent = None
    mock_profile = MagicMock()
    mock_profile.load.return_value = ""
    mock_profile.update = AsyncMock()
    app_state.profile_agent = mock_profile
    update = MagicMock()
    try:
        with patch("dispatch.run_agent", new=AsyncMock(return_value="Wetter-Antwort")):
            await dispatch._process_text("Wetter morgen?", 123, update)
    finally:
        app_state.profile_agent = None
    mock_profile.update.assert_called_once()


@pytest.mark.asyncio
async def test_answer_persisted_to_conversation_db():
    app_state.profile_agent = None
    app_state.memory_agent = None
    mock_conv_db = MagicMock()
    mock_conv_db.get_recent = AsyncMock(return_value=[])
    mock_conv_db.save = AsyncMock()
    app_state.conversation_db = mock_conv_db
    update = MagicMock()
    try:
        with patch("dispatch.run_agent", new=AsyncMock(return_value="Agent-Antwort")):
            await dispatch._process_text("Frage", 123, update)
    finally:
        app_state.conversation_db = None
    assert mock_conv_db.save.await_count == 2
    saved_roles = [call.args[1] for call in mock_conv_db.save.await_args_list]
    assert saved_roles == ["user", "assistant"]


@pytest.mark.asyncio
async def test_no_router_in_dispatch():
    import dispatch as dispatch_mod

    assert not hasattr(dispatch_mod, "route_with_llm")
```

- [ ] **Step 9: `test_dispatch_main.py` ersetzen**

Ersetze `tests/test_dispatch_main.py` vollständig mit:

```python
# tests/test_dispatch_main.py
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import dispatch as main
import app_state


@pytest.fixture(autouse=True)
def clear_processed_updates():
    app_state.processed_updates.clear()
    yield
    app_state.processed_updates.clear()


def _make_update(text, chat_id=123, update_id=90001):
    update = MagicMock()
    update.update_id = update_id
    update.message.text = text
    update.message.chat_id = chat_id
    update.message.reply_text = AsyncMock()
    return update


def test_any_message_dispatches_to_run_agent():
    """Ohne Router läuft jede Nachricht direkt durch run_agent."""
    app_state.conversation_db = None
    app_state.profile_agent = None
    app_state.memory_agent = None
    with patch(
        "dispatch.run_agent", new_callable=AsyncMock, return_value="Antwort"
    ) as mock_agent:
        asyncio.run(main.handle_message(_make_update("Hallo"), None))
    mock_agent.assert_awaited_once()


def test_no_router_import():
    """Router-Import ist weg."""
    import dispatch as dispatch_mod

    assert not hasattr(dispatch_mod, "route_with_llm")


def test_no_direct_handler_imports():
    """handle_briefing und handle_memory sind nicht mehr in dispatch."""
    import dispatch as dispatch_mod

    assert not hasattr(dispatch_mod, "handle_briefing")
    assert not hasattr(dispatch_mod, "handle_memory")
```

- [ ] **Step 10: Alle Tests ausführen**

```bash
PYTHONPATH=agents pytest tests/ -v --tb=short
```

Expected: alle grün (vorher 249, jetzt mehr durch neue Tests)

- [ ] **Step 11: `CLAUDE.md` aktualisieren**

Ändere in `agents/CLAUDE.md` das Architektur-Diagramm:

Alt:
```
        ▼
agents/router.py            Claude Haiku — klassifiziert Intent
        │                   Input: aktueller Text + letzte 3 User-Nachrichten
        │                   Output: {intent, confidence, params, reasoning}
        │
        ├── mail            mail_agent.py
        ├── calendar        calendar_agent.py
        ├── briefing        briefing_agent.py
        ├── coding          coding_agent.py + github_agent.py
        ├── memory          memory_agent.py
        ├── personal      ┐
        ├── work          │
        ├── research      ├─ agent.py run_agent — echter Agent (Claude Agent SDK):
        ├── weather       │  Tools workspace/web/weather/news/tasks, Denk-Schleife,
        ├── news          │  History, MemoryAgent, Write-Confirm
        ├── tasks         │
        └── reminder_write┘
```

Neu:
```
        ▼
agents/agent.py run_agent   Claude Agent SDK — alle Nachrichten
        │                   Tools: workspace/weather/news/tasks/mail/calendar/
        │                   coding/briefing/memory + WebSearch/WebFetch
        │                   History, MemoryAgent, Write-Confirm
        │
```

Lösche aus der Struktur-Liste: `router.py`

Aktualisiere den Abschnitt „Agentischer Pfad — Phase 1" → umbenennen in „Agentischer Pfad (Phase 1+2+3 abgeschlossen)" und passe den Inhalt an:
- Alle Intents laufen durch `run_agent`
- Werkzeuge: workspace, weather, news, tasks, mail, calendar, coding, briefing, memory
- Router entfallen

- [ ] **Step 12: Commit**

```bash
git add agents/tools/__init__.py agents/agent.py agents/dispatch.py \
        agents/intent_handlers.py CLAUDE.md \
        tests/test_tools_registry.py tests/test_agent_dispatch.py \
        tests/test_dispatch_main.py
git rm agents/router.py tests/test_router_context.py tests/test_router_memory.py
git commit -m "feat(phase3): Router-Entfall — dispatch kollabiert, briefing+memory als Tools"
git push
```

---

## Self-Review

**Spec coverage:**
- ✅ `briefing_tool.py` statisches `@tool`, `action='build'` → `build_briefing()`
- ✅ `memory_tool.py` Factory, `list` sofort, `delete` staged
- ✅ `dispatch._process_text` kollabiert, immer alle Kontext-Quellen laden
- ✅ `router.py` gelöscht
- ✅ `handle_briefing` + `handle_memory` aus `intent_handlers.py` entfernt (send_briefing bleibt)
- ✅ `tools/__init__.py` briefing + memory registriert
- ✅ `build_system_prompt` briefing + memory ergänzt
- ✅ Router-Tests gelöscht, Dispatch-Tests auf neuen Stand gebracht
- ✅ CLAUDE.md aktualisiert

**Placeholder-Scan:** Kein TBD/TODO/implement later in diesem Plan.

**Type consistency:** `execute_write(action: str, params: dict) -> str` konsistent mit anderen Tool-Modulen. `make_memory_tool(chat_id: int)` konsistent mit anderen Factory-Funktionen.
