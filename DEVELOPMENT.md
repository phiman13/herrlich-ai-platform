# Entwicklung — herrlich-ai-platform

> Projekt-spezifischer Workflow (mittleres Gewicht). On-demand gelesen — der
> Pointer steht in `CLAUDE.md`. Die universelle Arbeitsweise-Baseline steht im
> Kern (`.claude/CONVENTIONS.md`) und wird hier nicht wiederholt.

## Workflow

1. Tests lokal ausführen bevor Änderungen gepusht werden.
2. `git push` → GitHub Webhook triggert automatisch Deploy + Neustart auf VPS.
3. Nach Deploy: Logs kurz prüfen (`journalctl -u jarvis -n 30 --no-pager`).
4. Bei kritischen Fehlern: Rollback via `git revert` + erneuter Push.

**Tests lokal:**
```bash
PYTHONPATH=agents .venv/bin/pytest tests/ -q --tb=short \
  --ignore=tests/test_briefing_agent.py \
  --ignore=tests/test_mail_send.py \
  --ignore=tests/test_tasks_agent.py
```

Live-API-Tests (brauchen VPS-Zugang oder VPN + MS-Token):
```bash
PYTHONPATH=agents .venv/bin/pytest tests/ -v --tb=short
```

## Review & Verifikation

- Vor PR: alle Non-Live-Tests grün.
- Neue Agenten: Unit-Test (mocked) in `tests/test_<name>.py` ist Pflicht.
- Nach Deploy: kurzen Smoke-Test via Telegram durchführen (Test-Nachricht schicken).
- Nach Agent-SDK-Änderungen: Live-Smoke-Test ausführen.

## Anti-Patterns

- `PYTHONPATH=agents` vergessen → ImportError beim Test-Lauf.
- Direkt auf `/opt/jarvis/` editieren statt deploy-flow nutzen → nächster Deploy
  überschreibt Änderungen.
- `ANTHROPIC_API_KEY` für `run_agent()` setzen → Billing geht aufs API-Konto statt
  Abo; muss leer bleiben.
- Scope-Änderung an MS Graph ohne Re-Auth → Token-Fehler in Produktion.
- polkit-Regel auf VPS vergessen → GitHub Webhook rsync läuft, aber Neustart
  scheitert still; neuer Code ist nicht aktiv.
- Neue `.db`-Datei in `/tmp` oder Home anlegen → geht nach Neustart verloren;
  immer in `JARVIS_DATA_DIR`.

## Skills

<!-- A.2: Skill-Routing schärfen -->
