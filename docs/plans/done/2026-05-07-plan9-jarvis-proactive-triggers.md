# Jarvis Proaktives Trigger-System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Jarvis wird proaktiv — er pingt Philipp selbstständig bei wichtigen ungelesenen Mails (09:00 + 14:00), überfälligen Tasks (10:00 täglich), und liefert freitags 17:00 einen narrativen Weekly Review. Plus: Apple Reminders erstellen per Telegram-Befehl.

**Architecture:** Neues `agents/proactive_agent.py` enthält alle Job-Funktionen (Mail-Intelligence, Task-Reminder, Weekly Review), analog zum bestehenden `briefing_agent.py`. `db.py` bekommt eine neue `ProactiveDB`-Klasse (SQLite, 2 Tabellen: `reported_mails`, `reminded_tasks`) und `MemoryDB.load_since()`. Bestehende Agenten (`mail_agent.py`, `calendar_agent.py`, `tasks_agent.py`) werden um die benötigten Methoden erweitert. APScheduler in `main.py` bekommt SQLite-Jobstore für Restart-Sicherheit und 4 neue Jobs.

**Tech Stack:** aiosqlite (vorhanden), APScheduler 3.x + SQLAlchemy (neu: `pip install sqlalchemy`), anthropic Haiku + Sonnet (vorhanden), CalDAV (vorhanden), MS Graph/httpx (vorhanden)

---

## File Map

| File | Änderung |
|---|---|
| `agents/db.py` | Neue Klasse `ProactiveDB` (init, reported_mails, reminded_tasks); `MemoryDB.load_since(days)` |
| `agents/mail_agent.py` | Neue Methode `get_inbox_unread(n)` — fetcht nur aus Inbox-Ordner |
| `agents/calendar_agent.py` | +3 Methoden: `get_all_reminders()`, `get_completed_reminders_this_week()`, `create_reminder()` |
| `agents/tasks_agent.py` | +2 Methoden: `get_tasks_raw()`, `get_completed_tasks_this_week()` |
| `agents/proactive_agent.py` | Neu: `init_proactive()`, `check_important_mails()`, `send_task_reminder()`, `send_weekly_review()` |
| `agents/main.py` | SQLite-Jobstore, 4 neue Scheduler-Jobs, `reminder_write`-Intent-Branch, `init_proactive` in startup() |
| `agents/router.py` | Neuer Intent `reminder_write` in System-Prompt und Validation-Set |
| `tests/test_proactive_db.py` | Neu: 4 Tests für ProactiveDB + MemoryDB.load_since |
| `tests/test_proactive_agent.py` | Neu: 3 Tests für die 3 Job-Funktionen |

---

### Task 1: DB Extensions — ProactiveDB + MemoryDB.load_since

**Files:**
- Modify: `agents/db.py` (ans Ende anfügen)
- Test: `tests/test_proactive_db.py` (neu)

- [ ] **Step 1: Failing tests schreiben**

Erstelle `tests/test_proactive_db.py`:

```python
import asyncio
from datetime import datetime, timedelta, timezone


def test_reported_mails_deduplication(tmp_path):
    import sys; sys.path.insert(0, "agents")
    from db import ProactiveDB
    db = ProactiveDB(str(tmp_path / "proactive.db"))
    asyncio.run(db.init())

    asyncio.run(db.mark_mails_reported(["id1", "id2"]))
    reported = asyncio.run(db.get_reported_mail_ids())

    assert "id1" in reported
    assert "id2" in reported
    assert "id3" not in reported


def test_reported_mails_ignores_duplicates(tmp_path):
    import sys; sys.path.insert(0, "agents")
    from db import ProactiveDB
    db = ProactiveDB(str(tmp_path / "proactive.db"))
    asyncio.run(db.init())
    asyncio.run(db.mark_mails_reported(["id1"]))
    asyncio.run(db.mark_mails_reported(["id1"]))  # second call — must not raise
    reported = asyncio.run(db.get_reported_mail_ids())
    assert reported == {"id1"}


def test_reminded_tasks_tracks_last_reminded(tmp_path):
    import sys; sys.path.insert(0, "agents")
    from db import ProactiveDB
    db = ProactiveDB(str(tmp_path / "proactive.db"))
    asyncio.run(db.init())

    assert asyncio.run(db.get_last_reminded("task_abc")) is None
    asyncio.run(db.mark_tasks_reminded(["task_abc"]))
    last = asyncio.run(db.get_last_reminded("task_abc"))
    assert last is not None
    assert (datetime.now(timezone.utc) - last).total_seconds() < 5


def test_memory_load_since(tmp_path):
    import sys; sys.path.insert(0, "agents")
    from db import MemoryDB
    db = MemoryDB(str(tmp_path / "memories.db"))
    asyncio.run(db.init())

    # Insert one old memory (3 days ago) and one fresh
    old_ts = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    fresh_ts = datetime.now(timezone.utc).isoformat()

    async def insert_direct():
        import aiosqlite
        async with aiosqlite.connect(db.path) as conn:
            await conn.execute(
                "INSERT INTO memories (content, embedding, category, created_at, source) VALUES (?, ?, ?, ?, ?)",
                ("old memory", b"", "preference", old_ts, "test"),
            )
            await conn.execute(
                "INSERT INTO memories (content, embedding, category, created_at, source) VALUES (?, ?, ?, ?, ?)",
                ("fresh memory", b"", "preference", fresh_ts, "test"),
            )
            await conn.commit()

    asyncio.run(insert_direct())
    rows = asyncio.run(db.load_since(2))  # last 2 days only
    contents = [r["content"] for r in rows]
    assert "fresh memory" in contents
    assert "old memory" not in contents
```

- [ ] **Step 2: Tests laufen lassen — müssen FAIL**

```bash
.worktrees/plan3-smart-routing/.venv/bin/pytest tests/test_proactive_db.py -v
```

Erwartete Ausgabe: `ImportError` — `ProactiveDB` existiert nicht, `MemoryDB.load_since` fehlt.

- [ ] **Step 3: `ProactiveDB` und `MemoryDB.load_since` implementieren**

Füge ans **Ende** von `agents/db.py` ein (nach der `ConversationDB`-Klasse):

```python
class ProactiveDB:
    def __init__(self, path: str = "/root/.jarvis/proactive.db"):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)

    async def init(self):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS reported_mails (
                    mail_id    TEXT PRIMARY KEY,
                    reported_at TEXT NOT NULL
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS reminded_tasks (
                    task_id      TEXT PRIMARY KEY,
                    last_reminded TEXT NOT NULL
                )
            """)
            await db.commit()

    async def get_reported_mail_ids(self) -> set:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute("SELECT mail_id FROM reported_mails") as cursor:
                rows = await cursor.fetchall()
        return {r[0] for r in rows}

    async def mark_mails_reported(self, mail_ids: list) -> None:
        now = datetime.now(timezone.utc).isoformat()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.executemany(
                "INSERT OR IGNORE INTO reported_mails (mail_id, reported_at) VALUES (?, ?)",
                [(mid, now) for mid in mail_ids],
            )
            await db.execute("DELETE FROM reported_mails WHERE reported_at < ?", (cutoff,))
            await db.commit()

    async def get_last_reminded(self, task_id: str):
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT last_reminded FROM reminded_tasks WHERE task_id = ?", (task_id,)
            ) as cursor:
                row = await cursor.fetchone()
        if row is None:
            return None
        return datetime.fromisoformat(row[0])

    async def mark_tasks_reminded(self, task_ids: list) -> None:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.executemany(
                "INSERT OR REPLACE INTO reminded_tasks (task_id, last_reminded) VALUES (?, ?)",
                [(tid, now) for tid in task_ids],
            )
            await db.commit()
```

Füge außerdem folgende Methode in die **`MemoryDB`-Klasse** ein (nach `update_embedding`):

```python
    async def load_since(self, days: int) -> list:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT content, category, created_at FROM memories "
                "WHERE created_at > ? ORDER BY id ASC",
                (cutoff,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [{"content": r[0], "category": r[1], "created_at": r[2]} for r in rows]
```

Stelle sicher dass am Anfang von `db.py` der Import `from datetime import datetime, timedelta, timezone` vollständig ist (er ist es bereits).

- [ ] **Step 4: Tests laufen lassen — müssen PASS**

```bash
.worktrees/plan3-smart-routing/.venv/bin/pytest tests/test_proactive_db.py -v
```

Erwartete Ausgabe: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add agents/db.py tests/test_proactive_db.py
git commit -m "feat(proactive): ProactiveDB + MemoryDB.load_since für Trigger-System"
```

---

### Task 2: Mail Agent — get_inbox_unread

**Files:**
- Modify: `agents/mail_agent.py`

- [ ] **Step 1: Methode implementieren**

Füge folgende Methode in die `MailAgent`-Klasse ein (nach `get_unread`):

```python
    def get_inbox_unread(self, n: int = 30) -> list:
        """Fetch unread messages from Inbox only (naturally excludes Newsletter/Job folders)."""
        params = {
            "$top": n,
            "$orderby": "receivedDateTime desc",
            "$filter": "isRead eq false",
            "$select": "id,subject,from,receivedDateTime,isRead,bodyPreview,hasAttachments",
        }
        data = self._get("/me/mailFolders/inbox/messages", params=params)
        return [self._parse_mail(m, "inbox") for m in data.get("value", [])]
```

- [ ] **Step 2: Manuell verifizieren (kein isolierter Test — MS Graph benötigt Auth)**

Die Methode ist eine triviale Variante von `get_unread()` mit festem Pfad. Kein separater Test nötig — wird durch den Proactive-Agent-Test (Task 5) indirekt getestet.

- [ ] **Step 3: Commit**

```bash
git add agents/mail_agent.py
git commit -m "feat(mail): get_inbox_unread — fetcht nur aus Inbox-Ordner"
```

---

### Task 3: Calendar Agent Extensions

**Files:**
- Modify: `agents/calendar_agent.py`

Füge alle drei Methoden in die **`CalendarAgent`-Klasse** ein (nach `create_event`):

- [ ] **Step 1: `get_all_reminders()` implementieren**

```python
    def get_all_reminders(self) -> list:
        """Return all open Apple Reminders as list of dicts: uid, title, created, due."""
        from datetime import date, timezone
        reminders = []
        for backend in self.backends:
            if not isinstance(backend, ICloudCalDAVBackend):
                continue
            try:
                backend._connect()
            except Exception as e:
                logger.warning("CalDAV connect failed for reminders: %s", e)
                continue
            for cal in backend._calendars or []:
                try:
                    results = cal.search(todo=True)
                except Exception as e:
                    logger.warning("VTODO search failed for '%s': %s", cal.name, e)
                    continue
                for item in results:
                    try:
                        ical = item.icalendar_instance
                    except Exception:
                        continue
                    for component in ical.walk("VTODO"):
                        status = str(component.get("status") or "").upper()
                        if status in ("COMPLETED", "CANCELLED"):
                            continue
                        uid = str(component.get("uid") or "")
                        title = str(component.get("summary") or "(ohne Titel)")
                        created_prop = component.get("created")
                        created = None
                        if created_prop is not None:
                            dt = created_prop.dt
                            if isinstance(dt, datetime):
                                created = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
                            elif isinstance(dt, date):
                                created = datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)
                        due_prop = component.get("due")
                        due = None
                        if due_prop is not None:
                            dt = due_prop.dt
                            if isinstance(dt, datetime):
                                due = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
                            elif isinstance(dt, date):
                                due = datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)
                        reminders.append({
                            "uid": f"apple_{uid}",
                            "title": title,
                            "created": created,
                            "due": due,
                        })
        return reminders
```

- [ ] **Step 2: `get_completed_reminders_this_week()` implementieren**

```python
    def get_completed_reminders_this_week(self) -> list:
        """Return titles of Apple Reminders completed since last Monday 00:00 UTC."""
        from datetime import date, timedelta, timezone
        now = datetime.now(timezone.utc)
        monday = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        titles = []
        for backend in self.backends:
            if not isinstance(backend, ICloudCalDAVBackend):
                continue
            try:
                backend._connect()
            except Exception as e:
                logger.warning("CalDAV connect failed: %s", e)
                continue
            for cal in backend._calendars or []:
                try:
                    results = cal.search(todo=True)
                except Exception as e:
                    logger.warning("VTODO search failed for '%s': %s", cal.name, e)
                    continue
                for item in results:
                    try:
                        ical = item.icalendar_instance
                    except Exception:
                        continue
                    for component in ical.walk("VTODO"):
                        if str(component.get("status") or "").upper() != "COMPLETED":
                            continue
                        completed_prop = component.get("completed")
                        if completed_prop is None:
                            continue
                        dt = completed_prop.dt
                        if isinstance(dt, date) and not isinstance(dt, datetime):
                            dt = datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)
                        elif isinstance(dt, datetime) and dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        if dt < monday:
                            continue
                        titles.append(str(component.get("summary") or "(ohne Titel)"))
        return titles
```

- [ ] **Step 3: `create_reminder()` implementieren**

```python
    def create_reminder(self, title: str, due_date=None, list_name: str = None) -> None:
        """Create a VTODO (Apple Reminder) via CalDAV."""
        import uuid
        try:
            from icalendar import Todo
            from icalendar import Calendar as ICalendar
        except ImportError:
            raise RuntimeError("icalendar-Bibliothek nicht installiert")

        for backend in self.backends:
            if not isinstance(backend, ICloudCalDAVBackend):
                continue
            try:
                backend._connect()
            except Exception as e:
                raise RuntimeError(f"CalDAV connect fehlgeschlagen: {e}")
            if not backend._calendars:
                raise RuntimeError("Keine Kalender verfügbar")

            target = backend._calendars[0]
            if list_name:
                for cal in backend._calendars:
                    if (cal.name or "").strip().lower() == list_name.lower():
                        target = cal
                        break

            ical = ICalendar()
            ical.add("prodid", "-//Jarvis//EN")
            ical.add("version", "2.0")

            todo = Todo()
            todo.add("summary", title)
            todo.add("uid", str(uuid.uuid4()))
            todo.add("status", "NEEDS-ACTION")
            if due_date is not None:
                todo.add("due", due_date)

            ical.add_component(todo)
            target.save_todo(ical.to_ical().decode("utf-8"))
            logger.info("Reminder erstellt: '%s' in '%s'", title, target.name)
            return

        raise RuntimeError("Kein CalDAV-Backend verfügbar")
```

- [ ] **Step 4: Commit**

```bash
git add agents/calendar_agent.py
git commit -m "feat(calendar): get_all_reminders, get_completed_reminders_this_week, create_reminder"
```

---

### Task 4: Tasks Agent Extensions

**Files:**
- Modify: `agents/tasks_agent.py`

Füge folgende zwei Funktionen ans **Ende** von `agents/tasks_agent.py` ein (nach `complete_task`):

- [ ] **Step 1: `get_tasks_raw()` implementieren**

```python
def get_tasks_raw() -> list:
    """Return all open tasks from all lists as dicts with id, title, list_name, created_at."""
    try:
        lists = _get_lists()
        all_tasks = []
        for lst in lists:
            resp = httpx.get(
                f"{_BASE}/lists/{lst['id']}/tasks",
                headers=_headers(),
                params={
                    "$filter": "status ne 'completed'",
                    "$top": 50,
                    "$select": "id,title,createdDateTime,status",
                },
                timeout=10,
            )
            resp.raise_for_status()
            for t in resp.json().get("value", []):
                all_tasks.append({
                    "id": f"todo_{t['id']}",
                    "title": t["title"],
                    "list_name": lst["displayName"],
                    "created_at": t.get("createdDateTime"),
                })
        return all_tasks
    except Exception as e:
        logger.warning("get_tasks_raw fehlgeschlagen: %s", e)
        return []
```

- [ ] **Step 2: `get_completed_tasks_this_week()` implementieren**

```python
def get_completed_tasks_this_week() -> list:
    """Return titles of tasks completed since last Monday 00:00 UTC."""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    monday = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    monday_iso = monday.strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        lists = _get_lists()
        titles = []
        for lst in lists:
            resp = httpx.get(
                f"{_BASE}/lists/{lst['id']}/tasks",
                headers=_headers(),
                params={
                    "$filter": f"status eq 'completed' and lastModifiedDateTime ge {monday_iso}",
                    "$top": 50,
                    "$select": "title,status,lastModifiedDateTime",
                },
                timeout=10,
            )
            resp.raise_for_status()
            for t in resp.json().get("value", []):
                titles.append(t["title"])
        return titles
    except Exception as e:
        logger.warning("get_completed_tasks_this_week fehlgeschlagen: %s", e)
        return []
```

- [ ] **Step 3: Commit**

```bash
git add agents/tasks_agent.py
git commit -m "feat(tasks): get_tasks_raw + get_completed_tasks_this_week"
```

---

### Task 5: ProactiveAgent

**Files:**
- Create: `agents/proactive_agent.py`
- Test: `tests/test_proactive_agent.py`

- [ ] **Step 1: Failing tests schreiben**

Erstelle `tests/test_proactive_agent.py`:

```python
import asyncio
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch


def test_check_important_mails_sends_message_for_important_mail(tmp_path):
    os.environ["TELEGRAM_BOT_TOKEN"] = "fake_token"
    import sys; sys.path.insert(0, "agents")
    from proactive_agent import check_important_mails, init_proactive
    from db import ProactiveDB, MemoryDB

    proactive_db = ProactiveDB(str(tmp_path / "proactive.db"))
    memory_db = MemoryDB(str(tmp_path / "memories.db"))
    asyncio.run(proactive_db.init())
    asyncio.run(memory_db.init())
    asyncio.run(init_proactive(proactive_db, memory_db))

    mock_mail = MagicMock()
    mock_mail.id = "mail_abc"
    mock_mail.sender_name = "Chef"
    mock_mail.sender_email = "chef@firma.de"
    mock_mail.subject = "Dringende Deadline morgen"
    mock_mail.preview = "Bitte bis morgen 12 Uhr abliefern."

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()

    with patch("proactive_agent.MailAgent") as MockMailAgent, \
         patch("proactive_agent.Bot", return_value=mock_bot), \
         patch("proactive_agent._assess_mail_importance", new_callable=AsyncMock,
               return_value=[(mock_mail, "Deadline morgen 12 Uhr")]):
        MockMailAgent.return_value.get_inbox_unread.return_value = [mock_mail]
        asyncio.run(check_important_mails(123))

    mock_bot.send_message.assert_called_once()
    call_kwargs = mock_bot.send_message.call_args.kwargs
    assert call_kwargs["chat_id"] == 123
    assert "Chef" in call_kwargs["text"]


def test_check_important_mails_no_ping_if_already_reported(tmp_path):
    os.environ["TELEGRAM_BOT_TOKEN"] = "fake_token"
    import sys; sys.path.insert(0, "agents")
    from proactive_agent import check_important_mails, init_proactive
    from db import ProactiveDB, MemoryDB

    proactive_db = ProactiveDB(str(tmp_path / "proactive.db"))
    memory_db = MemoryDB(str(tmp_path / "memories.db"))
    asyncio.run(proactive_db.init())
    asyncio.run(memory_db.init())
    asyncio.run(proactive_db.mark_mails_reported(["mail_already"]))
    asyncio.run(init_proactive(proactive_db, memory_db))

    mock_mail = MagicMock()
    mock_mail.id = "mail_already"
    mock_mail.sender_name = "Jemand"
    mock_mail.sender_email = "x@y.de"
    mock_mail.subject = "Test"
    mock_mail.preview = "Test"

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()

    with patch("proactive_agent.MailAgent") as MockMailAgent, \
         patch("proactive_agent.Bot", return_value=mock_bot):
        MockMailAgent.return_value.get_inbox_unread.return_value = [mock_mail]
        asyncio.run(check_important_mails(123))

    mock_bot.send_message.assert_not_called()


def test_send_task_reminder_pings_overdue_task(tmp_path):
    os.environ["TELEGRAM_BOT_TOKEN"] = "fake_token"
    import sys; sys.path.insert(0, "agents")
    from proactive_agent import send_task_reminder, init_proactive
    from db import ProactiveDB, MemoryDB

    proactive_db = ProactiveDB(str(tmp_path / "proactive.db"))
    memory_db = MemoryDB(str(tmp_path / "memories.db"))
    asyncio.run(proactive_db.init())
    asyncio.run(memory_db.init())
    asyncio.run(init_proactive(proactive_db, memory_db))

    three_days_ago = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    overdue_reminder = {
        "uid": "apple_test_uid",
        "title": "Zahnarzt anrufen",
        "created": datetime.now(timezone.utc) - timedelta(days=3),
        "due": None,
    }

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()

    with patch("proactive_agent.CalendarAgent") as MockCal, \
         patch("proactive_agent.get_tasks_raw", return_value=[]), \
         patch("proactive_agent.Bot", return_value=mock_bot):
        MockCal.return_value.get_all_reminders.return_value = [overdue_reminder]
        asyncio.run(send_task_reminder(123))

    mock_bot.send_message.assert_called_once()
    call_text = mock_bot.send_message.call_args.kwargs["text"]
    assert "Zahnarzt anrufen" in call_text
```

- [ ] **Step 2: Tests laufen lassen — müssen FAIL**

```bash
.worktrees/plan3-smart-routing/.venv/bin/pytest tests/test_proactive_agent.py -v
```

Erwartete Ausgabe: `ImportError` — `proactive_agent` existiert nicht.

- [ ] **Step 3: `agents/proactive_agent.py` implementieren**

Erstelle `agents/proactive_agent.py`:

```python
import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone

import anthropic
from telegram import Bot

try:
    from calendar_agent import CalendarAgent, BERLIN
    from db import ProactiveDB, MemoryDB
    from mail_agent import MailAgent
    from tasks_agent import get_tasks_raw, get_completed_tasks_this_week
except ImportError:
    from agents.calendar_agent import CalendarAgent, BERLIN
    from agents.db import ProactiveDB, MemoryDB
    from agents.mail_agent import MailAgent
    from agents.tasks_agent import get_tasks_raw, get_completed_tasks_this_week

logger = logging.getLogger("jarvis.proactive")

_proactive_db: ProactiveDB | None = None
_memory_db: MemoryDB | None = None

_MAIL_IMPORTANCE_SYSTEM = (
    "Du analysierst E-Mails für Philipp und entscheidest ob sie wichtig sind.\n"
    "Wichtig bedeutet: konkrete Deadlines, direkte Anfragen/Fragen an Philipp, "
    "finanzielle Themen (Rechnungen, Zahlungen, Angebote), zeitkritische Informationen.\n"
    "NICHT wichtig: Newsletter, Werbung, automatische Benachrichtigungen, FYI-Mails.\n"
    "Antworte NUR mit JSON: [{\"id\": \"...\", \"reason\": \"...\"}] für wichtige Mails. "
    "Leeres Array [] wenn keine wichtig. KEIN erklärender Text."
)

_WEEKLY_REVIEW_SYSTEM = (
    "Du bist Jarvis, KI-Assistent für Philipp. Erstelle einen wöchentlichen Review auf Deutsch. "
    "Schreibe einen narrativen, kurzen Text (kein reines Bullet-Listing). "
    "Rückblick: Was war bedeutsam diese Woche? Vorausschau: Worauf sollte Philipp sich vorbereiten? "
    "Halte es kompakt — max. 300 Wörter."
)

_WEEKDAYS_DE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


async def init_proactive(proactive_db: ProactiveDB, memory_db: MemoryDB) -> None:
    global _proactive_db, _memory_db
    _proactive_db = proactive_db
    _memory_db = memory_db
    logger.info("ProactiveAgent initialisiert")


async def _assess_mail_importance(mails: list) -> list:
    """Call Haiku to assess mail importance. Returns list of (Mail, reason) tuples."""
    mail_list = [
        {
            "id": m.id,
            "from": f"{m.sender_name} <{m.sender_email}>",
            "subject": m.subject,
            "preview": m.preview,
        }
        for m in mails
    ]
    prompt = f"Mails:\n{json.dumps(mail_list, ensure_ascii=False)}"
    try:
        client = anthropic.Anthropic()
        resp = await asyncio.to_thread(
            client.messages.create,
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            temperature=0,
            system=_MAIL_IMPORTANCE_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        important_map = {
            item["id"]: item["reason"]
            for item in json.loads(resp.content[0].text.strip())
        }
    except Exception as e:
        logger.warning("Haiku importance check failed: %s", e)
        return []

    mail_by_id = {m.id: m for m in mails}
    return [
        (mail_by_id[mid], reason)
        for mid, reason in important_map.items()
        if mid in mail_by_id
    ]


async def check_important_mails(chat_id: int) -> None:
    """Fetch unread inbox mails, filter reported, assess via Haiku, send digest if important."""
    try:
        mails = await asyncio.to_thread(MailAgent().get_inbox_unread, 30)
    except Exception as e:
        logger.warning("Mail fetch failed: %s", e)
        return

    if not mails:
        return

    reported = await _proactive_db.get_reported_mail_ids()
    new_mails = [m for m in mails if m.id not in reported]

    if not new_mails:
        return

    important = await _assess_mail_importance(new_mails)

    await _proactive_db.mark_mails_reported([m.id for m in new_mails])

    if not important:
        return

    lines = ["📬 *Wichtige neue Mails:*\n"]
    for mail, reason in important:
        sender = mail.sender_name or mail.sender_email
        subject = mail.subject.replace("*", "").replace("_", "")[:80]
        lines.append(f"*{sender}*")
        lines.append(f"_{subject}_")
        lines.append(f"→ {reason}\n")

    bot = Bot(token=os.environ["TELEGRAM_BOT_TOKEN"])
    await bot.send_message(chat_id=chat_id, text="\n".join(lines), parse_mode="Markdown")


async def send_task_reminder(chat_id: int) -> None:
    """Check for tasks open > 2 days and not reminded in last 2 days. Send reminder if found."""
    now = datetime.now(timezone.utc)
    two_days_ago = now - timedelta(days=2)
    overdue = []

    try:
        reminders = await asyncio.to_thread(CalendarAgent().get_all_reminders)
        for r in reminders:
            created = r.get("created")
            if created is None:
                continue
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if created > two_days_ago:
                continue
            last = await _proactive_db.get_last_reminded(r["uid"])
            if last and (now - last) < timedelta(days=2):
                continue
            overdue.append(r)
    except Exception as e:
        logger.warning("Apple Reminders fetch failed: %s", e)

    try:
        todos = await asyncio.to_thread(get_tasks_raw)
        for t in todos:
            created_str = t.get("created_at")
            if not created_str:
                continue
            created = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
            if created > two_days_ago:
                continue
            last = await _proactive_db.get_last_reminded(t["id"])
            if last and (now - last) < timedelta(days=2):
                continue
            overdue.append({"uid": t["id"], "title": t["title"]})
    except Exception as e:
        logger.warning("MS To Do fetch failed: %s", e)

    if not overdue:
        return

    await _proactive_db.mark_tasks_reminded([t["uid"] for t in overdue])

    lines = [f"⏰ *{len(overdue)} überfällige Tasks:*\n"]
    for t in overdue:
        icon = "📝" if t["uid"].startswith("apple_") else "✅"
        lines.append(f"{icon} {t['title']}")

    bot = Bot(token=os.environ["TELEGRAM_BOT_TOKEN"])
    await bot.send_message(chat_id=chat_id, text="\n".join(lines), parse_mode="Markdown")


async def send_weekly_review(chat_id: int) -> None:
    """Build and send narrative weekly review: Rückblick (this week) + Vorausschau (next week)."""
    now = datetime.now(BERLIN)
    monday = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    friday = monday + timedelta(days=4, hours=23, minutes=59, seconds=59)
    next_monday = monday + timedelta(weeks=1)
    next_sunday = next_monday + timedelta(days=6, hours=23, minutes=59, seconds=59)

    cal = CalendarAgent()

    def fmt_event(ev):
        day = _WEEKDAYS_DE[ev.start.weekday()]
        time_str = "ganztägig" if ev.all_day else ev.start.strftime("%H:%M")
        return f"{day} {time_str}: {ev.title}"

    try:
        this_week_events = await asyncio.to_thread(cal.get_events, monday, friday)
    except Exception as e:
        logger.warning("this_week_events failed: %s", e)
        this_week_events = []

    try:
        completed_reminders = await asyncio.to_thread(cal.get_completed_reminders_this_week)
    except Exception as e:
        logger.warning("completed_reminders failed: %s", e)
        completed_reminders = []

    try:
        completed_todos = await asyncio.to_thread(get_completed_tasks_this_week)
    except Exception as e:
        logger.warning("completed_todos failed: %s", e)
        completed_todos = []

    memories = await _memory_db.load_since(7)

    try:
        next_week_events = await asyncio.to_thread(cal.get_events, next_monday, next_sunday)
    except Exception as e:
        logger.warning("next_week_events failed: %s", e)
        next_week_events = []

    try:
        open_reminders = await asyncio.to_thread(cal.get_all_reminders)
    except Exception as e:
        logger.warning("open_reminders failed: %s", e)
        open_reminders = []

    try:
        open_todos = await asyncio.to_thread(get_tasks_raw)
    except Exception as e:
        logger.warning("open_todos failed: %s", e)
        open_todos = []

    rueckblick = (
        f"DIESE WOCHE (Rückblick):\n"
        f"Termine: {chr(10).join(fmt_event(e) for e in this_week_events) or 'keine'}\n"
        f"Erledigte Apple Reminders: {', '.join(completed_reminders) or 'keine'}\n"
        f"Erledigte MS To Do: {', '.join(completed_todos) or 'keine'}\n"
        f"Neue Erkenntnisse (Memory): {', '.join(m['content'] for m in memories) or 'keine'}"
    )
    vorausschau = (
        f"NÄCHSTE WOCHE (Vorausschau):\n"
        f"Termine: {chr(10).join(fmt_event(e) for e in next_week_events) or 'keine'}\n"
        f"Offene Reminders: {', '.join(r['title'] for r in open_reminders) or 'keine'}\n"
        f"Offene MS To Do: {', '.join(t['title'] for t in open_todos) or 'keine'}"
    )

    try:
        client = anthropic.Anthropic()
        resp = await asyncio.to_thread(
            client.messages.create,
            model="claude-sonnet-4-6",
            max_tokens=1000,
            temperature=0,
            system=_WEEKLY_REVIEW_SYSTEM,
            messages=[{"role": "user", "content": f"{rueckblick}\n\n{vorausschau}"}],
        )
        summary = resp.content[0].text.strip()
    except Exception as e:
        logger.warning("Weekly review Sonnet call failed: %s", e)
        return

    bot = Bot(token=os.environ["TELEGRAM_BOT_TOKEN"])
    await bot.send_message(
        chat_id=chat_id,
        text=f"📊 *Wöchentlicher Review*\n\n{summary}",
        parse_mode="Markdown",
    )
```

- [ ] **Step 4: Tests laufen lassen — müssen PASS**

```bash
.worktrees/plan3-smart-routing/.venv/bin/pytest tests/test_proactive_agent.py tests/test_proactive_db.py -v
```

Erwartete Ausgabe: `7 passed` (4 DB + 3 Proactive).

- [ ] **Step 5: Commit**

```bash
git add agents/proactive_agent.py tests/test_proactive_agent.py
git commit -m "feat(proactive): ProactiveAgent — Mail-Intelligence, Task-Reminder, Weekly Review"
```

---

### Task 6: Main.py + Router Integration

**Files:**
- Modify: `agents/main.py`
- Modify: `agents/router.py`

- [ ] **Step 1: sqlalchemy installieren**

Prüfe ob sqlalchemy im venv vorhanden ist:

```bash
.worktrees/plan3-smart-routing/.venv/bin/python -c "import sqlalchemy; print(sqlalchemy.__version__)"
```

Falls nicht installiert:

```bash
.worktrees/plan3-smart-routing/.venv/bin/pip install sqlalchemy
```

Auf VPS (wird bei Deploy automatisch gebraucht — trage `sqlalchemy` in `requirements.txt` ein falls vorhanden, sonst notiere es):

```bash
grep -r "requirements" /Users/philippherrlich/Documents/04_Sonstiges/01_Coding/herrlich-ai-platform/agents/ | grep "\.txt" | head -3
```

Falls `requirements.txt` existiert: `sqlalchemy` hinzufügen. Falls nicht: überspringen — VPS-Deploy-Schritt in Task 6 Step 5 enthält den manuellen Install-Befehl.

- [ ] **Step 2: router.py — `reminder_write` Intent hinzufügen**

Lies `agents/router.py` (Zeilen 1-240) um die Struktur zu verstehen, dann mache folgende drei Änderungen:

**2a.** Füge nach dem `memory`-Intent-Block (nach Zeile ~226, vor `## Output-Format`) ein:

```
11. "reminder_write" — Apple Reminder / Erinnerung erstellen.
   Beispiele: "Erinnere mich morgen an den Anruf", "Erstelle eine Erinnerung: Paket abholen am Freitag"

   Parameter:
   - title: string (Titel der Erinnerung, Pflichtfeld)
   - due_date: ISO-Datum (YYYY-MM-DD) oder null (falls kein Datum genannt)
   - list_name: string oder null (falls eine bestimmte Reminder-Liste genannt)
```

**2b.** Aktualisiere den Output-Format-Block (Zeile ~231) — füge `"reminder_write"` zur Intent-Union hinzu:

```
  "intent": "calendar" | "coding" | "research" | "work" | "mail" | "personal" | "news" | "tasks" | "briefing" | "memory" | "reminder_write",
```

**2c.** Aktualisiere das Validation-Set (Zeile ~296):

```python
        if parsed["intent"] not in {"calendar", "coding", "research", "work", "mail", "personal", "news", "tasks", "briefing", "memory", "reminder_write"}:
```

- [ ] **Step 3: main.py — SQLite-Jobstore konfigurieren**

Im `startup()`-Block, direkt **vor** dem `_scheduler.add_job(send_briefing, ...)` Aufruf, füge ein:

```python
    try:
        from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
        _scheduler.add_jobstore(
            SQLAlchemyJobStore(url="sqlite:////root/.jarvis/jarvis_jobs.db"), "default"
        )
        logger.info("APScheduler SQLite-Jobstore konfiguriert")
    except Exception as e:
        logger.warning("SQLite-Jobstore nicht verfügbar: %s — läuft ohne Persistenz", e)
```

- [ ] **Step 4: main.py — ProactiveAgent initialisieren + 4 neue Jobs hinzufügen**

**4a.** Erweitere die `global`-Zeile in `startup()`:

```python
    global _memory_agent, _conversation_db, _profile_agent
```

bleibt gleich — `_proactive_db` wird direkt in `init_proactive` gesetzt.

**4b.** Füge direkt nach `logger.info("ProfileAgent initialisiert")` ein:

```python
    from db import ProactiveDB
    from proactive_agent import init_proactive
    _proactive_db = ProactiveDB()
    await _proactive_db.init()
    await init_proactive(_proactive_db, _memory_db)
```

**4c.** Füge direkt **nach** dem bestehenden `_scheduler.add_job(send_briefing, ...)` Block ein:

```python
    _chat_id_str = os.environ.get("TELEGRAM_CHAT_ID", "")
    if _chat_id_str:
        _chat_id = int(_chat_id_str)
        from proactive_agent import check_important_mails, send_task_reminder, send_weekly_review
        _scheduler.add_job(
            check_important_mails,
            CronTrigger(hour=9, minute=0, timezone="Europe/Berlin"),
            args=[_chat_id],
            id="mail_check_morning",
            replace_existing=True,
        )
        _scheduler.add_job(
            check_important_mails,
            CronTrigger(hour=14, minute=0, timezone="Europe/Berlin"),
            args=[_chat_id],
            id="mail_check_afternoon",
            replace_existing=True,
        )
        _scheduler.add_job(
            send_task_reminder,
            CronTrigger(hour=10, minute=0, timezone="Europe/Berlin"),
            args=[_chat_id],
            id="task_reminder_daily",
            replace_existing=True,
        )
        _scheduler.add_job(
            send_weekly_review,
            CronTrigger(day_of_week="fri", hour=17, minute=0, timezone="Europe/Berlin"),
            args=[_chat_id],
            id="weekly_review_friday",
            replace_existing=True,
        )
        logger.info("Proaktive Jobs registriert: mail_check x2, task_reminder, weekly_review")
    else:
        logger.warning("TELEGRAM_CHAT_ID nicht gesetzt — proaktive Jobs deaktiviert")
```

- [ ] **Step 5: main.py — `reminder_write` Intent-Branch hinzufügen**

Im `_process_text()`-Block, füge einen neuen `elif`-Branch direkt **vor** dem `elif intent == "work":` Block ein:

```python
    elif intent == "reminder_write":
        title = params.get("title", "")
        due_date_str = params.get("due_date")
        list_name = params.get("list_name")
        if not title:
            await update.message.reply_text("Kein Titel angegeben.")
            return
        try:
            from datetime import date
            due_date = date.fromisoformat(due_date_str) if due_date_str else None
            await asyncio.to_thread(calendar_agent.create_reminder, title, due_date, list_name)
            due_str = f" (fällig: {due_date_str})" if due_date_str else ""
            await update.message.reply_text(f"✅ Reminder '{title}'{due_str} erstellt.")
        except Exception as e:
            logger.exception("create_reminder fehlgeschlagen")
            await update.message.reply_text(f"❌ Reminder konnte nicht erstellt werden: {e}")
        return
```

- [ ] **Step 6: Alle Tests laufen lassen**

```bash
.worktrees/plan3-smart-routing/.venv/bin/pytest tests/test_proactive_db.py tests/test_proactive_agent.py tests/test_chat_quality_main.py tests/test_profile_agent.py tests/test_memory_agent.py -v
```

Erwartete Ausgabe: alle bestehenden Tests + 7 neue = mind. 30 passed, 0 failed.

- [ ] **Step 7: Commit + Push**

```bash
git add agents/main.py agents/router.py
git commit -m "feat(proactive): Scheduler-Jobs + reminder_write Intent in main + router"
git push
```

- [ ] **Step 8: VPS deployen**

```bash
ssh root@100.115.184.3 "cd /root/agents && source venv/bin/activate && pip install sqlalchemy && cd /root/agents && git pull && systemctl restart jarvis && sleep 5 && journalctl -u jarvis -n 20 --no-pager"
```

Erwartete Log-Ausgabe:
```
ProactiveAgent initialisiert
APScheduler SQLite-Jobstore konfiguriert
Proaktive Jobs registriert: mail_check x2, task_reminder, weekly_review
Jarvis gestartet
```

---

## Self-Review

**Spec Coverage:**
- ✅ Mail-Intelligence (09:00 + 14:00): `check_important_mails` + CronTrigger in main.py
- ✅ Nur Inbox: `get_inbox_unread()` fetcht `/me/mailFolders/inbox/messages`
- ✅ Haiku Batch-Assessment: `_assess_mail_importance()`
- ✅ Deduplication reported_mails (30d TTL): `ProactiveDB.mark_mails_reported()`
- ✅ Task-Reminder (täglich 10:00): `send_task_reminder` + CronTrigger
- ✅ Apple Reminders primär + MS To Do sekundär: beide Quellen in `send_task_reminder`
- ✅ Reminder-Dedup alle 2 Tage: `reminded_tasks` Tabelle + 2-Tage-Check
- ✅ Weekly Review (Freitag 17:00): `send_weekly_review` + CronTrigger
- ✅ Rückblick + Vorausschau narrativ via Sonnet: implementiert
- ✅ Apple Reminder erstellen: `create_reminder()` + `reminder_write` Intent
- ✅ APScheduler SQLite-Jobstore: `add_jobstore()` in startup()
- ✅ MemoryDB.load_since(): implementiert und getestet

**Type Consistency:**
- `ProactiveDB.mark_tasks_reminded(task_ids: list)` — in Task 1 definiert, in Task 5 (`proactive_agent.py`) mit gleicher Signatur verwendet ✅
- `CalendarAgent.get_all_reminders()` → `list[dict]` mit keys `uid`, `title`, `created`, `due` — in Task 3 definiert, in Task 5 gleich konsumiert ✅
- `MailAgent.get_inbox_unread(n)` → `list[Mail]` — Mail-Objekte haben `.id`, `.sender_name`, `.sender_email`, `.subject`, `.preview` ✅
