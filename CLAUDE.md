# Jarvis — herrlich-ai-platform

Persönlicher KI-Assistent via Telegram (@jarvis_herrlich_bot). FastAPI-Gateway auf Hetzner VPS, routet Nachrichten per Claude Haiku an spezialisierte Agenten.

**Stack:** Python 3.11 · FastAPI · python-telegram-bot · anthropic SDK · MSAL · APScheduler 3.x · MS Graph API · Open-Meteo · Groq Whisper · systemd · Caddy
**Live:** herrlich.dev | VPS: `root@100.115.184.3` (Tailscale) | Service: `jarvis.service`

## Architektur

```
Telegram Webhook (POST /webhook/telegram)
        │
        ▼
agents/main.py              FastAPI Gateway + APScheduler
        │
        ├── Voice? → voice_agent.py → transkribieren → weiter als Text
        │
        ▼
agents/agent.py run_agent   Claude Agent SDK — alle Nachrichten
        │                   Tools: workspace/weather/news/tasks/mail/calendar/
        │                   coding/briefing/memory + WebSearch/WebFetch
        │                   History, MemoryAgent, Write-Confirm
        │

APScheduler (SQLite Jobstore, restart-safe):
        └── proactive_agent.py
```

## Struktur

```
agents/
  main.py               FastAPI-App, Routen, startup/shutdown
  dispatch.py           Telegram-Dispatch: _process_text-Orchestrator + handle_message/voice/start
  app_state.py          Geteilter State (Pending-Agenten-Aktionen, lazy Agenten) + TTL-Helper
  formatting.py         Reine Formatter (Kalender/Mail/Markdown)
  intent_handlers.py    send_briefing (APScheduler-Proaktiv-Job)
  callbacks.py          InlineKeyboard-Callback-Router (handle_callback)
  github_webhook.py     GitHub-Auto-Deploy-Webhook
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

## Deploy

```bash
# Deploy auf VPS — automatisch via GitHub Webhook nach git push
# Manuell (Notfall):
ssh root@100.115.184.3 "cd /opt/herrlich-ai-platform && git pull && rsync -a --delete agents/ /opt/jarvis/ && systemctl restart jarvis"

# Logs live
ssh root@100.115.184.3 "journalctl -u jarvis -f --no-pager"

# Service-Status
ssh root@100.115.184.3 "systemctl status jarvis"

# VPS direkt öffnen
ssh root@100.115.184.3
# VS Code Browser
# code.herrlich.dev
```

**GitHub Webhook Auto-Deploy:** `POST /webhook/github` — validiert HMAC, `git fetch + reset --hard origin/main`, dann `post_rsync` (agents/ → /opt/jarvis/) + `systemctl restart jarvis` (benötigt polkit-Regel `/etc/polkit-1/rules.d/49-jarvis-restart.rules`).

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

## Arbeiten an diesem Projekt

MUSS vor Implementierungsarbeit gelesen werden: `DEVELOPMENT.md`.

## Projekt-spezifische Konventionen

### Environment Variables (`/var/lib/jarvis/.env` auf VPS)

| Variable | Pflicht | Beschreibung |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ | Bot-Token von @BotFather |
| `TELEGRAM_CHAT_ID` | ✅ | Chat-ID für proaktive Nachrichten |
| `ANTHROPIC_API_KEY` | ✅ | Anthropic API Key |
| `MICROSOFT_CLIENT_ID` | ✅ | Azure App Registration Client ID |
| `MICROSOFT_CLIENT_SECRET` | ✅ | Azure App Registration Client Secret |
| `OAUTH_LOGIN_SECRET` | ✅ | Schützt `/oauth/microsoft/login` |
| `GITHUB_TOKEN` | ✅ | GitHub Personal Access Token |
| `GITHUB_WEBHOOK_SECRET` | ✅ | HMAC-Secret für GitHub Webhook |
| `GROQ_API_KEY` | ✅ | Groq API Key für Whisper |
| `JARVIS_AGENT_MODEL` | ❌ | Modell für Agenten (Default: `claude-sonnet-4-6`) |
| `JARVIS_WORKSPACE_DIR` | ❌ | Workspace-Root (Default: `~/Code`) |
| `JARVIS_CLAUDE_CLI_PATH` | ❌ | Pfad zur `claude`-CLI |
| `CLAUDE_CODE_OAUTH_TOKEN` | ❌ | OAuth-Token der Claude Code CLI (headless) |
| `JARVIS_DATA_DIR` | ❌ | Pfad für DBs + Tokens (Default: `/var/lib/jarvis/.jarvis`) |
| `REMINDER_TODO_LIST` | ❌ | To-Do-Liste für Erinnerungen (Default: `Tasks`) |
| `WEATHER_LAT` / `WEATHER_LON` | ❌ | Heimatort-Koordinaten (Default: Tutzing) |
| `WEATHER_LOCATION_NAME` | ❌ | Anzeigename (Default: `Tutzing`) |

### Datenbank-Dateien (`/var/lib/jarvis/.jarvis/`)

| Datei | Klasse | Inhalt |
|---|---|---|
| `conversations.db` | `ConversationDB` | Gesprächsverlauf (nur personal/work/research) |
| `memories.db` | `MemoryDB` | Extrahierte Fakten + Embeddings |
| `sessions.db` | `SessionDB` | Claude-Code-Session-IDs (TTL 2h) |
| `proactive.db` | `ProactiveDB` | reported_mails + reminded_tasks (30-Tage-TTL) |
| `microsoft_tokens.json` | — | MSAL Token-Cache |
| `jarvis_jobs.db` | APScheduler | Persistente Job-Definitionen |

### Claude-Modelle

| Verwendung | Modell |
|---|---|
| Intent-Routing | `claude-haiku-4-5-20251001` |
| Personal / Work / Research | `claude-sonnet-4-6` |
| Mail-Importance, Memory, Briefing | `claude-haiku-4-5-20251001` |
| Weekly Review | `claude-sonnet-4-6` |

### Proaktive Jobs (APScheduler)

| Job-ID | Cron | Funktion |
|---|---|---|
| `send_briefing` | Mo–Fr 07:00 Berlin | Morgenbriefing (Haiku) |
| `check_important_mails` | 09:00 + 14:00 | Mail-Wichtigkeitsprüfung (Haiku) |
| `send_task_reminder` | 10:00 | Überfällige Tasks |
| `send_weekly_review` | Fr 17:00 | Wochenrückblick (Sonnet) |

### Pending-State in `app_state.py`

```python
pending_agent_actions: dict[int, dict]   # Vorgemerkte Agenten-Schreibaktionen (Write-Confirm)
_recent_conv: dict[int, list]            # Letzte Konversations-Paare für Router-Kontext
```

### Callbacks (InlineKeyboard)

| Callback-Data | Aktion |
|---|---|
| `push:{project}` | Git-Push für ein Projekt auslösen |
| `dismiss` | Keyboard entfernen ohne Aktion |
| `agent:confirm:{id}` | Vorgemerkte Agenten-Schreibaktionen ausführen |
| `agent:cancel:{id}` | Vorgemerkte Agenten-Schreibaktionen verwerfen |

### MS Graph OAuth

**Scopes:** `Mail.ReadWrite` · `Mail.Send` · `Tasks.ReadWrite` · `Tasks.ReadWrite.Shared` · `Calendars.ReadWrite`
**Re-Auth:** `https://herrlich.dev/oauth/microsoft/login?secret=<OAUTH_LOGIN_SECRET>`
Nach Scope-Änderung muss Re-Auth durchgeführt werden.

### Neues Tool hinzufügen

1. `agents/<name>_agent.py` — Agenten-Logik (falls noch nicht vorhanden)
2. `agents/tools/<name>_tool.py` — Tool-Objekt + `execute_write` (falls Schreib-Aktionen)
3. `agents/tools/__init__.py` — Tool in `_STATIC_TOOLS` oder `_all_tools()` + `_WRITE_EXECUTORS` eintragen
4. `agents/agent.py` — `build_system_prompt()` um Tool-Beschreibung ergänzen
5. `tests/test_<name>.py` — Unit-Tests (mocked)
6. `CLAUDE.md` — Dokumentation aktualisieren

### Agentischer Pfad (Phasen 1–3 abgeschlossen)

Alle Nachrichten laufen direkt durch `agents/agent.py` (Claude Agent SDK, `run_agent()`). Kein Router mehr vorgelagert.

- **Billing übers Abo:** `run_agent` setzt `env={"ANTHROPIC_API_KEY": ""}` — CLI nutzt `CLAUDE_CODE_OAUTH_TOKEN`.
- **Workspace:** `JARVIS_WORKSPACE_DIR=/home/claude/workspace`; jarvis hat Traverse-Recht via `setfacl`.
- **CLI:** `/usr/bin/claude`, SDK-venv `/opt/jarvis/venv/`.
- **Werkzeuge:** `workspace`, `weather`, `news`, `tasks`, `mail`, `calendar`, `coding`, `briefing`, `memory` + die eingebauten `WebSearch`/`WebFetch`.
- Live-Smoke-Test: `JARVIS_LIVE_TESTS=1 PYTHONPATH=agents .venv/bin/pytest tests/test_agent_live.py -v`

**Write-Confirm:** Schreib-Aktionen von Tools (ab `tasks`) führen nicht direkt
aus — sie werden vorgemerkt (`app_state.pending_agent_actions`, je Lauf ein Set
mit ID), `run_agent` hängt am Lauf-Ende einen gebündelten InlineKeyboard-Confirm
an. Die Callbacks `agent:confirm:{id}`/`agent:cancel:{id}` führen aus bzw.
verwerfen; die ID verhindert, dass ein veralteter Button fremde Aktionen ausführt.

### Bekannte Eigenheiten & Fallstricke

- Alle Agenten im gleichen Prozess — kein Microservice-Split
- `PYTHONPATH=agents` muss immer gesetzt sein
- `.venv` im Projekt-Root; auf VPS: `/opt/jarvis/venv/`
- VPS-Code unter `/opt/herrlich-ai-platform/`; rsync → `/opt/jarvis/`; Secrets aus `/var/lib/jarvis/.env`
- MS Graph `/archive` existiert nicht für persönliche Accounts → `move` mit `destinationId: "archive"`
- Conversation History für alle Nachrichten (kein Intent-Gate mehr)
- Mail- und Kalender-Schreibaktionen laufen durch Write-Confirm (agent-Tools)
- polkit-Regel auf VPS nötig für Webhook-Restart: fehlt sie → rsync läuft, Neustart scheitert still

---

@.claude/CONVENTIONS.md
