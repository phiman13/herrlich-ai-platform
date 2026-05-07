# Jarvis Proaktives Trigger-System — Design Spec

**Date:** 2026-05-07
**Status:** Approved

## Goal

Jarvis wird proaktiv: Statt nur auf Nachrichten zu reagieren, pingt er Philipp eigenständig bei wichtigen ungelesenen Mails, überfälligen Tasks und liefert einen wöchentlichen Review. Die Infrastruktur ist restart-sicher (SQLite-Jobstore) und dedupliziert alle Benachrichtigungen.

## Features

### 1. Mail-Intelligence (09:00 + 14:00)

Jarvis holt ungelesene Mails aus dem **Inbox** des persönlichen Microsoft-Kontos (MS Graph). Die Ordner "Newsletter" und "Job" werden grundsätzlich übersprungen.

**Wichtigkeits-Bewertung:** Claude Haiku bewertet alle neuen (noch nicht gemeldeten) Mails batchweise anhand von Inhalt und Betreff. Kriterien: Deadlines, konkrete Anfragen, finanzielle Themen, zeitkritische Informationen. Kein Absender-Filter — nur inhaltliche Bewertung.

**Deduplication:** Bereits gemeldete Mail-IDs werden in der Tabelle `reported_mails` gespeichert. Einträge älter als 30 Tage werden automatisch gelöscht.

**Output:** Telegram-Nachricht mit kompakter Zusammenfassung der wichtigen Mails (Absender, Betreff, Grund). Kein Ping wenn keine wichtigen Mails gefunden.

### 2. Task-Reminder (täglich 10:00)

Jarvis prüft alle offenen Tasks und erinnert an Tasks die seit mehr als 2 Tagen offen sind.

**Quellen:** Apple Reminders (primär, via CalDAV) + MS To Do (sekundär, via Graph API).

**Deduplication:** Pro Task wird maximal alle 2 Tage erinnert. Zuletzt-erinnert-Timestamp in Tabelle `reminded_tasks`.

**Output:** Telegram-Nachricht mit Liste der überfälligen Tasks, gruppiert nach Quelle. Kein Ping wenn alle Tasks frisch oder keine offen.

### 3. Weekly Review (Freitag 17:00)

Claude Sonnet fasst Rückblick und Vorausschau zu einer narrativen Nachricht zusammen — kein reines Bullet-Listing.

**Rückblick (diese Woche Mo–Fr):**
- Kalender-Termine
- Apple Reminders die diese Woche erledigt wurden
- Memory-Einträge der letzten 7 Tage aus SQLite

**Vorausschau (nächste Woche):**
- Kalender-Termine nächste Woche
- Alle offenen Apple Reminders
- Alle offenen MS To Do Tasks

### 4. Apple Reminder erstellen (Bonus)

Neue Methode `create_reminder(title, due_date=None, list_name=None)` in `calendar_agent.py` via CalDAV VTODO. Neuer Router-Intent `reminder_write` damit Philipp per Telegram Reminders anlegen kann ("Erinnere mich morgen an X").

### 5. APScheduler SQLite-Jobstore

APScheduler wird auf einen SQLite-Jobstore umgestellt. Jobs überleben Jarvis-Neustarts ohne erneutes Feuern. Jobstore-DB: `/root/.jarvis/jarvis_jobs.db` (separate Datei, nicht die Memory-DB).

## File Map

| File | Änderung |
|---|---|
| `agents/proactive_agent.py` | Neu: `check_important_mails()`, `send_task_reminder()`, `send_weekly_review()` |
| `agents/db.py` | +2 Tabellen: `reported_mails`, `reminded_tasks` |
| `agents/calendar_agent.py` | +3 Methoden: `get_all_reminders()`, `get_completed_reminders_this_week()`, `create_reminder()` |
| `agents/tasks_agent.py` | +2 Methoden: `get_tasks_raw()`, `get_completed_tasks_this_week()` |
| `agents/db.py` | +Methode: `MemoryDB.load_since(days: int) -> list[dict]` |
| `agents/mail_agent.py` | `get_unread()` erhält optionalen `exclude_folders: list[str]`-Parameter |
| `agents/main.py` | SQLite-Jobstore, 4 neue Scheduler-Jobs, `reminder_write`-Intent |
| `agents/router.py` | Neuer Intent `reminder_write` mit Params `title`, `due_date`, `list_name` |
| `tests/test_proactive_agent.py` | Neu: Tests für alle 3 Job-Funktionen |

## DB Schema

```sql
-- Deduplication für Mail-Intelligence
CREATE TABLE IF NOT EXISTS reported_mails (
    mail_id TEXT PRIMARY KEY,
    reported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Deduplication für Task-Reminder
CREATE TABLE IF NOT EXISTS reminded_tasks (
    task_id TEXT PRIMARY KEY,
    last_reminded TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## Data Flow

```
APScheduler (SQLite-Jobstore)
    ↓ 09:00 + 14:00
check_important_mails(chat_id)
    → MailAgent.get_unread(30, exclude_folders=["Newsletter","Job"])
    → filter gegen reported_mails
    → Haiku-Batch: wichtig ja/nein
    → Bot.send_message() wenn wichtige Mails
    → reported_mails INSERT

    ↓ 10:00 täglich
send_task_reminder(chat_id)
    → CalendarAgent.get_all_reminders()
    → TasksAgent.get_tasks_raw()
    → filter: älter als 2 Tage + last_reminded > 2 Tage
    → Bot.send_message() wenn überfällige Tasks
    → reminded_tasks UPSERT

    ↓ Freitag 17:00
send_weekly_review(chat_id)
    → CalendarAgent.get_events(diese Woche + nächste Woche)
    → CalendarAgent.get_completed_reminders_this_week()
    → TasksAgent.get_tasks_raw() + get_completed_tasks_this_week()
    → MemoryDB.load_since(7 Tage)
    → Sonnet: narratives Summary
    → Bot.send_message()
```

## Out of Scope

- Kalender/Reminder löschen, umbenennen, Datum ändern (eigenes Projekt)
- Mental Health Coach (Projekt B)
- Job Coach + Job-Ordner-Screening (Projekt C)
- Konfigurierbare Ausschlusslisten per Telegram-Command
- Reminder-Priorisierung / Wichtigkeitsstufen
