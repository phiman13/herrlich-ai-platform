# Jarvis Platform — Backlog

Master-Quelle: dieses File im Repo. Letzter Stand: 10.05.2026 (abends)

---

---

## P2 — Wichtig, nicht dringend

- [ ] **Mail: Verschieben in beliebigen Ordner**
      `move`-Op löst aktuell `find_folder_by_name()` auf — ungetestet.
      End-to-End testen + ggf. Fuzzy-Matching für Ordnernamen verbessern.
      Aufwand: 30 Min.

- [ ] **Gesprächsverlauf für alle Intents**
      ConversationDB speichert nur `personal`/`work`/`research`.
      `mail`, `calendar`, `tasks` könnten auch von History profitieren.
      Aufwand: 30 Min.

- [ ] **Secret- & Permission-Hygiene auf VPS — Restarbeiten**
      Jarvis läuft jetzt als `jarvis`-User, Claude Code als `claude`-User. ✅
      Noch offen: 1Password-CLI für Env-Injection statt `.env` (`.env` liegt unter `/var/lib/jarvis/` mit restriktiven Rechten — akzeptables Risiko).

---

## P3 — Später / Nice to have

- [ ] **UptimeRobot Monitoring**
      Health-Checks für jarvis.service und Webhook-Endpoint.

- [ ] **Kalender: Termin löschen / bearbeiten**
      CalDAV-Write für UPDATE/DELETE implementieren.

- [ ] **Mail: Entwürfe speichern (Drafts)**
      `POST /me/messages` + `PATCH` statt direktem Senden.

- [ ] **Proaktiver Agent: Standort-Kontext**
      iPhone → Jarvis Webhook bei Ankunft/Abfahrt (iOS Shortcuts).
      Ermöglicht kontextabhängige Briefings.

- [ ] **Health-Daten im Briefing**
      iOS Shortcut sendet Schritte/Schlaf morgens an Jarvis-Webhook.

- [ ] **iCloud-Dateizugriff (rclone)**
      Redundanz zu OneDrive-via-Graph vorher prüfen.

- [ ] **ntfy.sh Push-Notifications**
      `ntfy_agent.py` ist angelegt aber noch nicht in Betrieb.
      Alternative/Ergänzung zu Telegram für stille Hintergrund-Notifications.

---

## Erledigt

### 10.05.2026
- [x] Claude Code nicht als root — jarvis-User angelegt, Service migriert auf /opt/jarvis, JARVIS_DATA_DIR in allen Agenten (db.py, microsoft_auth.py, profile_agent.py, memory_agent.py)
- [x] GitHub Webhook aktiviert — alle Repos eingetragen, Push-Test erfolgreich (Telegram-Notification bestätigt)
- [x] SQLite-Backup — `scripts/backup_jarvis.sh`, Cron 3:00 Uhr täglich, 7-Tage-Rotation
- [x] Briefing: Markdown-Escaping — `_escape_md()` strippt `*`/`_` aus Kalender/Mail-Titeln
- [x] Router-Kontext: Jarvis-Antworten — `_recent_conv` interleaved Philipp/Jarvis-Paare
- [x] GitHub Webhook Endpoint — `POST /webhook/github` mit HMAC-Validierung + git pull
- [x] JARVIS_DATA_DIR env var — alle `/root/.jarvis/`-Pfade konfigurierbar (db.py, microsoft_auth.py, main.py)
- [x] scripts/migrate_to_jarvis_user.sh — interaktives Migrationsskript root → jarvis-User

### 09.–10.05.2026
- [x] Briefing: Fallback auf Plaintext wenn Markdown-Parse fehlschlägt
- [x] Router: letzte 3 User-Nachrichten als Kontext (Pronomen-Auflösung: "diese Mail")
- [x] Tasks: due_time aus Router extrahieren → reminderDateTime korrekt setzen
- [x] Tasks: System-Tasks ("Der Ersteller dieser Liste…") aus get_tasks_raw() filtern
- [x] Mail: archive via move+destinationId (Graph /archive-Endpoint nicht verfügbar)

### 08.05.2026
- [x] MS Graph Phase 4: Mail Write Ops (mark_read/unread, archive, move, delete, reply, forward)
      Smart-Search-basierte Mail-Identifikation, InlineKeyboard Confirm-Dialog
- [x] Wetter: Heimatort konfigurierbar per .env (WEATHER_LAT, WEATHER_LON, WEATHER_LOCATION_NAME)

### 04.–07.05.2026 — Proaktives Trigger-System
- [x] ProactiveDB: reported_mails + reminded_tasks (SQLite, 30-Tage-TTL)
- [x] MailAgent.get_inbox_unread()
- [x] CalendarAgent: get_all_reminders(), get_completed_reminders_this_week(), create_reminder()
- [x] TasksAgent: get_tasks_raw(), get_completed_tasks_this_week()
- [x] ProactiveAgent: check_important_mails(), send_task_reminder(), send_weekly_review()
- [x] APScheduler mit SQLAlchemyJobStore (restart-safe)
- [x] Router: reminder_write + weather Intents
- [x] Wetter: stündliche Vorhersage + time_of_day-Parameter
- [x] Wetter: Ortseingabe + Geocoding via Open-Meteo
- [x] Reminder-Write: auf MS To-Do umgestellt (iCloud CalDAV VTODO broken seit iOS 13)
- [x] Tasks: alle Listen anzeigen, auch leere

### ~25.04.2026 — Memory & Profile
- [x] ProfileAgent: Nutzerprofil-Kontext für Claude
- [x] MemoryDB: SQLite-Gedächtnisschicht mit Embeddings
- [x] Memory-Intent: list + delete Modi
- [x] Automatische Memory-Extraktion aus personal/work/research

### 13.04.2026 — MS Graph + Basis-Features
- [x] MS Graph Phase 3: Tasks / To Do
- [x] MS Graph Phase 2: Mail lesen
- [x] MS Graph Phase 1: OAuth (MSAL)
- [x] CalDAV-Kalender: lesen + schreiben
- [x] LLM-basiertes Intent-Routing
- [x] Web-Search Integration
- [x] Auto-Pull für VPS-Workspace
