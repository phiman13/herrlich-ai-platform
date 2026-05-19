"""tasks-Tool — MS-To-Do-Listen lesen und ändern.

action='list' ist read-only und läuft sofort. Alle anderen Aktionen sind
Schreib-Aktionen: sie führen NICHT direkt aus, sondern werden via
app_state.stage_agent_action vorgemerkt und nach dem gebündelten Confirm
durch execute_write ausgeführt.
"""

import asyncio

from claude_agent_sdk import tool

import app_state
from tasks_agent import (
    add_task,
    complete_task,
    create_list,
    delete_list,
    get_tasks,
    rename_list,
)

_WRITE_ACTIONS = {"add", "complete", "create_list", "delete_list", "rename_list"}


def _label(action: str, params: dict) -> str:
    """Menschenlesbare Beschreibung einer vorgemerkten Aktion (für den Confirm)."""
    ln = params.get("list_name", "")
    if action == "add":
        due = f" (fällig {params['due_date']})" if params.get("due_date") else ""
        return f"Task '{params['title']}' zu Liste '{ln}' hinzufügen{due}"
    if action == "complete":
        return f"Task '{params['title']}' in '{ln}' als erledigt markieren"
    if action == "create_list":
        return f"To-Do-Liste '{params['name']}' anlegen"
    if action == "delete_list":
        return f"To-Do-Liste '{ln}' löschen"
    if action == "rename_list":
        return f"Liste '{ln}' umbenennen zu '{params['new_name']}'"
    return action


def _missing_fields(action: str, params: dict) -> str:
    """Gibt fehlende Pflichtfelder als Text zurück, sonst ''."""
    required = {
        "add": ("list_name", "title"),
        "complete": ("list_name", "title"),
        "create_list": ("name",),
        "delete_list": ("list_name",),
        "rename_list": ("list_name", "new_name"),
    }[action]
    return ", ".join(f for f in required if not params.get(f))


def make_tasks_tool(chat_id: int):
    """Baut das tasks-Tool für einen Lauf — chat_id für das Vormerken eingeschlossen."""

    @tool(
        "tasks",
        "MS-To-Do-Listen lesen und ändern. "
        "action='list': offene Tasks einer Liste, oder alle Listen wenn list_name "
        "leer (read). "
        "action='add': Task/Erinnerung anlegen (list_name, title; optional due_date "
        "'YYYY-MM-DD', due_time 'HH:MM'). "
        "action='complete': Task abhaken (list_name, title — title muss EXAKT dem "
        "Task-Titel entsprechen; bei Unsicherheit vorher action='list' aufrufen). "
        "action='create_list' (name) / 'delete_list' (list_name) / "
        "'rename_list' (list_name, new_name). "
        "Alle Aktionen außer 'list' werden vorgemerkt und erst nach Bestätigung "
        "durch Philipp ausgeführt — sag ihm im Antworttext, was du vorbereitet hast.",
        {
            "action": str,
            "list_name": str,
            "title": str,
            "name": str,
            "new_name": str,
            "due_date": str,
            "due_time": str,
        },
    )
    async def tasks_tool(args: dict) -> dict:
        action = (args.get("action") or "").strip()
        if action == "list":
            list_name = (args.get("list_name") or "").strip() or None
            result = await asyncio.to_thread(get_tasks, list_name)
            return {"content": [{"type": "text", "text": result}]}
        if action not in _WRITE_ACTIONS:
            return _text(
                f"FEHLER: Unbekannte action '{action}'. Erlaubt: list, add, "
                "complete, create_list, delete_list, rename_list."
            )
        # Schreib-Aktion → Pflichtfelder prüfen, dann vormerken.
        params = {
            "list_name": (args.get("list_name") or "").strip(),
            "title": (args.get("title") or "").strip(),
            "name": (args.get("name") or "").strip(),
            "new_name": (args.get("new_name") or "").strip(),
            "due_date": (args.get("due_date") or "").strip() or None,
            "due_time": (args.get("due_time") or "").strip() or None,
        }
        missing = _missing_fields(action, params)
        if missing:
            return _text(f"FEHLER: action='{action}' braucht: {missing}.")
        label = _label(action, params)
        app_state.stage_agent_action(chat_id, "tasks", action, label, params)
        return _text(
            f"✅ Vorgemerkt: {label}. Wird nach Philipps Bestätigung ausgeführt "
            "— du musst nicht warten."
        )

    return tasks_tool


def _text(msg: str) -> dict:
    """MCP-Tool-Rückgabe mit einem Text-Block."""
    return {"content": [{"type": "text", "text": msg}]}


async def execute_write(action: str, params: dict) -> str:
    """Eine vorgemerkte tasks-Schreibaktion tatsächlich ausführen.

    Wird vom Confirm-Callback via tools.execute_pending_action aufgerufen.
    """
    if action == "add":
        ok = await asyncio.to_thread(
            add_task,
            params["list_name"],
            params["title"],
            params.get("due_date"),
            params.get("due_time"),
        )
        return (
            f"✅ Task '{params['title']}' angelegt."
            if ok
            else f"❌ Task '{params['title']}' — Liste '{params['list_name']}' "
            "nicht gefunden."
        )
    if action == "complete":
        ok = await asyncio.to_thread(
            complete_task, params["list_name"], params["title"]
        )
        return (
            f"✅ '{params['title']}' als erledigt markiert."
            if ok
            else f"❌ '{params['title']}' nicht gefunden oder schon erledigt."
        )
    if action == "create_list":
        ok = await asyncio.to_thread(create_list, params["name"])
        _invalidate_list_cache(ok)
        return (
            f"✅ Liste '{params['name']}' angelegt."
            if ok
            else "❌ Liste konnte nicht angelegt werden."
        )
    if action == "delete_list":
        ok = await asyncio.to_thread(delete_list, params["list_name"])
        _invalidate_list_cache(ok)
        return (
            f"✅ Liste '{params['list_name']}' gelöscht."
            if ok
            else f"❌ Liste '{params['list_name']}' nicht gefunden."
        )
    if action == "rename_list":
        ok = await asyncio.to_thread(
            rename_list, params["list_name"], params["new_name"]
        )
        _invalidate_list_cache(ok)
        return (
            f"✅ Liste '{params['list_name']}' umbenannt zu '{params['new_name']}'."
            if ok
            else f"❌ Liste '{params['list_name']}' nicht gefunden."
        )
    return f"❌ Unbekannte tasks-Aktion '{action}'."


def _invalidate_list_cache(ok: bool) -> None:
    """Nach einer Listen-Mutation den To-Do-Listen-Cache des Routers leeren.

    Deferred import — vermeidet einen Import-Zyklus tools -> router.
    """
    if not ok:
        return
    import router

    router._todo_lists_cache = ([], 0.0)
