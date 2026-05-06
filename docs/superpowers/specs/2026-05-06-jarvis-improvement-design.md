# Jarvis Platform — Improvement Design

**Date:** 2026-05-06  
**Status:** Approved  
**Scope:** Coding Assistant rewrite, Morning Briefing, Mail write, Tasks integration, AI News, VPS cleanup

---

## 1. Motivation

Jarvis wird kaum genutzt weil: zu viel Reibung (Telegram öffnen), kein Trigger (vergessen), fehlende Features, schwache Antwortqualität. Kernhebel: proaktives Morgen-Briefing als täglicher Anker + Coding Assistant der wirklich funktioniert wenn man unterwegs ist.

---

## 2. VPS-Ist-Zustand

```
Hetzner CX33, Ubuntu 24.04, IP 89.167.67.26, Tailscale 100.115.184.3

Dienste:
  jarvis.service          systemd → uvicorn → :9000 (als root)
  caddy.service           host-native, /etc/caddy/Caddyfile
  code-server@root        Node.js → :8080
  docker.service          container runtime

Caddy-Routing:
  herrlich.dev            → /var/www/herrlich.dev (static) + :9000 (webhook/oauth)
  code.herrlich.dev       → :8080
  refurbish.herrlich.dev  → :8002 (Docker)
  immo-radar              → :8001 (Tailscale only, kein öffentlicher Eintrag)

Docker-Container:
  refurbish-business-web-1    :8002
  refurbish-business-worker-1
  refurbish-business-db-1     postgres:16
  immo-radar-web              :8001 (Tailscale)
  immo-radar-worker

Claude Workspace: /home/claude/workspace/
  recipe-app  ✓ (geklont)
  — alle anderen fehlen

Repos (GitHub phiman13):
  herrlich-ai-platform   /root/herrlich-ai-platform/ (als root, nicht im Workspace)
  recipe-app             /home/claude/workspace/recipe-app ✓
  immo-radar             fehlt im Workspace
  refurbish-business     fehlt im Workspace
  herrlich-dev           fehlt im Workspace
```

**Bekannte Probleme:**
- Jarvis läuft als root (Security-Issue, P2-Backlog)
- `/etc/caddy/Caddyfile` weicht vom Repo-Stand ab (nicht versioniert)
- Verzeichnisse `600`, `700`, `CHMOD`, `ECHO` etc. in `/root/` — Artefakte aus versehentlich ausgeführten Shell-Befehlen, aufzuräumen
- `coding_agent.py` nutzt falschen Pfad (`/root/workspace/`), Docker ephemer, Output-Streaming kaputt

---

## 3. Coding Assistant (Neubau)

### 3.1 Workspace-Setup (einmalig)

Alle 5 Repos nach `/home/claude/workspace/` klonen:

```
/home/claude/workspace/
  recipe-app             (bereits vorhanden)
  immo-radar             git clone phiman13/immo-radar
  refurbish-business     git clone phiman13/refurbish-business
  herrlich-dev           git clone phiman13/herrlich-dev
  herrlich-ai-platform   git clone phiman13/herrlich-ai-platform
```

Voraussetzung: GitHub PAT in `/root/.env` und `/home/claude/.env` prüfen/anlegen. PAT-Scope: `repo` (read + write für private Repos).

### 3.2 Architektur

Docker fliegt raus. `claude` CLI läuft direkt als `claude-user` auf dem VPS via SSH-Subprocess aus Jarvis heraus.

```
Telegram → Jarvis (FastAPI, root) → SSH als claude-user → claude CLI
                                                         → direkte Git/Datei-Abfragen
```

Session-Persistenz: SQLite-Tabelle `coding_sessions(project TEXT, session_id TEXT, last_used TIMESTAMP)`. TTL: 2 Stunden. Nach TTL neue Session.

### 3.3 Query / Action / Backlog-Write Split

| Modus | Trigger-Beispiele | Mechanismus | Latenz |
|---|---|---|---|
| **query** | "Backlog recipe-app", "git log", "offene PRs" | SSH → Datei lesen / `git log` / `gh api` | ~1s |
| **action** | "Fix Login-Bug", "Implementiere Feature X" | `claude --print -p "<task>"` mit `cwd=/home/claude/workspace/<project>` | 30s–5min |
| **backlog_write** | "Füge X zum Backlog hinzu", "Markiere Item Y als erledigt" | SSH → BACKLOG.md editieren + `git commit -m "..."` | ~3s |

Router erhält die aktuelle Projektliste als Kontext (beim Start via `ls /home/claude/workspace/`). Projekt-Erkennung durch LLM, nicht mehr Regex.

### 3.4 Session-Handling

```python
# Erste Nachricht zu Projekt
result = run_claude(task, project, cwd)
session_id = parse_session_id_from_output(result)
db.upsert_session(project, session_id)

# Follow-up innerhalb von 2h
session_id = db.get_session(project)
result = run_claude_resume(task, session_id)  # claude --resume <id> --print -p "<task>"
```

### 3.5 Output-Streaming

`--output-format stream-json` wird geparst. Jarvis schickt Telegram-Updates bei `assistant`-Nachrichten (nicht blind alle 5 Iterationen). Abschluss: Zusammenfassung + geänderte Dateien.

### 3.6 Auto-Clone unbekannter Repos

Wenn Projekt-Name in Nachricht erkannt aber nicht in Workspace vorhanden:
1. Jarvis: "Projekt X nicht lokal — klone von GitHub..."
2. `git clone git@github.com:phiman13/<project> /home/claude/workspace/<project>`
3. Weiter mit Task

### 3.7 Security-Fix

Claude Code läuft als `claude-user` (nicht root). Jarvis selbst läuft weiterhin als root bis ein separates Ticket den vollen User-Migration-Plan abarbeitet.

---

## 4. Morning Briefing

### 4.1 Zeitplan

APScheduler in `main.py`, täglich 07:00 Europe/Berlin. Manuell triggerbar via "Morgen-Briefing", "Was steht heute an?", "Briefing".

### 4.2 Datenquellen & Format

```
☀️ Guten Morgen, Philipp — [Wochentag], [Datum]

📅 KALENDER
• 10:00 Team-Meeting (1h)
• 14:30 Zahnarzt

📧 MAIL (3 ungelesen)
• Anna Weber: "Angebot Projekt X" — 08:12
• Chef: "Re: Budget Q2" — gestern

✅ MS TO DO — Einkaufsliste (2 offen)
• Milch
• Brot

🔔 APPLE ERINNERUNGEN (1 heute fällig)
• Steuererklärung abgeben

🌤️ WETTER
• 18°C, bewölkt, kein Regen

💻 GITHUB (2 offene PRs)
• recipe-app: "Fix auth flow" — 2 Tage offen

📰 AI NEWS
• Claude Sonnet 4.6 released — Anthropic Blog
• GPT-5 Benchmarks — TLDR AI
```

### 4.3 Implementierung pro Block

| Block | Agent/API | Notizen |
|---|---|---|
| Kalender | `calendar_agent.py` (bestehend) | `kind=today` |
| Mail | `mail_agent.py` (bestehend) | `mode=unread`, max 5, LLM-Wichtigkeitsfilter |
| MS To Do | `tasks_agent.py` (neu) | Graph API `/me/todo/lists` + `/tasks` |
| Apple Erinnerungen | `calendar_agent.py` erweitern | CalDAV VTODO-Komponenten, nur heute fällige |
| Wetter | Open-Meteo API | kostenlos, kein Key, Koordinaten Berlin |
| GitHub | `gh api` via SSH oder PyGitHub | offene PRs + letzte Commits, alle 5 Repos |
| AI News | `news_agent.py` (neu) | RSS-Feeds (15 Quellen), letzte 24h, dedupliziert |

### 4.4 Neue Intents

Router bekommt zwei neue Intents:
- `"news"` — AI-News on-demand ("Was gibt's Neues in AI?")
- `"tasks"` — MS To Do lesen/schreiben ("Füge Milch zur Einkaufsliste hinzu")
- `"briefing"` — Manueller Briefing-Trigger

---

## 5. MS To Do Integration

### 5.1 Lesen

```
GET /me/todo/lists               → alle Listen
GET /me/todo/lists/{id}/tasks    → Tasks einer Liste
```

### 5.2 Schreiben

```
POST /me/todo/lists/{id}/tasks   → Task erstellen
PATCH /me/todo/lists/{id}/tasks/{taskId}  → Task als erledigt markieren
```

OAuth bereits vorhanden (Phase 1). Nur `tasks_agent.py` + Router-Intent nötig.

---

## 6. Apple Reminders (CalDAV VTODO)

Erweiterung in `calendar_agent.py`. Bestehende CalDAV-Verbindung (iCloud) nutzen, Filter auf `VTODO`-Komponenten statt `VEVENT`. Für Briefing: nur `DUE=heute` oder `PRIORITY=high`. Kein Write im ersten Schritt (Apple Reminders schreiben via CalDAV ist fehleranfällig).

---

## 7. Mail-Integration (Audit + Write)

### 7.1 Phase 1 — Audit & Fix

Systematischer Test aller Modi gegen echte Graph API:
- `quick_scan`, `unread`, `search`, `list_folders`
- Fix P2-Problem: neuer `smart_search`-Modus — 150 Mails holen, Haiku filtert lokal
- Fehlerbehandlung verbessern (Token-Expiry, Graph-Throttling)

### 7.2 Phase 2 — Write (nach erfolgreichem Audit)

| Aktion | Telegram-Flow |
|---|---|
| Als gelesen markieren | InlineKeyboard "✓ Ja / ✗ Nein" |
| Archivieren | InlineKeyboard "Archivieren?" |
| Antworten | Haiku generiert Entwurf → zeigen → "Absenden? / Bearbeiten / Abbrechen" |
| Löschen | Nur mit explizitem Confirm, nie automatisch |

**Invariante: Kein einziger Write-Aufruf ohne Nutzer-Bestätigung via InlineKeyboard.**

---

## 8. News Agent

`news_agent.py` — RSS-Logik aus `ai-news-skill` (github.com/tensakulabs/ai-news-skill) in Python portiert.

15 Feeds (Aggregatoren: TLDR AI, HN, The Decoder; Lab-Blogs: Anthropic, Claude, OpenAI, xAI, Google AI; Tools: Cursor, Windsurf, Ollama). Filter: letzte 24h. Dedup: Titel-Ähnlichkeit >80%. Kategorien: Model Releases, Research, Industry, Product. Ausgabe: formatierte Telegram-Nachricht.

---

## 9. VPS-Hygiene (Nebenarbeiten)

- `/etc/caddy/Caddyfile` in `herrlich-ai-platform/config/caddy/Caddyfile` synchronisieren und als Source of Truth etablieren (Caddy bleibt host-native, siehe Entscheidung §10)
- Verzeichnisse `600`, `700`, `77`, `CHMOD`, `ECHO`, `AAAAC3...`, `=2.1` in `/root/` löschen (Artefakte)
- GitHub PAT prüfen / anlegen

---

## 10. Entscheidung: Caddy bleibt host-native (nicht Docker)

Ein separater Chat schlug vor, Caddy in Docker zu containerisieren. Dagegen spricht:

Der VPS hostet 5 Projekte mit unterschiedlichen Laufzeitmodellen (systemd, Docker, statische Files). Ein projekt-spezifischer Caddy-Container würde entweder nur einen Dienst bedienen (unvollständig) oder alle Projekte in einer docker-compose zusammenfassen (massive Umstrukturierung ohne direkten Nutzen).

**Lösung für das eigentliche Problem** (Caddyfile nicht versioniert): Caddyfile ins Repo aufnehmen und Deploy-Script schreiben das bei Änderung nach `/etc/caddy/Caddyfile` kopiert und `systemctl reload caddy` ausführt. Reproduzierbar ohne Docker-Overhead.

---

## 11. Implementierungs-Reihenfolge

1. **VPS-Setup** — Repos klonen, PAT prüfen, Verzeichnisse aufräumen, Caddyfile sync
2. **Coding Agent Neubau** — Drop Docker, SSH-Subprocess, Session-SQLite, Query/Action Split
3. **Morning Briefing** — APScheduler + briefing_agent.py (Kalender, Mail, Wetter zuerst)
4. **Tasks Agent** — MS To Do (lesen + schreiben)
5. **Apple Reminders** — CalDAV VTODO-Erweiterung
6. **News Agent** — RSS-Feeds
7. **GitHub-Block** — ins Briefing integrieren
8. **Mail Audit** — Read-Integration testen und fixen
9. **Mail Write** — Phase 2 nach erfolgreichem Audit

---

## 12. Offene Punkte (beim Implementieren klären)

- GitHub PAT: existiert bereits auf VPS?
- `herrlich-ai-platform` im Workspace: Clone oder Symlink auf `/root/herrlich-ai-platform/`?
- Apple Reminders Write: CalDAV-VTODO-Create testen bevor in Scope aufnehmen
- Mail Write: erst wenn Read-Audit bestanden
