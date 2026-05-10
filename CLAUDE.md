# Jarvis — herrlich-ai-platform

Persönlicher KI-Assistent via Telegram (@jarvis_herrlich_bot). FastAPI-Gateway auf VPS, routet Nachrichten per Claude an spezialisierte Agenten.

**VPS:** `root@100.115.184.3` (Tailscale) | **Service:** `jarvis.service` | **Live:** herrlich.dev

---

## Architektur

```
agents/main.py          Telegram-Webhook-Gateway (FastAPI) + APScheduler
agents/router.py        Claude Haiku — Intent-Routing (mit 3-Nachrichten-Kontext)
agents/proactive_agent.py  Scheduler-Jobs (Briefing, Mail-Check, Task-Reminder, Weekly)
agents/<name>.py        Spezialisierte Agenten (siehe unten)
agents/db.py            ConversationDB (SQLite)
agents/microsoft_auth.py   MSAL OAuth-Flow für MS Graph
config/                 Caddy Caddyfile, jarvis.service
scripts/claude-guard.sh Bash-Hook: Blockliste für destruktive Kommandos
tests/                  pytest — immer mit PYTHONPATH=agents ausführen
```

## Agenten

| Agent | Datei | Intents | Funktion |
|---|---|---|---|
| Briefing | briefing_agent.py | briefing | Tages-Briefing (News + Kalender + Wetter + Tasks) |
| Calendar | calendar_agent.py | calendar | MS365 CalDAV lesen + Termine/Erinnerungen schreiben |
| Coding | coding_agent.py | coding | Claude Code auf VPS triggern (Fragen + Aktionen) |
| GitHub | github_agent.py | coding | PRs, Issues, Commits via gh CLI |
| Mail | mail_agent.py | mail | MS Graph Mail lesen + schreiben (alle Write-Ops) |
| Memory | memory_agent.py | memory | Notizen & Fakten (list, delete, auto-extract) |
| News | news_agent.py | news | RSS-Feeds via Claude zusammenfassen |
| Profile | profile_agent.py | — | Nutzerprofil-Kontext (wird in Startup geladen) |
| Proactive | proactive_agent.py | — | APScheduler-Jobs (kein direkter Intent) |
| Tasks | tasks_agent.py | tasks, reminder_write | MS To-Do lesen + schreiben |
| Voice | voice_agent.py | — | Telegram-Sprachnachrichten transkribieren |
| Weather | weather_agent.py | weather | Open-Meteo Wetter (heute/morgen/Woche, Geocoding) |

## Mail-Agent Modi (mail intent)

**Lesen:** `quick_scan` · `unread` · `search` · `list_folders`

**Schreiben (Write-Ops mit Smart-Search + Confirm-Dialog):**
`compose` · `mark_read` · `mark_unread` · `archive` · `move` · `delete` · `reply` · `forward`

Write-Ops nutzen `smart_search(mail_query, n=50)` zur Mail-Identifikation.
Ergebnis 0 → Fehlermeldung | 1 → direkt Confirm | 2–5 → InlineKeyboard-Auswahl | >5 → "zu viele Treffer"
`mark_read`/`mark_unread` ohne Confirm-Dialog (trivial reversibel).

## Pending State (main.py)

```python
_pending_mail_ops: dict[int, dict]   # Mail-Write-Op wartet auf Confirm-Button
_last_mail_search: dict[int, dict]   # Multi-Treffer-Auswahl (TTL: 3 Min)
_recent_user_texts: dict[int, list]  # Letzte 10 User-Nachrichten für Router-Kontext
```

## Callbacks (InlineKeyboard)

| Callback | Aktion |
|---|---|
| `mail:send` | Compose-Entwurf absenden |
| `mail:cancel` | Compose-Entwurf verwerfen |
| `mail:action:confirm` | Pending Write-Op ausführen |
| `mail:action:cancel` | Pending Write-Op verwerfen |
| `mail:select:{n}` | Mail n aus Multi-Treffer-Liste auswählen |

## Proaktive Jobs (APScheduler, SQLite Jobstore)

| Job | Cron | Funktion |
|---|---|---|
| send_briefing | Mo–Fr 07:00 Berlin | Morgenbriefing |
| check_important_mails | 09:00 + 14:00 | Ungelesene Mails → Claude-Wichtigkeitsprüfung |
| send_task_reminder | 14:00 | Tasks > 2 Tage offen → Erinnerung |
| send_weekly_review | Fr 17:00 | Wochenrückblick |

## MS Graph OAuth

Scopes: `Mail.ReadWrite` · `Mail.Send` · `Tasks.ReadWrite` · `Tasks.ReadWrite.Shared`
Re-Auth-URL: `https://herrlich.dev/oauth/microsoft/login?secret=<OAUTH_LOGIN_SECRET>`
Token-Speicher: `/root/.jarvis/microsoft_tokens.json`

## Key Commands

```bash
# Tests (lokal, ohne externe APIs)
PYTHONPATH=agents .venv/bin/pytest tests/ -q --tb=short \
  --ignore=tests/test_briefing_agent.py \
  --ignore=tests/test_mail_send.py \
  --ignore=tests/test_tasks_agent.py

# Deploy auf VPS
ssh root@100.115.184.3 "cd /root/agents && git pull && systemctl restart jarvis"

# Logs live
ssh root@100.115.184.3 "journalctl -u jarvis -f --no-pager"

# Service-Status
ssh root@100.115.184.3 "systemctl status jarvis"
```

## Stack

Python 3.11 · FastAPI · python-telegram-bot · anthropic SDK · MSAL · APScheduler
MS Graph API · CalDAV · Open-Meteo · systemd · Caddy

## Besonderheiten

- Alle Agenten laufen im gleichen Prozess (kein Microservice-Split)
- Router nutzt Claude Haiku für Intent-Routing + letzte 3 User-Nachrichten als Kontext
- Conversation History (letzte 20 Nachrichten) nur für `personal`/`work`/`research` Intents
- Memory-Extraktion läuft automatisch nach jedem `personal`/`work`/`research` Response
- `test_briefing_agent`, `test_mail_send`, `test_tasks_agent` → Live-API nötig, lokal ignorieren
- `.venv` liegt im Projekt-Root, `PYTHONPATH=agents` immer setzen
- VPS-Code: `/root/agents/` (git clone), systemd liest Secrets aus `/root/.env`
- `agents/claude-settings.json` + `scripts/claude-guard.sh` = Claude Code Hook-Config auf VPS
- Briefing-Text mit Markdown-Fehler → automatischer Fallback auf Plaintext
