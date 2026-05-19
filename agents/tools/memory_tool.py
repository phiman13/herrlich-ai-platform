"""memory-Tool — Erinnerungen auflisten und löschen.

action='list' läuft sofort. action='delete' wird vorgemerkt und erst nach
Philipps Bestätigung ausgeführt.
"""

from claude_agent_sdk import tool

import app_state


_WRITE_ACTIONS = {"delete"}


def _text(msg: str) -> dict:
    return {"content": [{"type": "text", "text": msg}]}


def make_memory_tool(chat_id: int):
    """Baut das memory-Tool für einen Lauf — chat_id für das Vormerken."""

    @tool(
        "memory",
        "Erinnerungen über Philipp verwalten. "
        "action='list': Alle gespeicherten Erinnerungen anzeigen. "
        "action='delete' (query optional): Eine Erinnerung löschen — query ist die "
        "Beschreibung; leer = letzte Erinnerung löschen. "
        "delete wird vorgemerkt und erst nach Philipps Bestätigung ausgeführt "
        "— sag ihm, was du vorbereitet hast.",
        {"action": str, "query": str},
    )
    async def memory_tool(args: dict) -> dict:
        action = (args.get("action") or "").strip()

        if action == "list":
            if not app_state.memory_agent:
                return _text("FEHLER: Memory-Agent nicht verfügbar.")
            result = await app_state.memory_agent.list_memories()
            return _text(result)

        if action not in _WRITE_ACTIONS:
            return _text(
                f"FEHLER: Unbekannte action '{action}'. Erlaubt: list, delete."
            )

        # delete: staged
        query = (args.get("query") or "").strip() or None
        label = (
            f"Erinnerung löschen: {query[:60]}"
            if query
            else "Letzte Erinnerung löschen"
        )
        params = {"query": query}
        app_state.stage_agent_action(chat_id, "memory", action, label, params)
        return _text(
            f"✅ Vorgemerkt: {label}. Wird nach Philipps Bestätigung ausgeführt "
            "— du musst nicht warten."
        )

    return memory_tool


async def execute_write(action: str, params: dict) -> str:
    """Eine vorgemerkte memory-Schreibaktion ausführen."""
    if action == "delete":
        if not app_state.memory_agent:
            return "❌ Memory-Agent nicht verfügbar."
        return await app_state.memory_agent.delete_memory(params.get("query"))
    return f"❌ Unbekannte memory-Aktion '{action}'."
