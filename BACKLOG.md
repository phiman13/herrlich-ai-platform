# Jarvis Platform — Backlog

Master-Quelle: dieses File im Repo.
Letzter Stand: 08.05.2026

## P1 — Nächster Schritt

- [ ] **Audit: Implementation gegen Best-Practice-Guides abgleichen**
      Unser VPS-/Claude-Code-/Jarvis-Setup ist organisch gewachsen.
      Vor weiteren Features einmal systematisch gegen externe
      Best-Practice-Quellen prüfen, insbesondere:

      Quellen:
      - reddit.com/r/ClaudeCode "best way to actually use remote mode"
      - claudefa.st "InfraOps VPS Guide" + "Permission Management"
      - andrey-markin.com "Claude Code VPS Setup"

      Erwartete Findings-Bereiche: Permission-Hygiene (claude-User vs root),
      Secret-Management, Hook-Strategie, Container-Isolation, Backup-Strategie.
      Output: Granulare neue Backlog-Items pro Finding.
      Aufwand: 60–90 Min.

- [ ] **Mail Smart-Search via LLM-Filter**
      Multi-Kriterien-Suche scheitert an Graph-API-Limits. Lösung:
      neuer `smart_search`-Modus, der 100–200 Mails holt und Claude
      Haiku zur semantischen Filterung nutzt. Aufwand: 60–90 Min.

## P2 — Wichtig, nicht dringend

- [ ] **Secret- & Permission-Hygiene auf VPS**
      Claude Code läuft als root → Permissions-Drift möglich.
      Fix: Claude Code via `sudo -u claude`, Ownership-Audit,
      evtl. 1Password-CLI für systemd-Env-Injection statt `.env`.

- [ ] **Auto-Sync für Code-Workspaces auf VPS via GitHub Webhook**
      GitHub Webhook → FastAPI-Endpoint → `git pull` für betroffenes Repo.
      Relevant sobald regelmäßig parallel auf Mac + VPS gearbeitet wird.
      Aufwand: 60–90 Min inkl. HMAC-Validierung.

- [ ] **MS Graph Phase 4: Schreibender Mail-Zugriff**
      Archivieren, Verschieben, Löschen, als gelesen markieren —
      mit Bestätigungs-Prompts im Telegram-Flow. Aufwand: 90–120 Min.

- [ ] **Wetter: Heimatort konfigurierbar per .env**
      Aktuell hardcodiert auf Tutzing (lat/lon). Sollte via
      `WEATHER_LAT`, `WEATHER_LON`, `WEATHER_LOCATION_NAME` konfigurierbar sein.

## P3 — Später

- [ ] **UptimeRobot Monitoring**
      Health-Checks für jarvis.service und Webhook-Endpoint.

- [ ] **iCloud-Dateizugriff (rclone)**
      Redundanz zu OneDrive-via-Graph vorher prüfen.

- [ ] **Proaktiver Agent: Standort-Kontext**
      iPhone → Jarvis Webhook bei Ankunft/Abfahrt (z.B. via iOS Shortcuts).
      Ermöglicht kontextabhängige Briefings und Erinnerungen.

- [ ] **Health-Daten im Briefing**
      iOS Shortcut sendet Schritte/Schlaf-Daten morgens an Jarvis-Webhook.
      Erscheint dann im Morning Briefing.

## Erledigt

### 08.05.2026
- [x] Wetter: stündliche Vorhersage + time_of_day Parameter (heute Nachmittag etc.)
- [x] Wetter: Ortseingabe + Geocoding via Open-Meteo (kostenfrei)
- [x] Reminder-Write: auf MS To-Do umgestellt (iCloud CalDAV VTODO seit iOS 13 broken)
- [x] Reminder-Write: dueDateTime als echtes MS Graph API Feld (nicht im Titel)
- [x] Tasks: alle Listen anzeigen statt nur 5, auch leere Listen
- [x] Briefing: Apple Erinnerungen entfernt, Tasks-Liste korrekt, Weather-Timeout erhöht
- [x] Bugfixes: Weather-Intent routing, personal_system Prompt, CalDAV Forbidden

### 04.–07.05.2026 — Plan 9: Proaktives Trigger-System
- [x] ProactiveDB: reported_mails + reminded_tasks Tabellen (SQLite, 30-Tage-TTL)
- [x] MemoryDB.load_since(days): neue Methode für zeitbasierte Memory-Abfragen
- [x] MailAgent.get_inbox_unread(): dedizierter Inbox-Unread-Fetch
- [x] CalendarAgent: get_all_reminders(), get_completed_reminders_this_week(), create_reminder()
- [x] TasksAgent: get_tasks_raw(), get_completed_tasks_this_week()
- [x] ProactiveAgent: check_important_mails(), send_task_reminder(), send_weekly_review()
- [x] APScheduler mit SQLAlchemy-Jobstore (restart-safe): 09:00, 14:00, 10:00, Fr 17:00
- [x] Router: reminder_write + weather Intents
- [x] Tests: test_proactive_db.py, test_proactive_agent.py

### ~25.04.2026 — Plan 8: Memory & Profile
- [x] ProfileAgent: Nutzerprofil-Kontext für Claude
- [x] MemoryDB: SQLite-Gedächtnisschicht mit Embeddings
- [x] Memory-Intent: list + delete Modi
- [x] Automatische Memory-Extraktion aus personal/work/research Intents

### 13.04.2026
- [x] MS Graph Phase 3: Tasks / To Do Integration (tasks_agent.py, Router-Intent)
- [x] MS Graph Phase 2 — Mail-Lesen (commit 2599bf5)
- [x] MS Graph Phase 1 — OAuth (commit e54b994)
- [x] CalDAV-Kalender: Lesen + Schreiben (commit 98a2c0c)
- [x] LLM-basiertes Intent-Routing (commit 1b159ee)
- [x] Web-Search Integration (commit 8628c44)
- [x] Auto-Pull für VPS-Workspace (commit 9c8dc29)
