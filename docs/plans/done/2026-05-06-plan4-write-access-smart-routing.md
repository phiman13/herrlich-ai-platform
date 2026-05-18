# Write Access + Smart Routing Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend Jarvis with calendar write access, mail compose+confirm flow, router context injection for calendar/mail names, and a confidence-based clarification fallback.

**Architecture:** Four independent improvements: (1) router gets real calendar + mail folder names injected into the system prompt for smarter routing; (2) low-confidence intents trigger a clarification request instead of guessing; (3) calendar write creates iCal events via CalDAV; (4) mail compose shows a draft with an Inline Keyboard confirm button before sending via MS Graph.

**Tech Stack:** Python 3.11, python-telegram-bot 20.x, icalendar library, caldav library, MS Graph REST API (requests), APScheduler, difflib

---

## File Map

| File | Change |
|------|--------|
| `agents/router.py` | Add `_get_calendar_names()`, `_get_mail_folder_names()`, extend prompt template with `{CALENDAR_NAMES}` + `{MAIL_FOLDERS}`, extend calendar intent to include `mode: read\|write`, extend mail intent to include `mode: compose` |
| `agents/calendar_agent.py` | Add `ICloudCalDAVBackend.create_event()`, `CalendarAgent.create_event()`, `CalendarAgent.get_calendar_names()` |
| `agents/mail_agent.py` | Add `MailAgent.send_mail(to_email, subject, body) -> bool` |
| `agents/main.py` | Add confidence fallback in `handle_message()`, calendar write branch in `handle_calendar()`, mail compose branch in `handle_mail()`, `_pending_mail_drafts` dict, callback handlers for `mail:send` / `mail:cancel` |
| `tests/test_router_context.py` | New: tests for `_get_calendar_names()`, `_get_mail_folder_names()`, confidence fallback logic |
| `tests/test_calendar_write.py` | New: tests for `create_event()` in both backend and agent |
| `tests/test_mail_send.py` | New: tests for `MailAgent.send_mail()` |

---

## Task 1: Router context — inject calendar names and mail folder names

**Files:**
- Modify: `agents/router.py`
- Create: `tests/test_router_context.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_router_context.py
import pytest
from unittest.mock import patch, MagicMock
import time


@pytest.mark.asyncio
async def test_get_calendar_names_reads_env():
    import importlib
    with patch.dict("os.environ", {"CALENDAR_WHITELIST": "Privat, Arbeit, Sport"}):
        import agents.router as router_mod
        importlib.reload(router_mod)
        names = await router_mod._get_calendar_names()
    assert "Privat" in names
    assert "Arbeit" in names
    assert "Sport" in names


@pytest.mark.asyncio
async def test_get_mail_folder_names_returns_cached():
    import agents.router as router_mod
    # Warm the cache
    router_mod._mail_folders_cache = (["Posteingang", "Steuern"], time.time())
    names = await router_mod._get_mail_folder_names()
    assert "Posteingang" in names
    assert "Steuern" in names


@pytest.mark.asyncio
async def test_build_system_prompt_includes_calendar_and_mail():
    import agents.router as router_mod
    with patch.dict("os.environ", {"CALENDAR_WHITELIST": "Privat"}):
        with patch.object(router_mod, "_get_project_list", return_value=["recipe-app"]), \
             patch.object(router_mod, "_get_todo_list_names", return_value=["Einkaufen"]), \
             patch.object(router_mod, "_get_calendar_names", return_value=["Privat"]), \
             patch.object(router_mod, "_get_mail_folder_names", return_value=["Steuern"]):
            prompt = await router_mod._build_system_prompt()
    assert "Privat" in prompt
    assert "Steuern" in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/philippherrlich/Documents/04_Sonstiges/01_Coding/herrlich-ai-platform && python -m pytest tests/test_router_context.py -v`
Expected: FAIL — `_get_calendar_names`, `_get_mail_folder_names` not defined

- [ ] **Step 3: Add `_get_calendar_names()` and `_get_mail_folder_names()` to `router.py`**

Add after `_todo_lists_cache` declaration (around line 24):

```python
# calendar names come directly from env — no network call needed
_calendar_names_cache: list[str] = []

# mail folder names cache: (value, fetched_at)
_mail_folders_cache: tuple[list[str], float] = ([], 0.0)
_MAIL_FOLDER_CACHE_TTL = 1800  # 30 min


async def _get_calendar_names() -> list[str]:
    global _calendar_names_cache
    if not _calendar_names_cache:
        import os as _os
        raw = _os.environ.get("CALENDAR_WHITELIST", "")
        _calendar_names_cache = [w.strip() for w in raw.split(",") if w.strip()]
    return _calendar_names_cache


async def _get_mail_folder_names() -> list[str]:
    global _mail_folders_cache
    names, fetched_at = _mail_folders_cache
    if names and (time.time() - fetched_at) < _MAIL_FOLDER_CACHE_TTL:
        return names
    try:
        def _fetch():
            try:
                from microsoft_auth import get_access_token
            except ImportError:
                from agents.microsoft_auth import get_access_token
            token = get_access_token()
            resp = httpx.get(
                "https://graph.microsoft.com/v1.0/me/mailFolders",
                headers={"Authorization": f"Bearer {token}"},
                params={"$top": 50, "$select": "displayName"},
                timeout=5,
            )
            resp.raise_for_status()
            return [f["displayName"] for f in resp.json().get("value", [])]
        names = await asyncio.to_thread(_fetch)
        _mail_folders_cache = (names, time.time())
    except Exception as e:
        logger.debug(f"Mail-Ordner nicht abrufbar: {e}")
    return names
```

- [ ] **Step 4: Extend `_build_system_prompt()` to gather all 4 context sources**

Replace the existing `_build_system_prompt` function:

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
        _SYSTEM_TEMPLATE
        .replace("{HEUTE_ISO}", heute)
        .replace("{PROJECT_LIST}", projects_str)
        .replace("{TODO_LISTS}", todo_str)
        .replace("{CALENDAR_NAMES}", calendar_str)
        .replace("{MAIL_FOLDERS}", mail_str)
    )
```

- [ ] **Step 5: Extend `_SYSTEM_TEMPLATE` — calendar intent gets write mode + mail intent gets compose mode**

In `_SYSTEM_TEMPLATE`, replace the calendar intent section (intent #1):

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

   WICHTIG: Heute ist {HEUTE_ISO}. Bei mode=read: Berechne start/end relativ zu diesem Datum.
   Bei mode=write: start MUSS gesetzt sein (ISO-8601). end=null bedeutet start+1h.
```

In `_SYSTEM_TEMPLATE`, extend the mail intent section (intent #5) to add compose mode:

```
5. "mail" — Anfragen zu Outlook-Mails. Verfügbare Ordner: {MAIL_FOLDERS}

   Beispiele:
   - "Was Wichtiges im Posteingang?" → quick_scan
   - "Ungelesene Mails" → unread
   - "Hat mir Anna geschrieben?" → search
   - "Welche Ordner gibt es?" → list_folders
   - "Schreibe eine Mail an anna@beispiel.de ..." → compose

   Parameter:
   - mode: "quick_scan" | "unread" | "search" | "list_folders" | "compose"
   - count: integer oder null
   - sender: string oder null
   - subject_contains: string oder null
   - since_iso: ISO-8601 datetime oder null
   - folder_name: string oder null (einer aus: {MAIL_FOLDERS})
   - to_email: string oder null (Empfänger, nur bei mode=compose)
   - subject: string oder null (Betreff, nur bei mode=compose)
   - body: string oder null (Mail-Text auf Deutsch, nur bei mode=compose)

   Mode-Bestimmung:
   - "Posteingang" / "Was Neues" → quick_scan
   - "Ungelesene" / "Was hab ich verpasst" → unread
   - "Hat mir X geschrieben" / "Mails von X" / "zum Thema Y" → search
   - "Welche Ordner" → list_folders
   - "Schreibe/Sende eine Mail" → compose (extrahiere to_email, subject, body aus dem Text)
```

Also add `"compose"` to the output-format intent list.

- [ ] **Step 6: Update VALID_INTENTS set in `route_with_llm`**

No change needed — the intent values don't change, only the params within them.

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest tests/test_router_context.py -v`
Expected: PASS all 3 tests

- [ ] **Step 8: Commit**

```bash
git add agents/router.py tests/test_router_context.py
git commit -m "feat(router): inject calendar and mail folder names into system prompt"
```

---

## Task 2: Confidence fallback — ask for clarification on low-confidence routing

**Files:**
- Modify: `agents/main.py`
- Modify: `tests/test_router_context.py` (add test)

- [ ] **Step 1: Write failing test**

Add to `tests/test_router_context.py`:

```python
@pytest.mark.asyncio
async def test_low_confidence_triggers_clarification():
    """handle_message sends clarification text when confidence < 5."""
    from unittest.mock import AsyncMock, patch, MagicMock

    low_confidence_result = {
        "intent": "personal",
        "confidence": 3,
        "params": {},
        "reasoning": "unsure",
    }

    fake_update = MagicMock()
    fake_update.update_id = 999
    fake_update.message.text = "bla bla foo"
    fake_update.message.chat_id = 12345
    fake_update.message.reply_text = AsyncMock()

    with patch("agents.main.route_with_llm", new_callable=AsyncMock, return_value=low_confidence_result), \
         patch("agents.main.processed_updates", new=set()):
        import agents.main as main_mod
        await main_mod.handle_message(fake_update, MagicMock())

    fake_update.message.reply_text.assert_called_once()
    call_text = fake_update.message.reply_text.call_args[0][0]
    assert "nicht sicher" in call_text.lower() or "präzisier" in call_text.lower() or "klär" in call_text.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_router_context.py::test_low_confidence_triggers_clarification -v`
Expected: FAIL — no clarification logic in handle_message yet

- [ ] **Step 3: Add confidence check to `handle_message()` in `main.py`**

After `intent = result["intent"]` and `params = result["params"]` (around line 313), add:

```python
    confidence = result.get("confidence", 10)
    if confidence < 5:
        await update.message.reply_text(
            "Ich bin mir nicht ganz sicher, was du meinst. "
            "Bitte präzisiere: Kalender, Mail, Task-Liste, Coding oder etwas anderes?"
        )
        return
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_router_context.py -v`
Expected: PASS all 4 tests

- [ ] **Step 5: Commit**

```bash
git add agents/main.py tests/test_router_context.py
git commit -m "feat(router): ask for clarification when routing confidence < 5"
```

---

## Task 3: Calendar write — create iCal events via CalDAV

**Files:**
- Modify: `agents/calendar_agent.py`
- Modify: `agents/main.py`
- Create: `tests/test_calendar_write.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_calendar_write.py
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime
from zoneinfo import ZoneInfo

BERLIN = ZoneInfo("Europe/Berlin")


def test_backend_create_event_calls_save():
    """ICloudCalDAVBackend.create_event() calls cal.save_event() on the right calendar."""
    from agents.calendar_agent import ICloudCalDAVBackend

    backend = ICloudCalDAVBackend("user@example.com", "pw", ["Privat", "Arbeit"])
    mock_cal_privat = MagicMock()
    mock_cal_privat.name = "Privat"
    mock_cal_arbeit = MagicMock()
    mock_cal_arbeit.name = "Arbeit"
    backend._calendars = [mock_cal_privat, mock_cal_arbeit]

    start = datetime(2026, 5, 10, 10, 0, tzinfo=BERLIN)
    end = datetime(2026, 5, 10, 11, 0, tzinfo=BERLIN)

    backend.create_event("Zahnarzt", start, end, calendar_name="Privat")

    mock_cal_privat.save_event.assert_called_once()
    ical_arg = mock_cal_privat.save_event.call_args[0][0]
    assert "Zahnarzt" in ical_arg
    assert "VEVENT" in ical_arg
    mock_cal_arbeit.save_event.assert_not_called()


def test_backend_create_event_defaults_to_first_calendar():
    """If calendar_name is None, use first whitelisted calendar."""
    from agents.calendar_agent import ICloudCalDAVBackend

    backend = ICloudCalDAVBackend("user@example.com", "pw", ["Privat"])
    mock_cal = MagicMock()
    mock_cal.name = "Privat"
    backend._calendars = [mock_cal]

    start = datetime(2026, 5, 10, 10, 0, tzinfo=BERLIN)
    end = datetime(2026, 5, 10, 11, 0, tzinfo=BERLIN)

    backend.create_event("Meeting", start, end, calendar_name=None)
    mock_cal.save_event.assert_called_once()


def test_agent_create_event_routes_to_backend():
    """CalendarAgent.create_event() delegates to ICloudCalDAVBackend."""
    from agents.calendar_agent import CalendarAgent, ICloudCalDAVBackend

    mock_backend = MagicMock(spec=ICloudCalDAVBackend)
    agent = CalendarAgent(backends=[mock_backend])

    start = datetime(2026, 5, 10, 10, 0, tzinfo=BERLIN)
    end = datetime(2026, 5, 10, 11, 0, tzinfo=BERLIN)

    agent.create_event("Besprechung", start, end, calendar_name="Arbeit")

    mock_backend.create_event.assert_called_once_with(
        "Besprechung", start, end, calendar_name="Arbeit"
    )


def test_agent_get_calendar_names_reads_env():
    from agents.calendar_agent import CalendarAgent
    with patch.dict("os.environ", {"CALENDAR_WHITELIST": "Privat, Arbeit"}):
        agent = CalendarAgent(backends=[])
        names = agent.get_calendar_names()
    assert "Privat" in names
    assert "Arbeit" in names
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_calendar_write.py -v`
Expected: FAIL — `create_event`, `get_calendar_names` not defined

- [ ] **Step 3: Add `create_event()` to `ICloudCalDAVBackend`**

Add after `fetch_events()` method in `ICloudCalDAVBackend` (after line 179):

```python
    def create_event(
        self,
        title: str,
        start_dt: datetime,
        end_dt: datetime,
        calendar_name: Optional[str] = None,
    ) -> None:
        """Create a new event in the specified calendar (or first whitelisted calendar)."""
        import uuid
        from icalendar import Calendar as ICalendar, Event as IEvent

        self._connect()
        if not self._calendars:
            raise RuntimeError("Keine Kalender verfügbar")

        target = None
        if calendar_name:
            for cal in self._calendars:
                if (cal.name or "").strip().lower() == calendar_name.lower():
                    target = cal
                    break
        if target is None:
            target = self._calendars[0]

        ical = ICalendar()
        ical.add("prodid", "-//Jarvis//EN")
        ical.add("version", "2.0")

        event = IEvent()
        event.add("summary", title)
        event.add("dtstart", start_dt)
        event.add("dtend", end_dt)
        event.add("uid", str(uuid.uuid4()))

        ical.add_component(event)
        target.save_event(ical.to_ical().decode("utf-8"))
        logger.info("Termin erstellt: '%s' in '%s' (%s)", title, target.name, start_dt.isoformat())
```

- [ ] **Step 4: Add `create_event()` and `get_calendar_names()` to `CalendarAgent`**

Add after `get_reminders_today()` in `CalendarAgent`:

```python
    def get_calendar_names(self) -> list[str]:
        """Return whitelisted calendar names from env."""
        raw = os.environ.get("CALENDAR_WHITELIST", "")
        return [w.strip() for w in raw.split(",") if w.strip()]

    def create_event(
        self,
        title: str,
        start_dt: datetime,
        end_dt: datetime,
        calendar_name: Optional[str] = None,
    ) -> None:
        """Create event on first available backend that supports it."""
        for backend in self.backends:
            if hasattr(backend, "create_event"):
                backend.create_event(title, start_dt, end_dt, calendar_name=calendar_name)
                return
        raise RuntimeError("Kein Backend mit create_event verfügbar")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_calendar_write.py -v`
Expected: PASS all 4 tests

- [ ] **Step 6: Add calendar write handler in `main.py`**

In `handle_calendar()`, change the function signature and add write branch:

```python
async def handle_calendar(chat_id, text, kind=None, start=None, end=None, mode="read", title=None, calendar_name=None):
    bot = Bot(token=TELEGRAM_TOKEN)

    if mode == "write":
        if not title or not start:
            await bot.send_message(chat_id=chat_id, text="Bitte Titel und Startzeit angeben.")
            return
        if end is None:
            end = start + timedelta(hours=1)
        try:
            await asyncio.to_thread(calendar_agent.create_event, title, start, end, calendar_name)
            cal_note = f" in '{calendar_name}'" if calendar_name else ""
            await bot.send_message(
                chat_id=chat_id,
                text=f"✅ Termin erstellt{cal_note}: *{title}*\n{start.strftime('%d.%m.%Y %H:%M')} – {end.strftime('%H:%M')}",
                parse_mode="Markdown",
            )
        except Exception as e:
            await bot.send_message(chat_id=chat_id, text=f"❌ Termin konnte nicht erstellt werden: {e}")
        return

    # Existing read logic below — unchanged
    if start is None or end is None:
        ...
```

In `handle_message()`, extend the calendar routing to pass write params:

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
            chat_id=chat_id, text=text, kind=kind, start=start, end=end,
            mode=mode, title=title, calendar_name=calendar_name,
        )
        return
```

- [ ] **Step 7: Verify `icalendar` is in requirements.txt**

Run: `grep icalendar /Users/philippherrlich/Documents/04_Sonstiges/01_Coding/herrlich-ai-platform/requirements.txt`

If not present, add it:
```
icalendar>=5.0
```

- [ ] **Step 8: Run full test suite**

Run: `python -m pytest tests/ -v --tb=short`
Expected: all previously passing tests still pass + 4 new calendar write tests pass

- [ ] **Step 9: Commit**

```bash
git add agents/calendar_agent.py agents/main.py tests/test_calendar_write.py requirements.txt
git commit -m "feat(calendar): add create_event() for CalDAV write access"
```

---

## Task 4: Mail compose with confirmation — draft preview + InlineKeyboard send/cancel

**Files:**
- Modify: `agents/mail_agent.py`
- Modify: `agents/main.py`
- Create: `tests/test_mail_send.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_mail_send.py
import pytest
from unittest.mock import patch, MagicMock


def test_send_mail_posts_to_graph():
    """MailAgent.send_mail() POSTs to /me/sendMail with correct payload."""
    from agents.mail_agent import MailAgent

    agent = MailAgent()

    mock_response = MagicMock()
    mock_response.status_code = 202
    mock_response.raise_for_status = MagicMock()

    with patch("agents.mail_agent.get_access_token", return_value="tok"), \
         patch("requests.post", return_value=mock_response) as mock_post:
        result = agent.send_mail(
            to_email="anna@beispiel.de",
            subject="Test",
            body="Hallo Anna, das ist ein Test.",
        )

    assert result is True
    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    payload = call_kwargs[1]["json"] if "json" in call_kwargs[1] else call_kwargs[0][1]
    assert payload["message"]["subject"] == "Test"
    assert payload["message"]["toRecipients"][0]["emailAddress"]["address"] == "anna@beispiel.de"
    assert "Hallo Anna" in payload["message"]["body"]["content"]


def test_send_mail_returns_false_on_error():
    """MailAgent.send_mail() returns False when Graph API returns error."""
    from agents.mail_agent import MailAgent
    import requests

    agent = MailAgent()

    mock_response = MagicMock()
    mock_response.status_code = 403
    mock_response.raise_for_status = MagicMock(side_effect=requests.HTTPError("403"))

    with patch("agents.mail_agent.get_access_token", return_value="tok"), \
         patch("requests.post", return_value=mock_response):
        result = agent.send_mail("anna@beispiel.de", "Test", "Body")

    assert result is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_mail_send.py -v`
Expected: FAIL — `send_mail` not defined, `get_access_token` import fails

- [ ] **Step 3: Add `send_mail()` to `MailAgent` in `mail_agent.py`**

Add `from microsoft_auth import get_access_token` to the top-level import section (outside the class, so it can be patched). Add at the top of the file after `import requests`:

```python
try:
    from microsoft_auth import get_access_token
except ImportError:
    from agents.microsoft_auth import get_access_token
```

Add `send_mail()` method to `MailAgent` class (after `search()`):

```python
    def send_mail(self, to_email: str, subject: str, body: str) -> bool:
        """Send mail via MS Graph POST /me/sendMail. Returns True on success."""
        payload = {
            "message": {
                "subject": subject,
                "body": {"contentType": "Text", "content": body},
                "toRecipients": [
                    {"emailAddress": {"address": to_email}}
                ],
            },
            "saveToSentItems": "true",
        }
        try:
            r = requests.post(
                f"{GRAPH_BASE}/me/sendMail",
                headers=self._get_headers(),
                json=payload,
                timeout=15,
            )
            r.raise_for_status()
            self.logger.info("Mail gesendet an %s", to_email)
            return True
        except Exception as e:
            self.logger.error("send_mail fehlgeschlagen: %s", e)
            return False
```

Note: `_get_headers()` already calls `get_access_token()` internally. The module-level import is for tests that need to patch it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_mail_send.py -v`
Expected: PASS both tests

- [ ] **Step 5: Add `_pending_mail_drafts` dict and compose handler in `main.py`**

After `processed_updates = set()` (around line 44), add:

```python
_pending_mail_drafts: dict[int, dict] = {}
```

In `handle_mail()`, add compose branch before the existing `try:` block:

```python
async def handle_mail(chat_id, text, params):
    bot = Bot(token=TELEGRAM_TOKEN)
    mode = params.get("mode", "quick_scan")

    if mode == "compose":
        to_email = params.get("to_email", "")
        subject = params.get("subject", "(kein Betreff)")
        body = params.get("body", "")

        if not to_email or "@" not in to_email:
            await bot.send_message(
                chat_id=chat_id,
                text="Empfänger-Adresse fehlt oder ungültig. Bitte nochmal mit vollständiger E-Mail-Adresse.",
            )
            return

        _pending_mail_drafts[chat_id] = {
            "to_email": to_email,
            "subject": subject,
            "body": body,
        }

        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        keyboard = [[
            InlineKeyboardButton("📤 Senden", callback_data="mail:send"),
            InlineKeyboardButton("❌ Abbrechen", callback_data="mail:cancel"),
        ]]

        preview = (
            f"📝 *Entwurf*\n\n"
            f"*An:* {to_email}\n"
            f"*Betreff:* {subject}\n\n"
            f"{body}"
        )
        await bot.send_message(
            chat_id=chat_id,
            text=preview,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    # Existing read-path logic unchanged below
    agent = MailAgent()
    ...
```

- [ ] **Step 6: Add callback handlers for `mail:send` and `mail:cancel` in `handle_callback()`**

Extend the existing `handle_callback()` function in `main.py`:

```python
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from vps import git_push
    from mail_agent import MailAgent
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    chat_id = query.message.chat_id

    if data.startswith("push:"):
        project = data[5:]
        await query.edit_message_reply_markup(reply_markup=None)
        success = await git_push(project)
        if success:
            await query.message.reply_text(f"✅ *{project}* gepusht.", parse_mode="Markdown")
        else:
            await query.message.reply_text(f"❌ Push fehlgeschlagen für {project}.")

    elif data == "dismiss":
        await query.edit_message_reply_markup(reply_markup=None)

    elif data == "mail:send":
        draft = _pending_mail_drafts.pop(chat_id, None)
        if draft is None:
            await query.edit_message_text("⚠️ Kein Entwurf mehr vorhanden.")
            return
        agent = MailAgent()
        success = await asyncio.to_thread(
            agent.send_mail, draft["to_email"], draft["subject"], draft["body"]
        )
        if success:
            await query.edit_message_text(
                f"✅ Mail gesendet an *{draft['to_email']}*.",
                parse_mode="Markdown",
            )
        else:
            await query.edit_message_text("❌ Mail konnte nicht gesendet werden.")

    elif data == "mail:cancel":
        _pending_mail_drafts.pop(chat_id, None)
        await query.edit_message_text("❌ Entwurf verworfen.")
```

- [ ] **Step 7: Update `handle_message()` to pass `mode` through to `handle_mail()` for compose**

The existing `handle_mail(chat_id=chat_id, text=text, params=params)` call already passes `params`, which contains `mode: "compose"`. No change needed here.

- [ ] **Step 8: Add `MailAgent` import at top of `main.py`**

Add to the imports at the top:

```python
from mail_agent import MailAgent
```

- [ ] **Step 9: Run full test suite**

Run: `python -m pytest tests/ -v --tb=short`
Expected: all tests pass

- [ ] **Step 10: Commit**

```bash
git add agents/mail_agent.py agents/main.py tests/test_mail_send.py
git commit -m "feat(mail): add send_mail() and compose+confirm flow with InlineKeyboard"
```

---

## Task 5: Deploy to VPS

**Files:** None (deployment only)

- [ ] **Step 1: Merge/push branch to main**

```bash
git checkout main
git merge --ff-only <feature-branch>
git push origin main
```

- [ ] **Step 2: Deploy on VPS**

```bash
ssh root@100.115.184.3 "cd /root/agents && git pull --ff-only && pip install -r /Users/philippherrlich/Documents/04_Sonstiges/01_Coding/herrlich-ai-platform/requirements.txt --quiet && systemctl restart jarvis"
```

- [ ] **Step 3: Verify service started**

```bash
ssh root@100.115.184.3 "journalctl -u jarvis --no-pager -n 30"
```

Expected: `Jarvis gestartet` without ImportError

- [ ] **Step 4: Smoke test — calendar write**

Send to @jarvis_herrlich_bot: `"Erstelle Termin 'Test Jarvis' morgen um 15 Uhr"`
Expected: `✅ Termin erstellt: *Test Jarvis*`

- [ ] **Step 5: Smoke test — mail compose**

Send to @jarvis_herrlich_bot: `"Schreib eine kurze Test-Mail an philipp.herrlich@googlemail.com, Betreff: Jarvis Test"`
Expected: Draft preview with 📤 Senden / ❌ Abbrechen buttons. Press Abbrechen.

- [ ] **Step 6: Smoke test — confidence fallback**

Send to @jarvis_herrlich_bot: `"xyz blabla qqq"` (nonsense)
Expected: clarification prompt asking to be more specific

---

## Self-Review

**Spec coverage:**
- Router calendar names ✅ Task 1
- Router mail folder names ✅ Task 1
- Confidence fallback ✅ Task 2
- Calendar write (CalDAV) ✅ Task 3
- Mail send_mail() ✅ Task 4
- Mail compose draft preview ✅ Task 4
- InlineKeyboard send/cancel ✅ Task 4

**No placeholders found.**

**Type consistency:**
- `create_event(title, start_dt, end_dt, calendar_name)` — consistent across backend and agent
- `send_mail(to_email, subject, body) -> bool` — consistent between implementation and tests
- `_pending_mail_drafts: dict[int, dict]` — keyed by `chat_id` (int) throughout
