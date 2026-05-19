# coding als Agent-Tool — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Konvertiere den `coding`-Intent vom direkten Handler zum Agenten-Tool, das denselben agentischen Pfad wie `mail`, `calendar` und `tasks` nutzt.

**Architecture:** `coding_tool.py` folgt dem etablierten Pattern aus Plan 3/4: `make_coding_tool(chat_id)` Factory + `execute_write(action, params)` + `_WRITE_ACTIONS`-Set. Besonderheit: `run` ist kein staged Write, sondern fire-and-forget — `asyncio.create_task(run_coding_action(...))` läuft sofort im Hintergrund und benachrichtigt Philipp direkt per Telegram. Nur `backlog_write` durchläuft Write-Confirm. Read-Aktionen (`query`, `list_projects`) laufen sofort.

**Tech Stack:** Python 3.11, asyncio, claude_agent_sdk.tool, pytest-asyncio, coding_agent.py (bestehend — wird nicht gelöscht)

---

## Datei-Überblick

**Neu:**
- `agents/tools/coding_tool.py` — coding-Tool Factory + execute_write
- `tests/test_tools_coding.py` — Unit-Tests

**Geändert:**
- `agents/tools/__init__.py` — coding_tool registrieren
- `agents/dispatch.py` — coding in `_AGENT_INTENTS` + `_HISTORY_INTENTS`; handle_coding-Import + elif-Branch entfernen
- `agents/agent.py` — System-Prompt: coding Werkzeug-Hinweis
- `agents/intent_handlers.py` — `handle_coding` Funktion + zugehörige Imports entfernen
- `CLAUDE.md` — Architektur-Diagramm + Tabellen aktualisieren

**Nicht gelöscht:**
- `agents/coding_agent.py` — Logik bleibt vollständig erhalten, nur der Aufruf-Pfad ändert sich
- `agents/intent_handlers.py` — bleibt (handle_briefing + handle_memory bleiben drin)
- `tests/test_coding_agent.py` — bleibt (testet coding_agent.py direkt)

---

## Task 1: `coding_tool.py` + Tests

**Files:**
- Create: `agents/tools/coding_tool.py`
- Create: `tests/test_tools_coding.py`

### Hintergrundwissen für den Implementer

**`coding_agent.py`-Funktionen (alle async):**
- `handle_coding_query(project, query_type)` → `str` — liest Datei/Git direkt, kein Claude Code
- `run_coding_action(task, project, chat_id)` → None — startet Claude Code im Hintergrund, sendet selbst Telegram-Nachrichten, dauert Minuten
- `add_backlog_item(project, item, priority)` → `bool` — schreibt BACKLOG.md + git push

**`vps.list_projects()`** — async, liefert `list[str]` aller geklonten Projekte im Workspace

**`conftest.py`** hat ein `autouse=True`-Fixture `mock_ensure_init`, das `coding_agent._ensure_init` in Tests patcht — keine manuelle DB-Init in Tests nötig.

**Besonderheit `run`-Aktion:** Kein Staging! `asyncio.create_task(run_coding_action(task, project, chat_id))` feuert sofort. Der Grund: Der Nutzer hat mit seiner Nachricht bereits bestätigt. `run_coding_action` sendet seine eigenen Telegram-Statusmeldungen. Tests müssen `asyncio.sleep(0)` aufrufen, damit der Task einen Zyklus laufen kann.

- [ ] **Step 1: Failenden Test schreiben**

Datei `tests/test_tools_coding.py` anlegen:

```python
"""Tests für agents/tools/coding_tool.py."""

import asyncio
import pytest
from unittest.mock import AsyncMock

import app_state
import tools.coding_tool as coding_tool_mod


# ── Helpers ──────────────────────────────────────────────────────────────────


def _text_of(result):
    return result["content"][0]["text"]


# ── Read-only: sofort ausführen ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_projects_reads_immediately(monkeypatch):
    monkeypatch.setattr(
        coding_tool_mod,
        "_list_projects",
        AsyncMock(return_value=["recipe-app", "immo-radar"]),
    )
    tool = coding_tool_mod.make_coding_tool(7)
    result = await tool.handler({"action": "list_projects"})
    text = _text_of(result)
    assert "recipe-app" in text
    assert "immo-radar" in text
    assert app_state.peek_pending(7) is None


@pytest.mark.asyncio
async def test_query_reads_immediately(monkeypatch):
    monkeypatch.setattr(
        coding_tool_mod,
        "handle_coding_query",
        AsyncMock(return_value="# Backlog\n- [ ] Fix login"),
    )
    tool = coding_tool_mod.make_coding_tool(7)
    result = await tool.handler(
        {"action": "query", "project": "recipe-app", "query_type": "backlog"}
    )
    text = _text_of(result)
    assert "Fix login" in text
    assert app_state.peek_pending(7) is None


@pytest.mark.asyncio
async def test_query_requires_project_and_query_type():
    tool = coding_tool_mod.make_coding_tool(7)
    result = await tool.handler({"action": "query", "project": "recipe-app"})
    assert _text_of(result).startswith("FEHLER")


# ── run: sofort feuern, NICHT vormerken ──────────────────────────────────────


@pytest.mark.asyncio
async def test_run_fires_background_task(monkeypatch):
    app_state.pending_agent_actions.clear()
    ran = []

    async def _fake_run(task, project, chat_id):
        ran.append((task, project, chat_id))

    monkeypatch.setattr(coding_tool_mod, "run_coding_action", _fake_run)
    tool = coding_tool_mod.make_coding_tool(7)
    result = await tool.handler(
        {"action": "run", "project": "recipe-app", "task": "Fix the login bug"}
    )
    await asyncio.sleep(0)  # ein Event-Loop-Tick — Background-Task läuft
    assert ran == [("Fix the login bug", "recipe-app", 7)]
    assert "Hintergrund" in _text_of(result)
    assert app_state.peek_pending(7) is None  # explizit: NICHT staged
    app_state.pending_agent_actions.clear()


@pytest.mark.asyncio
async def test_run_requires_project_and_task(monkeypatch):
    monkeypatch.setattr(coding_tool_mod, "run_coding_action", AsyncMock())
    tool = coding_tool_mod.make_coding_tool(7)
    result = await tool.handler({"action": "run", "task": "Fix bug"})
    assert _text_of(result).startswith("FEHLER")


# ── backlog_write: vormerken, nicht ausführen ─────────────────────────────────


@pytest.mark.asyncio
async def test_backlog_write_stages_not_executes(monkeypatch):
    app_state.pending_agent_actions.clear()
    called = []
    monkeypatch.setattr(
        coding_tool_mod,
        "add_backlog_item",
        AsyncMock(side_effect=lambda *a: called.append(a) or True),
    )
    tool = coding_tool_mod.make_coding_tool(7)
    result = await tool.handler(
        {
            "action": "backlog_write",
            "project": "recipe-app",
            "item": "Dark mode implementieren",
            "priority": "P1",
        }
    )
    assert called == []
    assert "vorgemerkt" in _text_of(result).lower()
    entry = app_state.peek_pending(7)
    assert entry is not None
    a = entry["actions"][0]
    assert a["tool"] == "coding"
    assert a["action"] == "backlog_write"
    assert a["params"]["item"] == "Dark mode implementieren"
    assert a["params"]["project"] == "recipe-app"
    app_state.pending_agent_actions.clear()


@pytest.mark.asyncio
async def test_backlog_write_requires_project_and_item():
    app_state.pending_agent_actions.clear()
    tool = coding_tool_mod.make_coding_tool(7)
    result = await tool.handler({"action": "backlog_write", "item": "Fix bug"})
    assert _text_of(result).startswith("FEHLER")
    assert app_state.peek_pending(7) is None


@pytest.mark.asyncio
async def test_backlog_write_default_priority(monkeypatch):
    """Kein priority-Argument → Default 'P1' im gestagten params."""
    app_state.pending_agent_actions.clear()
    tool = coding_tool_mod.make_coding_tool(7)
    await tool.handler(
        {"action": "backlog_write", "project": "recipe-app", "item": "Neues Feature"}
    )
    entry = app_state.peek_pending(7)
    assert entry["actions"][0]["params"]["priority"] == "P1"
    app_state.pending_agent_actions.clear()


@pytest.mark.asyncio
async def test_unknown_action_is_error():
    tool = coding_tool_mod.make_coding_tool(7)
    result = await tool.handler({"action": "frobnicate"})
    assert _text_of(result).startswith("FEHLER")


# ── execute_write ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_write_backlog_write_success(monkeypatch):
    calls = []
    monkeypatch.setattr(
        coding_tool_mod,
        "add_backlog_item",
        AsyncMock(side_effect=lambda p, i, prio: calls.append((p, i, prio)) or True),
    )
    msg = await coding_tool_mod.execute_write(
        "backlog_write",
        {"project": "recipe-app", "item": "Dark mode", "priority": "P2"},
    )
    assert calls == [("recipe-app", "Dark mode", "P2")]
    assert "✅" in msg
    assert "recipe-app" in msg


@pytest.mark.asyncio
async def test_execute_write_backlog_write_failure(monkeypatch):
    monkeypatch.setattr(
        coding_tool_mod, "add_backlog_item", AsyncMock(return_value=False)
    )
    msg = await coding_tool_mod.execute_write(
        "backlog_write",
        {"project": "recipe-app", "item": "Dark mode", "priority": "P1"},
    )
    assert "❌" in msg
    assert "recipe-app" in msg


@pytest.mark.asyncio
async def test_execute_write_unknown_action():
    msg = await coding_tool_mod.execute_write("frobnicate", {})
    assert "Unbekannte" in msg
```

- [ ] **Step 2: Test laufen lassen — muss scheitern**

```bash
cd /Users/philippherrlich/Code/herrlich-ai-platform
PYTHONPATH=agents .venv/bin/pytest tests/test_tools_coding.py -v 2>&1 | head -20
```

Erwartetes Ergebnis: `ModuleNotFoundError` oder `ImportError` (Modul existiert noch nicht).

- [ ] **Step 3: `agents/tools/coding_tool.py` implementieren**

```python
"""coding-Tool — Projekte lesen, Backlog schreiben, Claude Code starten.

Read-Aktionen (list_projects, query) laufen sofort.
action='run' startet Claude Code als asyncio-Background-Task — kein Staging,
weil run_coding_action seine eigenen Telegram-Updates sendet.
action='backlog_write' wird vorgemerkt und erst nach Philipps Bestätigung ausgeführt.
"""

import asyncio

from claude_agent_sdk import tool

import app_state
from coding_agent import add_backlog_item, handle_coding_query, run_coding_action
from vps import list_projects as _list_projects

_WRITE_ACTIONS = {"backlog_write"}


def _label(action: str, params: dict) -> str:
    if action == "backlog_write":
        prio = params.get("priority", "P1")
        return f"Backlog-Item in '{params['project']}' ({prio}): {params['item'][:60]}"
    return action


def _missing_fields(action: str, params: dict) -> str:
    required = {
        "backlog_write": ("project", "item"),
    }[action]
    return ", ".join(f for f in required if not params.get(f))


def _text(msg: str) -> dict:
    return {"content": [{"type": "text", "text": msg}]}


def make_coding_tool(chat_id: int):
    """Baut das coding-Tool für einen Lauf — chat_id für das Vormerken."""

    @tool(
        "coding",
        "Projekte lesen, Backlog verwalten und Claude Code starten. "
        "action='list_projects': Alle Projekte im Workspace auflisten. "
        "action='query' (project, query_type): Projekt-Infos lesen — "
        "query_type: 'backlog', 'git_log', 'readme', 'claude_md'. "
        "action='run' (project, task): Claude Code im Hintergrund starten — "
        "läuft SOFORT ohne Confirm; Philipp wird direkt per Telegram benachrichtigt. "
        "action='backlog_write' (project, item, priority optional): "
        "Neues Backlog-Item hinzufügen (priority: 'P0'/'P1'/'P2', Default 'P1'). "
        "backlog_write wird vorgemerkt und erst nach Philipps Bestätigung ausgeführt "
        "— sag ihm, was du vorbereitet hast.",
        {
            "action": str,
            "project": str,
            "query_type": str,
            "task": str,
            "item": str,
            "priority": str,
        },
    )
    async def coding_tool(args: dict) -> dict:
        action = (args.get("action") or "").strip()

        # ── list_projects ──────────────────────────────────────────────────────
        if action == "list_projects":
            projects = await _list_projects()
            if not projects:
                return _text("Keine Projekte im Workspace gefunden.")
            return _text("📁 Projekte im Workspace:\n" + "\n".join(f"• {p}" for p in projects))

        # ── query ──────────────────────────────────────────────────────────────
        if action == "query":
            project = (args.get("project") or "").strip()
            query_type = (args.get("query_type") or "").strip()
            if not project or not query_type:
                return _text("FEHLER: action='query' braucht: project, query_type.")
            result = await handle_coding_query(project, query_type)
            return _text(result)

        # ── run: fire-and-forget, kein Staging ────────────────────────────────
        if action == "run":
            project = (args.get("project") or "").strip()
            task = (args.get("task") or "").strip()
            if not project or not task:
                return _text("FEHLER: action='run' braucht: project, task.")
            asyncio.create_task(run_coding_action(task, project, chat_id))
            return _text(
                f"🚀 Claude Code läuft im Hintergrund in *{project}* "
                "— Philipp wird direkt per Telegram benachrichtigt."
            )

        if action not in _WRITE_ACTIONS:
            return _text(
                f"FEHLER: Unbekannte action '{action}'. Erlaubt: "
                "list_projects, query, run, backlog_write."
            )

        # ── backlog_write: Pflichtfelder prüfen + vormerken ────────────────────
        params = {
            "project": (args.get("project") or "").strip(),
            "item": (args.get("item") or "").strip(),
            "priority": (args.get("priority") or "").strip() or "P1",
        }
        missing = _missing_fields(action, params)
        if missing:
            return _text(f"FEHLER: action='{action}' braucht: {missing}.")
        label = _label(action, params)
        app_state.stage_agent_action(chat_id, "coding", action, label, params)
        return _text(
            f"✅ Vorgemerkt: {label}. Wird nach Philipps Bestätigung ausgeführt "
            "— du musst nicht warten."
        )

    return coding_tool


async def execute_write(action: str, params: dict) -> str:
    """Eine vorgemerkte coding-Schreibaktion ausführen."""
    if action == "backlog_write":
        ok = await add_backlog_item(
            params["project"], params["item"], params.get("priority", "P1")
        )
        return (
            f"✅ Backlog-Item in '{params['project']}' hinzugefügt: {params['item'][:60]}"
            if ok
            else f"❌ Backlog konnte nicht aktualisiert werden in '{params['project']}'."
        )
    return f"❌ Unbekannte coding-Aktion '{action}'."
```

- [ ] **Step 4: Tests laufen lassen — müssen grün sein**

```bash
PYTHONPATH=agents .venv/bin/pytest tests/test_tools_coding.py -v 2>&1 | tail -20
```

Erwartetes Ergebnis: alle 12 Tests grün.

- [ ] **Step 5: Gesamte Suite**

```bash
PYTHONPATH=agents .venv/bin/pytest tests/ -q --tb=short \
  --ignore=tests/test_briefing_agent.py \
  --ignore=tests/test_tasks_agent.py 2>&1 | tail -5
```

Erwartetes Ergebnis: alle grün (233+12 = 245 Tests).

- [ ] **Step 6: Commit**

```bash
git add agents/tools/coding_tool.py tests/test_tools_coding.py
git commit -m "feat(tools): coding-Tool — list_projects/query/run + backlog_write"
```

---

## Task 2: Verdrahtung + Cleanup

**Files:**
- Modify: `agents/tools/__init__.py`
- Modify: `agents/dispatch.py`
- Modify: `agents/agent.py`
- Modify: `agents/intent_handlers.py`
- Modify: `tests/test_tools_registry.py`
- Modify: `tests/test_agent_dispatch.py`
- Modify: `tests/test_dispatch_main.py`
- Modify: `tests/test_chat_quality_main.py`
- Modify: `CLAUDE.md`

### Hintergrundwissen für den Implementer

**Aktueller Stand in `dispatch.py`:**

```python
_HISTORY_INTENTS = {
    "personal", "work", "research",
    "weather", "news",
    "tasks", "reminder_write",
    "mail", "calendar",
}
_AGENT_INTENTS = {
    "personal", "work", "research",
    "weather", "news",
    "tasks", "reminder_write",
    "mail", "calendar",
}
```

`coding` ist aktuell in KEINEM der beiden Sets — es hat seinen eigenen `elif`-Branch:
```python
elif intent == "coding":
    await handle_coding(chat_id, text, params, update)
```

Außerdem in den Imports:
```python
from intent_handlers import (
    handle_briefing,
    handle_coding,   # ← muss raus
    handle_memory,
)
```

**`intent_handlers.py`** enthält neben `handle_coding` noch `handle_briefing` und `handle_memory` — die Datei bleibt, nur `handle_coding` + zugehörige Imports werden entfernt.

**`tests/__init__.py`** hat `_HISTORY_INTENTS`-Tests für `test_chat_quality_main.py` — prüfen ob `coding` dort relevant ist.

**Bestehende Dispatch-Tests in `test_dispatch_main.py`** — prüfen ob es Tests gibt, die `handle_coding` direkt aufrufen. Falls ja, entfernen oder auf `run_agent` umschreiben.

- [ ] **Step 1: `agents/tools/__init__.py` erweitern**

Zuerst `agents/tools/__init__.py` lesen. Dann:

1. Import hinzufügen (nach `from . import calendar_tool`):
```python
from . import coding_tool
```

2. `_all_tools` erweitern:
```python
def _all_tools(chat_id: int) -> list:
    return _STATIC_TOOLS + [
        tasks_tool.make_tasks_tool(chat_id),
        mail_tool.make_mail_tool(chat_id),
        calendar_tool.make_calendar_tool(chat_id),
        coding_tool.make_coding_tool(chat_id),
    ]
```

3. `_WRITE_EXECUTORS` erweitern:
```python
_WRITE_EXECUTORS: dict = {
    "tasks": tasks_tool.execute_write,
    "mail": mail_tool.execute_write,
    "calendar": calendar_tool.execute_write,
    "coding": coding_tool.execute_write,
}
```

- [ ] **Step 2: `tests/test_tools_registry.py` aktualisieren**

`tests/test_tools_registry.py` lesen. Dann prüfen ob `coding` in `_ALLOWED_TOOL_NAMES` und `_WRITE_EXECUTORS` getestet wird. Falls nicht, diese Assertions hinzufügen:

```python
def test_coding_in_allowed_tools():
    import tools
    assert "mcp__jarvis__coding" in tools._ALLOWED_TOOL_NAMES


def test_write_executors_include_coding():
    import tools
    assert "coding" in tools._WRITE_EXECUTORS
```

- [ ] **Step 3: `agents/dispatch.py` aktualisieren**

`agents/dispatch.py` lesen. Dann:

1. Import bereinigen — `handle_coding` aus dem Import entfernen:
```python
from intent_handlers import (
    handle_briefing,
    handle_memory,
)
```

2. `_HISTORY_INTENTS` erweitern:
```python
_HISTORY_INTENTS = {
    "personal", "work", "research",
    "weather", "news",
    "tasks", "reminder_write",
    "mail", "calendar",
    "coding",
}
```

3. `_AGENT_INTENTS` erweitern:
```python
_AGENT_INTENTS = {
    "personal", "work", "research",
    "weather", "news",
    "tasks", "reminder_write",
    "mail", "calendar",
    "coding",
}
```

4. `elif intent == "coding":` Branch komplett entfernen:
```python
# ENTFERNEN:
elif intent == "coding":
    await handle_coding(chat_id, text, params, update)
```

- [ ] **Step 4: `agents/intent_handlers.py` bereinigen**

`agents/intent_handlers.py` lesen. Dann:

1. Import entfernen:
```python
from coding_agent import handle_coding_query, run_coding_action, add_backlog_item
from vps import list_projects
```

2. `handle_coding`-Funktion komplett entfernen (Zeilen 36–67 ca.).

Nach dem Cleanup darf `intent_handlers.py` nur noch `send_briefing`, `handle_briefing` und `handle_memory` enthalten.

Sicherstellen dass kein Reference auf `handle_coding` übrig bleibt:
```bash
grep -n "handle_coding\|run_coding_action\|handle_coding_query\|add_backlog_item" agents/intent_handlers.py agents/dispatch.py
```

- [ ] **Step 5: `agents/agent.py` — System-Prompt erweitern**

`agents/agent.py` lesen, Funktion `build_system_prompt()` finden. Im Tools-Abschnitt (nach `mail:` und `calendar:`) ergänzen:

```python
"- coding: Projekte lesen und Claude Code starten. "
"action='list_projects' (kein Arg): Projekte auflisten. "
"action='query' (project, query_type): Projekt-Info lesen — query_type: "
"backlog/git_log/readme/claude_md. "
"action='run' (project, task): Claude Code sofort starten (KEIN Confirm, läuft im Hintergrund). "
"action='backlog_write' (project, item, priority): Backlog-Item vormerken.\n"
```

- [ ] **Step 6: Tests für Dispatch-Änderungen aktualisieren**

**`tests/test_agent_dispatch.py`** lesen. Prüfen ob Tests für `coding`-Routing existieren. Falls nicht, zwei Tests nach dem bestehenden Pattern für `mail`/`calendar` hinzufügen:

```python
@pytest.mark.asyncio
async def test_coding_routed_to_agent(monkeypatch):
    """coding-Intent läuft durch run_agent, nicht mehr durch handle_coding."""
    import dispatch as dispatch_mod
    assert not hasattr(dispatch_mod, "handle_coding")
```

**`tests/test_dispatch_main.py`** lesen. Wenn es Tests gibt, die `handle_coding` aufrufen oder `from intent_handlers import handle_coding` importieren → entfernen. Falls Tests den coding-Intent testen wollen, auf das `run_agent`-Pattern umschreiben (wie für mail/calendar in Task 3 von Plan 4 gemacht).

**`tests/test_chat_quality_main.py`** lesen. Prüfen ob `coding` in einem `_HISTORY_INTENTS`-Test vorkommt. Wenn nein: einen Test hinzufügen der bestätigt, dass coding jetzt History speichert (wie `test_history_saved_for_calendar_intent`):

```python
@pytest.mark.asyncio
async def test_history_saved_for_coding_intent(monkeypatch):
    """coding-Intent ist jetzt in _HISTORY_INTENTS — History wird gespeichert."""
    # Gleiches Pattern wie der calendar-Test in derselben Datei.
```

Bestehende Datei für das genaue Test-Pattern lesen, bevor du etwas schreibst.

- [ ] **Step 7: `CLAUDE.md` aktualisieren**

`CLAUDE.md` (im Repo-Root, nicht in agents/) lesen. Dann:

1. **Architektur-Diagramm**: `coding_agent.py + github_agent.py` aus der separaten Zeile entfernen; `coding` erscheint nun unter dem `run_agent`-Ast (wie `weather`, `news`, `tasks`, `mail`, `calendar`)

2. **Strukturliste** (`agents/`-Auflistung): `intent_handlers.py`-Beschreibung anpassen — `handle_coding` ist raus, nur noch `briefing/memory`.

3. **Pending-State-Tabelle** in `CLAUDE.md` ist bereits korrekt (kein coding-Eintrag nötig, da `backlog_write` das generische `pending_agent_actions`-Dict nutzt).

4. **Callbacks-Tabelle**: keine Änderung nötig (coding nutzt die generischen `agent:confirm/cancel`-Callbacks).

- [ ] **Step 8: Gesamte Suite — alle grün**

```bash
PYTHONPATH=agents .venv/bin/pytest tests/ -q --tb=short \
  --ignore=tests/test_briefing_agent.py \
  --ignore=tests/test_tasks_agent.py 2>&1 | tail -5
```

Erwartetes Ergebnis: alle Tests grün.

- [ ] **Step 9: Commit + Push**

```bash
git add -A
git commit -m "feat(dispatch): coding → _AGENT_INTENTS; coding-Tool verdrahtet, handle_coding entfernt"
git push
```

Nach Push deployt der GitHub-Webhook automatisch auf den VPS.

---

## Smoke-Test nach Deploy (manuell via Telegram — nach Plan 4-Nachtests)

1. **Projekte auflisten:** „Welche Projekte habe ich im Workspace?" → Agent nutzt `coding list_projects`
2. **Backlog lesen:** „Was steht im Backlog von recipe-app?" → `coding query` mit query_type=backlog
3. **Backlog schreiben:** „Füge 'Dark mode' zum recipe-app Backlog hinzu" → stages `backlog_write` → Confirm → BACKLOG.md aktualisiert
4. **Claude Code starten:** „Führe in recipe-app einen kleinen Refactor durch: ersetze alle `print` durch `logging.info`" → `coding run` → sofort bestätigt → Telegram-Status erscheint (kann Minuten dauern)
