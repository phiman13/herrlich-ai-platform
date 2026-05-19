Führe die Jarvis-Tests aus (ohne Live-API-Tests):

```bash
PYTHONPATH=agents .venv/bin/pytest tests/ -q --tb=short \
  --ignore=tests/test_briefing_agent.py \
  --ignore=tests/test_mail_send.py \
  --ignore=tests/test_tasks_agent.py
```

Berichte: wie viele Tests bestanden / fehlgeschlagen. Bei Fehlern zeige den vollständigen Fehler-Output.
