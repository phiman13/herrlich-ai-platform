#!/bin/bash
set -e

WORKSPACE="/home/claude/workspace"
GITHUB_USER="phiman13"
REPOS="recipe-app immo-radar refurbish-business herrlich-dev herrlich-ai-platform"

echo "=== Workspace Setup ==="

# PAT prüfen
if [ -z "$GITHUB_TOKEN" ] && [ -f /root/.env ]; then
    export $(grep -v '^#' /root/.env | xargs)
fi
if [ -z "$GITHUB_TOKEN" ]; then
    echo "ERROR: GITHUB_TOKEN nicht gesetzt. In /root/.env als GITHUB_TOKEN=ghp_... eintragen."
    exit 1
fi

# Git credential helper für PAT
git config --global credential.helper store
echo "https://${GITHUB_USER}:${GITHUB_TOKEN}@github.com" > /root/.git-credentials
chmod 600 /root/.git-credentials

# Workspace erstellen falls nicht vorhanden
mkdir -p "$WORKSPACE"
chown claude:claude "$WORKSPACE"

# Repos klonen oder updaten
for REPO in $REPOS; do
    TARGET="$WORKSPACE/$REPO"
    if [ -d "$TARGET/.git" ]; then
        echo "  UPDATE: $REPO"
        sudo -u claude git -C "$TARGET" pull --quiet
    else
        echo "  CLONE: $REPO"
        sudo -u claude git clone "https://${GITHUB_USER}:${GITHUB_TOKEN}@github.com/${GITHUB_USER}/${REPO}.git" "$TARGET"
    fi
done

# Caddyfile synchronisieren
REPO_CADDY="/root/herrlich-ai-platform/config/caddy/Caddyfile"
LIVE_CADDY="/etc/caddy/Caddyfile"
if [ -f "$LIVE_CADDY" ]; then
    cp "$LIVE_CADDY" "$REPO_CADDY"
    echo "  SYNC: Caddyfile -> Repo"
fi

# Artefakte in /root/ aufräumen
echo "=== Cleanup /root/ artifacts ==="
for ARTIFACT in "600" "700" "77" "CHMOD" "ECHO" "=2.1"; do
    TARGET="/root/$ARTIFACT"
    if [ -e "$TARGET" ]; then
        rm -rf "$TARGET"
        echo "  REMOVED: $TARGET"
    fi
done
# SSH-Key-Fragment Verzeichnis
for D in /root/AAAA*; do
    [ -e "$D" ] && rm -rf "$D" && echo "  REMOVED: $D"
done

echo "=== Done ==="
sudo -u claude ls "$WORKSPACE"
