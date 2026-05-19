# Agentischer Jarvis Phase 2 — Plan 2: Read-only-Pilot (`weather` + `news`)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die ersten beiden strukturierten Handler (`weather`, `news`) zu Agenten-Tools konvertieren. Der Agent übernimmt diese Intents danach produktiv; die alten Handler entfallen.

**Architecture:** Jeder Task ist eine vollständige Ende-zu-Ende-Konvertierung eines Intents — read-only Tool-Modul in `agents/tools/`, Registrierung im Registry-`__init__.py`, Eintrag im Agent-System-Prompt, Verdrahtung in `dispatch.py` (Intent wandert in `_AGENT_INTENTS`/`_MEMORY_INTENTS`/`_HISTORY_INTENTS`, der `elif`-Zweig entfällt), Löschen des alten Handlers. Ein Task = ein Commit = ein git-revertierbarer Mini-Zyklus.

**Tech Stack:** Python 3.11, pytest, claude-agent-sdk.

**Übergeordnetes Design:** `docs/plans/2026-05-19-agentischer-jarvis-phase2-design.md` (Konvertierungs-Sequenz #1 + #2). Voraussetzung: Plan 1 (Fundament) ist umgesetzt — das Paket `agents/tools/` existiert.

**Test-Kommando (Standard, kein Live-API-Zugang nötig):**
```bash
PYTHONPATH=agents .venv/bin/pytest tests/ -q --tb=short \
  --ignore=tests/test_briefing_agent.py \
  --ignore=tests/test_mail_send.py \
  --ignore=tests/test_tasks_agent.py
```

**Tool-Muster (gilt für beide Tasks):** Ein Tool-Modul `agents/tools/<name>_tool.py` exportiert ein `@tool`-dekoriertes Objekt `<name>_tool`. `tools/__init__.py` importiert es unter privatem Alias (`as _<name>_capability`) — sonst überschattet der re-exportierte Name das gleichnamige Submodul. `weather` und `news` sind read-only: das Tool ruft den bestehenden Unter-Agenten synchron via `asyncio.to_thread` und gibt Text-Content zurück.

---

### Task 1: `weather` als Tool — Ende-zu-Ende-Konvertierung

**Files:**
- Create: `agents/tools/weather_tool.py`
- Create: `tests/test_tools_weather.py`
- Modify: `agents/tools/__init__.py`
- Modify: `agents/agent.py`
- Modify: `agents/dispatch.py`
- Modify: `agents/intent_handlers.py`
- Modify: `tests/test_tools_registry.py`
- Modify: `tests/test_agent.py`
- Modify: `tests/test_agent_dispatch.py`
- Modify: `tests/test_dispatch_main.py`

- [ ] **Step 1: Failing-Test für das weather-Tool schreiben**

Erstelle `tests/test_tools_weather.py`:
```python
"""Tests für agents/tools/weather_tool.py."""

import pytest

import tools.weather_tool as weather_tool_mod


@pytest.mark.asyncio
async def test_weather_tool_returns_forecast(monkeypatch):
    def fake_get_weather(period, time_of_day, location):
        return "☀️ 22°C, klar"

    monkeypatch.setattr(weather_tool_mod, "get_weather", fake_get_weather)
    result = await weather_tool_mod.weather_tool.handler(
        {"period": "today", "time_of_day": "", "location": ""}
    )
    assert result["content"][0]["text"] == "☀️ 22°C, klar"


@pytest.mark.asyncio
async def test_weather_tool_passes_params(monkeypatch):
    captured = {}

    def fake_get_weather(period, time_of_day, location):
        captured["args"] = (period, time_of_day, location)
        return "x"

    monkeypatch.setattr(weather_tool_mod, "get_weather", fake_get_weather)
    await weather_tool_mod.weather_tool.handler(
        {"period": "tomorrow", "time_of_day": "morning", "location": "Berlin"}
    )
    assert captured["args"] == ("tomorrow", "morning", "Berlin")


@pytest.mark.asyncio
async def test_weather_tool_defaults_to_today(monkeypatch):
    captured = {}

    def fake_get_weather(period, time_of_day, location):
        captured["args"] = (period, time_of_day, location)
        return "x"

    monkeypatch.setattr(weather_tool_mod, "get_weather", fake_get_weather)
    await weather_tool_mod.weather_tool.handler({})
    assert captured["args"] == ("today", None, None)
```

- [ ] **Step 2: Test laufen lassen — muss fehlschlagen**

Run: `PYTHONPATH=agents .venv/bin/pytest tests/test_tools_weather.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.weather_tool'`.

- [ ] **Step 3: `agents/tools/weather_tool.py` anlegen**

Erstelle `agents/tools/weather_tool.py`:
```python
"""weather-Tool — Wettervorhersage via Open-Meteo. Read-only.

Dünner Wrapper um weather_agent.get_weather: typisierte Parameter rein,
Text-Content raus. Keine Telegram-Seiteneffekte.
"""

import asyncio

from claude_agent_sdk import tool

from weather_agent import get_weather


@tool(
    "weather",
    "Wettervorhersage für Tutzing (Philipps Heimatort) oder einen genannten Ort. "
    "period: 'today' (Standard), 'tomorrow' oder 'week'. "
    "time_of_day (optional): 'morning', 'noon', 'afternoon', 'evening', 'night'. "
    "location (optional): Ortsname; leer = Heimatort.",
    {"period": str, "time_of_day": str, "location": str},
)
async def weather_tool(args: dict) -> dict:
    period = (args.get("period") or "today").strip()
    time_of_day = (args.get("time_of_day") or "").strip() or None
    location = (args.get("location") or "").strip() or None
    result = await asyncio.to_thread(get_weather, period, time_of_day, location)
    return {"content": [{"type": "text", "text": result}]}
```

- [ ] **Step 4: weather-Test laufen lassen — muss bestehen**

Run: `PYTHONPATH=agents .venv/bin/pytest tests/test_tools_weather.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: weather-Tool in der Registry registrieren**

In `agents/tools/__init__.py`: füge direkt unter der Zeile
`from .workspace_tool import workspace_tool as _workspace_capability` die Zeile hinzu:
```python
from .weather_tool import weather_tool as _weather_capability
```
und ändere
```python
_TOOLS = [_workspace_capability]
```
zu
```python
_TOOLS = [_workspace_capability, _weather_capability]
```

- [ ] **Step 6: Registry-Test erweitern**

In `tests/test_tools_registry.py`: benenne `test_build_mcp_server_registers_workspace` um zu `test_build_mcp_server_registers_tools` und ergänze die weather-Assertion. Die Funktion lautet danach:
```python
def test_build_mcp_server_registers_tools():
    server = tools.build_mcp_server()
    assert server is not None
    assert "mcp__jarvis__workspace" in tools._ALLOWED_TOOL_NAMES
    assert "mcp__jarvis__weather" in tools._ALLOWED_TOOL_NAMES
```
Run: `PYTHONPATH=agents .venv/bin/pytest tests/test_tools_registry.py -q`
Expected: PASS.

- [ ] **Step 7: System-Prompt — Failing-Assertion zuerst**

In `tests/test_agent.py`, in der Funktion `test_system_prompt_empty_memory`, ergänze nach der bestehenden Assertion eine neue Zeile:
```python
    assert "weather" in prompt
```
Run: `PYTHONPATH=agents .venv/bin/pytest tests/test_agent.py::test_system_prompt_empty_memory -q`
Expected: FAIL (das Wort `weather` steht noch nicht im Prompt).

- [ ] **Step 8: weather in den System-Prompt aufnehmen**

In `agents/agent.py`, in `build_system_prompt`, ersetze:
```python
        "Fragen zu seinen Projekten — list/search/read, nicht raten.\n"
        "- WebSearch / WebFetch: Aktuelle Informationen aus dem Internet.\n\n"
```
durch:
```python
        "Fragen zu seinen Projekten — list/search/read, nicht raten.\n"
        "- weather: Wettervorhersage für Tutzing (Heimatort) oder einen "
        "genannten Ort.\n"
        "- WebSearch / WebFetch: Aktuelle Informationen aus dem Internet.\n\n"
```
Run: `PYTHONPATH=agents .venv/bin/pytest tests/test_agent.py::test_system_prompt_empty_memory -q`
Expected: PASS.

- [ ] **Step 9: `dispatch.py` — weather agentisch routen**

In `agents/dispatch.py`:

(a) Ergänze `"weather"` in allen drei Intent-Mengen:
```python
_MEMORY_INTENTS = {"personal", "work", "research", "weather"}
_HISTORY_INTENTS = {"personal", "work", "research", "weather"}
```
und
```python
_AGENT_INTENTS = {"personal", "work", "research", "weather"}
```

(b) Entferne im `intent_handlers`-Import die Zeile `    handle_weather,`.

(c) Entferne in `_process_text` den Zweig:
```python
    elif intent == "weather":
        await handle_weather(chat_id, params, update)
```

- [ ] **Step 10: `intent_handlers.py` — toten weather-Handler löschen**

In `agents/intent_handlers.py`:

(a) Entferne die Import-Zeile `from weather_agent import get_weather`.

(b) Lösche die gesamte Funktion `handle_weather`:
```python
async def handle_weather(chat_id: int, params: dict, update) -> None:
    period = params.get("period", "today")
    time_of_day = params.get("time_of_day")
    location = params.get("location")
    period_label = {
        "today": "heute",
        "tomorrow": "morgen",
        "week": "diese Woche",
    }.get(period, period)
    weather = await asyncio.to_thread(get_weather, period, time_of_day, location)
    await update.message.reply_text(
        f"🌤️ *Wetter {period_label}:*\n{weather}", parse_mode="Markdown"
    )
    _conv_complete(chat_id, f"Wetter {period_label} angezeigt")
```
(`import asyncio` und `_conv_complete` bleiben — werden von anderen Handlern im Modul genutzt.)

- [ ] **Step 11: Dispatch-Tests anpassen**

(a) In `tests/test_dispatch_main.py`: lösche die Funktion `test_weather_intent_calls_get_weather` vollständig (sie patcht `intent_handlers.get_weather`, das es nicht mehr gibt).

(b) In `tests/test_agent_dispatch.py`: ersetze die Funktion `test_weather_routed_to_handler` durch:
```python
@pytest.mark.asyncio
async def test_weather_routed_to_agent():
    app_state.conversation_db = None
    app_state.profile_agent = None
    app_state.memory_agent = None
    update = MagicMock()
    with (
        patch(
            "dispatch.route_with_llm", new=AsyncMock(return_value=_routing("weather"))
        ),
        patch(
            "dispatch.run_agent", new=AsyncMock(return_value="Wetter-Antwort")
        ) as mock_run,
    ):
        await dispatch._process_text("Wetter morgen?", 123, update)
    mock_run.assert_awaited_once()
```

- [ ] **Step 12: Volle Suite — grün**

Run:
```bash
PYTHONPATH=agents .venv/bin/pytest tests/ -q --tb=short \
  --ignore=tests/test_briefing_agent.py \
  --ignore=tests/test_mail_send.py \
  --ignore=tests/test_tasks_agent.py
```
Expected: PASS. Bei Fehlern nach übersehenen Referenzen auf `handle_weather` / `intent_handlers.get_weather` suchen.

- [ ] **Step 13: Commit**

```bash
git add agents/tools/weather_tool.py agents/tools/__init__.py agents/agent.py \
  agents/dispatch.py agents/intent_handlers.py tests/test_tools_weather.py \
  tests/test_tools_registry.py tests/test_agent.py tests/test_agent_dispatch.py \
  tests/test_dispatch_main.py
git commit -m "feat(agent): weather-Handler zu Agenten-Tool konvertiert

weather läuft jetzt agentisch (Intent in _AGENT_INTENTS) statt über
handle_weather. Neues read-only Tool agents/tools/weather_tool.py,
registriert + im System-Prompt; der alte Handler entfällt.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 2: `news` als Tool — Ende-zu-Ende-Konvertierung

Analog zu Task 1. `news` ist read-only und einfacher (ein optionaler Parameter).

**Files:**
- Create: `agents/tools/news_tool.py`
- Create: `tests/test_tools_news.py`
- Modify: `agents/tools/__init__.py`
- Modify: `agents/agent.py`
- Modify: `agents/dispatch.py`
- Modify: `agents/intent_handlers.py`
- Modify: `tests/test_tools_registry.py`
- Modify: `tests/test_agent.py`
- Modify: `tests/test_agent_dispatch.py`
- Modify: `tests/test_dispatch_main.py`

- [ ] **Step 1: Failing-Test für das news-Tool schreiben**

Erstelle `tests/test_tools_news.py`:
```python
"""Tests für agents/tools/news_tool.py."""

import pytest

import tools.news_tool as news_tool_mod


@pytest.mark.asyncio
async def test_news_tool_returns_news(monkeypatch):
    monkeypatch.setattr(
        news_tool_mod, "get_ai_news", lambda hours, max_items: "• Item 1 — Quelle"
    )
    result = await news_tool_mod.news_tool.handler({"hours": 24})
    assert "Item 1" in result["content"][0]["text"]


@pytest.mark.asyncio
async def test_news_tool_empty_feeds_message(monkeypatch):
    monkeypatch.setattr(news_tool_mod, "get_ai_news", lambda hours, max_items: "")
    result = await news_tool_mod.news_tool.handler({})
    assert "Keine AI-News" in result["content"][0]["text"]


@pytest.mark.asyncio
async def test_news_tool_default_hours(monkeypatch):
    captured = {}

    def fake_get_ai_news(hours, max_items):
        captured["hours"] = hours
        return "x"

    monkeypatch.setattr(news_tool_mod, "get_ai_news", fake_get_ai_news)
    await news_tool_mod.news_tool.handler({})
    assert captured["hours"] == 48
```

- [ ] **Step 2: Test laufen lassen — muss fehlschlagen**

Run: `PYTHONPATH=agents .venv/bin/pytest tests/test_tools_news.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.news_tool'`.

- [ ] **Step 3: `agents/tools/news_tool.py` anlegen**

Erstelle `agents/tools/news_tool.py`:
```python
"""news-Tool — aktuelle AI-/Tech-News aus kuratierten RSS-Feeds. Read-only.

Dünner Wrapper um news_agent.get_ai_news: typisierte Parameter rein,
Text-Content raus. Keine Telegram-Seiteneffekte.
"""

import asyncio

from claude_agent_sdk import tool

from news_agent import get_ai_news

_DEFAULT_HOURS = 48
_MAX_ITEMS = 10


@tool(
    "news",
    "Aktuelle AI-/Tech-News aus kuratierten RSS-Feeds. "
    "hours (optional): Zeitfenster in Stunden, Standard 48.",
    {"hours": int},
)
async def news_tool(args: dict) -> dict:
    hours = args.get("hours") or _DEFAULT_HOURS
    news = await asyncio.to_thread(get_ai_news, hours, _MAX_ITEMS)
    text = news or f"Keine AI-News in den letzten {hours} h gefunden."
    return {"content": [{"type": "text", "text": text}]}
```

- [ ] **Step 4: news-Test laufen lassen — muss bestehen**

Run: `PYTHONPATH=agents .venv/bin/pytest tests/test_tools_news.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: news-Tool in der Registry registrieren**

In `agents/tools/__init__.py`: füge unter der `_weather_capability`-Import-Zeile hinzu:
```python
from .news_tool import news_tool as _news_capability
```
und ändere
```python
_TOOLS = [_workspace_capability, _weather_capability]
```
zu
```python
_TOOLS = [_workspace_capability, _weather_capability, _news_capability]
```

- [ ] **Step 6: Registry-Test erweitern**

In `tests/test_tools_registry.py`, in `test_build_mcp_server_registers_tools`, ergänze nach der weather-Assertion:
```python
    assert "mcp__jarvis__news" in tools._ALLOWED_TOOL_NAMES
```
Run: `PYTHONPATH=agents .venv/bin/pytest tests/test_tools_registry.py -q`
Expected: PASS.

- [ ] **Step 7: System-Prompt — Failing-Assertion zuerst**

In `tests/test_agent.py`, in `test_system_prompt_empty_memory`, ergänze nach der `weather`-Assertion:
```python
    assert "news" in prompt
```
Run: `PYTHONPATH=agents .venv/bin/pytest tests/test_agent.py::test_system_prompt_empty_memory -q`
Expected: FAIL.

- [ ] **Step 8: news in den System-Prompt aufnehmen**

In `agents/agent.py`, in `build_system_prompt`, ersetze:
```python
        "- weather: Wettervorhersage für Tutzing (Heimatort) oder einen "
        "genannten Ort.\n"
        "- WebSearch / WebFetch: Aktuelle Informationen aus dem Internet.\n\n"
```
durch:
```python
        "- weather: Wettervorhersage für Tutzing (Heimatort) oder einen "
        "genannten Ort.\n"
        "- news: Aktuelle AI-/Tech-News aus kuratierten RSS-Feeds.\n"
        "- WebSearch / WebFetch: Aktuelle Informationen aus dem Internet.\n\n"
```
Run: `PYTHONPATH=agents .venv/bin/pytest tests/test_agent.py::test_system_prompt_empty_memory -q`
Expected: PASS.

- [ ] **Step 9: `dispatch.py` — news agentisch routen**

In `agents/dispatch.py`:

(a) Ergänze `"news"` in allen drei Intent-Mengen:
```python
_MEMORY_INTENTS = {"personal", "work", "research", "weather", "news"}
_HISTORY_INTENTS = {"personal", "work", "research", "weather", "news"}
```
und
```python
_AGENT_INTENTS = {"personal", "work", "research", "weather", "news"}
```

(b) Entferne im `intent_handlers`-Import die Zeile `    handle_news,`.

(c) Entferne in `_process_text` den Zweig:
```python
    elif intent == "news":
        await handle_news(chat_id, update)
```

- [ ] **Step 10: `intent_handlers.py` — toten news-Handler löschen**

In `agents/intent_handlers.py`:

(a) Entferne die Import-Zeile `from news_agent import get_ai_news`.

(b) Lösche die gesamte Funktion `handle_news`:
```python
async def handle_news(chat_id: int, update) -> None:
    await update.message.reply_text("📰 Lade AI-News...")
    news = await asyncio.to_thread(get_ai_news, 48, 10)
    await update.message.reply_text(
        f"📰 *AI NEWS — letzte 48h*\n\n{news or 'Keine News gefunden.'}",
        parse_mode="Markdown",
    )
    _conv_complete(chat_id, "AI-News angezeigt")
```

- [ ] **Step 11: Dispatch-Tests anpassen**

(a) In `tests/test_dispatch_main.py`: lösche die Funktion `test_news_intent_calls_get_ai_news` vollständig.

(b) In `tests/test_agent_dispatch.py`: ergänze nach `test_weather_routed_to_agent` eine analoge news-Funktion:
```python
@pytest.mark.asyncio
async def test_news_routed_to_agent():
    app_state.conversation_db = None
    app_state.profile_agent = None
    app_state.memory_agent = None
    update = MagicMock()
    with (
        patch(
            "dispatch.route_with_llm", new=AsyncMock(return_value=_routing("news"))
        ),
        patch(
            "dispatch.run_agent", new=AsyncMock(return_value="News-Antwort")
        ) as mock_run,
    ):
        await dispatch._process_text("Was gibt es Neues in AI?", 123, update)
    mock_run.assert_awaited_once()
```

- [ ] **Step 12: Volle Suite — grün**

Run:
```bash
PYTHONPATH=agents .venv/bin/pytest tests/ -q --tb=short \
  --ignore=tests/test_briefing_agent.py \
  --ignore=tests/test_mail_send.py \
  --ignore=tests/test_tasks_agent.py
```
Expected: PASS.

- [ ] **Step 13: Commit**

```bash
git add agents/tools/news_tool.py agents/tools/__init__.py agents/agent.py \
  agents/dispatch.py agents/intent_handlers.py tests/test_tools_news.py \
  tests/test_tools_registry.py tests/test_agent.py tests/test_agent_dispatch.py \
  tests/test_dispatch_main.py
git commit -m "feat(agent): news-Handler zu Agenten-Tool konvertiert

news läuft jetzt agentisch statt über handle_news. Neues read-only Tool
agents/tools/news_tool.py, registriert + im System-Prompt; der alte
Handler entfällt.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 3: `CLAUDE.md` nachziehen

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Architektur-Überblick — `weather`/`news` zum Agenten verschieben**

Im Code-Block „Architektur-Überblick": entferne die beiden Router-Zweige
```
        ├── weather         weather_agent.py
        ├── news            news_agent.py
```
und ersetze den Agenten-Block
```
        ├── personal ┐
        ├── work     ├─ agent.py run_agent — echter Agent (Claude Agent SDK):
        └── research ┘  Tools workspace/web, Denk-Schleife, History, MemoryAgent
```
durch
```
        ├── personal ┐
        ├── work     │
        ├── research ├─ agent.py run_agent — echter Agent (Claude Agent SDK):
        ├── weather  │  Tools workspace/web/weather/news, Denk-Schleife,
        └── news     ┘  History, MemoryAgent
```

- [ ] **Step 2: Datei-Struktur — `intent_handlers.py`-Beschreibung korrigieren**

Ersetze die Zeile
```
  intent_handlers.py    Schlanke Intent-Handler (coding/tasks/news/weather/briefing/...)
```
durch
```
  intent_handlers.py    Schlanke Intent-Handler (coding/tasks/briefing/...)
```

- [ ] **Step 3: Abschnitt „Agentischer Pfad" — Werkzeug-Liste ergänzen**

Ersetze im Abschnitt „Agentischer Pfad" die Zeile
```
- Werkzeuge: `workspace` + die eingebauten `WebSearch`/`WebFetch`. Built-in
```
durch
```
- Werkzeuge: `workspace`, `weather`, `news` + die eingebauten `WebSearch`/`WebFetch`. Built-in
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(agent): CLAUDE.md — weather/news laufen agentisch

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Self-Review-Notiz

Plan 2 deckt aus dem Design die Konvertierungs-Sequenz #1 (`weather`) und #2 (`news`)
ab — beide read-only, kein Write-Confirm nötig. Die Set-Konvergenz (Intent wandert
in alle drei `_*_INTENTS`-Mengen) ist umgesetzt; die drei Mengen bleiben bewusst
getrennt (eigene Gates), kollabieren erst in Phase 3. **Nicht** in Plan 2:
Write-/Confirm-Mechanik, `chat_id`-Scoping von `build_mcp_server` (beides Plan 3
mit dem ersten Write-Tool `tasks`), die übrigen Handler.
