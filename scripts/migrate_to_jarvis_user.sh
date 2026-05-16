#!/usr/bin/env bash
# Migration: jarvis.service von root → jarvis-User
# Ausführen auf VPS als root: bash /root/agents/scripts/migrate_to_jarvis_user.sh
# LIEST NICHTS, SCHREIBT NICHTS automatisch — alle Schritte sind interaktiv.

set -euo pipefail

echo "=== Jarvis User-Migration ==="
echo ""
echo "Dieser Script migriert jarvis.service von User=root auf User=jarvis."
echo "Voraussetzung: git pull bereits durchgeführt (neues jarvis.service, db.py etc.)"
echo ""
read -rp "Fortfahren? [j/N] " confirm
[ "$confirm" = "j" ] || { echo "Abgebrochen."; exit 0; }

# 1. User anlegen
if id jarvis &>/dev/null; then
  echo "[OK] User 'jarvis' existiert bereits"
else
  useradd -r -m -d /var/lib/jarvis -s /bin/bash jarvis
  echo "[OK] User 'jarvis' angelegt (Home: /var/lib/jarvis)"
fi

# 2. Daten-Verzeichnis vorbereiten
JARVIS_DATA_DIR="/var/lib/jarvis/.jarvis"
mkdir -p "$JARVIS_DATA_DIR"

# 3. Bestehende DBs und Token kopieren (nicht verschieben — Service läuft noch)
OLD_DIR="/root/.jarvis"
if [ -d "$OLD_DIR" ]; then
  cp -v "$OLD_DIR"/*.db "$JARVIS_DATA_DIR/" 2>/dev/null || true
  if [ -f "$OLD_DIR/microsoft_tokens.json" ]; then
    cp -v "$OLD_DIR/microsoft_tokens.json" "$JARVIS_DATA_DIR/"
    chmod 600 "$JARVIS_DATA_DIR/microsoft_tokens.json"
  fi
  echo "[OK] Daten aus $OLD_DIR → $JARVIS_DATA_DIR kopiert"
fi

# 4. Code-Verzeichnis einrichten
CODE_DIR="/opt/jarvis"
if [ -d "$CODE_DIR" ]; then
  echo "[INFO] $CODE_DIR existiert bereits — überspringe Clone"
else
  # Kopie aus /root/agents (der aktuelle Stand auf dem VPS)
  cp -a /root/agents "$CODE_DIR"
  echo "[OK] Code kopiert nach $CODE_DIR"
fi

# 5. venv einrichten (falls noch nicht vorhanden)
if [ ! -f "$CODE_DIR/venv/bin/uvicorn" ]; then
  python3 -m venv "$CODE_DIR/venv"
  "$CODE_DIR/venv/bin/pip" install -q -r "$CODE_DIR/requirements.txt"
  echo "[OK] venv angelegt und requirements installiert"
fi

# 6. Ownership setzen
chown -R jarvis:jarvis "$JARVIS_DATA_DIR"
chown -R jarvis:jarvis "$CODE_DIR"
# .env bleibt in /root/.env — jarvis braucht Lesezugriff
cp /root/.env /var/lib/jarvis/.env
chown jarvis:jarvis /var/lib/jarvis/.env
chmod 600 /var/lib/jarvis/.env
echo "[OK] Ownership und .env gesetzt"

# 7. Service-Datei aktualisieren
SERVICE_FILE="/etc/systemd/system/jarvis.service"
cat > "$SERVICE_FILE" <<'EOF'
[Unit]
Description=Jarvis Bot Gateway
After=network.target

[Service]
Type=simple
User=jarvis
WorkingDirectory=/opt/jarvis
EnvironmentFile=/var/lib/jarvis/.env
Environment=JARVIS_DATA_DIR=/var/lib/jarvis/.jarvis
ExecStart=/opt/jarvis/venv/bin/uvicorn main:app --host 0.0.0.0 --port 9000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
echo "[OK] $SERVICE_FILE aktualisiert"

# 7b. Sudoers — jarvis darf das claude-Workspace per `sudo -u claude` bedienen.
#     vps.py run_as_claude() ruft ls/cat/git/claude/cp als claude auf. Ohne
#     diese Regel ist der coding-Intent als unprivilegierter jarvis-User
#     komplett blockiert (als root lief es ohne sudoers-Eintrag).
SUDOERS_FILE="/etc/sudoers.d/jarvis-claude"
cat > /tmp/jarvis-claude.sudo <<'EOF'
jarvis ALL=(claude) NOPASSWD: /usr/bin/ls, /usr/bin/cat, /usr/bin/git, /usr/bin/claude, /usr/bin/cp
EOF
if visudo -cf /tmp/jarvis-claude.sudo; then
  install -m 0440 -o root -g root /tmp/jarvis-claude.sudo "$SUDOERS_FILE"
  rm -f /tmp/jarvis-claude.sudo
  echo "[OK] sudoers-Drop-in $SUDOERS_FILE angelegt"
else
  rm -f /tmp/jarvis-claude.sudo
  echo "[FEHLER] sudoers-Syntax ungültig — Drop-in NICHT installiert"
  exit 1
fi

# 8. Reload + Restart
systemctl daemon-reload
systemctl restart jarvis
sleep 3
systemctl status jarvis --no-pager

echo ""
echo "=== Migration abgeschlossen ==="
echo "Logs: journalctl -u jarvis -f --no-pager"
echo "Alte Daten in /root/.jarvis bleiben als Fallback erhalten."
echo ""
echo "GitHub Webhook-Pfad muss auf /opt/jarvis geändert werden (GITHUB_REPO_PATHS in main.py)"
echo "→ In main.py: 'herrlich-ai-platform': '/opt/jarvis'"
