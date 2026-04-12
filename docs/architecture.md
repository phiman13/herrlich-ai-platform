# Remote AI-Plattform - Architektur

Siehe remote-ai-platform-architektur-v2.md im Claude-Projekt fuer das vollstaendige Dokument.

## Kurzuebersicht

Interface: WhatsApp / Telegram / Browser
Gateway: Bot-Gateway (FastAPI) + Intent-Router
Agenten: Coding / Work / Personal
Ausfuehrung: Claude Code (Max) + Claude API (Haiku/Sonnet)
Daten: GitHub (Code) + SQLite (Gedaechtnis) + iCloud (Assets)
Infra: VPS + Tailscale + Caddy + Docker

## Intent-Routing

Coding (Frage)  -> Claude API Haiku  (liest Projektdateien)
Coding (Aktion) -> Claude Code YOLO  (arbeitet autonom, Max Abo)
Research        -> Claude API Sonnet + web_search
Work            -> Claude API Sonnet + web_search
Personal        -> Claude API Haiku
