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
    "mkfs"
    "dd if="
    "> /etc"
    "chmod -R 777"
    "curl.*|.*bash"
    "wget.*|.*bash"
    "systemctl stop jarvis"
    "systemctl stop caddy"
)

for pattern in "${BLOCKED_PATTERNS[@]}"; do
    if echo "$COMMAND" | grep -qE "$pattern"; then
        echo "BLOCKED: Gefaehrlicher Befehl: $pattern" >&2
        exit 1
    fi
done

exit 0
