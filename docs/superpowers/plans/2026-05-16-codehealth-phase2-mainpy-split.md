# Code-Gesundheit Phase 2 — `main.py`-Split — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `agents/main.py` (~1784 Zeilen) verhaltensneutral in zehn fokussierte Module aufteilen und `_process_text` in per-Intent-Handler zerlegen.

**Architecture:** Zuerst das Testnetz vervollständigen, dann `_process_text` *in place* zerlegen (einziger Logik-Risiko-Schritt), dann reine Datei-Moves. Geteilter State lebt in einem import-armen `app_state.py`. Abhängigkeiten fließen eine Richtung: `main → dispatch/callbacks → handler → app_state/formatting`.

**Tech Stack:** Python 3.11 · FastAPI · python-telegram-bot · pytest

**Spec:** `docs/superpowers/specs/2026-05-16-codehealth-phase2-mainpy-split-design.md`

**Tests lokal ausführen:**
```bash
PYTHONPATH=agents .venv/bin/pytest tests/ -q --tb=short \
  --ignore=tests/test_briefing_agent.py \
  --ignore=tests/test_mail_send.py \
  --ignore=tests/test_tasks_agent.py
```

---

## Standard-Move-Vorgehen (für Tasks 4–11)

Die Tasks 4–11 sind reine Relocations. Jeder folgt exakt diesem Ablauf — die Task-Beschreibung liefert nur die Parameter (Zielmodul, zu verschiebende Symbole):

1. **Neue Datei anlegen** mit Kopfzeile `"""<Modulzweck>"""` und `logger = logging.getLogger("jarvis.<modul>")`.
2. **Symbole verschieben** — die genannten Funktionen/Konstanten **byte-identisch** (Rumpf unverändert) aus `agents/main.py` ausschneiden und ins neue Modul einfügen.
3. **Importe im neuen Modul ergänzen** — alle Namen, die der verschobene Code referenziert (Stdlib, `telegram`, `app_state`, andere Handler-Module, Agenten-Module), als Import-Block oben ergänzen. Funktionslokale Importe (`from mail_agent import MailAgent` etc.) bleiben funktionslokal und ziehen unverändert mit.
4. **`main.py` anpassen** — `from <modul> import <namen>` für alle Symbole ergänzen, die `main.py` noch referenziert.
5. **Test-Importe nachziehen** — jede Testdatei, die ein verschobenes Symbol per `from agents.main import …` importiert oder per `patch("agents.main.<symbol>")` patcht, auf das neue Modul umstellen (`agents.<modul>.<symbol>`).
6. **Verifizieren:**
   - `PYTHONPATH=agents .venv/bin/python -m py_compile agents/main.py agents/<modul>.py` → keine Fehler
   - `PYTHONPATH=agents .venv/bin/python -c "import agents.main"` → kein ImportError (Smoke-Test, keine Zyklen)
   - komplette Suite grün
   - `git diff` der verschobenen Funktionen prüfen: die Rümpfe MÜSSEN identisch sein (reine Verschiebung) — nur Ort + Importzeilen ändern sich
7. **Commit.**

Wenn `py_compile` einen `NameError`/fehlenden Import meldet: den Import im neuen Modul ergänzen (Schritt 3) — nicht den Code ändern.

---

## Task 1: `_process_text`-Dispatch-Testnetz vervollständigen

Charakterisierungs-Tests für die Intent-Dispatch, die heute keinen Test haben. Sie treffen `handle_message` → `_process_text` und überleben die Zerlegung in Task 2 unverändert — sie sind deren Verifikat. Kein Code-Move.

**Files:**
- Create: `tests/test_dispatch_main.py`

- [ ] **Step 1: `tests/test_dispatch_main.py` schreiben**

```python
# tests/test_dispatch_main.py
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import agents.main as main


def _make_update(text, chat_id=123, update_id=90001):
    update = MagicMock()
    update.update_id = update_id
    update.message.text = text
    update.message.chat_id = chat_id
    update.message.reply_text = AsyncMock()
    return update


def _route(intent, params=None):
    return {"intent": intent, "confidence": 9, "params": params or {}, "reasoning": "t"}


def test_mail_intent_dispatches_to_handle_mail():
    with patch("agents.main.route_with_llm", return_value=_route("mail", {"mode": "quick_scan"})), \
         patch("agents.main.handle_mail", new_callable=AsyncMock) as mock_mail:
        asyncio.run(main.handle_message(_make_update("Was Wichtiges im Posteingang?"), None))
    mock_mail.assert_awaited_once()


def test_research_intent_calls_ask_claude_with_web_search():
    with patch("agents.main.route_with_llm", return_value=_route("research")), \
         patch("agents.main.ask_claude", new_callable=AsyncMock, return_value="ok") as mock_ask, \
         patch("agents.main.send_typing", new_callable=AsyncMock):
        asyncio.run(main.handle_message(_make_update("Recherchiere ESG 2026"), None))
    assert mock_ask.await_args.kwargs.get("use_web_search") is True


def test_work_intent_uses_sonnet():
    with patch("agents.main.route_with_llm", return_value=_route("work")), \
         patch("agents.main.ask_claude", new_callable=AsyncMock, return_value="ok") as mock_ask, \
         patch("agents.main.send_typing", new_callable=AsyncMock):
        asyncio.run(main.handle_message(_make_update("Fass das zusammen"), None))
    assert mock_ask.await_args.kwargs.get("model") == "claude-sonnet-4-6"


def test_news_intent_calls_get_ai_news():
    with patch("agents.main.route_with_llm", return_value=_route("news")), \
         patch("agents.main.get_ai_news", return_value="news text") as mock_news:
        asyncio.run(main.handle_message(_make_update("Was gibt es Neues in AI?"), None))
    mock_news.assert_called_once()


def test_weather_intent_calls_get_weather():
    with patch("agents.main.route_with_llm", return_value=_route("weather", {"period": "today"})), \
         patch("agents.main.get_weather", return_value="sonnig") as mock_weather:
        asyncio.run(main.handle_message(_make_update("Wie wird das Wetter?"), None))
    mock_weather.assert_called_once()


def test_briefing_intent_calls_build_briefing():
    with patch("agents.main.route_with_llm", return_value=_route("briefing")), \
         patch("agents.main.build_briefing", new_callable=AsyncMock, return_value="briefing") as mock_b:
        asyncio.run(main.handle_message(_make_update("Mein Briefing bitte"), None))
    mock_b.assert_awaited_once()


def test_tasks_read_intent_calls_get_tasks():
    with patch("agents.main.route_with_llm", return_value=_route("tasks", {"mode": "read"})), \
         patch("agents.main.get_tasks", return_value="• task") as mock_tasks:
        asyncio.run(main.handle_message(_make_update("Zeig meine Tasks"), None))
    mock_tasks.assert_called_once()


def test_reminder_write_intent_calls_add_task():
    with patch("agents.main.route_with_llm",
               return_value=_route("reminder_write", {"title": "Anruf", "due_date": None})), \
         patch("agents.main.add_task", return_value=True) as mock_add:
        asyncio.run(main.handle_message(_make_update("Erinnere mich an den Anruf"), None))
    mock_add.assert_called_once()


def test_coding_query_intent_calls_handle_coding_query():
    with patch("agents.main.route_with_llm",
               return_value=_route("coding", {"mode": "query", "project": "recipe-app", "query_type": "backlog"})), \
         patch("agents.main.handle_coding_query", new_callable=AsyncMock, return_value="backlog") as mock_q:
        asyncio.run(main.handle_message(_make_update("Backlog von recipe-app?"), None))
    mock_q.assert_awaited_once()


def test_low_confidence_asks_for_clarification():
    routing = {"intent": "mail", "confidence": 2, "params": {}, "reasoning": "t"}
    update = _make_update("hm")
    with patch("agents.main.route_with_llm", return_value=routing):
        asyncio.run(main.handle_message(update, None))
    assert "nicht ganz sicher" in update.message.reply_text.call_args[0][0]
```

- [ ] **Step 2: Tests laufen lassen**

Run: `PYTHONPATH=agents .venv/bin/pytest tests/test_dispatch_main.py -v`
Expected: 10 passed. Falls ein Test fehlschlägt, weil der Patch-Pfad nicht stimmt (z.B. ein Name ist funktionslokal importiert statt auf Modulebene) — den Patch-Pfad korrigieren; das Verhalten NICHT ändern. Falls ein echter Bug auffällt: melden, nicht einbetonieren.

- [ ] **Step 3: Komplette Suite**

Run:
```bash
PYTHONPATH=agents .venv/bin/pytest tests/ -q --tb=short \
  --ignore=tests/test_briefing_agent.py --ignore=tests/test_mail_send.py --ignore=tests/test_tasks_agent.py
```
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_dispatch_main.py
git commit -m "test(dispatch): Charakterisierungs-Tests für _process_text-Intent-Dispatch

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: `_process_text` *in place* zerlegen

Einziger Logik-Risiko-Task. Jeder `if/elif intent ==`-Branch wird **byte-identisch** zu einer `handle_<intent>`-Funktion; `_process_text` wird zum Orchestrator. Alles bleibt in `main.py` — kein Datei-Move. Das Testnetz (Task 1 + bestehende `test_*_main.py`) beweist Verhaltensneutralität.

**Files:**
- Modify: `agents/main.py`

- [ ] **Step 1: Pro Intent eine `handle_<intent>`-Funktion anlegen**

Für jeden Branch eine neue `async def`-Funktion direkt **vor** `_process_text` in `main.py` einfügen. Der Funktionsrumpf ist der **bestehende Branch-Body unverändert** (gleiche Einrückung angepasst). Signaturen (exakt diese — abgeleitet aus den Variablen, die der Branch heute aus dem `_process_text`-Scope liest):

| Funktion | Signatur | Branch-Body (Zeilen in alt-`main.py`) | Rückgabe |
|---|---|---|---|
| `handle_calendar_intent` | `(chat_id, text, params)` | calendar-Branch (`mode`-Logik, `handle_calendar`/`handle_calendar_modify`-Aufrufe, `_conv_complete`) | `None` |
| `handle_mail_intent` | `(chat_id, text, params)` | mail-Branch (`handle_mail` + `_conv_complete`) | `None` |
| `handle_research` | `(chat_id, text, memory_context, history)` | research-Branch (`_keep_typing`, `ask_claude` mit web_search, `_memory_agent.extract`) | `answer` (str) |
| `handle_coding` | `(chat_id, text, params, update)` | coding-Branch (query/backlog_write/action) | `None` |
| `handle_reminder_write` | `(chat_id, params, update)` | reminder_write-Branch | `None` |
| `handle_work` | `(chat_id, text, memory_context, history)` | work-Branch (`ask_claude` mit web_search, sonnet) | `answer` (str) |
| `handle_news` | `(chat_id, update)` | news-Branch | `None` |
| `handle_tasks` | `(chat_id, params, update)` | tasks-Branch (alle `mode`-Zweige) | `None` |
| `handle_weather` | `(chat_id, params, update)` | weather-Branch | `None` |
| `handle_briefing` | `(chat_id, update)` | briefing-Branch | `None` |
| `handle_memory` | `(chat_id, params, update)` | memory-Branch | `None` |
| `handle_personal` | `(chat_id, text, memory_context, history)` | else-Branch (personal_system, `ask_claude`) | `answer` (str) |

Regeln:
- Der Rumpf jeder Funktion ist der jeweilige Branch-Body **wörtlich** — keine Logik-Änderung.
- `handle_research`/`handle_work`/`handle_personal` enden mit `return answer` (die Variable, die sie heute setzen).
- `handle_calendar_intent`, `handle_reminder_write`, `handle_memory` enthalten ihr bestehendes `return` (sie kehren früh zurück) — kein expliziter Rückgabewert nötig.
- Die übrigen geben implizit `None` zurück.

- [ ] **Step 2: `_process_text` zum Orchestrator umbauen**

Ersetze in `_process_text` den gesamten `if intent == "calendar": … else: …`-Block (alle Branch-Bodies) durch diese Dispatch-Aufrufe — Vor-Logik (prev/append/route/confidence/memory_context/history) und Nach-Logik (`_conv_complete`/History-Speichern/Profil) bleiben **unverändert**:

```python
    if intent == "calendar":
        await handle_calendar_intent(chat_id, text, params)
        return

    if intent == "mail":
        await handle_mail_intent(chat_id, text, params)
        return

    if intent == "research":
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

Die Zeilen davor (bis einschließlich History-Laden) und danach (`if answer …: _conv_complete` + History-Speichern + Profil-Update) bleiben Zeile für Zeile unverändert.

- [ ] **Step 3: Syntax + komplette Suite**

Run:
```bash
PYTHONPATH=agents .venv/bin/python -m py_compile agents/main.py && \
PYTHONPATH=agents .venv/bin/pytest tests/ -q --tb=short \
  --ignore=tests/test_briefing_agent.py --ignore=tests/test_mail_send.py --ignore=tests/test_tasks_agent.py
```
Expected: kein Compile-Fehler; alle Tests grün — das beweist die Verhaltensneutralität der Zerlegung.

- [ ] **Step 4: Commit**

```bash
git add agents/main.py
git commit -m "refactor(dispatch): _process_text in per-Intent-Handler zerlegen (in place)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: `app_state.py` — geteilten State extrahieren

**Files:**
- Create: `agents/app_state.py`
- Modify: `agents/main.py`
- Modify: betroffene Testdateien

- [ ] **Step 1: `agents/app_state.py` anlegen**

```python
"""
Shared mutable state for the Jarvis gateway.

Import-light by design — holds only state values, no agent classes.
startup() in main.py populates memory_agent / conversation_db / profile_agent.
"""

import os
import time

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

# Pending confirm-ops (chat_id -> op dict) and multi-result selections.
pending_mail_ops: dict[int, dict] = {}
pending_calendar_ops: dict[int, dict] = {}
last_mail_search: dict[int, dict] = {}
last_calendar_search: dict[int, dict] = {}

# Telegram update dedup.
processed_updates: set = set()

# Lazy-initialized agents — set by startup().
memory_agent = None
conversation_db = None
profile_agent = None

_PENDING_OP_TTL = 600  # Sekunden — Confirm-Buttons älter als 10 Min gelten als abgelaufen


def _pending_op_expired(op: dict) -> bool:
    """True wenn eine Pending-Op älter als _PENDING_OP_TTL ist."""
    return time.time() - op.get("staged_at", 0) > _PENDING_OP_TTL
```

- [ ] **Step 2: In `agents/main.py` die alten Definitionen entfernen und alle Referenzen umbenennen**

Entferne aus `main.py` die jetzt nach `app_state.py` umgezogenen Definitionen: `TELEGRAM_TOKEN = …`, `processed_updates = set()`, die vier `_pending_*`/`_last_*`-Dict-Definitionen, `_PENDING_OP_TTL`, `_pending_op_expired`, und die drei `_memory_agent = None`/`_conversation_db = None`/`_profile_agent = None`-Zeilen.

Ergänze `import app_state` oben.

Benenne **alle** verbliebenen Referenzen in `main.py` um (reine Namens-Ersetzung, keine Logik-Änderung):
- `TELEGRAM_TOKEN` → `app_state.TELEGRAM_TOKEN`
- `processed_updates` → `app_state.processed_updates`
- `_pending_mail_ops` → `app_state.pending_mail_ops`
- `_pending_calendar_ops` → `app_state.pending_calendar_ops`
- `_last_mail_search` → `app_state.last_mail_search`
- `_last_calendar_search` → `app_state.last_calendar_search`
- `_pending_op_expired` → `app_state._pending_op_expired`
- `_memory_agent` → `app_state.memory_agent`
- `_conversation_db` → `app_state.conversation_db`
- `_profile_agent` → `app_state.profile_agent`

In `startup()`: die `global _memory_agent, _conversation_db, _profile_agent`-Zeile entfällt; die Zuweisungen werden zu `app_state.memory_agent = …` usw.

- [ ] **Step 3: Test-Referenzen nachziehen**

In `tests/test_callback_main.py`, `tests/test_chat_quality_main.py`, `tests/test_main_memory.py` (und jeder weiteren Datei, die diese Symbole nutzt): `main._pending_mail_ops` → `app_state.pending_mail_ops` etc., und `patch("agents.main._memory_agent")`-artige Pfade auf `agents.app_state.<name>`. Die `_clear_state`-Fixture in `test_callback_main.py` muss die Dicts aus `agents.app_state` clearen.
Importiere `import agents.app_state as app_state` in den betroffenen Testdateien.

- [ ] **Step 4: Verifizieren**

```bash
PYTHONPATH=agents .venv/bin/python -m py_compile agents/main.py agents/app_state.py && \
PYTHONPATH=agents .venv/bin/python -c "import agents.main" && \
PYTHONPATH=agents .venv/bin/pytest tests/ -q --tb=short \
  --ignore=tests/test_briefing_agent.py --ignore=tests/test_mail_send.py --ignore=tests/test_tasks_agent.py
```
Expected: kein Fehler; alle Tests grün.

- [ ] **Step 5: Commit**

```bash
git add agents/app_state.py agents/main.py tests/
git commit -m "refactor(state): geteilten State nach app_state.py extrahieren

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: `formatting.py` extrahieren

**Standard-Move-Vorgehen** mit:
- **Zielmodul:** `agents/formatting.py`
- **Symbole:** `_WEEKDAYS_DE`, `_fmt_time`, `_fmt_date`, `_fmt_time_or_allday`, `format_calendar_response`, `format_mail_list`, `format_folder_list`, `_md_safe`
- **Hinweis:** reine Funktionen, kein State. `format_calendar_response` referenziert `_fmt_*` (ziehen mit). `BERLIN` falls referenziert: `from calendar_agent import BERLIN`.
- **Commit-Message:** `refactor(format): reine Formatter nach formatting.py extrahieren`

`detect_calendar_window` bleibt vorerst in `main.py` (zieht in Task 7 mit `calendar_handler.py`).

---

## Task 5: `github_webhook.py` extrahieren

**Standard-Move-Vorgehen** mit:
- **Zielmodul:** `agents/github_webhook.py`
- **Symbole:** `_GITHUB_REPOS`, `github_webhook` (die `@app.post("/webhook/github")`-Route)
- **Hinweis:** `github_webhook` ist eine FastAPI-Route — der `@app.post(...)`-Dekorator braucht das `app`-Objekt. Lösung: `from main import app` am Kopf von `github_webhook.py` würde einen Zyklus erzeugen → stattdessen wird `app` in Task 12 final verdrahtet; für jetzt: `github_webhook.py` definiert die Funktion **ohne** Dekorator und exportiert sie; `main.py` behält die Registrierung via `app.post("/webhook/github")(github_webhook)` nach dem Import. Alternativ einen `APIRouter` nutzen — der Implementer wählt die zyklenfreie Variante und dokumentiert sie. `subprocess`, `hmac`, `hashlib`, `json`, `os` importieren; `Bot` + `app_state.TELEGRAM_TOKEN` für die Telegram-Notiz.
- **Commit-Message:** `refactor(webhook): github_webhook nach github_webhook.py extrahieren`

---

## Task 6: `mail_handler.py` extrahieren

**Standard-Move-Vorgehen** mit:
- **Zielmodul:** `agents/mail_handler.py`
- **Symbole:** `handle_mail`, `_handle_mail_write`, `_show_mail_action_confirm`, `handle_mail_intent` (aus Task 2), `_WRITE_MODES`
- **Hinweis:** referenziert `app_state`, `formatting.format_mail_list`/`format_folder_list`, `_conv_complete` (noch in `main.py` → bis Task 11 via `from main import _conv_complete`; oder `handle_mail_intent` ruft `_conv_complete` — siehe Hinweis unten). Funktionslokale `from mail_agent import MailAgent` bleiben.
- **`_conv_complete`-Abhängigkeit:** `handle_mail_intent` ruft `_conv_complete`. `_conv_complete` zieht erst in Task 11 nach `dispatch.py`. Übergang: bis dahin importiert `mail_handler.py` es via `from main import _conv_complete`. Das ist ein temporärer Aufwärts-Import; er wird in Task 11 aufgelöst (dann `from dispatch import _conv_complete`). Der Implementer prüft mit dem `import agents.main`-Smoke-Test, dass kein Zyklus entsteht — falls doch, `_conv_complete` früher (in Task 11-Vorgriff) isolieren und melden.
- **Commit-Message:** `refactor(mail): Mail-Handler nach mail_handler.py extrahieren`

---

## Task 7: `calendar_handler.py` extrahieren

**Standard-Move-Vorgehen** mit:
- **Zielmodul:** `agents/calendar_handler.py`
- **Symbole:** `calendar_agent` (der `CalendarAgent()`-Singleton), `detect_calendar_window`, `handle_calendar`, `handle_calendar_modify`, `_show_calendar_action_confirm`, `handle_calendar_intent` (aus Task 2)
- **Hinweis:** `from calendar_agent import CalendarAgent, BERLIN`. Referenziert `app_state`, `formatting.format_calendar_response`, `_conv_complete` (wie Task 6: temporär `from main import _conv_complete`).
- **Commit-Message:** `refactor(calendar): Kalender-Handler nach calendar_handler.py extrahieren`

---

## Task 8: `chat_handler.py` extrahieren

**Standard-Move-Vorgehen** mit:
- **Zielmodul:** `agents/chat_handler.py`
- **Symbole:** `claude` (der `anthropic.Anthropic()`-Client), `ask_claude`, `handle_research`, `handle_work`, `handle_personal` (aus Task 2)
- **Hinweis:** `import anthropic`; referenziert `app_state` (für `memory_agent`), `_keep_typing`/`send_typing` (ziehen in Task 11 nach `dispatch.py` → temporär `from main import _keep_typing`).
- **Commit-Message:** `refactor(chat): ask_claude + Chat-Handler nach chat_handler.py extrahieren`

---

## Task 9: `intent_handlers.py` extrahieren

**Standard-Move-Vorgehen** mit:
- **Zielmodul:** `agents/intent_handlers.py`
- **Symbole:** `handle_coding`, `handle_reminder_write`, `handle_news`, `handle_tasks`, `handle_weather`, `handle_briefing`, `handle_memory` (aus Task 2), `send_briefing` (Scheduler-Job)
- **Hinweis:** Importe für die Agenten: `handle_coding_query`/`run_coding_action`/`add_backlog_item`, `list_projects`, `get_ai_news`, `get_tasks`/`add_task`/`complete_task`/`create_list`/`delete_list`/`rename_list`, `get_weather`, `build_briefing`, `import router` (für `router._todo_lists_cache`). Referenziert `app_state` (memory_agent), `_conv_complete` (temporär `from main import`).
- **Commit-Message:** `refactor(intents): schlanke Intent-Handler nach intent_handlers.py extrahieren`

---

## Task 10: `callbacks.py` extrahieren

**Standard-Move-Vorgehen** mit:
- **Zielmodul:** `agents/callbacks.py`
- **Symbole:** `handle_callback`
- **Hinweis:** referenziert `app_state` (pending/last-Dicts, `_pending_op_expired`), `calendar_handler.calendar_agent` + `calendar_handler._show_calendar_action_confirm`, `mail_handler._show_mail_action_confirm`. Funktionslokale Importe (`from vps import git_push`, `from mail_agent import MailAgent`) bleiben. `ContextTypes` aus `telegram.ext`.
- **Test-Hinweis:** `tests/test_callback_main.py` patcht `agents.main.calendar_agent` / `agents.main._show_*` / importiert `main.handle_callback` — diese Pfade auf `agents.callbacks.handle_callback`, `agents.calendar_handler.calendar_agent`, `agents.mail_handler._show_mail_action_confirm`, `agents.calendar_handler._show_calendar_action_confirm` umstellen.
- **Commit-Message:** `refactor(callbacks): handle_callback nach callbacks.py extrahieren`

---

## Task 11: `dispatch.py` extrahieren + Aufwärts-Importe auflösen

**Standard-Move-Vorgehen** mit:
- **Zielmodul:** `agents/dispatch.py`
- **Symbole:** `_recent_conv`, `_conv_append_user`, `_conv_complete`, `_conv_to_prev_texts`, `send_typing`, `_keep_typing`, `_MEMORY_INTENTS`, `_HISTORY_INTENTS`, `_process_text` (der Orchestrator), `handle_message`, `handle_voice`, `start`
- **Zusätzlich:** Die temporären `from main import _conv_complete` / `from main import _keep_typing` in `mail_handler.py`, `calendar_handler.py`, `chat_handler.py`, `intent_handlers.py` (aus Tasks 6–9) auf `from dispatch import _conv_complete` / `from dispatch import _keep_typing` umstellen.
- **Hinweis:** `dispatch.py` importiert die Handler-Module (`from mail_handler import handle_mail_intent`, `from calendar_handler import handle_calendar_intent`, `from chat_handler import handle_research, handle_work, handle_personal`, `from intent_handlers import handle_coding, …`). `route_with_llm`, `import router`, `transcribe` (voice). Abhängigkeitsrichtung: `dispatch → handler` (Einbahn) — die Handler importieren `_conv_complete`/`_keep_typing` aus `dispatch`, aber rufen `_process_text` nie auf → kein Zyklus.
- **Test-Hinweis:** `tests/test_chat_quality_main.py`, `tests/test_main_memory.py`, `tests/test_dispatch_main.py`, `tests/test_voice_main.py` patchen/importieren `agents.main.handle_message`/`_process_text`/`ask_claude`/`send_typing`/`route_with_llm` etc. — Pfade auf `agents.dispatch.<symbol>` umstellen (bzw. `agents.chat_handler.ask_claude`).
- **Commit-Message:** `refactor(dispatch): Orchestrator + Telegram-Entry nach dispatch.py extrahieren`

---

## Task 12: `main.py` finalisieren + Deploy

**Files:**
- Modify: `agents/main.py`

- [ ] **Step 1: `main.py` Endzustand prüfen**

Nach Tasks 3–11 sollte `main.py` nur noch enthalten: Imports, `logging.basicConfig`, `logger`, `_scheduler`, `app = FastAPI()`, `bot_app`, die Routen `telegram_webhook`/`health`/`microsoft_login`/`microsoft_callback`, die `app.post`-Registrierung für `github_webhook`, `startup`, `shutdown`. Ziel: deutlich unter 300 Zeilen.

Sicherstellen, dass `startup()` die Handler korrekt aus den neuen Modulen importiert (`from dispatch import handle_message, handle_voice, start`, `from callbacks import handle_callback`) und auf `bot_app` registriert; die Scheduler-Jobs (`send_briefing` aus `intent_handlers`, die proaktiven Jobs) korrekt referenziert.

- [ ] **Step 2: Verifizieren**

```bash
PYTHONPATH=agents .venv/bin/python -m py_compile agents/main.py && \
PYTHONPATH=agents .venv/bin/python -c "import agents.main" && \
PYTHONPATH=agents .venv/bin/pytest tests/ -q --tb=short \
  --ignore=tests/test_briefing_agent.py --ignore=tests/test_mail_send.py --ignore=tests/test_tasks_agent.py && \
wc -l agents/main.py agents/*_handler.py agents/dispatch.py agents/callbacks.py agents/app_state.py agents/formatting.py agents/github_webhook.py agents/intent_handlers.py
```
Expected: kein Fehler; alle Tests grün; `main.py` deutlich kleiner.

- [ ] **Step 3: CLAUDE.md aktualisieren**

In `CLAUDE.md` die Datei-Struktur-Sektion um die neuen Module erweitern (`app_state.py`, `formatting.py`, `dispatch.py`, `mail_handler.py`, `calendar_handler.py`, `chat_handler.py`, `intent_handlers.py`, `callbacks.py`, `github_webhook.py`) und die `main.py`-Beschreibung auf „FastAPI-App, Routen, startup/shutdown" verschlanken. Den Pending-State-Abschnitt: Hinweis ergänzen, dass der State in `app_state.py` lebt.

- [ ] **Step 4: Commit**

```bash
git add agents/main.py CLAUDE.md
git commit -m "refactor(main): main.py auf Gateway-Shell verschlankt + CLAUDE.md

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

- [ ] **Step 5: Pushen — Auto-Deploy**

```bash
git push
```

- [ ] **Step 6: Deploy prüfen**

```bash
ssh root@100.115.184.3 "cd /opt/herrlich-ai-platform && git log --oneline -1 && systemctl is-active jarvis && journalctl -u jarvis -n 20 --no-pager"
```
Erwartet: jüngster Commit, Service `active`, in den Logs `Jarvis gestartet` / Scheduler-Init ohne Tracebacks.

- [ ] **Step 7: Live-Smoke-Test**

In Telegram (@jarvis_herrlich_bot): je eine Nachricht für `personal` („Hallo Jarvis"), `weather` („Wetter morgen?") und `calendar` („Was habe ich heute?") — erwartet: sinnvolle Antworten, keine Fehler. Bestätigt, dass Routing → Dispatch → Handler über die Modulgrenzen funktioniert.

---

## Self-Review

**Spec-Coverage:**
- Testnetz vervollständigen → Task 1 ✅
- `_process_text` in place zerlegen (Logik-Risiko isoliert, vor Moves) → Task 2 ✅
- `app_state.py` import-arm + Referenz-Umbenennung → Task 3 ✅
- 10 Module: main, app_state (T3), formatting (T4), github_webhook (T5), mail_handler (T6), calendar_handler (T7), chat_handler (T8), intent_handlers (T9), callbacks (T10), dispatch (T11) ✅
- Handler-Schnittstelle pro Handler festgelegt → Task 2 Signatur-Tabelle ✅
- Move-only-Disziplin + Verifikation (pure-relocation-Diff, py_compile, Smoke-Import) → Standard-Move-Vorgehen ✅
- Test-Importe in lockstep → in jedem Move-Task als Schritt ✅
- Sequenzierung (Netz → Zerlegen → app_state → Blätter → Handler → callbacks → dispatch → main) → Tasks 1–12 ✅
- CLAUDE.md-Update → Task 12 Step 3 ✅

**Placeholder-Scan:** Task 1 + Task 2 enthalten vollständigen Code. Die Move-Tasks 4–11 sind Relocations — der zu verschiebende Code existiert bereits und bleibt byte-identisch; „vollständig" heißt hier: exakte Symbol-Liste + Move-only-Disziplin + maschinell prüfbare Verifikations-Gates (`py_compile`, Suite grün, pure-relocation-Diff). Kein kreativer Spielraum offen.

**Typ-/Namens-Konsistenz:**
- `app_state`-Attributnamen (`pending_mail_ops`, `memory_agent`, `_pending_op_expired`, `TELEGRAM_TOKEN` …) identisch in Task 3 (Definition) und allen Referenz-Umbenennungen.
- `handle_<intent>`-Funktionsnamen + Signaturen identisch in Task 2 (Definition/Tabelle) und Task 11 (`dispatch.py`-Importe).
- Modulnamen (`mail_handler`, `calendar_handler`, `chat_handler`, `intent_handlers`, `dispatch`, `callbacks`, `formatting`, `github_webhook`, `app_state`) konsistent über alle Tasks und Test-Importe.
- Abhängigkeits-Einbahn (`main → dispatch/callbacks → handler → app_state/formatting`) — die temporären Aufwärts-Importe aus Tasks 6–9 werden in Task 11 aufgelöst; jeder Move-Task verifiziert via `import agents.main`-Smoke-Test, dass kein Zyklus besteht.
