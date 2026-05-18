#!/usr/bin/env bash
# Tägliches Backup der Jarvis-Datenbanken und MS-Token.
# Cron (als root): 0 3 * * * /opt/herrlich-ai-platform/scripts/backup_jarvis.sh >> /var/log/jarvis-backup.log 2>&1

set -euo pipefail

JARVIS_DIR="${JARVIS_DATA_DIR:-/var/lib/jarvis/.jarvis}"
BACKUP_BASE="/root/backups/jarvis"
DATE=$(date +%Y-%m-%d)
BACKUP_DIR="$BACKUP_BASE/$DATE"
KEEP_DAYS=7

mkdir -p "$BACKUP_DIR"

backed_up=0

# Datenbanken
for db in "$JARVIS_DIR"/*.db; do
  [ -f "$db" ] || continue
  cp "$db" "$BACKUP_DIR/"
  echo "$(date -Iseconds) backed up: $(basename "$db")"
  backed_up=$((backed_up + 1))
done

# Microsoft-Token
TOKEN_FILE="$JARVIS_DIR/microsoft_tokens.json"
if [ -f "$TOKEN_FILE" ]; then
  cp "$TOKEN_FILE" "$BACKUP_DIR/"
  chmod 600 "$BACKUP_DIR/microsoft_tokens.json"
  echo "$(date -Iseconds) backed up: microsoft_tokens.json"
  backed_up=$((backed_up + 1))
fi

# Alte Backups löschen (> KEEP_DAYS Tage)
find "$BACKUP_BASE" -maxdepth 1 -mindepth 1 -type d -mtime +$KEEP_DAYS -print -exec rm -rf {} \; 2>/dev/null || true

echo "$(date -Iseconds) backup complete: $backed_up files → $BACKUP_DIR"
