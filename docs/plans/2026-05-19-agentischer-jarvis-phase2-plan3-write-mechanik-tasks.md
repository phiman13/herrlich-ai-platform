# Agentischer Jarvis Phase 2 — Plan 3: Write-Mechanik + `tasks`

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Den Write-Confirm-Mechanismus bauen (vormerken → gebündelter Confirm am Lauf-Ende → Ausführung per Callback) und als ersten Schreib-Intent `tasks` (inkl. `reminder_write`) darauf umstellen.

**Architecture:** Schreib-Aktionen führen nicht direkt aus. Ein chat-skopiertes Tool merkt sie in einem Pending-Store (`app_state.pending_agent_actions`) vor und gibt „vorgemerkt" an den Agenten zurück. Jedes Pending-Set hat eine **ID**; am Lauf-Ende hängt `run_agent` einen gebündelten InlineKeyboard-Confirm an die Antwort, dessen `callback_data` die ID trägt. Der Callback `agent:confirm:{id}` führt nur aus, wenn die ID noch zum aktuellen Set passt — so führt ein veralteter Button nie fremde Aktionen aus. `agent:cancel:{id}` verwirft. Lese-Aktionen laufen unverändert frei. Reihenfolge: erst die Mechanik (Task 1, isoliert unit-getestet), dann das `tasks`-Tool als erster Nutzer (Task 2), dann Verdrahtung (Task 3) + Doku (Task 4).

**Tech Stack:** Python 3.11, pytest, claude-agent-sdk, python-telegram-bot.

**Übergeordnetes Design:** `docs/plans/2026-05-19-agentischer-jarvis-phase2-design.md` — Sektion 3 (Read vs. Write) + Konvertierungs-Sequenz #3. Voraussetzung: Plan 1 + 2 sind umgesetzt (`agents/tools/`-Paket mit 3 Tools).

**Test-Kommando (Standard, kein Live-API-Zugang nötig):**
```bash
PYTHONPATH=agents .venv/bin/pytest tests/ -q --tb=short \
  --ignore=tests/test_briefing_agent.py \
  --ignore=tests/test_mail_send.py \
  --ignore=tests/test_tasks_agent.py
```

**Begriffe:**
- *Pending-Store* — `app_state.pending_agent_actions: dict[int, dict]`, `chat_id → {"id": int, "actions": [...], "staged_at": float}`. Eine Aktion: `{"tool": str, "action": str, "label": str, "params": dict}`.
- *Pending-Set-ID* — monotoner Zähler. Jeder neue Lauf erzeugt (nach `clear_pending_actions` beim Lauf-Start) ein frisches Set mit neuer ID. Der Confirm-Button trägt die ID; ein Button eines überholten Sets wird abgelehnt.
- *Executor-Registry* — `tools._WRITE_EXECUTORS: dict[str, callable]`, `tool-name → execute_write`. `tools.execute_pending_action(action)` dispatcht.
- *Restart-Verhalten* — der Pending-Store ist in-memory, TTL 10 Min (`app_state._PENDING_OP_TTL`, wie die bestehenden `pending_mail_ops`). Ein Restart im Confirm-Fenster verliert die Vormerkung — akzeptiert.

---

### Task 1: Write-Confirm-Mechanik (Fundament)

Baut Pending-Store (mit Set-ID), Lauf-Ende-Confirm und die `agent:*`-Callbacks. Noch kein Schreib-Tool — die Mechanik wird isoliert unit-getestet (Store direkt befüllt, Executor gestubbt).

**Files:**
- Modify: `agents/app_state.py`
- Modify: `agents/agent.py`
- Modify: `agents/callbacks.py`
- Modify: `agents/tools/__init__.py`
- Create: `tests/test_pending_actions.py`
- Modify: `tests/test_agent.py`
- Create: `tests/test_callbacks_agent.py`

- [ ] **Step 1: Grüne Basislinie bestätigen**

Run das Test-Kommando oben. Expected: PASS (`212 passed, 1 skipped`). Bei Rot — stoppen.

- [ ] **Step 2: Pending-Store + Helfer in `app_state.py`**

Füge in `agents/app_state.py` bei den anderen Pending-Dicts (nach `pending_calendar_ops` / `last_calendar_search`) hinzu:
```python
# Vorgemerkte Agenten-Schreibaktionen, die auf den gebündelten Confirm warten.
# chat_id -> {"id": int, "actions": list[dict], "staged_at": float}
# Eine Aktion: {"tool": str, "action": str, "label": str, "params": dict}
pending_agent_actions: dict[int, dict] = {}
_pending_seq: int = 0
```
Füge nach `_pending_op_expired` diese vier Helfer hinzu:
```python
def stage_agent_action(
    chat_id: int, tool: str, action: str, label: str, params: dict
) -> None:
    """Eine Schreibaktion für den Lauf-Ende-Confirm vormerken.

    Hängt an das Pending-Set des laufenden Laufs an. Existiert noch keins (oder
    ist es abgelaufen), wird ein frisches mit neuer ID erzeugt. run_agent leert
    den Store beim Lauf-Start — daher gehört ein Set immer genau einem Lauf.
    """
    global _pending_seq
    entry = pending_agent_actions.get(chat_id)
    if entry is None or _pending_op_expired(entry):
        _pending_seq += 1
        entry = {"id": _pending_seq, "actions": [], "staged_at": time.time()}
        pending_agent_actions[chat_id] = entry
    entry["actions"].append(
        {"tool": tool, "action": action, "label": label, "params": params}
    )


def peek_pending(chat_id: int) -> dict | None:
    """Das Pending-Set lesen ohne zu entnehmen (für den Lauf-Ende-Confirm).

    Gibt {"id", "actions", "staged_at"} zurück oder None.
    """
    entry = pending_agent_actions.get(chat_id)
    if entry is None or _pending_op_expired(entry):
        return None
    return entry


def take_pending_actions(chat_id: int, expected_id: int) -> list[dict]:
    """Aktionen entnehmen — nur wenn die ID zum erwarteten Set passt.

    Schützt davor, dass ein veralteter Confirm-Button die Aktionen eines
    neueren Laufs ausführt. Bei ID-Mismatch bleibt der (neuere) Eintrag
    unangetastet; bei Treffer wird er gelöscht und zurückgegeben.
    """
    entry = pending_agent_actions.get(chat_id)
    if entry is None:
        return []
    if _pending_op_expired(entry):
        pending_agent_actions.pop(chat_id, None)
        return []
    if entry["id"] != expected_id:
        return []
    pending_agent_actions.pop(chat_id, None)
    return entry["actions"]


def clear_pending_actions(chat_id: int) -> None:
    """Pending-Set verwerfen (run_agent beim Lauf-Start und bei Lauf-Fehler)."""
    pending_agent_actions.pop(chat_id, None)
```
(`time` ist in `app_state.py` bereits importiert.)

- [ ] **Step 3: Test für den Pending-Store**

Erstelle `tests/test_pending_actions.py`:
```python
"""Tests für den Write-Confirm-Pending-Store in app_state."""

import time

import app_state


def _clear():
    app_state.pending_agent_actions.clear()


def test_stage_and_peek():
    _clear()
    app_state.stage_agent_action(1, "tasks", "add", "Task X anlegen", {"title": "X"})
    entry = app_state.peek_pending(1)
    assert entry is not None
    assert isinstance(entry["id"], int)
    assert len(entry["actions"]) == 1
    assert entry["actions"][0]["tool"] == "tasks"
    assert entry["actions"][0]["label"] == "Task X anlegen"
    # peek entnimmt nicht
    assert app_state.peek_pending(1) is not None


def test_stage_appends_within_same_set():
    _clear()
    app_state.stage_agent_action(1, "tasks", "add", "A", {})
    id1 = app_state.peek_pending(1)["id"]
    app_state.stage_agent_action(1, "tasks", "complete", "B", {})
    entry = app_state.peek_pending(1)
    assert len(entry["actions"]) == 2
    assert entry["id"] == id1  # gleicher Lauf -> gleiches Set


def test_take_with_matching_id_consumes():
    _clear()
    app_state.stage_agent_action(1, "tasks", "add", "A", {})
    pid = app_state.peek_pending(1)["id"]
    taken = app_state.take_pending_actions(1, pid)
    assert len(taken) == 1
    assert app_state.peek_pending(1) is None


def test_take_with_wrong_id_returns_empty_and_keeps():
    _clear()
    app_state.stage_agent_action(1, "tasks", "add", "A", {})
    pid = app_state.peek_pending(1)["id"]
    assert app_state.take_pending_actions(1, pid + 999) == []
    # falsche ID -> Eintrag bleibt unangetastet
    assert app_state.peek_pending(1) is not None


def test_new_set_after_clear_gets_new_id():
    _clear()
    app_state.stage_agent_action(1, "tasks", "add", "A", {})
    id1 = app_state.peek_pending(1)["id"]
    app_state.clear_pending_actions(1)
    app_state.stage_agent_action(1, "tasks", "add", "B", {})
    id2 = app_state.peek_pending(1)["id"]
    assert id2 != id1
    # alter Button (id1) greift nicht mehr, neuer schon
    assert app_state.take_pending_actions(1, id1) == []
    assert len(app_state.take_pending_actions(1, id2)) == 1


def test_clear_discards():
    _clear()
    app_state.stage_agent_action(1, "tasks", "add", "A", {})
    app_state.clear_pending_actions(1)
    assert app_state.peek_pending(1) is None


def test_expired_set_ignored():
    _clear()
    app_state.pending_agent_actions[1] = {
        "id": 999,
        "actions": [{"tool": "tasks", "action": "add", "label": "alt", "params": {}}],
        "staged_at": time.time() - app_state._PENDING_OP_TTL - 1,
    }
    assert app_state.peek_pending(1) is None
    assert app_state.take_pending_actions(1, 999) == []


def test_per_chat_isolation():
    _clear()
    app_state.stage_agent_action(1, "tasks", "add", "Chat1", {})
    app_state.stage_agent_action(2, "tasks", "add", "Chat2", {})
    assert app_state.peek_pending(1)["actions"][0]["label"] == "Chat1"
    assert app_state.peek_pending(2)["actions"][0]["label"] == "Chat2"
```
Run: `PYTHONPATH=agents .venv/bin/pytest tests/test_pending_actions.py -q`
Expected: PASS (8 passed).

- [ ] **Step 4: Executor-Registry in `tools/__init__.py`**

Füge in `agents/tools/__init__.py` am Ende hinzu:
```python
# Executor-Registry — tool-name -> execute_write(action, params) -> str.
# Wird von den Schreib-Tool-Modulen befüllt (ab Plan 3: tasks).
_WRITE_EXECUTORS: dict = {}


async def execute_pending_action(action: dict) -> str:
    """Eine vorgemerkte Schreibaktion ausführen — dispatcht ans Tool-Modul.

    action: {"tool", "action", "label", "params"}. Gibt eine Ergebnis-Zeile zurück.
    """
    executor = _WRITE_EXECUTORS.get(action["tool"])
    if executor is None:
        return f"❌ {action['label']}: kein Executor für Tool '{action['tool']}'."
    return await executor(action["action"], action["params"])
```

- [ ] **Step 5: Lauf-Start-Clear + Lauf-Ende-Confirm in `run_agent`**

In `agents/agent.py`: erweitere den Telegram-Import
```python
from telegram import Bot
```
zu
```python
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
```

In `run_agent`, direkt nach `async with app_state.get_agent_lock(chat_id):` (als erste Zeile im With-Block, vor `bot = Bot(...)`), füge ein:
```python
        # Un-bestätigte Vormerkungen eines früheren Laufs verwerfen — ein
        # Pending-Set gehört immer genau einem Lauf.
        app_state.clear_pending_actions(chat_id)
```

Ersetze den Sende-Block
```python
        if not final_text:
            final_text = "Keine Antwort erhalten."
        if len(final_text) > 4000:
            final_text = final_text[:4000] + "\n[...]"
        await bot.send_message(chat_id=chat_id, text=final_text)
```
durch
```python
        if not final_text:
            final_text = "Keine Antwort erhalten."
        # Lauf mit Fehler → keine vorgemerkten Aktionen bestätigen lassen.
        if final_text.startswith("Fehler:"):
            app_state.clear_pending_actions(chat_id)
            pending = None
        else:
            pending = app_state.peek_pending(chat_id)
        if len(final_text) > 4000:
            final_text = final_text[:4000] + "\n[...]"
        if pending:
            staged = "\n".join(
                f"{i}. {a['label']}" for i, a in enumerate(pending["actions"], 1)
            )
            pid = pending["id"]
            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "✅ Bestätigen", callback_data=f"agent:confirm:{pid}"
                        ),
                        InlineKeyboardButton(
                            "❌ Abbrechen", callback_data=f"agent:cancel:{pid}"
                        ),
                    ]
                ]
            )
            await bot.send_message(
                chat_id=chat_id,
                text=f"{final_text}\n\nVorgemerkt:\n{staged}",
                reply_markup=keyboard,
            )
        else:
            await bot.send_message(chat_id=chat_id, text=final_text)
```

- [ ] **Step 6: `run_agent`-Confirm-Tests**

Füge in `tests/test_agent.py` am Ende hinzu:
```python
@pytest.mark.asyncio
async def test_run_agent_appends_confirm_keyboard_when_pending():
    async def fake_query(*, prompt, options=None, transport=None):
        # Simuliert ein Tool, das während des Laufs zwei Aktionen vormerkt.
        app_state.stage_agent_action(560, "tasks", "add", "Task 'Milch' anlegen", {})
        app_state.stage_agent_action(560, "tasks", "complete", "Task 'Brot' abhaken", {})
        yield _fake_result("Ich habe das vorbereitet.")

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()
    app_state.agent_run_locks.clear()
    app_state.pending_agent_actions.clear()
    try:
        with (
            patch("agent.query", fake_query),
            patch("agent.Bot", return_value=mock_bot),
            patch("agent._keep_typing", new=AsyncMock()),
        ):
            await agent.run_agent(560, "Leg an", [], "")
    finally:
        app_state.pending_agent_actions.clear()
    kwargs = mock_bot.send_message.call_args.kwargs
    assert kwargs.get("reply_markup") is not None
    # gebündelt: beide Aktionen stehen nummeriert in der Nachricht
    assert "1. Task 'Milch' anlegen" in kwargs["text"]
    assert "2. Task 'Brot' abhaken" in kwargs["text"]


@pytest.mark.asyncio
async def test_run_agent_no_keyboard_without_pending():
    async def fake_query(*, prompt, options=None, transport=None):
        yield _fake_result("Nur Text.")

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()
    app_state.agent_run_locks.clear()
    app_state.pending_agent_actions.clear()
    with (
        patch("agent.query", fake_query),
        patch("agent.Bot", return_value=mock_bot),
        patch("agent._keep_typing", new=AsyncMock()),
    ):
        await agent.run_agent(561, "Hallo", [], "")
    assert mock_bot.send_message.call_args.kwargs.get("reply_markup") is None


@pytest.mark.asyncio
async def test_run_agent_clears_stale_pending_at_start():
    """Ein neuer Lauf verwirft un-bestätigte Vormerkungen eines früheren Laufs."""
    async def fake_query(*, prompt, options=None, transport=None):
        yield _fake_result("Antwort ohne neue Vormerkung.")

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()
    app_state.agent_run_locks.clear()
    app_state.pending_agent_actions.clear()
    app_state.stage_agent_action(563, "tasks", "add", "alte Vormerkung", {})
    try:
        with (
            patch("agent.query", fake_query),
            patch("agent.Bot", return_value=mock_bot),
            patch("agent._keep_typing", new=AsyncMock()),
        ):
            await agent.run_agent(563, "Was anderes", [], "")
    finally:
        app_state.pending_agent_actions.clear()
    # Lauf-Start hat die alte Vormerkung verworfen -> kein Keyboard.
    assert mock_bot.send_message.call_args.kwargs.get("reply_markup") is None


@pytest.mark.asyncio
async def test_run_agent_error_discards_pending():
    async def fake_query(*, prompt, options=None, transport=None):
        app_state.stage_agent_action(562, "tasks", "add", "Task X", {})
        raise RuntimeError("CLI weg")
        yield  # pragma: no cover

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()
    app_state.agent_run_locks.clear()
    app_state.pending_agent_actions.clear()
    try:
        with (
            patch("agent.query", fake_query),
            patch("agent.Bot", return_value=mock_bot),
            patch("agent._keep_typing", new=AsyncMock()),
        ):
            await agent.run_agent(562, "Leg X an", [], "")
    finally:
        app_state.pending_agent_actions.clear()
    assert mock_bot.send_message.call_args.kwargs.get("reply_markup") is None
    assert app_state.peek_pending(562) is None
```
Run: `PYTHONPATH=agents .venv/bin/pytest tests/test_agent.py -q`
Expected: PASS.

- [ ] **Step 7: `agent:confirm` / `agent:cancel` Callbacks**

In `agents/callbacks.py`: füge im `handle_callback`-Router nach dem `dismiss`-Zweig (vor dem `mail:send`-Zweig) hinzu:
```python
    elif data.startswith("agent:confirm:"):
        chat_id = query.message.chat_id
        try:
            expected_id = int(data.split(":")[2])
        except (ValueError, IndexError):
            await query.edit_message_text("❌ Ungültiger Confirm.")
            return
        actions = app_state.take_pending_actions(chat_id, expected_id)
        if not actions:
            await query.edit_message_text(
                "⏱️ Diese Vormerkung ist abgelaufen oder überholt — bitte nochmal."
            )
            return
        from tools import execute_pending_action

        results = []
        for action in actions:
            try:
                results.append(await execute_pending_action(action))
            except Exception as e:
                logger.exception("agent:confirm — Aktion fehlgeschlagen")
                results.append(f"❌ {action['label']}: Fehler — {e}")
        await query.edit_message_text("\n".join(results))

    elif data.startswith("agent:cancel:"):
        chat_id = query.message.chat_id
        try:
            expected_id = int(data.split(":")[2])
        except (ValueError, IndexError):
            await query.edit_message_text("❌ Ungültiger Abbruch.")
            return
        cancelled = app_state.take_pending_actions(chat_id, expected_id)
        if cancelled:
            await query.edit_message_text("❌ Abgebrochen.")
        else:
            await query.edit_message_text("⏱️ Diese Vormerkung ist bereits überholt.")
```

- [ ] **Step 8: Callback-Tests**

Erstelle `tests/test_callbacks_agent.py`:
```python
"""Tests für die agent:confirm / agent:cancel Callbacks."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app_state
import callbacks


def _query(data: str):
    q = MagicMock()
    q.data = data
    q.answer = AsyncMock()
    q.edit_message_text = AsyncMock()
    q.message.chat_id = 42
    update = MagicMock()
    update.callback_query = q
    return update, q


@pytest.mark.asyncio
async def test_agent_confirm_executes_pending():
    app_state.pending_agent_actions.clear()
    app_state.stage_agent_action(42, "tasks", "add", "Task A anlegen", {"x": 1})
    pid = app_state.peek_pending(42)["id"]
    update, q = _query(f"agent:confirm:{pid}")

    async def fake_exec(action):
        return f"✅ {action['label']}"

    with patch("tools.execute_pending_action", side_effect=fake_exec):
        await callbacks.handle_callback(update, None)
    q.edit_message_text.assert_awaited_once()
    assert "✅ Task A anlegen" in q.edit_message_text.call_args.args[0]
    assert app_state.peek_pending(42) is None


@pytest.mark.asyncio
async def test_agent_confirm_executes_all_bundled():
    app_state.pending_agent_actions.clear()
    app_state.stage_agent_action(42, "tasks", "add", "Task A", {})
    app_state.stage_agent_action(42, "tasks", "complete", "Task B abhaken", {})
    pid = app_state.peek_pending(42)["id"]
    update, q = _query(f"agent:confirm:{pid}")

    async def fake_exec(action):
        return f"✅ {action['label']}"

    with patch("tools.execute_pending_action", side_effect=fake_exec):
        await callbacks.handle_callback(update, None)
    msg = q.edit_message_text.call_args.args[0]
    assert "Task A" in msg and "Task B abhaken" in msg
    assert app_state.peek_pending(42) is None


@pytest.mark.asyncio
async def test_agent_confirm_stale_id_rejected():
    app_state.pending_agent_actions.clear()
    app_state.stage_agent_action(42, "tasks", "add", "Task A", {})
    pid = app_state.peek_pending(42)["id"]
    update, q = _query(f"agent:confirm:{pid + 999}")  # veraltete/falsche ID
    await callbacks.handle_callback(update, None)
    assert "überholt" in q.edit_message_text.call_args.args[0].lower()
    # falsche ID -> Pending bleibt unangetastet
    assert app_state.peek_pending(42) is not None
    app_state.pending_agent_actions.clear()


@pytest.mark.asyncio
async def test_agent_confirm_nothing_pending():
    app_state.pending_agent_actions.clear()
    update, q = _query("agent:confirm:1")
    await callbacks.handle_callback(update, None)
    assert "abgelaufen" in q.edit_message_text.call_args.args[0].lower()


@pytest.mark.asyncio
async def test_agent_cancel_discards():
    app_state.pending_agent_actions.clear()
    app_state.stage_agent_action(42, "tasks", "add", "Task A", {})
    pid = app_state.peek_pending(42)["id"]
    update, q = _query(f"agent:cancel:{pid}")
    await callbacks.handle_callback(update, None)
    assert app_state.peek_pending(42) is None
    assert "Abgebrochen" in q.edit_message_text.call_args.args[0]
```
Run: `PYTHONPATH=agents .venv/bin/pytest tests/test_callbacks_agent.py -q`
Expected: PASS (5 passed).

- [ ] **Step 9: Volle Suite — grün**

Run das Test-Kommando oben. Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add agents/app_state.py agents/agent.py agents/callbacks.py \
  agents/tools/__init__.py tests/test_pending_actions.py tests/test_agent.py \
  tests/test_callbacks_agent.py
git commit -m "feat(agent): Write-Confirm-Mechanik — Pending-Store mit Set-ID

Schreibaktionen werden vorgemerkt statt direkt ausgeführt; run_agent
leert beim Lauf-Start, hängt am Lauf-Ende einen gebündelten Confirm an.
Jedes Pending-Set hat eine ID im callback_data — ein veralteter Button
führt nie fremde Aktionen aus. Noch ohne Schreib-Tool (Task 2).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 2: `tasks`-Tool

Erstes Schreib-Tool. Chat-skopiert (`make_tasks_tool(chat_id)`), weil Schreib-Aktionen `chat_id` zum Vormerken brauchen. Lese-Aktion `list` läuft frei; Schreib-Aktionen merken vor.

**Files:**
- Create: `agents/tools/tasks_tool.py`
- Create: `tests/test_tools_tasks.py`
- Modify: `agents/tools/__init__.py`
- Modify: `agents/agent.py`
- Modify: `tests/test_tools_registry.py`

- [ ] **Step 1: Failing-Test für das tasks-Tool**

Erstelle `tests/test_tools_tasks.py`:
```python
"""Tests für agents/tools/tasks_tool.py."""

import pytest

import app_state
import tools.tasks_tool as tasks_tool_mod


@pytest.mark.asyncio
async def test_list_action_reads_immediately(monkeypatch):
    monkeypatch.setattr(tasks_tool_mod, "get_tasks", lambda ln: "📋 Liste: A, B")
    tool = tasks_tool_mod.make_tasks_tool(7)
    result = await tool.handler({"action": "list", "list_name": "Einkaufen"})
    assert "Liste: A, B" in result["content"][0]["text"]


@pytest.mark.asyncio
async def test_add_action_stages_not_executes(monkeypatch):
    app_state.pending_agent_actions.clear()
    called = []
    monkeypatch.setattr(
        tasks_tool_mod, "add_task", lambda *a, **k: called.append(a) or True
    )
    tool = tasks_tool_mod.make_tasks_tool(7)
    result = await tool.handler(
        {"action": "add", "list_name": "Einkaufen", "title": "Milch"}
    )
    # vorgemerkt, NICHT ausgeführt
    assert called == []
    assert "vorgemerkt" in result["content"][0]["text"].lower()
    entry = app_state.peek_pending(7)
    assert entry is not None and len(entry["actions"]) == 1
    assert entry["actions"][0]["tool"] == "tasks"
    assert entry["actions"][0]["action"] == "add"
    assert entry["actions"][0]["params"]["title"] == "Milch"
    app_state.pending_agent_actions.clear()


@pytest.mark.asyncio
async def test_add_action_requires_list_and_title():
    app_state.pending_agent_actions.clear()
    tool = tasks_tool_mod.make_tasks_tool(7)
    result = await tool.handler({"action": "add", "title": "Milch"})
    assert result["content"][0]["text"].startswith("FEHLER")
    assert app_state.peek_pending(7) is None


@pytest.mark.asyncio
async def test_unknown_action_is_error():
    tool = tasks_tool_mod.make_tasks_tool(7)
    result = await tool.handler({"action": "frobnicate"})
    assert result["content"][0]["text"].startswith("FEHLER")


@pytest.mark.asyncio
async def test_execute_write_add_calls_add_task(monkeypatch):
    calls = []
    monkeypatch.setattr(
        tasks_tool_mod, "add_task", lambda *a: calls.append(a) or True
    )
    msg = await tasks_tool_mod.execute_write(
        "add", {"list_name": "Einkaufen", "title": "Milch", "due_date": None,
                "due_time": None}
    )
    assert calls == [("Einkaufen", "Milch", None, None)]
    assert "✅" in msg


@pytest.mark.asyncio
async def test_execute_write_add_failure(monkeypatch):
    monkeypatch.setattr(tasks_tool_mod, "add_task", lambda *a: False)
    msg = await tasks_tool_mod.execute_write(
        "add", {"list_name": "Nope", "title": "X", "due_date": None,
                "due_time": None}
    )
    assert "❌" in msg


@pytest.mark.asyncio
async def test_stage_then_execute_via_registry(monkeypatch):
    """Integration: Tool merkt vor -> execute_pending_action führt aus."""
    import tools

    app_state.pending_agent_actions.clear()
    calls = []
    monkeypatch.setattr(tasks_tool_mod, "add_task", lambda *a: calls.append(a) or True)
    tool = tasks_tool_mod.make_tasks_tool(9)
    await tool.handler({"action": "add", "list_name": "Einkaufen", "title": "Milch"})
    entry = app_state.peek_pending(9)
    assert entry is not None and len(entry["actions"]) == 1
    msg = await tools.execute_pending_action(entry["actions"][0])
    assert calls == [("Einkaufen", "Milch", None, None)]
    assert "✅" in msg
    app_state.pending_agent_actions.clear()
```
Run: `PYTHONPATH=agents .venv/bin/pytest tests/test_tools_tasks.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.tasks_tool'`.

- [ ] **Step 2: `agents/tools/tasks_tool.py` anlegen**

Erstelle `agents/tools/tasks_tool.py`:
```python
"""tasks-Tool — MS-To-Do-Listen lesen und ändern.

action='list' ist read-only und läuft sofort. Alle anderen Aktionen sind
Schreib-Aktionen: sie führen NICHT direkt aus, sondern werden via
app_state.stage_agent_action vorgemerkt und nach dem gebündelten Confirm
durch execute_write ausgeführt.
"""

import asyncio

from claude_agent_sdk import tool

import app_state
from tasks_agent import (
    add_task,
    complete_task,
    create_list,
    delete_list,
    get_tasks,
    rename_list,
)

_WRITE_ACTIONS = {"add", "complete", "create_list", "delete_list", "rename_list"}


def _label(action: str, params: dict) -> str:
    """Menschenlesbare Beschreibung einer vorgemerkten Aktion (für den Confirm)."""
    ln = params.get("list_name", "")
    if action == "add":
        due = f" (fällig {params['due_date']})" if params.get("due_date") else ""
        return f"Task '{params['title']}' zu Liste '{ln}' hinzufügen{due}"
    if action == "complete":
        return f"Task '{params['title']}' in '{ln}' als erledigt markieren"
    if action == "create_list":
        return f"To-Do-Liste '{params['name']}' anlegen"
    if action == "delete_list":
        return f"To-Do-Liste '{ln}' löschen"
    if action == "rename_list":
        return f"Liste '{ln}' umbenennen zu '{params['new_name']}'"
    return action


def _missing_fields(action: str, params: dict) -> str:
    """Gibt fehlende Pflichtfelder als Text zurück, sonst ''."""
    required = {
        "add": ("list_name", "title"),
        "complete": ("list_name", "title"),
        "create_list": ("name",),
        "delete_list": ("list_name",),
        "rename_list": ("list_name", "new_name"),
    }[action]
    return ", ".join(f for f in required if not params.get(f))


def make_tasks_tool(chat_id: int):
    """Baut das tasks-Tool für einen Lauf — chat_id für das Vormerken eingeschlossen."""

    @tool(
        "tasks",
        "MS-To-Do-Listen lesen und ändern. "
        "action='list': offene Tasks einer Liste, oder alle Listen wenn list_name "
        "leer (read). "
        "action='add': Task/Erinnerung anlegen (list_name, title; optional due_date "
        "'YYYY-MM-DD', due_time 'HH:MM'). "
        "action='complete': Task abhaken (list_name, title — title muss EXAKT dem "
        "Task-Titel entsprechen; bei Unsicherheit vorher action='list' aufrufen). "
        "action='create_list' (name) / 'delete_list' (list_name) / "
        "'rename_list' (list_name, new_name). "
        "Alle Aktionen außer 'list' werden vorgemerkt und erst nach Bestätigung "
        "durch Philipp ausgeführt — sag ihm im Antworttext, was du vorbereitet hast.",
        {
            "action": str,
            "list_name": str,
            "title": str,
            "name": str,
            "new_name": str,
            "due_date": str,
            "due_time": str,
        },
    )
    async def tasks_tool(args: dict) -> dict:
        action = (args.get("action") or "").strip()
        if action == "list":
            list_name = (args.get("list_name") or "").strip() or None
            result = await asyncio.to_thread(get_tasks, list_name)
            return {"content": [{"type": "text", "text": result}]}
        if action not in _WRITE_ACTIONS:
            return _text(
                f"FEHLER: Unbekannte action '{action}'. Erlaubt: list, add, "
                "complete, create_list, delete_list, rename_list."
            )
        # Schreib-Aktion → Pflichtfelder prüfen, dann vormerken.
        params = {
            "list_name": (args.get("list_name") or "").strip(),
            "title": (args.get("title") or "").strip(),
            "name": (args.get("name") or "").strip(),
            "new_name": (args.get("new_name") or "").strip(),
            "due_date": (args.get("due_date") or "").strip() or None,
            "due_time": (args.get("due_time") or "").strip() or None,
        }
        missing = _missing_fields(action, params)
        if missing:
            return _text(f"FEHLER: action='{action}' braucht: {missing}.")
        label = _label(action, params)
        app_state.stage_agent_action(chat_id, "tasks", action, label, params)
        return _text(
            f"✅ Vorgemerkt: {label}. Wird nach Philipps Bestätigung ausgeführt "
            "— du musst nicht warten."
        )

    return tasks_tool


def _text(msg: str) -> dict:
    """MCP-Tool-Rückgabe mit einem Text-Block."""
    return {"content": [{"type": "text", "text": msg}]}


async def execute_write(action: str, params: dict) -> str:
    """Eine vorgemerkte tasks-Schreibaktion tatsächlich ausführen.

    Wird vom Confirm-Callback via tools.execute_pending_action aufgerufen.
    """
    if action == "add":
        ok = await asyncio.to_thread(
            add_task,
            params["list_name"],
            params["title"],
            params.get("due_date"),
            params.get("due_time"),
        )
        return (
            f"✅ Task '{params['title']}' angelegt."
            if ok
            else f"❌ Task '{params['title']}' — Liste '{params['list_name']}' "
            "nicht gefunden."
        )
    if action == "complete":
        ok = await asyncio.to_thread(
            complete_task, params["list_name"], params["title"]
        )
        return (
            f"✅ '{params['title']}' als erledigt markiert."
            if ok
            else f"❌ '{params['title']}' nicht gefunden oder schon erledigt."
        )
    if action == "create_list":
        ok = await asyncio.to_thread(create_list, params["name"])
        _invalidate_list_cache(ok)
        return (
            f"✅ Liste '{params['name']}' angelegt."
            if ok
            else "❌ Liste konnte nicht angelegt werden."
        )
    if action == "delete_list":
        ok = await asyncio.to_thread(delete_list, params["list_name"])
        _invalidate_list_cache(ok)
        return (
            f"✅ Liste '{params['list_name']}' gelöscht."
            if ok
            else f"❌ Liste '{params['list_name']}' nicht gefunden."
        )
    if action == "rename_list":
        ok = await asyncio.to_thread(
            rename_list, params["list_name"], params["new_name"]
        )
        _invalidate_list_cache(ok)
        return (
            f"✅ Liste '{params['list_name']}' umbenannt zu '{params['new_name']}'."
            if ok
            else f"❌ Liste '{params['list_name']}' nicht gefunden."
        )
    return f"❌ Unbekannte tasks-Aktion '{action}'."


def _invalidate_list_cache(ok: bool) -> None:
    """Nach einer Listen-Mutation den To-Do-Listen-Cache des Routers leeren.

    Deferred import — vermeidet einen Import-Zyklus tools -> router.
    """
    if not ok:
        return
    import router

    router._todo_lists_cache = ([], 0.0)
```

- [ ] **Step 3: tasks-Test laufen lassen — muss bestehen**

Run: `PYTHONPATH=agents .venv/bin/pytest tests/test_tools_tasks.py -q`
Expected: PASS (7 passed).

- [ ] **Step 4: `tasks` in der Registry registrieren (chat-skopiert)**

In `agents/tools/__init__.py`:

(a) Ergänze unter den bestehenden Tool-Imports:
```python
from . import tasks_tool
```

(b) Ersetze den Block, der `_TOOLS`, `_ALLOWED_TOOL_NAMES` und `build_mcp_server` definiert, durch:
```python
# Read-only Tools sind module-level; chat-skopierte Tools (tasks) werden pro
# Lauf gebaut, weil sie chat_id zum Vormerken von Schreibaktionen brauchen.
_STATIC_TOOLS = [_workspace_capability, _weather_capability, _news_capability]


def _all_tools(chat_id: int) -> list:
    """Alle Tool-Objekte für einen Lauf."""
    return _STATIC_TOOLS + [tasks_tool.make_tasks_tool(chat_id)]


# Allowlist — aus einem Probe-Build; chat_id ist für die Namen irrelevant.
_ALLOWED_TOOL_NAMES = {
    f"mcp__{_MCP_SERVER_NAME}__{t.name}" for t in _all_tools(0)
}


def build_mcp_server(chat_id: int) -> McpSdkServerConfig:
    """In-Process-MCP-Server mit allen Jarvis-Tools für einen Chat."""
    return create_sdk_mcp_server(
        name=_MCP_SERVER_NAME, version="1.0.0", tools=_all_tools(chat_id)
    )
```
(Die alte `_TOOLS`-Liste und das alte `build_mcp_server` ohne Parameter entfallen.)

(c) Ändere `_WRITE_EXECUTORS: dict = {}` zu:
```python
_WRITE_EXECUTORS: dict = {"tasks": tasks_tool.execute_write}
```

- [ ] **Step 5: `run_agent` ruft `build_mcp_server(chat_id)`**

In `agents/agent.py`, in `run_agent`, ändere
```python
                mcp_servers={"jarvis": build_mcp_server()},
```
zu
```python
                mcp_servers={"jarvis": build_mcp_server(chat_id)},
```

- [ ] **Step 6: Registry-Test erweitern**

In `tests/test_tools_registry.py`:

(a) In `test_build_mcp_server_registers_tools`: ergänze nach der news-Assertion `assert "mcp__jarvis__tasks" in tools._ALLOWED_TOOL_NAMES` und ändere jeden `build_mcp_server(...)`-Aufruf zu `tools.build_mcp_server(0)`.

Run: `PYTHONPATH=agents .venv/bin/pytest tests/test_tools_registry.py tests/test_tools_tasks.py -q`
Expected: PASS.

- [ ] **Step 7: Volle Suite — grün**

Run das Test-Kommando oben. Expected: PASS. Die `run_agent`-Tests in `test_agent.py` mocken `agent.query`, daher wird `build_mcp_server(chat_id)` real aufgerufen — `run_agent` reicht `chat_id` durch; kein Test-Change nötig, aber verifizieren.

- [ ] **Step 8: Commit**

```bash
git add agents/tools/tasks_tool.py agents/tools/__init__.py agents/agent.py \
  tests/test_tools_tasks.py tests/test_tools_registry.py
git commit -m "feat(agent): tasks-Tool — erstes Schreib-Tool mit Vormerk-Confirm

Chat-skopiertes tasks-Tool (make_tasks_tool): action='list' liest frei,
add/complete/create_list/delete_list/rename_list werden vorgemerkt und
nach Bestätigung via execute_write ausgeführt. build_mcp_server nimmt
jetzt chat_id.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 3: Verdrahtung — `tasks` + `reminder_write` agentisch

**Files:**
- Modify: `agents/dispatch.py`
- Modify: `agents/intent_handlers.py`
- Modify: `agents/agent.py`
- Modify: `tests/test_agent.py`
- Modify: `tests/test_agent_dispatch.py`
- Modify: `tests/test_dispatch_main.py`

- [ ] **Step 1: System-Prompt — Failing-Assertion**

In `tests/test_agent.py`, in `test_system_prompt_empty_memory`, ergänze nach der `news`-Assertion:
```python
    assert "- tasks:" in prompt
```
Run: `PYTHONPATH=agents .venv/bin/pytest tests/test_agent.py::test_system_prompt_empty_memory -q`
Expected: FAIL.

- [ ] **Step 2: tasks in den System-Prompt**

In `agents/agent.py`, in `build_system_prompt`, ersetze:
```python
        "- news: Aktuelle AI-/Tech-News aus kuratierten RSS-Feeds.\n"
        "- WebSearch / WebFetch: Aktuelle Informationen aus dem Internet.\n\n"
```
durch:
```python
        "- news: Aktuelle AI-/Tech-News aus kuratierten RSS-Feeds.\n"
        "- tasks: MS-To-Do-Listen lesen und ändern (Tasks/Erinnerungen anlegen, "
        "abhaken, Listen verwalten). Schreib-Aktionen werden vorgemerkt und erst "
        "nach Philipps Bestätigung ausgeführt — sag ihm, was du vorbereitet hast.\n"
        "- WebSearch / WebFetch: Aktuelle Informationen aus dem Internet.\n\n"
```
Run: `PYTHONPATH=agents .venv/bin/pytest tests/test_agent.py::test_system_prompt_empty_memory -q`
Expected: PASS.

- [ ] **Step 3: `dispatch.py` — `tasks` + `reminder_write` agentisch routen**

In `agents/dispatch.py`:

(a) Ergänze `"tasks"` und `"reminder_write"` in `_HISTORY_INTENTS` und `_AGENT_INTENTS` (nicht `_MEMORY_INTENTS`). Ergebnis:
```python
_HISTORY_INTENTS = {"personal", "work", "research", "weather", "news", "tasks", "reminder_write"}
```
und
```python
_AGENT_INTENTS = {"personal", "work", "research", "weather", "news", "tasks", "reminder_write"}
```

(b) Entferne im `from intent_handlers import (...)`-Block die Zeilen `    handle_reminder_write,` und `    handle_tasks,`.

(c) Entferne in `_process_text` die beiden Zweige:
```python
    elif intent == "reminder_write":
        await handle_reminder_write(chat_id, params, update)
        return
```
und
```python
    elif intent == "tasks":
        await handle_tasks(chat_id, params, update)
```

- [ ] **Step 4: `intent_handlers.py` — tote Handler löschen**

In `agents/intent_handlers.py`:

(a) Entferne die Import-Zeile `import router`.

(b) Entferne den `from tasks_agent import (...)`-Block vollständig.

(c) Lösche die gesamte Funktion `handle_reminder_write`.

(d) Lösche die gesamte Funktion `handle_tasks`.

(`asyncio`, `os`, `_conv_complete` und die übrigen Handler/Imports bleiben.)

- [ ] **Step 5: Dispatch-Tests anpassen**

(a) In `tests/test_dispatch_main.py`: lösche `test_tasks_read_intent_calls_get_tasks` und `test_reminder_write_intent_calls_add_task` vollständig.

(b) In `tests/test_agent_dispatch.py`: ergänze nach `test_news_routed_to_agent`:
```python
@pytest.mark.asyncio
async def test_tasks_routed_to_agent():
    app_state.conversation_db = None
    app_state.profile_agent = None
    app_state.memory_agent = None
    update = MagicMock()
    with (
        patch("dispatch.route_with_llm", new=AsyncMock(return_value=_routing("tasks"))),
        patch(
            "dispatch.run_agent", new=AsyncMock(return_value="Tasks-Antwort")
        ) as mock_run,
    ):
        await dispatch._process_text("Zeig meine Tasks", 123, update)
    mock_run.assert_awaited_once()


@pytest.mark.asyncio
async def test_reminder_write_routed_to_agent():
    app_state.conversation_db = None
    app_state.profile_agent = None
    app_state.memory_agent = None
    update = MagicMock()
    with (
        patch(
            "dispatch.route_with_llm",
            new=AsyncMock(return_value=_routing("reminder_write")),
        ),
        patch(
            "dispatch.run_agent", new=AsyncMock(return_value="Erinnerung-Antwort")
        ) as mock_run,
    ):
        await dispatch._process_text("Erinnere mich an den Anruf", 123, update)
    mock_run.assert_awaited_once()
```

- [ ] **Step 6: Volle Suite — grün**

Run das Test-Kommando oben. Expected: PASS. Bei Fehlern nach übersehenen Referenzen auf `handle_tasks` / `handle_reminder_write` suchen.

- [ ] **Step 7: Commit**

```bash
git add agents/dispatch.py agents/intent_handlers.py agents/agent.py \
  tests/test_agent.py tests/test_agent_dispatch.py tests/test_dispatch_main.py
git commit -m "feat(agent): tasks + reminder_write laufen agentisch

Beide Intents wandern in _AGENT_INTENTS/_HISTORY_INTENTS; der Agent
nutzt das tasks-Tool. handle_tasks und handle_reminder_write entfallen.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 4: `CLAUDE.md` nachziehen

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Architektur-Überblick — `tasks`/`reminder_write` zum Agenten**

Im Code-Block „Architektur-Überblick": entferne die Router-Zweige
```
        ├── tasks           tasks_agent.py
        ├── reminder_write  tasks_agent.py (add_task mit due_date/due_time)
```
und ersetze den Agenten-Block durch:
```
        ├── personal      ┐
        ├── work          │
        ├── research      ├─ agent.py run_agent — echter Agent (Claude Agent SDK):
        ├── weather       │  Tools workspace/web/weather/news/tasks, Denk-Schleife,
        ├── news          │  History, MemoryAgent, Write-Confirm
        ├── tasks         │
        └── reminder_write┘
```

- [ ] **Step 2: Datei-Struktur — `intent_handlers.py`-Beschreibung**

Ersetze die Zeile
```
  intent_handlers.py    Schlanke Intent-Handler (coding/tasks/briefing/...)
```
durch
```
  intent_handlers.py    Schlanke Intent-Handler (coding/briefing/memory)
```

- [ ] **Step 3: Abschnitt „Agentischer Pfad" — Werkzeug-Liste + Write-Confirm**

Ersetze im Abschnitt „Agentischer Pfad" die Zeile
```
- Werkzeuge: `workspace`, `weather`, `news` + die eingebauten `WebSearch`/`WebFetch`. Built-in
```
durch
```
- Werkzeuge: `workspace`, `weather`, `news`, `tasks` + die eingebauten `WebSearch`/`WebFetch`. Built-in
```
und ergänze direkt nach dem `- Werkzeuge:`-Listenpunkt einen neuen Absatz:
```
**Write-Confirm:** Schreib-Aktionen von Tools (ab `tasks`) führen nicht direkt
aus — sie werden vorgemerkt (`app_state.pending_agent_actions`, je Lauf ein Set
mit ID), `run_agent` hängt am Lauf-Ende einen gebündelten InlineKeyboard-Confirm
an. Die Callbacks `agent:confirm:{id}`/`agent:cancel:{id}` führen aus bzw.
verwerfen; die ID verhindert, dass ein veralteter Button fremde Aktionen ausführt.
```

- [ ] **Step 4: Callbacks-Tabelle ergänzen**

Ergänze in der Callback-Tabelle (Abschnitt „Callbacks (InlineKeyboard)") zwei Zeilen:
```
| `agent:confirm:{id}` | handle_callback | Vorgemerkte Agenten-Schreibaktionen ausführen |
| `agent:cancel:{id}` | handle_callback | Vorgemerkte Agenten-Schreibaktionen verwerfen |
```

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(agent): CLAUDE.md — tasks agentisch + Write-Confirm dokumentiert

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Self-Review-Notiz

Plan 3 deckt aus dem Design Sektion 3 (Read vs. Write, Vormerk-/Confirm-Mechanik)
und Konvertierungs-Sequenz #3 (`tasks`, mit `reminder_write` eingefaltet) ab. Task 1
baut die Mechanik isoliert + unit-getestet (Pending-Store mit Set-ID, Lauf-Start-
Clear, Lauf-Ende-Confirm, `agent:*`-Callbacks, Executor-Registry); Task 2 ist der
erste Nutzer (`tasks`) inkl. Integrationstest Tool→`stage`→`execute_pending_action`;
Task 3 verdrahtet; Task 4 Doku. Die **Set-ID** im `callback_data` stellt sicher,
dass ein veralteter Confirm-Button niemals die Aktionen eines neueren Laufs
ausführt — kritisch, weil 7 weitere Write-Tools auf dieser Mechanik aufbauen.
**Nicht** in Plan 3: `mail`/`calendar` (Plan 4), `coding` (Plan 5), Agent-
Fortsetzung nach Confirm (v2 laut Design). Das `chat_id`-Scoping von
`build_mcp_server` kommt in Task 2 — beim ersten Tool, das es real braucht.
Alle `tasks`-Schreib-Aktionen confirmen einheitlich (auch unkritische wie `add`);
das bewährt die Mechanik sauber und zeigt das geparste Erinnerungs-Datum vor dem
Speichern — Watch-Item siehe Design Sektion 3.
