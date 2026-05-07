# Jarvis — herrlich-ai-platform

Persönlicher KI-Assistent via Telegram (@jarvis_herrlich_bot). FastAPI-Gateway auf VPS, routet Nachrichten per Claude an spezialisierte Agenten.

**VPS:** `root@100.115.184.3` (Tailscale) | **Service:** `jarvis.service` | **Live:** herrlich.dev

---

## Architektur

```
agents/main.py      Telegram-Webhook-Gateway (FastAPI)
agents/router.py    Claude-basiertes Intent-Routing
agents/<name>.py    Spezialisierte Agenten (siehe unten)
agents/db.py        SQLite-Persistenz (Conversations)
config/             caddy Caddyfile, jarvis.service
scripts/            Hilfsskripte (claude-guard.sh etc.)
tests/              pytest — immer mit PYTHONPATH=agents ausführen
```

## Agenten

| Agent | Datei | Funktion |
|---|---|---|
| Briefing | briefing_agent.py | Tages-Briefing (News, Kalender, Wetter) |
| Calendar | calendar_agent.py | MS365-Kalender lesen/schreiben |
| Coding | coding_agent.py | Claude Code auf VPS triggern |
| GitHub | github_agent.py | PRs, Issues, Commits |
| Mail | mail_agent.py | MS365 Mails lesen/senden |
| Memory | memory_agent.py | Persönliche Notizen & Fakten |
| News | news_agent.py | RSS-Feeds zusammenfassen |
| Profile | profile_agent.py | Nutzerprofil-Kontext |
| Tasks | tasks_agent.py | Microsoft To-Do |
| Voice | voice_agent.py | Sprachnachrichten transkribieren |
| Weather | weather_agent.py | Wetter-Abfragen |

## Key Commands

```bash
# Tests (lokal, ohne externe APIs)
PYTHONPATH=agents .venv/bin/pytest tests/ -q --tb=short \
  --ignore=tests/test_briefing_agent.py \
  --ignore=tests/test_mail_send.py \
  --ignore=tests/test_tasks_agent.py

# Alle Tests inkl. Live-APIs (VPN/MS-Token nötig)
PYTHONPATH=agents .venv/bin/pytest tests/ -v --tb=short

# Deploy auf VPS
ssh root@100.115.184.3 "cd /root/agents && git pull && systemctl restart jarvis"

# Logs live
ssh root@100.115.184.3 "journalctl -u jarvis -f --no-pager"

# Service-Status
ssh root@100.115.184.3 "systemctl status jarvis"
```

## Stack

Python 3.11 · FastAPI · anthropic SDK · systemd · Caddy (Reverse Proxy)
MS Graph API (Mail + Kalender + Tasks) · Telegram Bot API

## Besonderheiten

- Alle Agenten laufen im gleichen Prozess — kein Microservice-Split
- Router nutzt Claude für Intent-Routing, dann den passenden Agenten-Call
- `test_briefing_agent`, `test_mail_send`, `test_tasks_agent` brauchen Live-API-Zugänge → lokal immer ignorieren
- `.venv` liegt im Projekt-Root, `PYTHONPATH=agents` muss immer gesetzt sein
- VPS-Code liegt unter `/root/agents/` (git clone), systemd liest `.env` aus dem Verzeichnis
- `agents/claude-settings.json` + `scripts/claude-guard.sh` = Claude Code Hook-Config auf dem VPS (Blockliste für destruktive Kommandos)
