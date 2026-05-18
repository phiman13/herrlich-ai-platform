#!/bin/bash
INPUT=$(cat)
COMMAND=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print(data.get('tool_input', {}).get('command', ''))
except:
    print('')
")

BLOCKED_PATTERNS=(
    "rm -rf /"
    "rm -rf ~"
    "rm -rf \*"
    "mkfs"
    "dd if="
    "> /etc"
    "chmod -R 777"
    "curl.*|.*bash"
    "curl.*|.*sh"
    "wget.*|.*bash"
    "wget.*|.*sh"
    "systemctl stop jarvis"
    "systemctl stop caddy"
    "systemctl disable jarvis"
    "cat .*\.env"
    "cat /root/\.env"
    "base64.*\.env"
    "nc -e"
    "ncat -e"
    "> /etc/passwd"
    "> /etc/shadow"
    "crontab -r"
    "ufw disable"
    "ufw reset"
)

for pattern in "${BLOCKED_PATTERNS[@]}"; do
    if echo "$COMMAND" | grep -qiE "$pattern"; then
        echo "BLOCKED: Gefaehrlicher Befehl erkannt: $pattern" >&2
        # exit 2 = PreToolUse-Hook blockt das Tool. exit 1 wuerde NICHT
        # blocken (gilt als nicht-blockierender Fehler) — der Befehl liefe.
        exit 2
    fi
done

exit 0
