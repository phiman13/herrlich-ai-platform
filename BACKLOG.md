# Jarvis Platform — Backlog

Master-Quelle: dieses File im Repo. Das Claude-Projekt führt eine
Sync-Kopie (jarvis-platform-backlog.md) — bei Divergenz gilt Repo.

Letzter Stand: 13.04.2026

## P1 — Nächster Schritt

- [ ] **Audit: Implementation gegen Best-Practice-Guides abgleichen**
      Unser VPS-/Claude-Code-/Jarvis-Setup ist organisch gewachsen.
      Vor weiteren Features einmal systematisch gegen externe
      Best-Practice-Quellen prüfen, insbesondere:
      
      Quellen:
      - reddit.com/r/ClaudeCode "best way to actually use remote mode"
        (https://www.reddit.com/r/ClaudeCode/comments/1ri6t1h/the_best_way_to_actually_use_remote_mode/)
      - claudefa.st "InfraOps VPS Guide"
        (https://claudefa.st/blog/guide/development/infraops-vps-guide)
      - claudefa.st "Permission Management"
        (https://claudefa.st/blog/guide/development/permission-management)
      - andrey-markin.com "Claude Code VPS Setup"
        (https://andrey-markin.com/blog/claude-code-vps-setup)
      - Eigene Web-Recherche zu weiteren Best Practices
      
      Vorgehen: Quellen lesen, Findings sammeln, gegen aktuellen
      Stand abgleichen, Lücken dokumentieren, neue Backlog-Items
      pro Lücke anlegen. Erwartete Findings-Bereiche: Permission-
      Hygiene (claude-User vs root), Secret-Management, Hook-Strategie,
      Container-Isolation, Backup-Strategie.
      
      Output: Dieser Audit-Punkt wird abgeschlossen, indem die
      Findings als neue, granulare Backlog-Items eingetragen werden.
      Aufwand: 60–90 Min Lesen + Strukturieren, danach pro Finding
      eigener Aufwand.
      
- [ ] **MS Graph Phase 3: Tasks / To Do Integration**
      OAuth-Fundament aus Phase 1 steht, nur `tasks_agent.py` +
      Router-Intent "tasks" nötig. Aufwand: 45–60 Min.

## P2 — Wichtig, nicht dringend

- [ ] **Mail Smart-Search via LLM-Filter**
      Multi-Kriterien-Suche scheitert an Graph-API-Limits ($search
      ohne KQL-Properties, $filter ohne contains auf Mails). Lösung:
      neuer `smart_search`-Modus, der 100–200 Mails holt und Claude
      Haiku zur semantischen Filterung nutzt. Aufwand: 60–90 Min.

- [ ] **Secret- & Permission-Hygiene auf VPS**
      Claude Code läuft aktuell als root → Permissions-Drift im
      recipe-app-Workspace nach git pull als root (heute beobachtet).
      Fix: Claude Code konsequent via `sudo -u claude`, Ownership-
      Audit `/home/claude/workspace`, evtl. 1Password-CLI für
      systemd-Env-Injection statt `.env`.

- [ ] **SQLite-Gedächtnis-Schicht**
      Persistente Konversations-/Kontext-Memory für Jarvis.

- [ ] **Auto-Sync für Code-Workspaces auf VPS via GitHub Webhook**
      Heutiger Auto-Pull-Fix gilt nur für `read_project_files()` in
      Jarvis (Coding-Question-Pfad). Andere Stellen sind weiter
      drift-anfällig: code-server (VS Code im Browser), direktes
      Claude Code im VPS-Terminal, parallele Mac-Sessions. Lösung:
      GitHub Webhook → FastAPI-Endpoint → `git pull` für betroffenes
      Repo. Wird relevant, sobald regelmäßig parallel auf Mac und
      VPS gearbeitet wird. Aufwand: 60–90 Min plus HMAC-Validierung
      und Tests.

## P3 — Später

- [ ] **MS Graph Phase 4: Schreibender Mail-Zugriff**
      Archivieren, Verschieben, Löschen, als gelesen markieren — mit
      Bestätigungs-Prompts im Telegram-Flow. Aufwand: 90–120 Min.

- [ ] **iCloud-Dateizugriff (rclone)**
      Redundanz zu OneDrive-via-Graph vorher prüfen.

- [ ] **UptimeRobot Monitoring**
      Health-Checks für jarvis.service und Webhook-Endpoint.

- [ ] **Backlog-Doppelpflege auflösen**
      Aktuell zwei Orte (Repo + Claude-Project). Entweder Project-
      Version entfernen oder automatischen Sync bauen.

## Erledigt (13.04.2026)

- [x] Web-Search Integration (commit 8628c44)
- [x] CalDAV-Kalender-Integration, Lesen (commit 98a2c0c, 12.04.2026)
- [x] LLM-basiertes Intent-Routing (commit 1b159ee)
- [x] Auto-Pull für VPS-Workspace (commit 9c8dc29)
- [x] MS Graph Phase 1 — OAuth (commit e54b994)
- [x] MS Graph Phase 2 — Mail-Lesen (commit 2599bf5, 13.04.2026)
