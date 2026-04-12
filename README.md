# herrlich-ai-platform

Persoenliche KI-Plattform (Jarvis) auf Hetzner VPS.

## Stack

- VPS: Hetzner CX33, Ubuntu 24.04, Helsinki
- Domain: herrlich.dev (Cloudflare)
- Zugang: Tailscale VPN, code.herrlich.dev (VS Code im Browser)
- Bot: Telegram @jarvis_herrlich_bot (FastAPI, Python)
- Coding: Claude Code CLI als claude-User, YOLO Mode, Hooks
- Modelle: Haiku fuer Coding/Personal, Sonnet fuer Work/Research

## Struktur

agents/main.py                 Bot-Gateway (FastAPI)
agents/claude-settings.json    Claude Code Hook-Konfiguration
scripts/claude-guard.sh        Hook-Skript (Blockliste)
config/caddy/Caddyfile         Reverse Proxy Konfiguration
config/jarvis.service          systemd Service
docs/setup-vps.md              VPS Setup Anleitung
docs/architecture.md           Architektur-Dokument
docs/mac-setup.md              Mac Setup (codeopen, zshrc)

## Drei Kontexte

1. Coding - Claude Code startet autonom auf dem VPS
2. Work - Strategieberatung, Push-Modell
3. Personal - Apple Calendar, iCloud

## Workspace

VPS: /home/claude/workspace/
Mac: ~/Library/Mobile Documents/.../04_Sonstiges/01_Coding/
Sync: GitHub (Source of Truth)

## Laufende Kosten

Hetzner CX33: ~8,50 Euro/Mo
herrlich.dev Domain: ~1,00 Euro/Mo
Anthropic API: ~2-5 Euro/Mo geschaetzt
Claude Max Abo: bereits vorhanden
