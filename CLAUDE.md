# Jarvis — herrlich-ai-platform

Persönlicher KI-Assistent via Telegram (@jarvis_herrlich_bot). FastAPI-Gateway auf Hetzner VPS, routet Nachrichten per Claude Haiku an spezialisierte Agenten.

**VPS:** `root@100.115.184.3` (Tailscale) | **Service:** `jarvis.service` | **Live:** herrlich.dev

---

## Architektur-Überblick

```
Telegram Webhook (POST /webhook/telegram)
        │
        ▼
agents/main.py              FastAPI Gateway + APScheduler
        │
        ├── Voice? → voice_agent.py → transkribieren → weiter als Text
        │
        ▼
agents/router.py            Claude Haiku — klassifiziert Intent
        │                   Input: aktueller Text + letzte 3 User-Nachrichten
        │                   Output: {intent, confidence, params, reasoning}
        │
        ├── mail            mail_agent.py
        ├── calendar        calendar_agent.py
        ├── tasks           tasks_agent.py
        ├── reminder_write  tasks_agent.py (add_task mit due_date/due_time)
        ├── briefing        briefing_agent.py
        ├── coding          coding_agent.py + github_agent.py
        ├── memory          memory_agent.py
        ├── personal ┐
        ├── work     │
        ├── research ├─ agent.py run_agent — echter Agent (Claude Agent SDK):
        ├── weather  │  Tools workspace/web/weather/news, Denk-Schleife,
        └── news     ┘  History, MemoryAgent

APScheduler (SQLite Jobstore, restart-safe):
        └── proactive_agent.py
```

---

## Datei-Struktur

```
agents/
  main.py               FastAPI-App, Routen, startup/shutdown
  dispatch.py           Telegram-Dispatch: _process_text-Orchestrator + handle_message/voice/start
  app_state.py          Geteilter State (Pending-Ops, Such-Dicts, lazy Agenten) + TTL-Helper
  formatting.py         Reine Formatter (Kalender/Mail/Markdown)
  mail_handler.py       Mail-Intent-Handler (lesen/suchen/schreiben)
  calendar_handler.py   Kalender-Intent-Handler (lesen/anlegen/ändern/absagen)
  intent_handlers.py    Schlanke Intent-Handler (coding/tasks/briefing/...)
  callbacks.py          InlineKeyboard-Callback-Router (handle_callback)
  github_webhook.py     GitHub-Auto-Deploy-Webhook
  router.py             Intent-Routing via Claude Haiku
  db.py                 SessionDB, MemoryDB, ConversationDB, ProactiveDB (alle SQLite-async)
  microsoft_auth.py     MSAL OAuth-Flow für MS Graph
  mail_agent.py         MS Graph Mail (MailAgent-Klasse)
  calendar_agent.py     Outlook-Kalender via MS Graph (lesen + schreiben)
  tasks_agent.py        MS Graph To-Do
  briefing_agent.py     Morgenbriefing aggregiert
  proactive_agent.py    APScheduler-Jobs
  memory_agent.py       MemoryAgent-Klasse (Embeddings + Extraktion)
  news_agent.py         RSS + Claude-Zusammenfassung
  coding_agent.py       Claude Code auf VPS triggern
  github_agent.py       gh CLI wrapper
  voice_agent.py        Groq Whisper Transkription
  weather_agent.py      Open-Meteo API
  profile_agent.py      Nutzerprofil-Kontext laden
  vps.py                Workspace-Verwaltung (Projektliste etc.)
  requirements.txt      Python-Abhängigkeiten
  claude-settings.json  Claude Code Permission-Config (VPS)

scripts/
  claude-guard.sh             Bash-Hook: blockt destruktive Befehle
  backup_jarvis.sh            SQLite-Backup, Cron 3:00 täglich, 7-Tage-Rotation
  migrate_to_jarvis_user.sh   Migration root → jarvis-User (einmalig ausgeführt)

config/
  caddy/Caddyfile       Reverse Proxy (herrlich.dev → :9000)
  jarvis.service        systemd Unit

tests/                  pytest-Suite (PYTHONPATH=agents)
docs/plans/             Aktive Pläne (done/ = Archiv abgeschlossener)
```

---

## Environment Variables (`/var/lib/jarvis/.env` auf VPS)

| Variable | Pflicht | Beschreibung |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ | Bot-Token von @BotFather |
| `TELEGRAM_CHAT_ID` | ✅ | Chat-ID für proaktive Nachrichten (Philipps Chat) |
| `ANTHROPIC_API_KEY` | ✅ | Anthropic API Key (wird vom SDK automatisch gelesen) |
| `MICROSOFT_CLIENT_ID` | ✅ | Azure App Registration Client ID |
| `MICROSOFT_CLIENT_SECRET` | ✅ | Azure App Registration Client Secret |
| `OAUTH_LOGIN_SECRET` | ✅ | Schützt `/oauth/microsoft/login` Endpoint |
| `GITHUB_TOKEN` | ✅ | GitHub Personal Access Token für github_agent |
| `GITHUB_WEBHOOK_SECRET` | ✅ | HMAC-Secret für GitHub Webhook Validierung |
| `GROQ_API_KEY` | ✅ | Groq API Key für Whisper-Transkription |
| `JARVIS_AGENT_MODEL` | ❌ | Modell für den Agenten (Default: `claude-sonnet-4-6`) |
| `JARVIS_WORKSPACE_DIR` | ❌ | Workspace-Root für den `workspace`-Tool (Default: `~/Code`) |
| `JARVIS_CLAUDE_CLI_PATH` | ❌ | Expliziter Pfad zur `claude`-CLI, falls nicht auf PATH |
| `CLAUDE_CODE_OAUTH_TOKEN` | ❌ | OAuth-Token der Claude Code CLI (headless, Abo-Auth) |
| `JARVIS_DATA_DIR` | ❌ | Pfad für DBs + Tokens (Default: `/root/.jarvis`, prod: `/var/lib/jarvis/.jarvis`) |
| `REMINDER_TODO_LIST` | ❌ | To-Do-Liste für Erinnerungen (Default: `Tasks`) |
| `WEATHER_LAT` | ❌ | Breitengrad Heimatort (Default: `48.14`) |
| `WEATHER_LON` | ❌ | Längengrad Heimatort (Default: `11.58`) |
| `WEATHER_LOCATION_NAME` | ❌ | Anzeigename Heimatort (Default: `Tutzing`) |

---

## Datenbank-Dateien (alle auf VPS unter `/var/lib/jarvis/.jarvis/`)

| Datei | Klasse | Inhalt |
|---|---|---|
| `conversations.db` | `ConversationDB` | Gesprächsverlauf pro chat_id (role, content, timestamp) — nur für personal/work/research |
| `memories.db` | `MemoryDB` | Extrahierte Fakten + Notizen (text, source, embedding blob, created_at) |
| `sessions.db` | `SessionDB` | Claude-Code-Session-IDs pro Projekt (TTL 2h) |
| `proactive.db` | `ProactiveDB` | reported_mails (mail_id, reported_at) + reminded_tasks (task_id, reminded_at) — 30-Tage-TTL |
| `microsoft_tokens.json` | — | MSAL Token-Cache (verschlüsselt durch MSAL) |
| `jarvis_jobs.db` | APScheduler | Persistente Job-Definitionen (restart-safe) |

---

## Claude-Modelle im Einsatz

| Verwendung | Modell |
|---|---|
| Intent-Routing (`router.py`) | `claude-haiku-4-5-20251001` |
| Personal / Work / Research Antworten | `claude-sonnet-4-6` |
| Mail-Importance-Check (`proactive_agent.py`) | `claude-haiku-4-5-20251001` |
| Weekly Review (`proactive_agent.py`) | `claude-sonnet-4-6` |
| Mail Smart-Search (`mail_agent.py`) | `claude-haiku-4-5-20251001` |
| Memory-Extraktion (`memory_agent.py`) | `claude-haiku-4-5-20251001` |
| Briefing (`main.py`) | `claude-haiku-4-5-20251001` |

---

## Agenten im Detail

### mail_agent.py — MailAgent-Klasse
MS Graph REST-Calls via `requests`. Token via `get_access_token()` (MSAL).

**Lese-Methoden:** `quick_scan`, `get_unread`, `search`, `smart_search`, `list_folders`, `find_folder_by_name`, `get_mail_body`

**Schreib-Methoden:** `mark_read`, `archive`, `move`, `delete`, `reply`, `forward`, `send_mail`

**Write-Flow in main.py:**
1. `_handle_mail_write()` → `smart_search(mail_query, n=50)`
2. 0 Treffer → Fehlermeldung | >5 Treffer → "zu viele" | 1 Treffer → direkt Confirm | 2–5 → InlineKeyboard
3. Auswahl gespeichert in `_last_mail_search[chat_id]` (TTL 3 Min)
4. `_show_mail_action_confirm()` → mark_read/unread direkt ausführen, alle anderen → Confirm-Dialog
5. Confirm gespeichert in `_pending_mail_ops[chat_id]`
6. Callback `mail:action:confirm` → Aktion ausführen

**Hinweis:** MS Graph `/messages/{id}/archive` existiert nicht → stattdessen `move` mit `destinationId: "archive"`

### calendar_agent.py — CalendarAgent-Klasse
Outlook-Kalender via MS Graph (`httpx`). Auth über `microsoft_auth.get_access_token()`.

Lesen: `GET /me/calendarView` (Header `Prefer: outlook.timezone="Europe/Berlin"`) — expandiert Serien- und Multi-Day-Termine serverseitig. Anlegen: `POST /me/events` (`create_event`). Ändern: `PATCH /me/events/{id}` (`update_event`). Absagen: `DELETE /me/events/{id}` (`delete_event`). Termin-Suche: `search_events(query, start, end)` — Substring-Match auf den Titel.
Es wird ausschließlich der Standard-Kalender (`/me/...`) genutzt — keine Kalender-Whitelist, kein `calendar_name`-Parameter. Änderungen an Serienterminen betreffen nur das einzelne Vorkommen.

### tasks_agent.py
MS Graph To-Do. Kein eigenes Class-Wrapper — direkte `httpx`-Calls mit Token aus `get_access_token()`.

`add_task(list_name, title, due_date=None, due_time=None)`:
- Setzt `dueDateTime`, `isReminderOn=True`, `reminderDateTime` auf `due_time` (Default: 09:00)
- System-Tasks werden in `get_tasks_raw()` via `_SYSTEM_TASK_PREFIXES` herausgefiltert

### memory_agent.py — MemoryAgent-Klasse
Embeddings via `sentence-transformers` (Modell wird lazy geladen, Fallback: kein Embedding).
Speichert Fakten aus Gesprächen → `MemoryDB`. Retrieval via Cosine-Similarity.
Wird nach jedem personal/work/research Response automatisch aufgerufen (`extract(user_msg, assistant_msg)`).

### proactive_agent.py
Alle Jobs sind async, laufen als APScheduler-Jobs.
- `check_important_mails()`: Holt ungelesene Inbox-Mails → Claude-Haiku-Wichtigkeitsprüfung → sendet Digest wenn wichtig. Bereits gemeldete Mails in `ProactiveDB` skippt.
- `send_task_reminder()`: Tasks > 2 Tage offen + nicht innerhalb 2 Tage erinnert → Telegram-Nachricht.
- `send_weekly_review()`: Freitags — abgeschlossene Tasks + Kalender-Woche → Claude-Sonnet-Zusammenfassung.

### router.py
Baut dynamisch einen System-Prompt mit aktuellen Kalender-Namen, To-Do-Listen, Mail-Ordnern.
Gibt JSON zurück: `{intent, confidence, params, reasoning}`. Confidence < 5 → Fallback-Antwort.

---

## Pending-State in app_state.py (Module-Level)

```python
_pending_mail_ops: dict[int, dict]       # Mail-Write-Op wartet auf Confirm-Button
_pending_calendar_ops: dict[int, dict]   # Kalender-Aktion (create/update/delete) wartet auf Confirm-Button
_last_mail_search: dict[int, dict]       # Mail-Multi-Treffer-Auswahl (TTL: 3 Min, timestamp im Dict)
_last_calendar_search: dict[int, dict]   # Termin-Multi-Treffer-Auswahl (TTL: 3 Min, timestamp im Dict)
_recent_conv: dict[int, list]            # Letzte Konversations-Paare (user + assistant) pro chat_id für Router-Kontext
```

---

## Callbacks (InlineKeyboard)

| Callback-Data | Handler | Aktion |
|---|---|---|
| `mail:send` | handle_callback | Compose-Entwurf absenden |
| `mail:cancel` | handle_callback | Compose-Entwurf verwerfen |
| `mail:action:confirm` | handle_callback | Pending Write-Op ausführen (archive/delete/move/reply/forward) |
| `mail:action:cancel` | handle_callback | Pending Write-Op + Suchergebnis verwerfen |
| `mail:select:{n}` | handle_callback | Mail n aus Multi-Treffer-Liste wählen → Confirm |
| `cal:action:confirm` | handle_callback | Pending Kalender-Aktion (Erstellen/Ändern/Absagen) ausführen |
| `cal:action:cancel` | handle_callback | Pending Kalender-Aktion verwerfen |
| `cal:select:{n}` | handle_callback | Termin n aus Multi-Treffer-Liste wählen → Confirm |

---

## MS Graph OAuth

**Scopes:** `Mail.ReadWrite` · `Mail.Send` · `Tasks.ReadWrite` · `Tasks.ReadWrite.Shared` · `Calendars.ReadWrite`
**Authority:** `https://login.microsoftonline.com/consumers` (persönliche MS-Accounts)
**Token-Cache:** `/var/lib/jarvis/.jarvis/microsoft_tokens.json` (MSAL SerializableTokenCache)
**Re-Auth:** `https://herrlich.dev/oauth/microsoft/login?secret=<OAUTH_LOGIN_SECRET>`

Achtung: Nach Scope-Änderung muss Re-Auth durchgeführt werden — MSAL upgraded Token nicht automatisch.
Kalender läuft seit der Outlook-Migration über MS Graph (`/me/calendarView`, `/me/events`).

---

## Tests

```bash
# Standard (kein Live-API-Zugang nötig)
PYTHONPATH=agents .venv/bin/pytest tests/ -q --tb=short \
  --ignore=tests/test_briefing_agent.py \
  --ignore=tests/test_mail_send.py \
  --ignore=tests/test_tasks_agent.py

# Mit Live-APIs (VPS oder VPN + MS-Token)
PYTHONPATH=agents .venv/bin/pytest tests/ -v --tb=short
```

**Test-Dateien:**

| Datei | Live-API? | Testet |
|---|---|---|
| test_mail_write.py | Nein | MailAgent Write-Methoden (mock requests) |
| test_memory_agent.py | Nein | MemoryAgent extract/retrieve |
| test_router_context.py | Nein | Router mit Kontext-Nachrichten |
| test_proactive_agent.py | Nein | ProactiveAgent-Logik (mock) |
| test_weather_agent.py | Nein | Weather-Parsing |
| test_briefing_agent.py | **Ja** | Briefing-Build (Live-APIs) |
| test_mail_send.py | **Ja** | Mail-Senden via MS Graph |
| test_tasks_agent.py | **Ja** | To-Do via MS Graph |

**Mock-Muster in test_mail_write.py:**
```python
with patch("agents.mail_agent.get_access_token", return_value="tok"), \
     patch("requests.post", return_value=_ok(200)) as mock_post:
    result = agent.archive("mail123")
```

---

## Neuen Agenten / Intent hinzufügen — Checkliste

1. **`agents/<name>_agent.py`** — Agenten-Logik implementieren
2. **`agents/router.py`** — neuen Intent in `_SYSTEM_TEMPLATE` dokumentieren (Beispiele + Parameter)
3. **`agents/router.py`** — Intent-Name in die Whitelist-Liste im `route_with_llm`-Validator eintragen
4. **`agents/dispatch.py`** — `elif intent == "<name>":` Block in `_process_text()` hinzufügen
5. **`tests/test_<name>.py`** — Unit-Tests (mocked)
6. **`CLAUDE.md`** — Agenten-Tabelle aktualisieren

---

## Proaktive Jobs (APScheduler)

| Job-ID | Cron | Funktion | Modell |
|---|---|---|---|
| `send_briefing` | Mo–Fr 07:00 Berlin | Morgenbriefing | Haiku |
| `check_important_mails` | 09:00 täglich | Mail-Wichtigkeitsprüfung | Haiku |
| `check_important_mails` | 14:00 täglich | Mail-Wichtigkeitsprüfung | Haiku |
| `send_task_reminder` | 10:00 täglich | Überfällige Tasks | — |
| `send_weekly_review` | Fr 17:00 | Wochenrückblick | Sonnet |

Jobs werden in `jarvis_jobs.db` (SQLite) persistiert — überleben Neustarts.

---

## GitHub Webhook — Auto-Deploy

`POST /webhook/github` — validiert HMAC, führt `git fetch + reset --hard origin/main` aus, dann repo-spezifische Post-Pull-Aktionen.

```python
_GITHUB_REPOS: dict[str, dict] = {
    "herrlich-ai-platform": {
        "git_path": "/opt/herrlich-ai-platform",
        "post_rsync": ("/opt/herrlich-ai-platform/agents/", "/opt/jarvis/"),
        "post_restart": "jarvis",
    },
    "high-five-website": {
        "git_path": "/opt/high-five-website",
        "post_docker": "/opt/high-five-website",
    },
    "immo-radar": {
        "git_path": "/opt/immo-radar",
        "post_docker": "/opt/immo-radar",
    },
    "refurbish-business": {
        "git_path": "/opt/refurbish-business",
        "post_docker": "/opt/refurbish-business",
    },
}
```

**Post-Pull-Aktionen:**
- `post_rsync`: rsync src → dst (sync agents/ ins laufende Service-Verzeichnis)
- `post_restart`: `systemctl restart <service>` (nach 3s Delay via Popen)
- `post_docker`: `docker compose up -d --build` im angegebenen Verzeichnis

**Voraussetzung für `post_restart`:** Der Webhook läuft als `jarvis`-User. Damit
`systemctl restart jarvis` nicht-interaktiv durchläuft, muss die polkit-Regel
`/etc/polkit-1/rules.d/49-jarvis-restart.rules` existieren — sie erlaubt dem
`jarvis`-User das Verwalten von `jarvis.service`. Fehlt sie, scheitert der
Restart still mit „Interactive authentication required": git-pull + rsync laufen
durch, aber der Prozess lädt den neuen Code **nicht** — Deploys wirken erst beim
nächsten manuellen Neustart. Bei VPS-Neuaufbau die Regel mit anlegen.

---

## Key Commands

```bash
# Tests lokal
PYTHONPATH=agents .venv/bin/pytest tests/ -q --tb=short \
  --ignore=tests/test_briefing_agent.py \
  --ignore=tests/test_mail_send.py \
  --ignore=tests/test_tasks_agent.py

# Deploy auf VPS — läuft automatisch via GitHub Webhook nach git push
# Manuell (Notfall):
ssh root@100.115.184.3 "cd /opt/herrlich-ai-platform && git pull && rsync -a --delete agents/ /opt/jarvis/ && systemctl restart jarvis"

# Logs live
ssh root@100.115.184.3 "journalctl -u jarvis -f --no-pager"

# Service-Status
ssh root@100.115.184.3 "systemctl status jarvis"

# VPS direkt öffnen
ssh root@100.115.184.3
```

---

## Agentischer Pfad — Phase 1 (live seit 18.05.2026)

`personal`/`work`/`research` laufen durch einen echten Agenten
(`agents/agent.py`, Claude Agent SDK) statt durch die alten Single-shot-
`chat_handler`-Funktionen. Der Router bleibt
vorerst vorgelagert — strukturierte Intents (`mail`, `calendar`, …) laufen
unverändert über ihre Handler. Verklassifiziert der Router eine Frage (z.B. als
`mail`), erreicht sie den Agenten nicht — bekannte Limitierung, behoben in Phase 3.

- `agents/agent.py` — `run_agent()`: ein zustandsloser SDK-Lauf pro Nachricht,
  History als Text eingebettet, Antwort an Telegram. Pro Chat serialisiert.
- `agents/tools/` — Tool-Paket: `workspace_tool.py` (`workspace`-Tool: Datei
  lesen/suchen/listen, sandboxed auf `JARVIS_WORKSPACE_DIR`) + Registry
  `__init__.py` (MCP-Server-Bau, `can_use_tool`-Permission-Hook).
- Werkzeuge: `workspace`, `weather`, `news` + die eingebauten `WebSearch`/`WebFetch`. Built-in
  `Bash`/`Edit`/`Read` sind für den Agenten deaktiviert.

### Auth, Billing & Runtime (VPS)

Das Agent SDK startet die `claude`-CLI als Subprozess. Aktueller Stand:

- **Billing übers Abo:** `run_agent` setzt `env={"ANTHROPIC_API_KEY": ""}` — die CLI
  ignoriert den API-Key und nutzt `CLAUDE_CODE_OAUTH_TOKEN` (in `/var/lib/jarvis/.env`).
  Der jarvis-Prozess behält `ANTHROPIC_API_KEY` für die alten Agenten (Router/Memory).
- **Workspace:** `JARVIS_WORKSPACE_DIR=/home/claude/workspace`; `jarvis` hat via
  `setfacl -m u:jarvis:--x /home/claude` Traverse-Recht (einmalig gesetzt).
- **CLI:** Claude Code CLI unter `/usr/bin/claude`, `claude-agent-sdk` im venv
  `/opt/jarvis/venv/`.

**Rollback:** Per `git revert` des betroffenen Commits + Redeploy (GitHub-Webhook
oder manueller Neustart). Das frühere Feature-Flag `JARVIS_AGENT_ENABLED` ist mit
Phase 2 entfallen.

Live-Smoke-Test: `JARVIS_LIVE_TESTS=1 PYTHONPATH=agents .venv/bin/pytest tests/test_agent_live.py -v`

---

## Stack

Python 3.11 · FastAPI · python-telegram-bot · anthropic SDK · MSAL · APScheduler 3.x
MS Graph API · Open-Meteo · Groq Whisper · systemd · Caddy

---

## Bekannte Eigenheiten & Fallstricke

- **Alle Agenten im gleichen Prozess** — kein Microservice-Split, kein shared state zwischen Requests außer den module-level Dicts
- **Router-Kontext**: interleaved User+Jarvis-Paare — letzte Einträge aus `_recent_conv`
- **Conversation History** nur für `personal`/`work`/`research` — andere Intents haben kein Claude-Gedächtnis
- **Memory-Extraktion** läuft async nach jedem personal/work/research Response (nicht blockierend)
- **MS Graph `/archive`-Endpoint** existiert nicht für persönliche Accounts → wird als `move` mit `destinationId: "archive"` implementiert
- **Briefing** kann Markdown-Fehler produzieren (unkontrollierte `*`/`_` in News/Kalender) → automatischer Plaintext-Fallback
- **Erinnerungen** — laufen vollständig über MS To Do (`tasks_agent`, Intent `reminder_write`); kein Apple/CalDAV-Pfad mehr
- **Kalender-Schreibaktionen** — Erstellen, Ändern und Absagen zeigen einen Confirm-Dialog (Callbacks `cal:action:*`); bei mehreren Treffern zuerst Auswahl via `cal:select:{n}`, analog zu Mail-Write
- **PYTHONPATH=agents** muss immer gesetzt sein — alle Agenten importieren sich gegenseitig ohne Package-Prefix
- **`.venv`** liegt im Projekt-Root — auf VPS ist es `/opt/jarvis/venv/`
- **VPS-Code** unter `/opt/herrlich-ai-platform/` (git clone), rsync synchronisiert `agents/` → `/opt/jarvis/` nach jedem Pull; systemd liest Secrets aus `/var/lib/jarvis/.env`
