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

# Vorgemerkte Agenten-Schreibaktionen, die auf den gebündelten Confirm warten.
# chat_id -> {"id": int, "actions": list[dict], "staged_at": float}
# Eine Aktion: {"tool": str, "action": str, "label": str, "params": dict}
pending_agent_actions: dict[int, dict] = {}
_pending_seq: int = 0

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


def _pending_op_expired(entry: dict) -> bool:
    """True wenn ein Pending-Eintrag älter als _PENDING_OP_TTL ist."""
    return time.time() - entry.get("staged_at", 0) > _PENDING_OP_TTL


def stage_agent_action(
    chat_id: int, tool: str, action: str, label: str, params: dict
) -> None:
    """Eine Schreibaktion für den Lauf-Ende-Confirm vormerken.

    Hängt an das Pending-Set des laufenden Laufs an. Existiert noch keins (oder
    ist es abgelaufen), wird ein frisches mit neuer ID erzeugt. run_agent leert
    den Store beim Lauf-Start — daher gehört ein Set immer genau einem Lauf.
    """
    global _pending_seq
    entry = pending_agent_actions.get(chat_id)
    if entry is None or _pending_op_expired(entry):
        _pending_seq += 1
        entry = {"id": _pending_seq, "actions": [], "staged_at": time.time()}
        pending_agent_actions[chat_id] = entry
    entry["actions"].append(
        {"tool": tool, "action": action, "label": label, "params": params}
    )


def peek_pending(chat_id: int) -> dict | None:
    """Das Pending-Set lesen ohne zu entnehmen (für den Lauf-Ende-Confirm).

    Gibt {"id", "actions", "staged_at"} zurück oder None.
    """
    entry = pending_agent_actions.get(chat_id)
    if entry is None or _pending_op_expired(entry):
        return None
    return entry


def take_pending_actions(chat_id: int, expected_id: int) -> list[dict]:
    """Aktionen entnehmen — nur wenn die ID zum erwarteten Set passt.

    Schützt davor, dass ein veralteter Confirm-Button die Aktionen eines
    neueren Laufs ausführt. Bei ID-Mismatch bleibt der (neuere) Eintrag
    unangetastet; bei Treffer wird er gelöscht und zurückgegeben.
    """
    entry = pending_agent_actions.get(chat_id)
    if entry is None:
        return []
    if _pending_op_expired(entry):
        pending_agent_actions.pop(chat_id, None)
        return []
    if entry["id"] != expected_id:
        return []
    pending_agent_actions.pop(chat_id, None)
    return entry["actions"]


def clear_pending_actions(chat_id: int) -> None:
    """Pending-Set verwerfen (run_agent beim Lauf-Start und bei Lauf-Fehler)."""
    pending_agent_actions.pop(chat_id, None)


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
