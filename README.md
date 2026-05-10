# herrlich-ai-platform — Jarvis

Persönlicher KI-Assistent via Telegram. Läuft als FastAPI-Service auf einem Hetzner VPS, routet Nachrichten über Claude an spezialisierte Agenten und agiert proaktiv über geplante Jobs.

**Bot:** [@jarvis_herrlich_bot](https://t.me/jarvis_herrlich_bot) | **Live:** herrlich.dev | **VPS:** Hetzner CX33, Helsinki

---

## Was Jarvis kann

### Kommunikation & Mail (MS Graph)
- Posteingang lesen, Mails suchen, Ordner durchsuchen
- Mails **schreiben, archivieren, verschieben, löschen**
- Als gelesen/ungelesen markieren, **antworten, weiterleiten**
- Smart-Search: Mails per Freitext finden ("letzte Mail von Sparkasse")
- Bestätigungs-Dialog vor destruktiven Aktionen

### Kalender (MS365 CalDAV)
- Termine lesen (heute, morgen, diese Woche, nächster Termin)
- Termine erstellen und Erinnerungen anlegen

### Aufgaben (Microsoft To-Do)
- Tasks lesen, erstellen (mit Fälligkeitsdatum + Uhrzeit), abschließen
- Listen anlegen, umbenennen, löschen
- Automatischer Reminder bei überfälligen Tasks (täglich 14:00)

### Wetter
- Aktuelle Wetterlage + stündliche Vorhersage
- Ortseingabe ("Wie wird das Wetter in Berlin?")
- Tages-/Morgen-/Wochenübersicht

### Nachrichten
- RSS-Feeds zusammengefasst via Claude
- Technologie-News auf Abruf

### Coding-Assistent
- Claude Code auf VPS triggern (Fragen + autonome Aktionen)
- GitHub: PRs, Issues, Commits abfragen

### Proaktive Benachrichtigungen (APScheduler)
| Zeit | Job |
|---|---|
| Mo–Fr 07:00 | Morgenbriefing (News + Kalender + Wetter + offene Tasks) |
| 09:00 + 14:00 | Wichtige ungelesene Mails prüfen & melden |
| 14:00 | Überfällige Task-Erinnerung (> 2 Tage offen) |
| Fr 17:00 | Wochenrückblick (abgeschlossene Tasks + Kalender) |

### Gedächtnis & Profil
- Automatische Memory-Extraktion aus Gesprächen (personal/work/research)
- Persistente Notizen & Fakten via SQLite + Embeddings
- Nutzerprofil-Kontext für personalisierte Antworten
- Gesprächsverlauf (letzte 20 Nachrichten) für personal/work/research

### Sprachnachrichten
- Telegram-Sprachnachrichten werden transkribiert und wie Text verarbeitet

---

## Architektur

```
Telegram Webhook
      │
      ▼
agents/main.py          FastAPI Gateway — empfängt Updates, dispatcht
      │
      ▼
agents/router.py        Claude Haiku — klassifiziert Intent (+ letzte 3 Nachrichten als Kontext)
      │
      ├── mail          mail_agent.py       MS Graph Mail (lesen + schreiben)
      ├── calendar      calendar_agent.py   MS365 CalDAV
      ├── tasks         tasks_agent.py      Microsoft To-Do
      ├── reminder_write tasks_agent.py     To-Do mit Datum/Uhrzeit
      ├── weather       weather_agent.py    Open-Meteo API
      ├── news          news_agent.py       RSS + Claude
      ├── briefing      briefing_agent.py   Tages-Briefing aggregiert
      ├── coding        coding_agent.py     Claude Code auf VPS
      ├── personal      main.py + memory    Claude + Gedächtnis
      ├── work          main.py             Claude Sonnet
      ├── research      main.py             Claude + Web-Search
      └── memory        memory_agent.py     Notizen verwalten

APScheduler (SQLite Jobstore, restart-safe)
      └── proactive_agent.py  Briefing, Mail-Check, Task-Reminder, Weekly Review

Persistenz:
      agents/db.py            ConversationDB (SQLite)
      agents/memory_agent.py  MemoryDB (SQLite + Embeddings)
      agents/proactive_agent.py ProactiveDB (SQLite, reported_mails + reminded_tasks)
```

---

## Stack

| Komponente | Technologie |
|---|---|
| Sprache | Python 3.11 |
| Web-Framework | FastAPI + Uvicorn |
| Bot-API | python-telegram-bot |
| KI | Anthropic Claude (Haiku für Routing, Sonnet für Work/Research) |
| MS-Integration | MSAL + MS Graph API (Mail.ReadWrite, Calendars.ReadWrite, Tasks.ReadWrite) |
| Kalender | CalDAV (MS365) |
| Wetter | Open-Meteo API (kostenlos) |
| Persistenz | SQLite (Conversations, Memory, Proactive State) |
| Scheduler | APScheduler 3.x mit SQLAlchemyJobStore |
| Reverse Proxy | Caddy |
| Prozess-Management | systemd |
| VPN | Tailscale |

---

## Infrastruktur

```
Hetzner CX33 (4 vCPU, 8 GB RAM, Ubuntu 24.04, Helsinki)
├── jarvis.service          systemd — läuft als root, Port 9000
├── caddy                   Reverse Proxy — herrlich.dev → :9000
├── /root/agents/           Git-Checkout (Source of Truth: GitHub)
└── /root/.env              Secrets (TELEGRAM_BOT_TOKEN, ANTHROPIC_API_KEY, ...)

Mac (Entwicklung)
├── ~/Documents/.../herrlich-ai-platform/   lokaler Clone
├── .venv/                                  lokale virtuelle Umgebung
└── launchd                                 auto git pull alle 10 Min
```

**Laufende Kosten:** Hetzner ~8,50 €/Mo · Domain ~1 €/Mo · Anthropic API ~2–5 €/Mo

---

## Zugang

```bash
ssh root@100.115.184.3              # VPS via Tailscale
code.herrlich.dev                   # VS Code im Browser
journalctl -u jarvis -f --no-pager  # Logs live
```

---

## Deployment

```bash
# Von Mac: Push → VPS zieht automatisch beim nächsten Pull (launchd, alle 10 Min)
# Oder manuell:
ssh root@100.115.184.3 "cd /root/agents && git pull && systemctl restart jarvis"
```

---

## Sicherheit

- `agents/claude-settings.json` — Claude Code Permission-Konfiguration
- `scripts/claude-guard.sh` — Bash-Hook: blockt destruktive Befehle (rm -rf /, cat .env, ufw disable, …)
- `.env` aus systemd `EnvironmentFile=/root/.env` geladen — nie im Repo
- MS OAuth Token unter `/root/.jarvis/microsoft_tokens.json` (aus Claude-Lesezugriff geblockt)
