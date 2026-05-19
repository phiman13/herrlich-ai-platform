# Agentischer Jarvis Phase 2 — Plan 1: Fundament

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Das Phase-1-Scaffolding abbauen (Feature-Flag `JARVIS_AGENT_ENABLED` + Single-shot-Konversations-Handler `chat_handler.py`) und das `agents/tools/`-Tool-Paket anlegen — die Grundlage für die Handler→Tool-Konvertierungen ab Plan 2.

**Architecture:** Drei in sich abgeschlossene Änderungen ohne neues Nutzerverhalten. (1) `JARVIS_AGENT_ENABLED` abschaffen — der Agent-Pfad wird dauerhaft für `personal`/`work`/`research`, wodurch `chat_handler.py` tot wird und mitgelöscht wird. (2) `agent_tools.py` zum Paket `agents/tools/` umbauen (ein Modul pro Fähigkeit + Registry). (3) `CLAUDE.md` nachziehen.

**Tech Stack:** Python 3.11, pytest, claude-agent-sdk.

**Übergeordnetes Design:** `docs/plans/2026-05-19-agentischer-jarvis-phase2-design.md`

**Test-Kommando (Standard, kein Live-API-Zugang nötig):**
```bash
PYTHONPATH=agents .venv/bin/pytest tests/ -q --tb=short \
  --ignore=tests/test_briefing_agent.py \
  --ignore=tests/test_mail_send.py \
  --ignore=tests/test_tasks_agent.py
```

---

### Task 1: `JARVIS_AGENT_ENABLED` abschaffen + `chat_handler.py` löschen

Das Entfernen des Flags und das Löschen von `chat_handler.py` sind **eine atomare Änderung** — jeder Zwischenzustand lässt die Suite rot. Darum ein Task, ein Commit. Kein neuer Test (Teardown): die Disziplin ist „Suite grün vorher, Suite grün nachher".

**Files:**
- Modify: `agents/agent.py`
- Modify: `agents/dispatch.py`
- Delete: `agents/chat_handler.py`
- Modify: `tests/test_agent.py`
- Modify: `tests/test_agent_dispatch.py`
- Modify: `tests/test_chat_quality_main.py`
- Modify: `tests/test_dispatch_main.py`
- Modify: `tests/test_main_memory.py`

- [ ] **Step 1: Grüne Basislinie bestätigen**

Run:
```bash
PYTHONPATH=agents .venv/bin/pytest tests/ -q --tb=short \
  --ignore=tests/test_briefing_agent.py \
  --ignore=tests/test_mail_send.py \
  --ignore=tests/test_tasks_agent.py
```
Expected: PASS (alle Tests grün). Wenn nicht grün — stoppen, Ursache klären, bevor irgendetwas geändert wird.

- [ ] **Step 2: `agents/agent.py` — Docstring + `agent_enabled()` entfernen**

Ersetze den Modul-Docstring (Zeilen 1–6):
```python
"""Agentische Konversations-Runtime — Phase 1 des agentischen Jarvis.

Ein zustandsloser SDK-Lauf pro Telegram-Nachricht. Der Router bleibt vorgelagert;
diese Runtime übernimmt personal/work/research, wenn JARVIS_AGENT_ENABLED gesetzt
ist.
"""
```
durch:
```python
"""Agentische Konversations-Runtime des agentischen Jarvis.

Ein zustandsloser SDK-Lauf pro Telegram-Nachricht. Der Router bleibt in Phase 2
vorgelagert; diese Runtime übernimmt die agentischen Intents (_AGENT_INTENTS in
dispatch.py).
"""
```

Lösche die Funktion `agent_enabled()` vollständig — diesen Block:
```python
def agent_enabled() -> bool:
    """True, wenn der agentische Pfad per Feature-Flag aktiv ist."""
    return os.environ.get("JARVIS_AGENT_ENABLED", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


```
(Die folgende Funktion `build_system_prompt` bleibt. `import os` bleibt — wird weiter von `JARVIS_AGENT_MODEL` / `JARVIS_CLAUDE_CLI_PATH` genutzt.)

- [ ] **Step 3: `agents/dispatch.py` — Imports, Intent-Mengen, `_process_text`**

Lösche die Import-Zeile vollständig:
```python
from chat_handler import handle_research, handle_work, handle_personal
```

Ändere:
```python
from agent import run_agent, agent_enabled
```
zu:
```python
from agent import run_agent
```

Ersetze den Kommentar über `_AGENT_INTENTS`:
```python
# Intents, die der agentische Pfad übernimmt (wenn JARVIS_AGENT_ENABLED).
# Bewusst eine eigene Menge — deckt sich aktuell mit _MEMORY_INTENTS /
# _HISTORY_INTENTS, kann in Phase 2 aber divergieren.
_AGENT_INTENTS = {"personal", "work", "research"}
```
durch:
```python
# Intents, die der agentische Pfad (run_agent) übernimmt. Wächst in Phase 2 mit
# jeder Handler→Tool-Konvertierung; deckt sich aktuell mit den anderen Mengen.
_AGENT_INTENTS = {"personal", "work", "research"}
```

Ersetze in `_process_text` den Routing-Block. Alt:
```python
    if intent in _AGENT_INTENTS and agent_enabled():
        answer = await run_agent(chat_id, text, history, memory_context)
    elif intent == "calendar":
        await handle_calendar_intent(chat_id, text, params)
        return
    elif intent == "mail":
        await handle_mail_intent(chat_id, text, params)
        return
    elif intent == "research":
        answer = await handle_research(chat_id, text, memory_context, history)
    elif intent == "coding":
        await handle_coding(chat_id, text, params, update)
    elif intent == "reminder_write":
        await handle_reminder_write(chat_id, params, update)
        return
    elif intent == "work":
        answer = await handle_work(chat_id, text, memory_context, history)
    elif intent == "news":
        await handle_news(chat_id, update)
    elif intent == "tasks":
        await handle_tasks(chat_id, params, update)
    elif intent == "weather":
        await handle_weather(chat_id, params, update)
    elif intent == "briefing":
        await handle_briefing(chat_id, update)
    elif intent == "memory":
        await handle_memory(chat_id, params, update)
        return
    else:
        answer = await handle_personal(chat_id, text, memory_context, history)
```
Neu:
```python
    if intent in _AGENT_INTENTS:
        answer = await run_agent(chat_id, text, history, memory_context)
    elif intent == "calendar":
        await handle_calendar_intent(chat_id, text, params)
        return
    elif intent == "mail":
        await handle_mail_intent(chat_id, text, params)
        return
    elif intent == "coding":
        await handle_coding(chat_id, text, params, update)
    elif intent == "reminder_write":
        await handle_reminder_write(chat_id, params, update)
        return
    elif intent == "news":
        await handle_news(chat_id, update)
    elif intent == "tasks":
        await handle_tasks(chat_id, params, update)
    elif intent == "weather":
        await handle_weather(chat_id, params, update)
    elif intent == "briefing":
        await handle_briefing(chat_id, update)
    elif intent == "memory":
        await handle_memory(chat_id, params, update)
        return
    else:
        answer = await run_agent(chat_id, text, history, memory_context)
```
Geändert: `and agent_enabled()` entfernt; die toten Zweige `elif intent == "research"` und `elif intent == "work"` entfernt (beide werden jetzt vom `if` gefangen); der `else`-Zweig leitet den Catch-all auf `run_agent` statt auf den gelöschten `handle_personal`.

- [ ] **Step 4: `agents/chat_handler.py` löschen**

Run:
```bash
git rm agents/chat_handler.py
```

- [ ] **Step 5: `tests/test_agent.py` — Flag-Tests entfernen**

Lösche diese drei Test-Funktionen vollständig:
- `test_agent_enabled_default_off`
- `test_agent_enabled_on`
- `test_agent_enabled_all_truthy_values`

Die übrigen Tests (`test_system_prompt_*`, `test_format_history_*`, `test_build_user_prompt_*`, `test_get_agent_lock_*`, `test_run_agent_*`) bleiben unverändert.

- [ ] **Step 6: `tests/test_agent_dispatch.py` — Datei ersetzen**

Ersetze den **gesamten Inhalt** von `tests/test_agent_dispatch.py` durch:
```python
"""Tests für die Intent-Verdrahtung in dispatch._process_text."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app_state
import dispatch


def _routing(intent):
    return {"intent": intent, "params": {}, "confidence": 8, "reasoning": ""}


@pytest.mark.asyncio
async def test_personal_routed_to_agent():
    app_state.conversation_db = None
    app_state.profile_agent = None
    app_state.memory_agent = None
    update = MagicMock()
    with (
        patch(
            "dispatch.route_with_llm", new=AsyncMock(return_value=_routing("personal"))
        ),
        patch(
            "dispatch.run_agent", new=AsyncMock(return_value="Agent-Antwort")
        ) as mock_run,
    ):
        await dispatch._process_text("Hallo", 123, update)
    mock_run.assert_awaited_once()


@pytest.mark.asyncio
async def test_weather_routed_to_handler():
    app_state.conversation_db = None
    app_state.profile_agent = None
    app_state.memory_agent = None
    update = MagicMock()
    with (
        patch(
            "dispatch.route_with_llm", new=AsyncMock(return_value=_routing("weather"))
        ),
        patch("dispatch.run_agent", new=AsyncMock()) as mock_run,
        patch("dispatch.handle_weather", new=AsyncMock()) as mock_weather,
    ):
        await dispatch._process_text("Wetter morgen?", 123, update)
    mock_weather.assert_awaited_once()
    mock_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_agent_answer_persisted_to_conversation_db():
    app_state.profile_agent = None
    app_state.memory_agent = None
    mock_conv_db = MagicMock()
    mock_conv_db.get_recent = AsyncMock(return_value=[])
    mock_conv_db.save = AsyncMock()
    app_state.conversation_db = mock_conv_db
    update = MagicMock()
    try:
        with (
            patch(
                "dispatch.route_with_llm",
                new=AsyncMock(return_value=_routing("personal")),
            ),
            patch("dispatch.run_agent", new=AsyncMock(return_value="Agent-Antwort")),
        ):
            await dispatch._process_text("Frage", 123, update)
    finally:
        app_state.conversation_db = None
    assert mock_conv_db.save.await_count == 2
    saved_roles = [call.args[1] for call in mock_conv_db.save.await_args_list]
    assert saved_roles == ["user", "assistant"]
```
Entfernt: die drei `*_when_flag_off`-Tests (kein Flag mehr) und alle `patch("dispatch.agent_enabled", ...)`. `test_weather_never_routed_to_agent` → `test_weather_routed_to_handler` (weather bleibt in Plan 1 handler-geroutet; konvertiert erst in Plan 2).

- [ ] **Step 7: `tests/test_chat_quality_main.py` — chat_handler-Tests umbauen**

Lösche die Import-Zeile `import chat_handler`.

Lösche diese zwei Test-Funktionen vollständig (sie testen den gelöschten `chat_handler`):
- `test_personal_intent_uses_sonnet`
- `test_ask_claude_injects_history`

Ersetze `test_history_saved_after_personal_intent` durch:
```python
def test_history_saved_after_personal_intent():
    mock_db = MagicMock()
    mock_db.get_recent = AsyncMock(return_value=[])
    mock_db.save = AsyncMock()
    app_state.conversation_db = mock_db

    with patch(
        "dispatch.route_with_llm",
        return_value={
            "intent": "personal",
            "confidence": 9,
            "params": {},
            "reasoning": "test",
        },
    ):
        with patch(
            "dispatch.run_agent",
            new_callable=AsyncMock,
            return_value="Antwort auf Hallo",
        ):
            with patch("app_state.send_typing", new_callable=AsyncMock):
                update = MagicMock()
                update.update_id = 77772
                update.message.text = "Hallo"
                update.message.chat_id = 123
                update.message.reply_text = AsyncMock()
                asyncio.run(main_module.handle_message(update, None))

    save_calls = mock_db.save.call_args_list
    assert any(c.args == (123, "user", "Hallo") for c in save_calls)
    assert any(c.args == (123, "assistant", "Antwort auf Hallo") for c in save_calls)

    app_state.conversation_db = None
```

Ersetze `test_profile_content_injected_for_personal_intent` durch:
```python
def test_profile_content_injected_for_personal_intent():
    mock_profile = MagicMock()
    mock_profile.load.return_value = "## Beruf & Rolle\nStrategischer Berater\n"
    mock_profile.update = AsyncMock()
    app_state.profile_agent = mock_profile

    with patch(
        "dispatch.route_with_llm",
        return_value={
            "intent": "personal",
            "confidence": 9,
            "params": {},
            "reasoning": "test",
        },
    ):
        with patch(
            "dispatch.run_agent", new_callable=AsyncMock, return_value="ok"
        ) as mock_run:
            with patch("app_state.send_typing", new_callable=AsyncMock):
                update = MagicMock()
                update.update_id = 88881
                update.message.text = "Was soll ich tun?"
                update.message.chat_id = 456
                update.message.reply_text = AsyncMock()
                asyncio.run(main_module.handle_message(update, None))

    app_state.profile_agent = None
    # run_agent(chat_id, text, history, memory_context) — memory_context = args[3]
    memory_context_arg = mock_run.call_args.args[3]
    assert "Strategischer Berater" in memory_context_arg
```

`test_send_typing_calls_send_chat_action`, `test_keep_typing_stops_on_event` und `test_history_not_saved_for_calendar_intent` bleiben unverändert.

- [ ] **Step 8: `tests/test_dispatch_main.py` — obsolete Konversations-Tests entfernen**

Lösche diese zwei Test-Funktionen vollständig (research/work laufen jetzt über den Agenten, nicht `ask_claude`):
- `test_research_intent_calls_ask_claude_with_web_search`
- `test_work_intent_uses_sonnet`

Alle anderen Tests bleiben (mail, news, weather, briefing, tasks, reminder_write, coding, low_confidence — alle in Plan 1 noch handler-geroutet).

- [ ] **Step 9: `tests/test_main_memory.py` — `test_retrieve_called_for_personal_intent` umbauen**

Ersetze `test_retrieve_called_for_personal_intent` durch:
```python
def test_retrieve_called_for_personal_intent(fresh_memory_agent):
    """retrieve() is called when intent is personal."""
    called = []

    async def fake_retrieve():
        called.append(True)
        return []

    with patch.object(fresh_memory_agent, "retrieve", side_effect=fake_retrieve):
        with patch(
            "dispatch.route_with_llm",
            return_value={
                "intent": "personal",
                "confidence": 8,
                "params": {},
                "reasoning": "test",
            },
        ):
            with patch("dispatch.run_agent", new_callable=AsyncMock, return_value="ok"):
                with patch("app_state.send_typing", new_callable=AsyncMock):
                    update = MagicMock()
                    update.update_id = 99991
                    update.message.text = "Wie geht's dir?"
                    update.message.chat_id = 123
                    update.message.reply_text = AsyncMock()
                    asyncio.run(main_module.handle_message(update, None))

    assert len(called) == 1
```
Nur das Patch-Ziel wechselt von `chat_handler.ask_claude` auf `dispatch.run_agent`. Die anderen Tests der Datei bleiben unverändert.

- [ ] **Step 10: Volle Suite — grün**

Run:
```bash
PYTHONPATH=agents .venv/bin/pytest tests/ -q --tb=short \
  --ignore=tests/test_briefing_agent.py \
  --ignore=tests/test_mail_send.py \
  --ignore=tests/test_tasks_agent.py
```
Expected: PASS. Bei Fehlern: nach übersehenen Referenzen auf `agent_enabled`, `chat_handler`, `handle_personal`/`handle_work`/`handle_research` suchen und beheben.

- [ ] **Step 11: Commit**

Die Löschung von `agents/chat_handler.py` wurde bereits in Step 4 via `git rm`
gestaget.
```bash
git add agents/agent.py agents/dispatch.py tests/test_agent.py \
  tests/test_agent_dispatch.py tests/test_chat_quality_main.py \
  tests/test_dispatch_main.py tests/test_main_memory.py
git commit -m "refactor(agent): JARVIS_AGENT_ENABLED abschaffen, chat_handler.py löschen

Der Agent-Pfad ist dauerhaft für personal/work/research; Rollback ab
Phase 2 = git revert. Die Phase-1-Single-shot-Handler (chat_handler.py)
sind damit tot und entfallen.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 2: `agents/tools/`-Paket — `agent_tools.py` umbauen

Reiner Refactor: `agent_tools.py` wird zum Paket `agents/tools/` (ein Modul pro Fähigkeit + Registry im `__init__.py`). Kein Verhaltenswechsel — die Suite muss vorher wie nachher grün sein.

**Files:**
- Create: `agents/tools/__init__.py`
- Create: `agents/tools/workspace_tool.py`
- Delete: `agents/agent_tools.py`
- Modify: `agents/agent.py`
- Delete: `tests/test_agent_tools.py`
- Create: `tests/test_tools_workspace.py`
- Create: `tests/test_tools_registry.py`

- [ ] **Step 1: `agents/tools/workspace_tool.py` anlegen**

Erstelle `agents/tools/workspace_tool.py` mit diesem Inhalt:
```python
"""workspace-Tool — liest und durchsucht Dateien in Philipps Coding-Workspace.

Sicherheitsmodell: der workspace-Tool liest ausschließlich unterhalb von
JARVIS_WORKSPACE_DIR. _resolve_in_workspace lehnt jeden Pfad ab, der den Root
verlässt (Parent-Traversal, absolute Pfade, Symlink-Escape).
"""

import os
import re
from pathlib import Path

from claude_agent_sdk import tool

_MAX_FILE_CHARS = 60_000
_SEARCH_MAX_HITS = 60
_SKIP_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    "dist",
    "build",
    ".next",
    ".worktrees",
}


def _workspace_root() -> Path:
    """Der Workspace-Root — konfigurierbar via JARVIS_WORKSPACE_DIR."""
    return Path(
        os.environ.get("JARVIS_WORKSPACE_DIR", os.path.expanduser("~/Code"))
    ).resolve()


def _resolve_in_workspace(rel_path: str) -> Path | None:
    """rel_path relativ zum Workspace-Root auflösen.

    Gibt None zurück, wenn der aufgelöste Pfad den Root verlässt.
    """
    root = _workspace_root()
    candidate = (root / rel_path).resolve()
    if candidate == root or root in candidate.parents:
        return candidate
    return None


def _do_read(rel_path: str) -> str:
    """Eine Datei im Workspace lesen. Strukturierter Fehlertext bei Problemen."""
    target = _resolve_in_workspace(rel_path)
    if target is None:
        return f"FEHLER: Pfad '{rel_path}' liegt außerhalb des Workspace."
    if not target.is_file():
        return f"FEHLER: '{rel_path}' ist keine Datei oder existiert nicht."
    data = target.read_bytes()
    if b"\x00" in data[:4096]:
        return (
            f"FEHLER: '{rel_path}' ist eine Binärdatei und kann nicht gelesen werden."
        )
    text = data.decode("utf-8", errors="replace")
    if len(text) > _MAX_FILE_CHARS:
        text = text[:_MAX_FILE_CHARS] + "\n[... gekürzt ...]"
    return text


def _do_search(pattern: str, rel_path: str = "") -> str:
    """Regex-Suche über Dateien im Workspace (rekursiv ab rel_path)."""
    base = _resolve_in_workspace(rel_path or ".")
    if base is None or not base.exists():
        return f"FEHLER: Suchpfad '{rel_path}' ist ungültig."
    try:
        rx = re.compile(pattern)
    except re.error as e:
        return f"FEHLER: Ungültiges Suchmuster: {e}"
    root = _workspace_root()
    hits: list[str] = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fn in sorted(filenames):
            fp = Path(dirpath) / fn
            try:
                with open(fp, "r", encoding="utf-8", errors="ignore") as fh:
                    for lineno, line in enumerate(fh, 1):
                        if rx.search(line):
                            hits.append(
                                f"{fp.relative_to(root)}:{lineno}: {line.strip()[:200]}"
                            )
                            if len(hits) >= _SEARCH_MAX_HITS:
                                hits.append("[... weitere Treffer abgeschnitten ...]")
                                return "\n".join(hits)
            except (OSError, UnicodeError):
                continue
    return "\n".join(hits) if hits else f"Keine Treffer für '{pattern}'."


def _do_list(rel_path: str = "") -> str:
    """Ein Verzeichnis im Workspace auflisten (Dotfiles + Skip-Dirs ausgeblendet)."""
    target = _resolve_in_workspace(rel_path or ".")
    if target is None or not target.is_dir():
        return f"FEHLER: '{rel_path}' ist kein Verzeichnis."
    entries: list[str] = []
    for child in sorted(target.iterdir()):
        if child.name in _SKIP_DIRS or child.name.startswith("."):
            continue
        entries.append(f"{child.name}/" if child.is_dir() else child.name)
    return "\n".join(entries) if entries else "(leer)"


@tool(
    "workspace",
    "Liest und durchsucht Dateien in Philipps Coding-Workspace. "
    "action='read': Datei lesen (path = relativer Pfad). "
    "action='search': Regex-Suche (query = Muster, path = optionaler Unterordner). "
    "action='list': Verzeichnis auflisten (path = relativer Pfad, leer = Workspace-Wurzel).",
    {"action": str, "path": str, "query": str},
)
async def workspace_tool(args: dict) -> dict:
    action = (args.get("action") or "").strip()
    path = (args.get("path") or "").strip()
    query = (args.get("query") or "").strip()
    if action == "read":
        result = _do_read(path)
    elif action == "search":
        if not query:
            result = (
                "FEHLER: action='search' erfordert ein nicht-leeres 'query'-Suchmuster."
            )
        else:
            result = _do_search(query, path)
    elif action == "list":
        result = _do_list(path)
    else:
        result = f"FEHLER: Unbekannte action '{action}'. Erlaubt: read, search, list."
    return {"content": [{"type": "text", "text": result}]}
```
(Inhaltlich identisch zu den workspace-Teilen des alten `agent_tools.py` — nur die nicht mehr benötigte Konstante `_WORKSPACE_TOOL_NAME` entfällt.)

- [ ] **Step 2: `agents/tools/__init__.py` anlegen**

Erstelle `agents/tools/__init__.py` mit diesem Inhalt:
```python
"""Agent-SDK-Werkzeuge — Registry, MCP-Server-Bau, Permission-Gate.

Ein Modul pro Fähigkeit (workspace_tool, ab Plan 2: weather_tool, news_tool, …).
build_mcp_server versammelt alle Tools zu einem In-Process-MCP-Server;
permission_hook ist die Allowlist der freigegebenen MCP-Tool-Namen.
"""

from claude_agent_sdk import (
    McpSdkServerConfig,
    PermissionResultAllow,
    PermissionResultDeny,
    create_sdk_mcp_server,
)

from .workspace_tool import workspace_tool

_MCP_SERVER_NAME = "jarvis"
# Alle in diesem Server registrierten Tools.
_TOOLS = [workspace_tool]
# Voller MCP-Tool-Name: mcp__<server-name>__<tool-name>
_ALLOWED_TOOL_NAMES = {f"mcp__{_MCP_SERVER_NAME}__{t.name}" for t in _TOOLS}


def build_mcp_server() -> McpSdkServerConfig:
    """In-Process-MCP-Server mit allen Jarvis-Tools."""
    return create_sdk_mcp_server(
        name=_MCP_SERVER_NAME, version="1.0.0", tools=_TOOLS
    )


async def permission_hook(tool_name: str, tool_input: dict, context) -> object:
    """can_use_tool-Gate — Allowlist der Jarvis-MCP-Tools.

    Feuert nur für Tools, die NICHT in allowed_tools stehen (WebSearch/WebFetch
    sind dort gelistet → auto-erlaubt). Lese-/Schreib-Unterscheidung macht ab
    Plan 3 das Tool selbst (Schreib-Aktionen werden vorgemerkt).
    """
    if tool_name in _ALLOWED_TOOL_NAMES:
        return PermissionResultAllow(updated_input=tool_input)
    return PermissionResultDeny(
        message=f"Werkzeug '{tool_name}' ist nicht freigegeben.",
        interrupt=False,
    )
```

- [ ] **Step 3: `agents/agent_tools.py` löschen**

Run:
```bash
git rm agents/agent_tools.py
```

- [ ] **Step 4: `agents/agent.py` — Import umstellen**

Ändere:
```python
from agent_tools import build_mcp_server, permission_hook
```
zu:
```python
from tools import build_mcp_server, permission_hook
```

- [ ] **Step 5: Test-Dateien umstellen**

`tests/test_agent_tools.py` umbenennen:
```bash
git mv tests/test_agent_tools.py tests/test_tools_workspace.py
```

In `tests/test_tools_workspace.py`:
1. Lösche die Import-Zeile `from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny` (nur von den Registry-Tests gebraucht).
2. Ändere `import agent_tools` zu `import tools.workspace_tool as agent_tools` (Alias hält alle `agent_tools._resolve…` / `agent_tools._do_…` / `agent_tools.workspace_tool`-Aufrufe unverändert gültig).
3. Lösche die drei Registry-Tests vollständig: `test_build_mcp_server_registers_workspace`, `test_permission_hook_allows_workspace`, `test_permission_hook_denies_unknown_tool`.

Erstelle `tests/test_tools_registry.py` mit diesem Inhalt:
```python
"""Tests für agents/tools/__init__.py — MCP-Server-Bau + Permission-Hook."""

import pytest
from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

import tools


def test_build_mcp_server_registers_workspace():
    server = tools.build_mcp_server()
    assert server is not None
    assert "mcp__jarvis__workspace" in tools._ALLOWED_TOOL_NAMES


@pytest.mark.asyncio
async def test_permission_hook_allows_workspace():
    result = await tools.permission_hook(
        "mcp__jarvis__workspace", {"action": "read", "path": "x"}, None
    )
    assert isinstance(result, PermissionResultAllow)


@pytest.mark.asyncio
async def test_permission_hook_denies_unknown_tool():
    result = await tools.permission_hook("Bash", {}, None)
    assert isinstance(result, PermissionResultDeny)
    assert result.interrupt is False
```

- [ ] **Step 6: Volle Suite — grün**

Run:
```bash
PYTHONPATH=agents .venv/bin/pytest tests/ -q --tb=short \
  --ignore=tests/test_briefing_agent.py \
  --ignore=tests/test_mail_send.py \
  --ignore=tests/test_tasks_agent.py
```
Expected: PASS. Insbesondere `tests/test_tools_workspace.py` und `tests/test_tools_registry.py` müssen grün sein, und `tests/test_agent.py` (importiert `agent`, das jetzt aus `tools` importiert).

- [ ] **Step 7: Commit**

Die Löschung von `agents/agent_tools.py` (Step 3, `git rm`) und die Umbenennung
`test_agent_tools.py` → `test_tools_workspace.py` (Step 5, `git mv`) sind bereits
gestaget.
```bash
git add agents/tools/__init__.py agents/tools/workspace_tool.py \
  agents/agent.py tests/test_tools_workspace.py tests/test_tools_registry.py
git commit -m "refactor(agent): agent_tools.py zum Paket agents/tools/ umbauen

Ein Modul pro Fähigkeit (workspace_tool) + Registry im __init__.py
(build_mcp_server, permission_hook). Grundlage für die Tool-Module
ab Plan 2.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 3: `CLAUDE.md` nachziehen

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Env-Variablen-Tabelle — Flag-Zeile entfernen**

Lösche in der Tabelle „Environment Variables" die Zeile:
```
| `JARVIS_AGENT_ENABLED` | ❌ | Feature-Flag agentischer Pfad — prod: `1` (aktiv seit 18.05.2026); `0` = alter Pfad (Rollback) |
```

- [ ] **Step 2: Abschnitt „Agentischer Pfad" — Flag-Erwähnungen entfernen**

Im Abschnitt „Agentischer Pfad — Phase 1": entferne den Satz „Aktiv über `JARVIS_AGENT_ENABLED=1`." und ersetze den Rollback-Absatz:
```
**Rollback:** `JARVIS_AGENT_ENABLED=0` in `/var/lib/jarvis/.env` + `systemctl restart
jarvis` → sofort zurück zum alten Pfad, kein Code-Revert nötig.
```
durch:
```
**Rollback:** Per `git revert` des betroffenen Commits + Redeploy (GitHub-Webhook
oder manueller Neustart). Das frühere Feature-Flag `JARVIS_AGENT_ENABLED` ist mit
Phase 2 entfallen.
```

- [ ] **Step 3: Datei-Struktur — `chat_handler.py` entfernen**

Lösche in der „Datei-Struktur"-Liste die Zeile:
```
  chat_handler.py       LLM-Chat-Handler (personal/work/research) + ask_claude
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(agent): CLAUDE.md — Flag entfernt, chat_handler.py raus

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Self-Review-Notiz

Plan-1-Scope deckt aus dem Spec ab: das „Phase-1-Scaffolding-Abbau (Plan 1)" (Flag
weg, `chat_handler.py` weg) und den Start von Sektion 1 des Spec (das `agents/tools/`
-Paket, Registry, Permission-Hook-Allowlist). **Nicht** in Plan 1: `chat_id`-Scoping
von `build_mcp_server` (kommt mit dem ersten Write-Tool, Plan 3), neue Tools (Plan 2+),
Pending-/Confirm-Mechanik (Plan 3). Der `weather`/`news`-Pilot ist Plan 2.
