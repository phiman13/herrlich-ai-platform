# Mac Setup

## codeopen Shell-Funktion (~/.zshrc)

function codeopen() {
  if [ -z "$1" ]; then
    echo "Usage: codeopen <projektname> [claude]"
    return 1
  fi

  PROJECT_PATH="$HOME/Library/Mobile Documents/com~apple~CloudDocs/Documents/04_Sonstiges/01_Coding/$1"

  if [ ! -d "$PROJECT_PATH" ]; then
    echo "Projekt nicht gefunden."
    return 1
  fi

  cd "$PROJECT_PATH"
  echo "Pulling neuesten Stand von GitHub..."

  if ! git diff --quiet || ! git diff --staged --quiet; then
    echo "Lokale Aenderungen gefunden - stashe sie..."
    git stash
    git pull --rebase origin main
    git stash pop
    echo "Lokale Aenderungen wiederhergestellt."
  else
    git pull --rebase origin main
  fi

  if [ "$2" = "claude" ]; then
    claude
  else
    code .
  fi
}

## Nutzung
codeopen recipe-app          # oeffnet VS Code
codeopen recipe-app claude   # startet Claude Code

## Tailscale
Tailscale App installieren und mit Account verbinden.
Nur noetig fuer direkten SSH-Zugang.
Jarvis per Telegram und code.herrlich.dev funktionieren ohne Tailscale.

## SSH-Verbindung zum VPS
ssh -i ~/ssh-key root@100.115.184.3
