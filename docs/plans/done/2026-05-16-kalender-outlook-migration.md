# Kalender-Migration iCloud CalDAV → Outlook (MS Graph) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Jarvis liest und schreibt Kalender-Termine über Microsoft Graph (Outlook) statt iCloud CalDAV; Termin-Erstellung erhält einen Bestätigungsdialog.

**Architecture:** `calendar_agent.py` wird neu geschrieben — `CalendarAgent` spricht direkt MS Graph (`/me/calendarView` lesen, `/me/events` schreiben), wiederverwendet `microsoft_auth.get_access_token()` wie `tasks_agent.py`. Die CalDAV-Backend-Abstraktion entfällt. Die Public-API (`get_events`, `get_next_event`, `create_event`) bleibt stabil, damit `main.py`, `briefing_agent.py` und `proactive_agent.py` minimal betroffen sind.

**Tech Stack:** Python 3.11 · `httpx` · Microsoft Graph API · MSAL · pytest

**Spec:** `docs/superpowers/specs/2026-05-16-kalender-outlook-migration-design.md`

**Tests lokal ausführen:**
```bash
PYTHONPATH=agents .venv/bin/pytest tests/ -q --tb=short \
  --ignore=tests/test_briefing_agent.py \
  --ignore=tests/test_mail_send.py \
  --ignore=tests/test_tasks_agent.py
```

---

## Task 1: `calendar_agent.py` auf MS Graph umschreiben

Kern der Migration. `CalendarAgent` spricht direkt MS Graph. Die alte CalDAV-Abstraktion (`CalendarBackend`, `ICloudCalDAVBackend`), `get_reminders_today()` und `get_calendar_names()` entfallen. Beide alten Testdateien werden mit ersetzt/gelöscht, damit die Suite nie rot ist.

**Files:**
- Modify (Neuschrieb): `agents/calendar_agent.py`
- Create: `tests/test_calendar_read.py`
- Modify (Neuschrieb): `tests/test_calendar_write.py`
- Delete: `tests/test_calendar_reminders.py`

- [ ] **Step 1: Alten Reminders-Test löschen**

```bash
git rm tests/test_calendar_reminders.py
```

Grund: `get_reminders_today()` (CalDAV-VTODO) entfällt — der Test wäre danach ungültig. Heutige Aufgaben erscheinen bereits über die MS-To-Do-Sektion im Morgenbriefing.

- [ ] **Step 2: Lese-Test schreiben (`tests/test_calendar_read.py`)**

```python
# tests/test_calendar_read.py
from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import httpx

BERLIN = ZoneInfo("Europe/Berlin")

_CALENDAR_VIEW_JSON = {
    "value": [
        {
            "subject": "Zahnarzt",
            "start": {"dateTime": "2026-05-16T10:00:00.0000000", "timeZone": "Europe/Berlin"},
            "end": {"dateTime": "2026-05-16T11:00:00.0000000", "timeZone": "Europe/Berlin"},
            "isAllDay": False,
            "location": {"displayName": "Praxis Dr. Müller"},
        },
        {
            "subject": "Urlaub",
            "start": {"dateTime": "2026-05-16T00:00:00.0000000", "timeZone": "Europe/Berlin"},
            "end": {"dateTime": "2026-05-17T00:00:00.0000000", "timeZone": "Europe/Berlin"},
            "isAllDay": True,
            "location": {"displayName": ""},
        },
    ]
}


def _resp(json_data, status=200):
    m = MagicMock()
    m.status_code = status
    m.json.return_value = json_data
    m.raise_for_status.return_value = None
    return m


def test_get_events_maps_graph_payload():
    from agents.calendar_agent import CalendarAgent

    start = datetime(2026, 5, 16, 0, 0, tzinfo=BERLIN)
    end = datetime(2026, 5, 17, 0, 0, tzinfo=BERLIN)
    with patch("agents.calendar_agent.get_access_token", return_value="tok"), \
         patch("httpx.get", return_value=_resp(_CALENDAR_VIEW_JSON)) as mock_get:
        events = CalendarAgent().get_events(start, end)

    assert len(events) == 2
    ev = events[0]
    assert ev.title == "Zahnarzt"
    assert ev.start == datetime(2026, 5, 16, 10, 0, tzinfo=BERLIN)
    assert ev.end == datetime(2026, 5, 16, 11, 0, tzinfo=BERLIN)
    assert ev.location == "Praxis Dr. Müller"
    assert ev.all_day is False
    assert ev.source == "outlook"
    assert "calendarView" in mock_get.call_args[0][0]


def test_get_events_marks_all_day_and_empty_location():
    from agents.calendar_agent import CalendarAgent

    start = datetime(2026, 5, 16, 0, 0, tzinfo=BERLIN)
    end = datetime(2026, 5, 17, 0, 0, tzinfo=BERLIN)
    with patch("agents.calendar_agent.get_access_token", return_value="tok"), \
         patch("httpx.get", return_value=_resp(_CALENDAR_VIEW_JSON)):
        events = CalendarAgent().get_events(start, end)

    urlaub = [e for e in events if e.title == "Urlaub"][0]
    assert urlaub.all_day is True
    assert urlaub.location is None


def test_get_events_returns_empty_on_error():
    from agents.calendar_agent import CalendarAgent

    start = datetime(2026, 5, 16, 0, 0, tzinfo=BERLIN)
    end = datetime(2026, 5, 17, 0, 0, tzinfo=BERLIN)
    with patch("agents.calendar_agent.get_access_token", return_value="tok"), \
         patch("httpx.get", side_effect=httpx.HTTPError("boom")):
        events = CalendarAgent().get_events(start, end)
    assert events == []
```

- [ ] **Step 3: Schreib-Test ersetzen (`tests/test_calendar_write.py`)**

Komplett neuer Inhalt — der alte Test importierte `ICloudCalDAVBackend`, das es nicht mehr gibt:

```python
# tests/test_calendar_write.py
from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import httpx
import pytest

BERLIN = ZoneInfo("Europe/Berlin")


def _resp(status=201):
    m = MagicMock()
    m.status_code = status
    m.raise_for_status.return_value = None
    return m


def test_create_event_posts_to_graph():
    from agents.calendar_agent import CalendarAgent

    start = datetime(2026, 5, 17, 10, 0, tzinfo=BERLIN)
    end = datetime(2026, 5, 17, 11, 0, tzinfo=BERLIN)
    with patch("agents.calendar_agent.get_access_token", return_value="tok"), \
         patch("httpx.post", return_value=_resp(201)) as mock_post:
        CalendarAgent().create_event("Zahnarzt", start, end)

    mock_post.assert_called_once()
    url = mock_post.call_args[0][0]
    assert url.endswith("/me/events")
    body = mock_post.call_args[1]["json"]
    assert body["subject"] == "Zahnarzt"
    assert body["start"]["dateTime"] == "2026-05-17T10:00:00"
    assert body["start"]["timeZone"] == "Europe/Berlin"
    assert body["end"]["dateTime"] == "2026-05-17T11:00:00"


def test_create_event_raises_on_http_error():
    from agents.calendar_agent import CalendarAgent

    start = datetime(2026, 5, 17, 10, 0, tzinfo=BERLIN)
    end = datetime(2026, 5, 17, 11, 0, tzinfo=BERLIN)
    with patch("agents.calendar_agent.get_access_token", return_value="tok"), \
         patch("httpx.post", side_effect=httpx.HTTPError("403")):
        with pytest.raises(httpx.HTTPError):
            CalendarAgent().create_event("X", start, end)
```

- [ ] **Step 4: Tests laufen lassen — müssen fehlschlagen**

Run: `PYTHONPATH=agents .venv/bin/pytest tests/test_calendar_read.py tests/test_calendar_write.py -v`
Expected: FAIL — die alte `CalendarAgent` nutzt CalDAV (kein `httpx`-Call), `get_events` liefert `[]` statt 2 Events, `create_event` wirft `RuntimeError` mangels Backend.

- [ ] **Step 5: `agents/calendar_agent.py` komplett neu schreiben**

Gesamter neuer Dateiinhalt:

```python
"""
Calendar Agent for Jarvis.

Reads and writes events on the user's default Outlook calendar via
Microsoft Graph. Auth is shared with the mail/tasks agents through
microsoft_auth.get_access_token().
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import httpx

try:
    from microsoft_auth import get_access_token
except ImportError:
    from agents.microsoft_auth import get_access_token  # type: ignore

logger = logging.getLogger("jarvis.calendar")

BERLIN = ZoneInfo("Europe/Berlin")
UTC = ZoneInfo("UTC")

_GRAPH = "https://graph.microsoft.com/v1.0"


@dataclass
class Event:
    title: str
    start: datetime
    end: datetime
    location: Optional[str]
    calendar_name: str
    source: str  # "outlook"
    all_day: bool = False


def _to_berlin(dt: datetime) -> datetime:
    """Normalize a naive-or-aware datetime to Europe/Berlin."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=BERLIN)
    return dt.astimezone(BERLIN)


def _parse_graph_dt(value: dict) -> datetime:
    """Parse a Graph dateTimeTimeZone object into an aware Berlin datetime.

    With the `Prefer: outlook.timezone` header Graph returns local times
    without an offset (e.g. "2026-05-16T10:00:00.0000000"). Parse them
    naively and attach Europe/Berlin. Graph sends 7 fractional digits;
    datetime.fromisoformat accepts at most 6, so trim.
    """
    raw = value["dateTime"]
    if "." in raw:
        head, frac = raw.split(".", 1)
        raw = f"{head}.{frac[:6]}"
    return _to_berlin(datetime.fromisoformat(raw))


class CalendarAgent:
    """Reads and writes the user's default Outlook calendar via MS Graph."""

    DEFAULT_CALENDAR_NAME = "Outlook"

    def _headers(self, prefer_berlin: bool = False) -> dict:
        headers = {
            "Authorization": f"Bearer {get_access_token()}",
            "Content-Type": "application/json",
        }
        if prefer_berlin:
            headers["Prefer"] = 'outlook.timezone="Europe/Berlin"'
        return headers

    def get_events(self, start: datetime, end: datetime) -> list[Event]:
        if start.tzinfo is None:
            start = start.replace(tzinfo=BERLIN)
        if end.tzinfo is None:
            end = end.replace(tzinfo=BERLIN)
        try:
            events = self._fetch_calendar_view(start, end)
        except Exception as e:
            logger.error("get_events failed: %s", e)
            return []
        events.sort(key=lambda ev: ev.start)
        logger.info(
            "get_events: %s..%s -> %d events",
            start.isoformat(),
            end.isoformat(),
            len(events),
        )
        return events

    def _fetch_calendar_view(self, start: datetime, end: datetime) -> list[Event]:
        url: Optional[str] = f"{_GRAPH}/me/calendarView"
        params: Optional[dict] = {
            "startDateTime": start.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
            "endDateTime": end.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
            "$orderby": "start/dateTime",
            "$top": 100,
            "$select": "subject,start,end,isAllDay,location",
        }
        headers = self._headers(prefer_berlin=True)
        events: list[Event] = []
        while url:
            resp = httpx.get(url, headers=headers, params=params, timeout=15)
            resp.raise_for_status()
            payload = resp.json()
            for item in payload.get("value", []):
                events.append(self._to_event(item))
            url = payload.get("@odata.nextLink")
            params = None  # nextLink already carries the query string
        return events

    @classmethod
    def _to_event(cls, item: dict) -> Event:
        location = (item.get("location") or {}).get("displayName") or None
        return Event(
            title=item.get("subject") or "(ohne Titel)",
            start=_parse_graph_dt(item["start"]),
            end=_parse_graph_dt(item["end"]),
            location=location,
            calendar_name=cls.DEFAULT_CALENDAR_NAME,
            source="outlook",
            all_day=bool(item.get("isAllDay")),
        )

    def get_next_event(self) -> Optional[Event]:
        now = datetime.now(BERLIN)
        events = self.get_events(now, now + timedelta(days=60))
        for ev in events:
            if ev.start >= now:
                return ev
        return None

    def create_event(
        self, title: str, start_dt: datetime, end_dt: datetime
    ) -> None:
        """Create an event on the default Outlook calendar. Raises on failure."""
        body = {
            "subject": title,
            "start": {
                "dateTime": _to_berlin(start_dt).strftime("%Y-%m-%dT%H:%M:%S"),
                "timeZone": "Europe/Berlin",
            },
            "end": {
                "dateTime": _to_berlin(end_dt).strftime("%Y-%m-%dT%H:%M:%S"),
                "timeZone": "Europe/Berlin",
            },
        }
        resp = httpx.post(
            f"{_GRAPH}/me/events",
            headers=self._headers(),
            json=body,
            timeout=15,
        )
        resp.raise_for_status()
        logger.info("Termin erstellt: '%s' (%s)", title, start_dt.isoformat())
```

- [ ] **Step 6: Kalender-Tests laufen lassen — müssen bestehen**

Run: `PYTHONPATH=agents .venv/bin/pytest tests/test_calendar_read.py tests/test_calendar_write.py -v`
Expected: PASS — alle 5 Tests grün.

- [ ] **Step 7: Komplette Test-Suite laufen lassen**

Run:
```bash
PYTHONPATH=agents .venv/bin/pytest tests/ -q --tb=short \
  --ignore=tests/test_briefing_agent.py \
  --ignore=tests/test_mail_send.py \
  --ignore=tests/test_tasks_agent.py
```
Expected: PASS — keine Importfehler durch entferntes `ICloudCalDAVBackend` / `get_reminders_today`.

- [ ] **Step 8: Commit**

```bash
git add agents/calendar_agent.py tests/test_calendar_read.py tests/test_calendar_write.py tests/test_calendar_reminders.py
git commit -m "feat(calendar): Outlook (MS Graph) statt iCloud CalDAV

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: OAuth-Scope `Calendars.ReadWrite` ergänzen

`microsoft_auth.py` muss MS Graph zusätzlich Kalender-Rechte anfordern.

**Files:**
- Modify: `agents/microsoft_auth.py:12`

- [ ] **Step 1: `SCOPES` erweitern**

Edit `agents/microsoft_auth.py` — ersetze:

```python
SCOPES = ["Mail.ReadWrite", "Mail.Send", "Tasks.ReadWrite", "Tasks.ReadWrite.Shared"]
```

mit:

```python
SCOPES = [
    "Mail.ReadWrite",
    "Mail.Send",
    "Tasks.ReadWrite",
    "Tasks.ReadWrite.Shared",
    "Calendars.ReadWrite",
]
```

- [ ] **Step 2: Verifizieren**

Run: `PYTHONPATH=agents .venv/bin/python -c "from microsoft_auth import SCOPES; assert 'Calendars.ReadWrite' in SCOPES; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add agents/microsoft_auth.py
git commit -m "feat(auth): Calendars.ReadWrite-Scope für MS Graph ergänzen

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

> ⚠️ **Hinweis für den Deploy:** MSAL upgraded gecachte Tokens nicht automatisch auf neue Scopes. Nach dem Deploy muss einmalig `https://herrlich.dev/oauth/microsoft/login?secret=<OAUTH_LOGIN_SECRET>` aufgerufen werden, sonst liefert MS Graph für Kalender-Calls `403`. Siehe Task 6 (Verifikation nach Deploy).

---

## Task 3: Router auf Outlook-Kalender umstellen

`router.py` beschreibt den Kalender-Intent noch als "Apple Calendar via CalDAV", injiziert Kalendernamen aus `CALENDAR_WHITELIST` und kennt einen `calendar_name`-Schreibparameter. Alles entfällt. Das `reminder_write`-Label wird korrigiert.

**Files:**
- Modify: `agents/router.py` (Zeilen 29, 71-78, 114-130, 250, 289-307)

- [ ] **Step 1: `_calendar_names_cache`-Deklaration entfernen**

Edit `agents/router.py` — lösche die Zeile:

```python
_calendar_names_cache: list[str] = []
```

- [ ] **Step 2: `_get_calendar_names()`-Helper entfernen**

Edit `agents/router.py` — lösche die komplette Funktion:

```python
async def _get_calendar_names() -> list[str]:
    global _calendar_names_cache
    if not _calendar_names_cache:
        import os as _os

        raw = _os.environ.get("CALENDAR_WHITELIST", "")
        _calendar_names_cache = [w.strip() for w in raw.split(",") if w.strip()]
    return _calendar_names_cache
```

- [ ] **Step 3: Kalender-Intent im `_SYSTEM_TEMPLATE` umschreiben**

Edit `agents/router.py` — ersetze den Block:

```
1. "calendar" — Fragen zum Kalender (Apple Calendar via CalDAV).
   Verfügbare Kalender: {CALENDAR_NAMES}

   Beispiele:
   - "Was habe ich heute?" → mode=read, kind=today
   - "Erstelle Termin Zahnarzt morgen 10 Uhr" → mode=write

   Parameter:
   - mode: "read" | "write"
   - kind: "today" | "tomorrow" | "week" | "next" | "range" | "specific_day" (nur bei mode=read)
   - start: ISO-8601 datetime oder null
   - end: ISO-8601 datetime oder null (bei mode=write und null → start + 1 Stunde)
   - label: deutsche Beschreibung des Zeitfensters (nur bei mode=read)
   - title: string (Termin-Titel, nur bei mode=write)
   - calendar_name: string oder null (Ziel-Kalender, einer aus: {CALENDAR_NAMES}, nur bei mode=write)
```

mit:

```
1. "calendar" — Fragen zum Outlook-Kalender.

   Beispiele:
   - "Was habe ich heute?" → mode=read, kind=today
   - "Erstelle Termin Zahnarzt morgen 10 Uhr" → mode=write

   Parameter:
   - mode: "read" | "write"
   - kind: "today" | "tomorrow" | "week" | "next" | "range" | "specific_day" (nur bei mode=read)
   - start: ISO-8601 datetime oder null
   - end: ISO-8601 datetime oder null (bei mode=write und null → start + 1 Stunde)
   - label: deutsche Beschreibung des Zeitfensters (nur bei mode=read)
   - title: string (Termin-Titel, nur bei mode=write)
```

(Die `WICHTIG:`-Zeile darunter bleibt unverändert.)

- [ ] **Step 4: `reminder_write`-Label korrigieren**

Edit `agents/router.py` — ersetze:

```
11. "reminder_write" — Apple Reminder / Erinnerung erstellen.
```

mit:

```
11. "reminder_write" — Erinnerung in MS To Do erstellen.
```

- [ ] **Step 5: `_build_system_prompt()` entrümpeln**

Edit `agents/router.py` — ersetze den Funktionskörper:

```python
async def _build_system_prompt() -> str:
    heute = datetime.now(BERLIN).strftime("%Y-%m-%d")
    project_list, todo_names, calendar_names, mail_folders = await asyncio.gather(
        _get_project_list(),
        _get_todo_list_names(),
        _get_calendar_names(),
        _get_mail_folder_names(),
    )
    projects_str = ", ".join(project_list) if project_list else "recipe-app"
    todo_str = ", ".join(todo_names) if todo_names else "(nicht verfügbar)"
    calendar_str = ", ".join(calendar_names) if calendar_names else "(nicht verfügbar)"
    mail_str = ", ".join(mail_folders) if mail_folders else "(nicht verfügbar)"
    return (
        _SYSTEM_TEMPLATE.replace("{HEUTE_ISO}", heute)
        .replace("{PROJECT_LIST}", projects_str)
        .replace("{TODO_LISTS}", todo_str)
        .replace("{CALENDAR_NAMES}", calendar_str)
        .replace("{MAIL_FOLDERS}", mail_str)
    )
```

mit:

```python
async def _build_system_prompt() -> str:
    heute = datetime.now(BERLIN).strftime("%Y-%m-%d")
    project_list, todo_names, mail_folders = await asyncio.gather(
        _get_project_list(),
        _get_todo_list_names(),
        _get_mail_folder_names(),
    )
    projects_str = ", ".join(project_list) if project_list else "recipe-app"
    todo_str = ", ".join(todo_names) if todo_names else "(nicht verfügbar)"
    mail_str = ", ".join(mail_folders) if mail_folders else "(nicht verfügbar)"
    return (
        _SYSTEM_TEMPLATE.replace("{HEUTE_ISO}", heute)
        .replace("{PROJECT_LIST}", projects_str)
        .replace("{TODO_LISTS}", todo_str)
        .replace("{MAIL_FOLDERS}", mail_str)
    )
```

- [ ] **Step 6: Syntax + Router-Test prüfen**

Run:
```bash
PYTHONPATH=agents .venv/bin/python -m py_compile agents/router.py && \
PYTHONPATH=agents .venv/bin/pytest tests/test_router_context.py -v
```
Expected: keine Compile-Fehler; `test_router_context.py` grün. Falls ein Test gegen `{CALENDAR_NAMES}` oder Kalender-Wortlaut assertet, an die neue Formulierung anpassen.

- [ ] **Step 7: Commit**

```bash
git add agents/router.py
git commit -m "refactor(router): Kalender-Intent auf Outlook umstellen

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: Bestätigungsdialog für Termin-Erstellung in `main.py`

Termin-Erstellung führt aktuell sofort aus. Neu: Confirm-Dialog analog zum Mail-Write-Pattern. Außerdem fällt der `calendar_name`-Parameter überall weg (Single-Kalender).

**Files:**
- Modify: `agents/main.py:87` (Module-State), `:529-563` (`handle_calendar`), `:697-722` (Dispatch), `:1243` (`handle_callback`)

- [ ] **Step 1: Module-Level-State `_pending_calendar_ops` ergänzen**

Edit `agents/main.py` — ersetze:

```python
_pending_mail_ops: dict[int, dict] = {}
```

mit:

```python
_pending_mail_ops: dict[int, dict] = {}
_pending_calendar_ops: dict[int, dict] = {}
```

- [ ] **Step 2: `handle_calendar`-Signatur + Write-Branch ersetzen**

Edit `agents/main.py` — ersetze den Funktionskopf:

```python
async def handle_calendar(
    chat_id,
    text,
    kind=None,
    start=None,
    end=None,
    mode="read",
    title=None,
    calendar_name=None,
):
```

mit:

```python
async def handle_calendar(
    chat_id,
    text,
    kind=None,
    start=None,
    end=None,
    mode="read",
    title=None,
):
```

Edit `agents/main.py` — ersetze den gesamten `if mode == "write":`-Block:

```python
    if mode == "write":
        if not title or not start:
            await bot.send_message(
                chat_id=chat_id, text="Bitte Titel und Startzeit angeben."
            )
            return
        if end is None:
            end = start + timedelta(hours=1)
        try:
            await asyncio.to_thread(
                calendar_agent.create_event, title, start, end, calendar_name
            )
            cal_note = f" in '{calendar_name}'" if calendar_name else ""
            await bot.send_message(
                chat_id=chat_id,
                text=f"✅ Termin erstellt{cal_note}: *{title}*\n{start.strftime('%d.%m.%Y %H:%M')} – {end.strftime('%H:%M')}",
                parse_mode="Markdown",
            )
        except Exception as e:
            await bot.send_message(
                chat_id=chat_id, text=f"❌ Termin konnte nicht erstellt werden: {e}"
            )
        return
```

mit:

```python
    if mode == "write":
        if not title or not start:
            await bot.send_message(
                chat_id=chat_id, text="Bitte Titel und Startzeit angeben."
            )
            return
        if end is None:
            end = start + timedelta(hours=1)
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        _pending_calendar_ops[chat_id] = {"title": title, "start": start, "end": end}
        keyboard = [
            [
                InlineKeyboardButton(
                    "✅ Erstellen", callback_data="cal:create:confirm"
                ),
                InlineKeyboardButton(
                    "❌ Abbrechen", callback_data="cal:create:cancel"
                ),
            ]
        ]
        await bot.send_message(
            chat_id=chat_id,
            text=(
                f"📅 *Termin erstellen?*\n\n*{title}*\n"
                f"{start.strftime('%d.%m.%Y %H:%M')} – {end.strftime('%H:%M')}"
            ),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return
```

- [ ] **Step 3: Dispatch-Block anpassen (`calendar_name` entfernen)**

Edit `agents/main.py` — ersetze:

```python
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
            chat_id=chat_id,
            text=text,
            kind=kind,
            start=start,
            end=end,
            mode=mode,
            title=title,
            calendar_name=calendar_name,
        )
        cal_summary = (
            f"Termin erstellt: {title}"
            if mode == "write" and title
            else "Kalender angezeigt"
        )
        _conv_complete(chat_id, cal_summary)
        return
```

mit:

```python
    if intent == "calendar":
        mode = params.get("mode", "read")
        kind = params.get("kind")
        start_str = params.get("start")
        end_str = params.get("end")
        start = datetime.fromisoformat(start_str) if start_str else None
        end = datetime.fromisoformat(end_str) if end_str else None
        title = params.get("title")
        await handle_calendar(
            chat_id=chat_id,
            text=text,
            kind=kind,
            start=start,
            end=end,
            mode=mode,
            title=title,
        )
        cal_summary = (
            f"Termin-Erstellung angefragt: {title}"
            if mode == "write" and title
            else "Kalender angezeigt"
        )
        _conv_complete(chat_id, cal_summary)
        return
```

- [ ] **Step 4: Callback-Handler für `cal:create:confirm` / `cal:create:cancel` ergänzen**

Edit `agents/main.py` — ersetze die letzten beiden Zeilen des `mail:select:`-Blocks:

```python
        await query.edit_message_reply_markup(reply_markup=None)
        await _show_mail_action_confirm(chat_id, mail, mode, params)
```

mit:

```python
        await query.edit_message_reply_markup(reply_markup=None)
        await _show_mail_action_confirm(chat_id, mail, mode, params)

    elif data == "cal:create:confirm":
        chat_id = query.message.chat_id
        op = _pending_calendar_ops.pop(chat_id, None)
        if op is None:
            await query.edit_message_text("⚠️ Keine ausstehende Aktion gefunden.")
            return
        try:
            await asyncio.to_thread(
                calendar_agent.create_event, op["title"], op["start"], op["end"]
            )
            await query.edit_message_text(
                f"✅ Termin erstellt: *{op['title']}*\n"
                f"{op['start'].strftime('%d.%m.%Y %H:%M')} – "
                f"{op['end'].strftime('%H:%M')}",
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.exception("cal:create:confirm fehlgeschlagen")
            await query.edit_message_text(
                f"❌ Termin konnte nicht erstellt werden: {e}"
            )

    elif data == "cal:create:cancel":
        chat_id = query.message.chat_id
        _pending_calendar_ops.pop(chat_id, None)
        await query.edit_message_text("❌ Abgebrochen.")
```

- [ ] **Step 5: Syntax-Check + komplette Test-Suite**

Run:
```bash
PYTHONPATH=agents .venv/bin/python -m py_compile agents/main.py && \
PYTHONPATH=agents .venv/bin/pytest tests/ -q --tb=short \
  --ignore=tests/test_briefing_agent.py \
  --ignore=tests/test_mail_send.py \
  --ignore=tests/test_tasks_agent.py
```
Expected: keine Compile-Fehler; alle Tests grün.

- [ ] **Step 6: Commit**

```bash
git add agents/main.py
git commit -m "feat(calendar): Bestätigungsdialog für Termin-Erstellung

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: Aufräumen — Dependencies, .env.example, Doku

CalDAV-Pakete entfernen, `ICLOUD_*`/`CALENDAR_WHITELIST` aus Beispiel-Env streichen, `CLAUDE.md` an den neuen Stand anpassen.

**Files:**
- Modify: `agents/requirements.txt`
- Modify: `.env.example`
- Modify: `herrlich-ai-platform/CLAUDE.md`

- [ ] **Step 1: Prüfen, dass die CalDAV-Pakete nirgends mehr importiert werden**

Run: `grep -rn "import caldav\|from caldav\|import icalendar\|from icalendar\|recurring_ical_events\|x_wr_timezone" agents/ tests/`
Expected: keine Treffer (nach Task 1 wurden alle Importe entfernt).

- [ ] **Step 2: CalDAV-Pakete aus `requirements.txt` entfernen**

Edit `agents/requirements.txt` — lösche diese 5 Zeilen:

```
caldav==3.1.0
icalendar==7.0.3
icalendar-searcher==1.0.5
recurring-ical-events==3.8.1
x-wr-timezone==2.0.1
```

(`caldav`/`icalendar`/`icalendar-searcher` sind die direkten Pakete; `recurring-ical-events` und `x-wr-timezone` sind transitive Abhängigkeiten von `caldav`, die sonst verwaisen.)

- [ ] **Step 3: `.env.example` bereinigen**

Edit `.env.example` — lösche die 3 Zeilen:

```
ICLOUD_USER=your-apple-id-email
ICLOUD_APP_PASSWORD=your-app-specific-password
CALENDAR_WHITELIST=Privat
```

- [ ] **Step 4: `CLAUDE.md` — Datei-Struktur**

Edit `herrlich-ai-platform/CLAUDE.md` — ersetze:

```
  calendar_agent.py     iCloud CalDAV (lesen + schreiben)
```

mit:

```
  calendar_agent.py     Outlook-Kalender via MS Graph (lesen + schreiben)
```

- [ ] **Step 5: `CLAUDE.md` — Environment-Variablen-Tabelle**

Edit `herrlich-ai-platform/CLAUDE.md` — lösche die 3 Tabellenzeilen:

```
| `ICLOUD_USER` | ✅ | Apple-ID E-Mail für CalDAV |
| `ICLOUD_APP_PASSWORD` | ✅ | Apple App-spezifisches Passwort für CalDAV |
| `CALENDAR_WHITELIST` | ✅ | Komma-separierte Kalender-Namen, z.B. `Privat,Arbeit` |
```

- [ ] **Step 6: `CLAUDE.md` — Agenten-Detail-Abschnitt**

Edit `herrlich-ai-platform/CLAUDE.md` — ersetze:

```
### calendar_agent.py — CalendarAgent-Klasse
iCloud CalDAV via `caldav`-Bibliothek. Konfiguriert via `ICLOUD_USER`, `ICLOUD_APP_PASSWORD`, `CALENDAR_WHITELIST`.

Kalender-Schrankenliste: nur Kalender aus `CALENDAR_WHITELIST` werden gelesen/beschrieben.
Erinnerungen: `/reminders/`-Kalender werden separat behandelt (`get_all_reminders`, `create_reminder`).
```

mit:

```
### calendar_agent.py — CalendarAgent-Klasse
Outlook-Kalender via MS Graph (`httpx`). Auth über `microsoft_auth.get_access_token()`.

Lesen: `GET /me/calendarView` (Header `Prefer: outlook.timezone="Europe/Berlin"`) — expandiert Serien- und Multi-Day-Termine serverseitig. Schreiben: `POST /me/events`.
Es wird ausschließlich der Standard-Kalender (`/me/...`) genutzt — keine Kalender-Whitelist, kein `calendar_name`-Parameter.
```

- [ ] **Step 7: `CLAUDE.md` — MS Graph OAuth-Abschnitt**

Edit `herrlich-ai-platform/CLAUDE.md` — ersetze:

```
**Scopes:** `Mail.ReadWrite` · `Mail.Send` · `Tasks.ReadWrite` · `Tasks.ReadWrite.Shared`
```

mit:

```
**Scopes:** `Mail.ReadWrite` · `Mail.Send` · `Tasks.ReadWrite` · `Tasks.ReadWrite.Shared` · `Calendars.ReadWrite`
```

Edit `herrlich-ai-platform/CLAUDE.md` — ersetze:

```
Achtung: Nach Scope-Änderung muss Re-Auth durchgeführt werden — MSAL upgraded Token nicht automatisch.
Kalender läuft über CalDAV (iCloud), nicht über MS Graph.
```

mit:

```
Achtung: Nach Scope-Änderung muss Re-Auth durchgeführt werden — MSAL upgraded Token nicht automatisch.
Kalender läuft seit der Outlook-Migration über MS Graph (`/me/calendarView`, `/me/events`).
```

- [ ] **Step 8: `CLAUDE.md` — Pending-State-Abschnitt**

Edit `herrlich-ai-platform/CLAUDE.md` — ersetze:

```
_pending_mail_ops: dict[int, dict]    # Mail-Write-Op wartet auf Confirm-Button
_last_mail_search: dict[int, dict]    # Multi-Treffer-Auswahl (TTL: 3 Min, timestamp im Dict)
_recent_conv: dict[int, list]         # Letzte Konversations-Paare (user + assistant) pro chat_id für Router-Kontext
```

mit:

```
_pending_mail_ops: dict[int, dict]      # Mail-Write-Op wartet auf Confirm-Button
_pending_calendar_ops: dict[int, dict]  # Termin-Erstellung wartet auf Confirm-Button
_last_mail_search: dict[int, dict]      # Multi-Treffer-Auswahl (TTL: 3 Min, timestamp im Dict)
_recent_conv: dict[int, list]           # Letzte Konversations-Paare (user + assistant) pro chat_id für Router-Kontext
```

- [ ] **Step 9: `CLAUDE.md` — Callbacks-Tabelle**

Edit `herrlich-ai-platform/CLAUDE.md` — ersetze:

```
| `mail:select:{n}` | handle_callback | Mail n aus Multi-Treffer-Liste wählen → Confirm |
```

mit:

```
| `mail:select:{n}` | handle_callback | Mail n aus Multi-Treffer-Liste wählen → Confirm |
| `cal:create:confirm` | handle_callback | Pending Termin-Erstellung ausführen |
| `cal:create:cancel` | handle_callback | Pending Termin-Erstellung verwerfen |
```

- [ ] **Step 10: `CLAUDE.md` — Bekannte Eigenheiten**

Edit `herrlich-ai-platform/CLAUDE.md` — ersetze:

```
- **CalDAV Erinnerungen** — Apple Reminders über CalDAV seit iOS 13 instabil. Neue Erinnerungen gehen in MS To Do (tasks_agent)
```

mit:

```
- **Erinnerungen** — laufen vollständig über MS To Do (`tasks_agent`, Intent `reminder_write`); kein Apple/CalDAV-Pfad mehr
- **Kalender-Schreibaktionen** — zeigen seit der Outlook-Migration einen Confirm-Dialog (Callbacks `cal:create:*`), analog zu Mail-Write
```

- [ ] **Step 11: `CLAUDE.md` — Stack-Zeile**

Edit `herrlich-ai-platform/CLAUDE.md` — ersetze:

```
MS Graph API · iCloud CalDAV · Open-Meteo · Groq Whisper · systemd · Caddy
```

mit:

```
MS Graph API · Open-Meteo · Groq Whisper · systemd · Caddy
```

- [ ] **Step 12: Commit**

```bash
git add agents/requirements.txt .env.example CLAUDE.md
git commit -m "chore(calendar): CalDAV-Deps + Doku nach Outlook-Migration aufräumen

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: Deploy & Verifikation

- [ ] **Step 1: Pushen — löst Auto-Deploy via GitHub-Webhook aus**

```bash
git push
```
Der GitHub-Webhook führt auf dem VPS `git reset --hard origin/main`, `rsync agents/ → /opt/jarvis/` und `systemctl restart jarvis` aus.

- [ ] **Step 2: Re-Auth durchführen (PFLICHT — neuer Scope)**

Im Browser öffnen: `https://herrlich.dev/oauth/microsoft/login?secret=<OAUTH_LOGIN_SECRET>`
Microsoft-Login durchlaufen, damit der Token-Cache den `Calendars.ReadWrite`-Scope erhält. Ohne diesen Schritt liefert MS Graph `403` und der Kalender bleibt leer.

- [ ] **Step 3: Lesen live testen**

In Telegram an @jarvis_herrlich_bot: „Was habe ich heute?" — erwartet: heutige Outlook-Termine (oder leere/keine-Termine-Antwort, falls heute nichts ansteht).

- [ ] **Step 4: Schreiben live testen**

In Telegram: „Erstelle Termin Testtermin morgen 15 Uhr" — erwartet: Confirm-Dialog mit „✅ Erstellen" / „❌ Abbrechen". Auf „✅ Erstellen" tippen → Bestätigung; Termin erscheint im Outlook-Kalender. Anschließend Testtermin in Outlook wieder löschen.

- [ ] **Step 5: Env-Var-Aufräumen auf dem VPS (optional)**

`ICLOUD_USER`, `ICLOUD_APP_PASSWORD`, `CALENDAR_WHITELIST` aus `/var/lib/jarvis/.env` entfernen — werden nicht mehr gelesen, schaden aber auch nicht.

---

## Self-Review

**Spec coverage:**
- `calendar_agent.py`-Neuschrieb (MS Graph read/write) → Task 1 ✅
- `Calendars.ReadWrite`-Scope → Task 2 ✅
- Router: Outlook-Text, `{CALENDAR_NAMES}` raus, `calendar_name` raus, `reminder_write`-Label → Task 3 ✅
- `main.py`: Confirm-Dialog, `_pending_calendar_ops`, neue Callbacks, `calendar_name` raus → Task 4 ✅
- `requirements.txt`-Cleanup → Task 5 (Steps 1–2) ✅
- `.env.example`-Cleanup → Task 5 (Step 3) ✅
- `CLAUDE.md`-Updates → Task 5 (Steps 4–11) ✅
- Tests: `test_calendar_reminders.py` löschen, `test_calendar_write.py` neu, `test_calendar_read.py` neu → Task 1 ✅
- Re-Auth-Verifikation nach Deploy → Task 6 ✅
- `get_reminders_today()` entfernt → Task 1 (im Neuschrieb nicht mehr enthalten) ✅

Keine Lücken.

**Placeholder-Scan:** Keine TBD/TODO/„später"-Platzhalter; jeder Code-Step enthält vollständigen Code.

**Type-Konsistenz:**
- `CalendarAgent()` wird ohne Argumente konstruiert (Task 1, 4 — Konstruktor nimmt keine Argumente mehr).
- `create_event(title, start_dt, end_dt)` — 3 Argumente, kein `calendar_name`; identisch in Task 1 (Definition), Task 4 (Aufruf via `_pending_calendar_ops`-Dict `{title, start, end}`).
- `get_events(start, end)` / `get_next_event()` — Signaturen unverändert gegenüber Alt-API, daher `briefing_agent.py` und `proactive_agent.py` ohne Änderung kompatibel.
- Callback-Strings `cal:create:confirm` / `cal:create:cancel` — identisch in `handle_calendar` (Erzeugung) und `handle_callback` (Auswertung).
