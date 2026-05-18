"""
Shared mutable state for the Jarvis gateway.

Import-light by design — holds only state values, no agent classes.
startup() in main.py populates memory_agent / conversation_db / profile_agent.
Also holds conversation-state helpers and Telegram typing utilities.
"""

import asyncio
import os
import time

from telegram import Bot
from telegram.constants import ChatAction

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

# Pending confirm-ops (chat_id -> op dict) and multi-result selections.
pending_mail_ops: dict[int, dict] = {}
pending_calendar_ops: dict[int, dict] = {}
last_mail_search: dict[int, dict] = {}
last_calendar_search: dict[int, dict] = {}

# Telegram update dedup.
processed_updates: set = set()

# Per-Chat-Locks — serialisieren agentische Läufe innerhalb eines Chats.
agent_run_locks: dict[int, asyncio.Lock] = {}


def get_agent_lock(chat_id: int) -> asyncio.Lock:
    """Den (lazy erzeugten) asyncio.Lock für einen Chat zurückgeben."""
    lock = agent_run_locks.get(chat_id)
    if lock is None:
        lock = asyncio.Lock()
        agent_run_locks[chat_id] = lock
    return lock


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


# ---------------------------------------------------------------------------
# Typing helpers
# ---------------------------------------------------------------------------


async def send_typing(chat_id: int):
    bot = Bot(token=TELEGRAM_TOKEN)
    await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)


async def _keep_typing(chat_id: int, stop_event: asyncio.Event):
    while not stop_event.is_set():
        await send_typing(chat_id)
        await asyncio.sleep(4)


# ---------------------------------------------------------------------------
# Conversation history for router context
# Each entry: {"u": user_text, "j": bot_summary}
# ---------------------------------------------------------------------------

_recent_conv: dict[int, list[dict]] = {}


def _conv_append_user(chat_id: int, text: str) -> None:
    hist = _recent_conv.get(chat_id, [])
    hist.append({"u": text, "j": ""})
    _recent_conv[chat_id] = hist[-8:]


def _conv_complete(chat_id: int, summary: str) -> None:
    hist = _recent_conv.get(chat_id, [])
    if hist:
        hist[-1]["j"] = summary[:180]


def _conv_to_prev_texts(chat_id: int) -> list[str]:
    """Return interleaved Philipp/Jarvis lines for the last 3 completed turns."""
    completed = [t for t in _recent_conv.get(chat_id, []) if t["j"]][-3:]
    lines = []
    for t in completed:
        lines.append(f"Philipp: {t['u']}")
        lines.append(f"Jarvis: {t['j']}")
    return lines
