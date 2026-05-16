"""
Shared mutable state for the Jarvis gateway.

Import-light by design — holds only state values, no agent classes.
startup() in main.py populates memory_agent / conversation_db / profile_agent.
"""

import os
import time

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

# Pending confirm-ops (chat_id -> op dict) and multi-result selections.
pending_mail_ops: dict[int, dict] = {}
pending_calendar_ops: dict[int, dict] = {}
last_mail_search: dict[int, dict] = {}
last_calendar_search: dict[int, dict] = {}

# Telegram update dedup.
processed_updates: set = set()

# Lazy-initialized agents — set by startup().
memory_agent = None
conversation_db = None
profile_agent = None

_PENDING_OP_TTL = (
    600  # Sekunden — Confirm-Buttons älter als 10 Min gelten als abgelaufen
)


def _pending_op_expired(op: dict) -> bool:
    """True wenn eine Pending-Op älter als _PENDING_OP_TTL ist."""
    return time.time() - op.get("staged_at", 0) > _PENDING_OP_TTL
