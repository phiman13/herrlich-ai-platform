# Kalender-Termine ändern & absagen — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Jarvis kann bestehende Outlook-Termine verschieben, bearbeiten (Titel/Ort) und absagen — über einen Suche→Auswahl→Bestätigungs-Flow analog zum Mail-Write.

**Architecture:** `CalendarAgent` bekommt `search_events`/`update_event`/`delete_event` (MS Graph `calendarView`/`PATCH`/`DELETE`). Das `Event`-Dataclass erhält `id` (für PATCH/DELETE) und `recurring`. `main.py` bekommt einen `handle_calendar_modify`-Flow; die Kalender-Confirm-Callbacks werden auf ein generisches `cal:action:*` mit `type`-Dispatch (create/update/delete) vereinheitlicht.

**Tech Stack:** Python 3.11 · `httpx` · Microsoft Graph API · python-telegram-bot · pytest

**Spec:** `docs/superpowers/specs/2026-05-16-kalender-termine-aendern-design.md`

**Tests lokal ausführen:**
```bash
PYTHONPATH=agents .venv/bin/pytest tests/ -q --tb=short \
  --ignore=tests/test_briefing_agent.py \
  --ignore=tests/test_mail_send.py \
  --ignore=tests/test_tasks_agent.py
```

---

## Task 1: `Event`-Dataclass um `id` und `recurring` erweitern

PATCH/DELETE brauchen die MS-Graph-Event-ID. `recurring` steuert später einen Hinweis im Confirm-Dialog. `_to_event` und das `$select` werden mitgezogen.

**Files:**
- Modify: `agents/calendar_agent.py`
- Modify: `tests/test_calendar_read.py`

- [ ] **Step 1: `tests/test_calendar_read.py` — Fixture + Assertions anpassen (Test soll fehlschlagen)**

Ersetze das gesamte `_CALENDAR_VIEW_JSON`-Dict:

```python
_CALENDAR_VIEW_JSON = {
    "value": [
        {
            "id": "evt-zahnarzt",
            "subject": "Zahnarzt",
            "start": {
                "dateTime": "2026-05-16T10:00:00.0000000",
                "timeZone": "Europe/Berlin",
            },
            "end": {
                "dateTime": "2026-05-16T11:00:00.0000000",
                "timeZone": "Europe/Berlin",
            },
            "isAllDay": False,
            "location": {"displayName": "Praxis Dr. Müller"},
            "type": "singleInstance",
        },
        {
            "id": "evt-urlaub",
            "subject": "Urlaub",
            "start": {
                "dateTime": "2026-05-16T00:00:00.0000000",
                "timeZone": "Europe/Berlin",
            },
            "end": {
                "dateTime": "2026-05-17T00:00:00.0000000",
                "timeZone": "Europe/Berlin",
            },
            "isAllDay": True,
            "location": {"displayName": ""},
            "type": "occurrence",
        },
    ]
}
```

In `test_get_events_maps_graph_payload`, ersetze:

```python
    assert ev.source == "outlook"
    assert "calendarView" in mock_get.call_args[0][0]
```

mit:

```python
    assert ev.source == "outlook"
    assert ev.id == "evt-zahnarzt"
    assert ev.recurring is False
    assert "calendarView" in mock_get.call_args[0][0]
```

In `test_get_events_marks_all_day_and_empty_location`, ersetze:

```python
    urlaub = [e for e in events if e.title == "Urlaub"][0]
    assert urlaub.all_day is True
    assert urlaub.location is None
```

mit:

```python
    urlaub = [e for e in events if e.title == "Urlaub"][0]
    assert urlaub.all_day is True
    assert urlaub.location is None
    assert urlaub.id == "evt-urlaub"
    assert urlaub.recurring is True
```

- [ ] **Step 2: Tests laufen lassen — müssen fehlschlagen**

Run: `PYTHONPATH=agents .venv/bin/pytest tests/test_calendar_read.py -v`
Expected: FAIL — `Event.__init__` kennt `id`/`recurring` noch nicht bzw. `_to_event` setzt sie nicht.

- [ ] **Step 3: `Event`-Dataclass erweitern**

Edit `agents/calendar_agent.py` — ersetze:

```python
@dataclass
class Event:
    title: str
    start: datetime
    end: datetime
    location: Optional[str]
    calendar_name: str
    source: str  # "outlook"
    all_day: bool = False
```

mit:

```python
@dataclass
class Event:
    id: str
    title: str
    start: datetime
    end: datetime
    location: Optional[str]
    calendar_name: str
    source: str  # "outlook"
    all_day: bool = False
    recurring: bool = False
```

- [ ] **Step 4: `$select` um `id` und `type` erweitern**

Edit `agents/calendar_agent.py` — ersetze:

```python
            "$select": "subject,start,end,isAllDay,location",
```

mit:

```python
            "$select": "id,subject,start,end,isAllDay,location,type",
```

- [ ] **Step 5: `_to_event` — `id` und `recurring` setzen**

Edit `agents/calendar_agent.py` — ersetze:

```python
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
```

mit:

```python
    @classmethod
    def _to_event(cls, item: dict) -> Event:
        location = (item.get("location") or {}).get("displayName") or None
        return Event(
            id=item["id"],
            title=item.get("subject") or "(ohne Titel)",
            start=_parse_graph_dt(item["start"]),
            end=_parse_graph_dt(item["end"]),
            location=location,
            calendar_name=cls.DEFAULT_CALENDAR_NAME,
            source="outlook",
            all_day=bool(item.get("isAllDay")),
            recurring=item.get("type") not in (None, "singleInstance"),
        )
```

- [ ] **Step 6: Tests laufen lassen — müssen bestehen**

Run: `PYTHONPATH=agents .venv/bin/pytest tests/test_calendar_read.py -v`
Expected: PASS (3 Tests).

- [ ] **Step 7: Komplette Suite**

Run:
```bash
PYTHONPATH=agents .venv/bin/pytest tests/ -q --tb=short \
  --ignore=tests/test_briefing_agent.py \
  --ignore=tests/test_mail_send.py \
  --ignore=tests/test_tasks_agent.py
```
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add agents/calendar_agent.py tests/test_calendar_read.py
git commit -m "feat(calendar): Event-ID + recurring-Flag für Termin-Änderungen

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: `search_events`, `update_event`, `delete_event` in `calendar_agent.py`

Drei neue Methoden auf `CalendarAgent`: Termin-Suche (deterministischer Titel-Match), Ändern (`PATCH`), Absagen (`DELETE`).

**Files:**
- Modify: `agents/calendar_agent.py`
- Create: `tests/test_calendar_modify.py`

- [ ] **Step 1: `tests/test_calendar_modify.py` schreiben (Tests sollen fehlschlagen)**

```python
# tests/test_calendar_modify.py
from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import httpx
import pytest

BERLIN = ZoneInfo("Europe/Berlin")

_SEARCH_JSON = {
    "value": [
        {
            "id": "evt-zahnarzt",
            "subject": "Zahnarzt Dr. Müller",
            "start": {"dateTime": "2026-05-20T10:00:00.0000000", "timeZone": "Europe/Berlin"},
            "end": {"dateTime": "2026-05-20T11:00:00.0000000", "timeZone": "Europe/Berlin"},
            "isAllDay": False,
            "location": {"displayName": ""},
            "type": "singleInstance",
        },
        {
            "id": "evt-standup",
            "subject": "Standup Team Backend",
            "start": {"dateTime": "2026-05-21T09:00:00.0000000", "timeZone": "Europe/Berlin"},
            "end": {"dateTime": "2026-05-21T09:15:00.0000000", "timeZone": "Europe/Berlin"},
            "isAllDay": False,
            "location": {"displayName": ""},
            "type": "occurrence",
        },
        {
            "id": "evt-lunch",
            "subject": "Lunch mit Anna",
            "start": {"dateTime": "2026-05-22T12:00:00.0000000", "timeZone": "Europe/Berlin"},
            "end": {"dateTime": "2026-05-22T13:00:00.0000000", "timeZone": "Europe/Berlin"},
            "isAllDay": False,
            "location": {"displayName": ""},
            "type": "singleInstance",
        },
    ]
}


def _resp(json_data=None, status=200):
    m = MagicMock()
    m.status_code = status
    m.json.return_value = json_data or {}
    m.raise_for_status.return_value = None
    return m


def _win():
    return (
        datetime(2026, 5, 19, 0, 0, tzinfo=BERLIN),
        datetime(2026, 6, 19, 0, 0, tzinfo=BERLIN),
    )


def test_search_events_matches_single_word():
    from agents.calendar_agent import CalendarAgent

    start, end = _win()
    with (
        patch("agents.calendar_agent.get_access_token", return_value="tok"),
        patch("httpx.get", return_value=_resp(_SEARCH_JSON)),
    ):
        hits = CalendarAgent().search_events("Zahnarzt", start, end)

    assert len(hits) == 1
    assert hits[0].id == "evt-zahnarzt"


def test_search_events_requires_all_words():
    from agents.calendar_agent import CalendarAgent

    start, end = _win()
    with (
        patch("agents.calendar_agent.get_access_token", return_value="tok"),
        patch("httpx.get", return_value=_resp(_SEARCH_JSON)),
    ):
        hits = CalendarAgent().search_events("Standup Backend", start, end)

    assert len(hits) == 1
    assert hits[0].id == "evt-standup"


def test_search_events_no_match_returns_empty():
    from agents.calendar_agent import CalendarAgent

    start, end = _win()
    with (
        patch("agents.calendar_agent.get_access_token", return_value="tok"),
        patch("httpx.get", return_value=_resp(_SEARCH_JSON)),
    ):
        hits = CalendarAgent().search_events("Friseur", start, end)

    assert hits == []


def test_update_event_patches_only_changed_fields():
    from agents.calendar_agent import CalendarAgent

    new_start = datetime(2026, 5, 20, 15, 0, tzinfo=BERLIN)
    new_end = datetime(2026, 5, 20, 16, 0, tzinfo=BERLIN)
    with (
        patch("agents.calendar_agent.get_access_token", return_value="tok"),
        patch("httpx.patch", return_value=_resp(status=200)) as mock_patch,
    ):
        CalendarAgent().update_event("evt-zahnarzt", new_start=new_start, new_end=new_end)

    mock_patch.assert_called_once()
    assert mock_patch.call_args[0][0].endswith("/me/events/evt-zahnarzt")
    body = mock_patch.call_args[1]["json"]
    assert body["start"]["dateTime"] == "2026-05-20T15:00:00"
    assert body["end"]["dateTime"] == "2026-05-20T16:00:00"
    assert "subject" not in body
    assert "location" not in body


def test_update_event_changes_title_and_location():
    from agents.calendar_agent import CalendarAgent

    with (
        patch("agents.calendar_agent.get_access_token", return_value="tok"),
        patch("httpx.patch", return_value=_resp(status=200)) as mock_patch,
    ):
        CalendarAgent().update_event(
            "evt-x", new_title="Strategie-Call", new_location="Raum 3"
        )

    body = mock_patch.call_args[1]["json"]
    assert body["subject"] == "Strategie-Call"
    assert body["location"] == {"displayName": "Raum 3"}
    assert "start" not in body


def test_update_event_raises_without_changes():
    from agents.calendar_agent import CalendarAgent

    with patch("agents.calendar_agent.get_access_token", return_value="tok"):
        with pytest.raises(ValueError):
            CalendarAgent().update_event("evt-x")


def test_delete_event_calls_graph_delete():
    from agents.calendar_agent import CalendarAgent

    with (
        patch("agents.calendar_agent.get_access_token", return_value="tok"),
        patch("httpx.delete", return_value=_resp(status=204)) as mock_delete,
    ):
        CalendarAgent().delete_event("evt-zahnarzt")

    mock_delete.assert_called_once()
    assert mock_delete.call_args[0][0].endswith("/me/events/evt-zahnarzt")


def test_delete_event_raises_on_http_error():
    from agents.calendar_agent import CalendarAgent

    with (
        patch("agents.calendar_agent.get_access_token", return_value="tok"),
        patch("httpx.delete", side_effect=httpx.HTTPError("boom")),
    ):
        with pytest.raises(httpx.HTTPError):
            CalendarAgent().delete_event("evt-x")
```

- [ ] **Step 2: Tests laufen lassen — müssen fehlschlagen**

Run: `PYTHONPATH=agents .venv/bin/pytest tests/test_calendar_modify.py -v`
Expected: FAIL — `search_events`/`update_event`/`delete_event` existieren noch nicht (`AttributeError`).

- [ ] **Step 3: Die drei Methoden implementieren**

Edit `agents/calendar_agent.py` — ersetze die letzte Zeile von `create_event`:

```python
        resp.raise_for_status()
        logger.info("Termin erstellt: '%s' (%s)", title, start_dt.isoformat())
```

mit (Methode + drei neue Methoden):

```python
        resp.raise_for_status()
        logger.info("Termin erstellt: '%s' (%s)", title, start_dt.isoformat())

    def search_events(
        self, query: str, start: datetime, end: datetime
    ) -> list[Event]:
        """Return events in [start, end] whose title matches `query`.

        Match rule: every word in `query` with length >= 3 must appear as a
        case-insensitive substring of the title. If `query` has no such word,
        the whole (stripped, lowercased) query must be a substring.
        """
        events = self.get_events(start, end)
        words = [w for w in query.lower().split() if len(w) >= 3]
        if not words:
            words = [query.lower().strip()]
        return [ev for ev in events if all(w in ev.title.lower() for w in words)]

    def update_event(
        self,
        event_id: str,
        new_start: Optional[datetime] = None,
        new_end: Optional[datetime] = None,
        new_title: Optional[str] = None,
        new_location: Optional[str] = None,
    ) -> None:
        """Patch an event — only the provided fields change. Raises on failure."""
        body: dict = {}
        if new_title is not None:
            body["subject"] = new_title
        if new_start is not None:
            body["start"] = {
                "dateTime": _to_berlin(new_start).strftime("%Y-%m-%dT%H:%M:%S"),
                "timeZone": "Europe/Berlin",
            }
        if new_end is not None:
            body["end"] = {
                "dateTime": _to_berlin(new_end).strftime("%Y-%m-%dT%H:%M:%S"),
                "timeZone": "Europe/Berlin",
            }
        if new_location is not None:
            body["location"] = {"displayName": new_location}
        if not body:
            raise ValueError("update_event: keine Änderung angegeben")
        resp = httpx.patch(
            f"{_GRAPH}/me/events/{event_id}",
            headers=self._headers(),
            json=body,
            timeout=15,
        )
        resp.raise_for_status()
        logger.info("Termin geändert: %s", event_id)

    def delete_event(self, event_id: str) -> None:
        """Delete an event. Raises on failure."""
        resp = httpx.delete(
            f"{_GRAPH}/me/events/{event_id}",
            headers=self._headers(),
            timeout=15,
        )
        resp.raise_for_status()
        logger.info("Termin abgesagt: %s", event_id)
```

- [ ] **Step 4: Tests laufen lassen — müssen bestehen**

Run: `PYTHONPATH=agents .venv/bin/pytest tests/test_calendar_modify.py -v`
Expected: PASS (8 Tests).

- [ ] **Step 5: Komplette Suite**

Run:
```bash
PYTHONPATH=agents .venv/bin/pytest tests/ -q --tb=short \
  --ignore=tests/test_briefing_agent.py \
  --ignore=tests/test_mail_send.py \
  --ignore=tests/test_tasks_agent.py
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add agents/calendar_agent.py tests/test_calendar_modify.py
git commit -m "feat(calendar): search_events, update_event, delete_event

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: Router — `update`/`delete`-Modes für den Kalender-Intent

Der Kalender-Intent bekommt zwei neue Modes plus die zugehörigen Parameter.

**Files:**
- Modify: `agents/router.py`

- [ ] **Step 1: Kalender-Intent-Block im `_SYSTEM_TEMPLATE` erweitern**

Edit `agents/router.py` — ersetze den Block:

```
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

   WICHTIG: Heute ist {HEUTE_ISO}. Bei mode=read: Berechne start/end relativ zu diesem Datum, in Europe/Berlin Zeitzone. Bei "today" / "tomorrow" / "week" / "next" können start/end null sein. Bei "range" oder "specific_day" MUSS start/end gesetzt sein. Bei mode=write: start MUSS gesetzt sein. end=null bedeutet start+1h.
```

mit:

```
   Beispiele:
   - "Was habe ich heute?" → mode=read, kind=today
   - "Erstelle Termin Zahnarzt morgen 10 Uhr" → mode=write
   - "Verschiebe den Zahnarzttermin auf 15 Uhr" → mode=update, query=Zahnarzt
   - "Sag den Termin mit Anna morgen ab" → mode=delete, query=Anna
   - "Ändere den Titel von Meeting zu Strategie-Call" → mode=update, query=Meeting, new_title=Strategie-Call

   Parameter:
   - mode: "read" | "write" | "update" | "delete"
   - kind: "today" | "tomorrow" | "week" | "next" | "range" | "specific_day" (nur bei mode=read)
   - start: ISO-8601 datetime oder null
   - end: ISO-8601 datetime oder null (bei mode=write und null → start + 1 Stunde)
   - label: deutsche Beschreibung des Zeitfensters (nur bei mode=read)
   - title: string (Termin-Titel, nur bei mode=write)
   - query: string (markanter Titel-Ausschnitt des Ziel-Termins, nur bei mode=update/delete)
   - search_start: ISO-8601 datetime oder null (Beginn Suchfenster, nur bei mode=update/delete)
   - search_end: ISO-8601 datetime oder null (Ende Suchfenster, nur bei mode=update/delete)
   - new_start: ISO-8601 datetime oder null (neue Startzeit, nur bei mode=update)
   - new_end: ISO-8601 datetime oder null (neue Endzeit, nur bei mode=update)
   - new_title: string oder null (neuer Titel, nur bei mode=update)
   - new_location: string oder null (neuer Ort, nur bei mode=update)

   WICHTIG: Heute ist {HEUTE_ISO}. Bei mode=read: Berechne start/end relativ zu diesem Datum, in Europe/Berlin Zeitzone. Bei "today" / "tomorrow" / "week" / "next" können start/end null sein. Bei "range" oder "specific_day" MUSS start/end gesetzt sein. Bei mode=write: start MUSS gesetzt sein. end=null bedeutet start+1h. Bei mode=update/delete: query MUSS gesetzt sein; leite search_start/search_end aus Zeitangaben in der Nachricht ab, sonst null. Bei mode=update MUSS mindestens eines der new_*-Felder gesetzt sein.
```

- [ ] **Step 2: Syntax + Router-Test prüfen**

Run:
```bash
PYTHONPATH=agents .venv/bin/python -m py_compile agents/router.py && \
PYTHONPATH=agents .venv/bin/pytest tests/test_router_context.py -v
```
Expected: keine Compile-Fehler; `test_router_context.py` grün (der Intent `calendar` und die Whitelist bleiben unverändert — `mode` ist nur ein Parameter).

- [ ] **Step 3: Commit**

```bash
git add agents/router.py
git commit -m "feat(router): Kalender-Intent um update/delete-Modes erweitern

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: `main.py` — Änderungs-Flow + Callback-Vereinheitlichung

Neuer `handle_calendar_modify`-Flow (Suche → Auswahl → Confirm). Die Kalender-Confirm-Callbacks werden von `cal:create:*` auf ein generisches `cal:action:*` mit `type`-Dispatch umgestellt.

**Files:**
- Modify: `agents/main.py`

- [ ] **Step 1: Module-State `_last_calendar_search` ergänzen**

Edit `agents/main.py` — ersetze:

```python
_last_mail_search: dict[int, dict] = {}
```

mit:

```python
_last_mail_search: dict[int, dict] = {}
_last_calendar_search: dict[int, dict] = {}
```

- [ ] **Step 2: `handle_calendar_modify` und `_show_calendar_action_confirm` ergänzen**

Edit `agents/main.py` — ersetze das Ende von `handle_calendar`:

```python
    try:
        if kind == "next":
            ev = await asyncio.to_thread(calendar_agent.get_next_event)
            msg = format_calendar_response("next", ev)
        else:
            events = await asyncio.to_thread(calendar_agent.get_events, start, end)
            msg = format_calendar_response(kind, events, query_start=start)
        await bot.send_message(chat_id=chat_id, text=msg)
    except Exception as e:
        await bot.send_message(chat_id=chat_id, text=f"Kalender-Fehler: {str(e)}")
```

mit (gleicher Block + zwei neue Funktionen):

```python
    try:
        if kind == "next":
            ev = await asyncio.to_thread(calendar_agent.get_next_event)
            msg = format_calendar_response("next", ev)
        else:
            events = await asyncio.to_thread(calendar_agent.get_events, start, end)
            msg = format_calendar_response(kind, events, query_start=start)
        await bot.send_message(chat_id=chat_id, text=msg)
    except Exception as e:
        await bot.send_message(chat_id=chat_id, text=f"Kalender-Fehler: {str(e)}")


async def handle_calendar_modify(chat_id, mode, params):
    """Find a target event from a description, then show an update/delete confirm."""
    bot = Bot(token=TELEGRAM_TOKEN)
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    query = params.get("query")
    if not query:
        await bot.send_message(
            chat_id=chat_id,
            text="Welchen Termin meinst du? Bitte mit einem Stichwort beschreiben.",
        )
        return

    if mode == "update" and not any(
        params.get(k) for k in ("new_start", "new_end", "new_title", "new_location")
    ):
        await bot.send_message(
            chat_id=chat_id, text="Was soll an dem Termin geändert werden?"
        )
        return

    now = datetime.now(BERLIN)
    search_start_str = params.get("search_start")
    search_end_str = params.get("search_end")
    search_start = (
        datetime.fromisoformat(search_start_str) if search_start_str else now
    )
    search_end = (
        datetime.fromisoformat(search_end_str)
        if search_end_str
        else now + timedelta(days=30)
    )

    events = await asyncio.to_thread(
        calendar_agent.search_events, query, search_start, search_end
    )
    if not events:
        await bot.send_message(
            chat_id=chat_id, text=f"Keinen Termin gefunden, der zu '{query}' passt."
        )
        return
    if len(events) > 5:
        await bot.send_message(
            chat_id=chat_id,
            text=f"Mehr als 5 Treffer für '{query}' — bitte präziser beschreiben.",
        )
        return
    if len(events) == 1:
        await _show_calendar_action_confirm(chat_id, events[0], mode, params)
        return

    _last_calendar_search[chat_id] = {
        "events": events,
        "mode": mode,
        "params": params,
        "timestamp": time.time(),
    }
    keyboard = [
        [
            InlineKeyboardButton(
                f"{i + 1}. {ev.title} ({ev.start.strftime('%d.%m. %H:%M')})",
                callback_data=f"cal:select:{i}",
            )
        ]
        for i, ev in enumerate(events)
    ]
    await bot.send_message(
        chat_id=chat_id,
        text=f"Mehrere Termine passen zu '{query}' — welchen meinst du?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def _show_calendar_action_confirm(chat_id, event, mode, params):
    """Stage an update/delete op in _pending_calendar_ops and send the confirm dialog."""
    bot = Bot(token=TELEGRAM_TOKEN)
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    recurring_note = (
        "\n_(nur dieser Termin — die Serie bleibt)_" if event.recurring else ""
    )

    if mode == "delete":
        _pending_calendar_ops[chat_id] = {
            "type": "delete",
            "event_id": event.id,
            "title": event.title,
        }
        text = (
            f"🗑️ *Termin absagen?*\n\n*{event.title}*\n"
            f"{event.start.strftime('%d.%m.%Y %H:%M')} – "
            f"{event.end.strftime('%H:%M')}{recurring_note}"
        )
        confirm_label = "✅ Absagen"
    else:  # update
        new_start_str = params.get("new_start")
        new_end_str = params.get("new_end")
        new_start = datetime.fromisoformat(new_start_str) if new_start_str else None
        new_end = datetime.fromisoformat(new_end_str) if new_end_str else None
        new_title = params.get("new_title")
        new_location = params.get("new_location")
        if new_start and not new_end:
            new_end = new_start + (event.end - event.start)

        _pending_calendar_ops[chat_id] = {
            "type": "update",
            "event_id": event.id,
            "title": new_title or event.title,
            "new_start": new_start,
            "new_end": new_end,
            "new_title": new_title,
            "new_location": new_location,
        }
        lines = [f"📅 *Termin ändern?*\n\n*{event.title}*"]
        if new_start:
            lines.append(
                f"Zeit: {event.start.strftime('%d.%m. %H:%M')}–"
                f"{event.end.strftime('%H:%M')} → "
                f"{new_start.strftime('%d.%m. %H:%M')}–{new_end.strftime('%H:%M')}"
            )
        if new_title:
            lines.append(f"Titel: {event.title} → {new_title}")
        if new_location:
            lines.append(f"Ort: {event.location or '—'} → {new_location}")
        text = "\n".join(lines) + recurring_note
        confirm_label = "✅ Ändern"

    keyboard = [
        [
            InlineKeyboardButton(confirm_label, callback_data="cal:action:confirm"),
            InlineKeyboardButton("❌ Abbrechen", callback_data="cal:action:cancel"),
        ]
    ]
    await bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
```

- [ ] **Step 3: Write-Branch — Pending-Op + Callback-Daten umstellen**

Edit `agents/main.py` — ersetze im `if mode == "write":`-Zweig von `handle_calendar`:

```python
        _pending_calendar_ops[chat_id] = {"title": title, "start": start, "end": end}
        keyboard = [
            [
                InlineKeyboardButton(
                    "✅ Erstellen", callback_data="cal:create:confirm"
                ),
                InlineKeyboardButton("❌ Abbrechen", callback_data="cal:create:cancel"),
            ]
        ]
```

mit:

```python
        _pending_calendar_ops[chat_id] = {
            "type": "create",
            "title": title,
            "start": start,
            "end": end,
        }
        keyboard = [
            [
                InlineKeyboardButton(
                    "✅ Erstellen", callback_data="cal:action:confirm"
                ),
                InlineKeyboardButton("❌ Abbrechen", callback_data="cal:action:cancel"),
            ]
        ]
```

- [ ] **Step 4: Callback-Handler — `cal:create:*` durch `cal:action:*` + `cal:select:*` ersetzen**

Edit `agents/main.py` — ersetze die beiden Blöcke:

```python
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

mit:

```python
    elif data == "cal:action:confirm":
        chat_id = query.message.chat_id
        op = _pending_calendar_ops.pop(chat_id, None)
        if op is None:
            await query.edit_message_text("⚠️ Keine ausstehende Aktion gefunden.")
            return
        try:
            if op["type"] == "create":
                await asyncio.to_thread(
                    calendar_agent.create_event,
                    op["title"],
                    op["start"],
                    op["end"],
                )
                msg = (
                    f"✅ Termin erstellt: *{op['title']}*\n"
                    f"{op['start'].strftime('%d.%m.%Y %H:%M')} – "
                    f"{op['end'].strftime('%H:%M')}"
                )
            elif op["type"] == "update":
                await asyncio.to_thread(
                    calendar_agent.update_event,
                    op["event_id"],
                    op["new_start"],
                    op["new_end"],
                    op["new_title"],
                    op["new_location"],
                )
                msg = f"✅ Termin geändert: *{op['title']}*"
            elif op["type"] == "delete":
                await asyncio.to_thread(
                    calendar_agent.delete_event, op["event_id"]
                )
                msg = f"✅ Termin abgesagt: *{op['title']}*"
            else:
                msg = "❌ Unbekannte Aktion."
            await query.edit_message_text(msg, parse_mode="Markdown")
        except Exception as e:
            logger.exception("cal:action:confirm fehlgeschlagen")
            await query.edit_message_text(f"❌ Aktion fehlgeschlagen: {e}")

    elif data == "cal:action:cancel":
        chat_id = query.message.chat_id
        _pending_calendar_ops.pop(chat_id, None)
        _last_calendar_search.pop(chat_id, None)
        await query.edit_message_text("❌ Abgebrochen.")

    elif data.startswith("cal:select:"):
        chat_id = query.message.chat_id
        entry = _last_calendar_search.get(chat_id)
        if entry is None or (time.time() - entry["timestamp"]) > 180:
            _last_calendar_search.pop(chat_id, None)
            await query.edit_message_text("⏱️ Auswahl abgelaufen — bitte nochmal.")
            return
        try:
            idx = int(data.split(":")[-1])
            events = entry["events"]
            if idx >= len(events):
                await query.edit_message_text("❌ Ungültige Auswahl.")
                return
        except (ValueError, IndexError):
            await query.edit_message_text("❌ Ungültige Auswahl.")
            return
        event = events[idx]
        mode = entry["mode"]
        params = entry["params"]
        _last_calendar_search.pop(chat_id, None)
        await query.edit_message_reply_markup(reply_markup=None)
        await _show_calendar_action_confirm(chat_id, event, mode, params)
```

- [ ] **Step 5: Dispatch-Block — `update`/`delete` an `handle_calendar_modify` routen**

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

mit:

```python
    if intent == "calendar":
        mode = params.get("mode", "read")
        if mode in ("update", "delete"):
            await handle_calendar_modify(chat_id, mode, params)
            _conv_complete(chat_id, f"Termin-Aktion ({mode}) angefragt")
            return
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

- [ ] **Step 6: Syntax-Check + komplette Suite**

Run:
```bash
PYTHONPATH=agents .venv/bin/python -m py_compile agents/main.py && \
PYTHONPATH=agents .venv/bin/pytest tests/ -q --tb=short \
  --ignore=tests/test_briefing_agent.py \
  --ignore=tests/test_mail_send.py \
  --ignore=tests/test_tasks_agent.py
```
Expected: keine Compile-Fehler; alle Tests grün. Danach `grep -n "cal:create" agents/main.py` — Erwartung: keine Treffer mehr.

- [ ] **Step 7: Commit**

```bash
git add agents/main.py
git commit -m "feat(calendar): Termine ändern & absagen — Modify-Flow + Callback-Vereinheitlichung

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: Doku — `CLAUDE.md` aktualisieren

**Files:**
- Modify: `CLAUDE.md`

> Hinweis: Es geht um die Projekt-`CLAUDE.md` in `herrlich-ai-platform/` (mit der Env-Var-Tabelle und „Agenten im Detail"). Sollte ein `old_string` nicht exakt matchen, den betreffenden Abschnitt vorher lesen und an den Ist-Stand anpassen.

- [ ] **Step 1: `calendar_agent.py`-Detailabschnitt erweitern**

Edit `CLAUDE.md` — ersetze:

```
### calendar_agent.py — CalendarAgent-Klasse
Outlook-Kalender via MS Graph (`httpx`). Auth über `microsoft_auth.get_access_token()`.

Lesen: `GET /me/calendarView` (Header `Prefer: outlook.timezone="Europe/Berlin"`) — expandiert Serien- und Multi-Day-Termine serverseitig. Schreiben: `POST /me/events`.
Es wird ausschließlich der Standard-Kalender (`/me/...`) genutzt — keine Kalender-Whitelist, kein `calendar_name`-Parameter.
```

mit:

```
### calendar_agent.py — CalendarAgent-Klasse
Outlook-Kalender via MS Graph (`httpx`). Auth über `microsoft_auth.get_access_token()`.

Lesen: `GET /me/calendarView` (Header `Prefer: outlook.timezone="Europe/Berlin"`) — expandiert Serien- und Multi-Day-Termine serverseitig. Anlegen: `POST /me/events` (`create_event`). Ändern: `PATCH /me/events/{id}` (`update_event`). Absagen: `DELETE /me/events/{id}` (`delete_event`). Termin-Suche: `search_events(query, start, end)` — Substring-Match auf den Titel.
Es wird ausschließlich der Standard-Kalender (`/me/...`) genutzt — keine Kalender-Whitelist, kein `calendar_name`-Parameter. Änderungen an Serienterminen betreffen nur das einzelne Vorkommen.
```

- [ ] **Step 2: Callbacks-Tabelle aktualisieren**

Edit `CLAUDE.md` — ersetze:

```
| `cal:create:confirm` | handle_callback | Pending Termin-Erstellung ausführen |
| `cal:create:cancel` | handle_callback | Pending Termin-Erstellung verwerfen |
```

mit:

```
| `cal:action:confirm` | handle_callback | Pending Kalender-Aktion (Erstellen/Ändern/Absagen) ausführen |
| `cal:action:cancel` | handle_callback | Pending Kalender-Aktion verwerfen |
| `cal:select:{n}` | handle_callback | Termin n aus Multi-Treffer-Liste wählen → Confirm |
```

- [ ] **Step 3: Pending-State-Abschnitt aktualisieren**

Edit `CLAUDE.md` — ersetze:

```
_pending_mail_ops: dict[int, dict]      # Mail-Write-Op wartet auf Confirm-Button
_pending_calendar_ops: dict[int, dict]  # Termin-Erstellung wartet auf Confirm-Button
_last_mail_search: dict[int, dict]      # Multi-Treffer-Auswahl (TTL: 3 Min, timestamp im Dict)
_recent_conv: dict[int, list]           # Letzte Konversations-Paare (user + assistant) pro chat_id für Router-Kontext
```

mit:

```
_pending_mail_ops: dict[int, dict]       # Mail-Write-Op wartet auf Confirm-Button
_pending_calendar_ops: dict[int, dict]   # Kalender-Aktion (create/update/delete) wartet auf Confirm-Button
_last_mail_search: dict[int, dict]       # Mail-Multi-Treffer-Auswahl (TTL: 3 Min, timestamp im Dict)
_last_calendar_search: dict[int, dict]   # Termin-Multi-Treffer-Auswahl (TTL: 3 Min, timestamp im Dict)
_recent_conv: dict[int, list]            # Letzte Konversations-Paare (user + assistant) pro chat_id für Router-Kontext
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: Kalender ändern/absagen in CLAUDE.md dokumentieren

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: Deploy & Verifikation

- [ ] **Step 1: Pushen — löst Auto-Deploy via GitHub-Webhook aus**

```bash
git push
```
Keine Re-Auth nötig — der Scope `Calendars.ReadWrite` (deckt PATCH/DELETE ab) wurde bereits bei der Outlook-Migration erteilt.

- [ ] **Step 2: Deploy prüfen** (falls Tailscale erreichbar)

```bash
ssh root@100.115.184.3 "cd /opt/herrlich-ai-platform && git log --oneline -1 && systemctl is-active jarvis"
```
Erwartet: jüngster Commit, Service `active`.

- [ ] **Step 3: Test-Termine anlegen**

In Telegram (@jarvis_herrlich_bot): zwei Wegwerf-Termine anlegen, z.B.
„Erstelle Termin Testtermin Alpha morgen 10 Uhr" und
„Erstelle Termin Testtermin Beta übermorgen 14 Uhr" — jeweils bestätigen.

- [ ] **Step 4: Verschieben testen**

„Verschiebe Testtermin Alpha auf 16 Uhr" → Confirm-Dialog mit Vorher→Nachher-Diff → ✅ Ändern → in Outlook prüfen, dass Alpha jetzt 16:00 ist und 1 h dauert (Dauer erhalten).

- [ ] **Step 5: Bearbeiten testen**

„Ändere den Ort von Testtermin Beta zu Büro" → Confirm zeigt die Ort-Änderung → ✅ Ändern → in Outlook prüfen.

- [ ] **Step 6: Mehrdeutigkeit testen**

„Sag den Testtermin ab" → da „Testtermin" auf Alpha **und** Beta passt, müssen Auswahl-Buttons erscheinen → einen wählen → Confirm → ✅ Absagen.

- [ ] **Step 7: Serientermin testen**

Einen echten wiederkehrenden Termin per Stichwort verschieben („Verschiebe das [Serientermin-Stichwort] am [Tag] auf [Zeit]") → der Confirm-Dialog muss „(nur dieser Termin — die Serie bleibt)" zeigen → bestätigen → in Outlook prüfen, dass nur dieses eine Vorkommen verschoben wurde und die Serie intakt ist.

- [ ] **Step 8: Aufräumen**

Den verbliebenen Test-Termin in Outlook löschen.

---

## Self-Review

**Spec-Coverage:**
- `Event.id` + `Event.recurring` + `_to_event` + `$select` → Task 1 ✅
- `search_events` (deterministischer Match) → Task 2 ✅
- `update_event` (PATCH, nur geänderte Felder, ValueError bei leer) → Task 2 ✅
- `delete_event` (DELETE) → Task 2 ✅
- Router: `update`/`delete`-Modes + Params (`query`, `search_start/end`, `new_*`) → Task 3 ✅
- `handle_calendar_modify` Find→Select→Confirm-Flow (0/1/2–5/>5) → Task 4 ✅
- Dauer-Erhalt bei `new_start` ohne `new_end` → Task 4, `_show_calendar_action_confirm` ✅
- Confirm-Dialoge Absagen/Ändern + Serientermin-Hinweis → Task 4 ✅
- Callback-Vereinheitlichung `cal:action:*` + `cal:select:{n}`, `type`-Feld → Task 4 ✅
- `_last_calendar_search` (TTL 3 Min) → Task 4 ✅
- Tests: `test_calendar_modify.py` neu, `test_calendar_read.py` erweitert → Tasks 1+2 ✅
- CLAUDE.md (calendar_agent, Callbacks, Pending-State) → Task 5 ✅

Keine Lücken.

**Placeholder-Scan:** Keine TBD/TODO; jeder Code-Step enthält vollständigen Code.

**Typ-Konsistenz:**
- `Event(id, title, start, end, location, calendar_name, source, all_day=False, recurring=False)` — in Task 1 definiert, `_to_event` setzt alle Felder per Keyword.
- `search_events(query, start, end) -> list[Event]`, `update_event(event_id, new_start=None, new_end=None, new_title=None, new_location=None)`, `delete_event(event_id)` — in Task 2 definiert, in Task 4 mit identischen Signaturen aufgerufen (`update_event` positional: `event_id, new_start, new_end, new_title, new_location`).
- `_pending_calendar_ops`-Einträge haben durchgängig ein `type`-Feld (`create`/`update`/`delete`) — gesetzt in `handle_calendar` (write) und `_show_calendar_action_confirm`, ausgewertet in `cal:action:confirm`.
- Callback-Strings `cal:action:confirm`/`cal:action:cancel`/`cal:select:{n}` — identisch in Erzeugung (`handle_calendar`, `handle_calendar_modify`, `_show_calendar_action_confirm`) und Auswertung (`handle_callback`).
- `_last_calendar_search`-Eintrag `{events, mode, params, timestamp}` — geschrieben in `handle_calendar_modify`, gelesen in `cal:select:`-Callback.
