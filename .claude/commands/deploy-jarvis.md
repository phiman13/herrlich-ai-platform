Deploy Jarvis auf den VPS:

1. Führe aus:

```bash
ssh root@100.115.184.3 "cd /opt/herrlich-ai-platform && git pull && rsync -a --delete agents/ /opt/jarvis/ && systemctl restart jarvis"
```

2. Warte 3 Sekunden, dann zeige die letzten 30 Log-Zeilen:

```bash
ssh root@100.115.184.3 "journalctl -u jarvis -n 30 --no-pager"
```

3. Prüfe ob der Service läuft (kein "failed" / "error" in den Logs) und berichte kurz den Status.
