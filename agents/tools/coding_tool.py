"""coding-Tool — Projekte lesen, Backlog schreiben, Claude Code starten.

Read-Aktionen (list_projects, query) laufen sofort.
action='run' startet Claude Code als asyncio-Background-Task — kein Staging,
weil run_coding_action seine eigenen Telegram-Updates sendet.
action='backlog_write' wird vorgemerkt und erst nach Philipps Bestätigung ausgeführt.
"""

import asyncio

from claude_agent_sdk import tool

import app_state
from coding_agent import add_backlog_item, handle_coding_query, run_coding_action
from vps import list_projects as _list_projects

_WRITE_ACTIONS = {"backlog_write"}


def _label(action: str, params: dict) -> str:
    if action == "backlog_write":
        prio = params.get("priority", "P1")
        return f"Backlog-Item in '{params['project']}' ({prio}): {params['item'][:60]}"
    return action


def _missing_fields(action: str, params: dict) -> str:
    required = {
        "backlog_write": ("project", "item"),
    }[action]
    return ", ".join(f for f in required if not params.get(f))


def _text(msg: str) -> dict:
    return {"content": [{"type": "text", "text": msg}]}


def make_coding_tool(chat_id: int):
    """Baut das coding-Tool für einen Lauf — chat_id für das Vormerken."""

    @tool(
        "coding",
        "Projekte lesen, Backlog verwalten und Claude Code starten. "
        "action='list_projects': Alle Projekte im Workspace auflisten. "
        "action='query' (project, query_type): Projekt-Infos lesen — "
        "query_type: 'backlog', 'git_log', 'readme', 'claude_md'. "
        "action='run' (project, task): Claude Code im Hintergrund starten — "
        "läuft SOFORT ohne Confirm; Philipp wird direkt per Telegram benachrichtigt. "
        "action='backlog_write' (project, item, priority optional): "
        "Neues Backlog-Item hinzufügen (priority: 'P0'/'P1'/'P2', Default 'P1'). "
        "backlog_write wird vorgemerkt und erst nach Philipps Bestätigung ausgeführt "
        "— sag ihm, was du vorbereitet hast.",
        {
            "action": str,
            "project": str,
            "query_type": str,
            "task": str,
            "item": str,
            "priority": str,
        },
    )
    async def coding_tool(args: dict) -> dict:
        action = (args.get("action") or "").strip()

        # ── list_projects ──────────────────────────────────────────────────────
        if action == "list_projects":
            projects = await _list_projects()
            if not projects:
                return _text("Keine Projekte im Workspace gefunden.")
            return _text(
                "📁 Projekte im Workspace:\n" + "\n".join(f"• {p}" for p in projects)
            )

        # ── query ──────────────────────────────────────────────────────────────
        if action == "query":
            project = (args.get("project") or "").strip()
            query_type = (args.get("query_type") or "").strip()
            if not project or not query_type:
                return _text("FEHLER: action='query' braucht: project, query_type.")
            result = await handle_coding_query(project, query_type)
            return _text(result)

        # ── run: fire-and-forget, kein Staging ────────────────────────────────
        if action == "run":
            project = (args.get("project") or "").strip()
            task = (args.get("task") or "").strip()
            if not project or not task:
                return _text("FEHLER: action='run' braucht: project, task.")
            asyncio.create_task(run_coding_action(task, project, chat_id))
            return _text(
                f"🚀 Claude Code läuft im Hintergrund in *{project}* "
                "— Philipp wird direkt per Telegram benachrichtigt."
            )

        if action not in _WRITE_ACTIONS:
            return _text(
                f"FEHLER: Unbekannte action '{action}'. Erlaubt: "
                "list_projects, query, run, backlog_write."
            )

        # ── backlog_write: Pflichtfelder prüfen + vormerken ────────────────────
        params = {
            "project": (args.get("project") or "").strip(),
            "item": (args.get("item") or "").strip(),
            "priority": (args.get("priority") or "").strip() or "P1",
        }
        missing = _missing_fields(action, params)
        if missing:
            return _text(f"FEHLER: action='{action}' braucht: {missing}.")
        label = _label(action, params)
        app_state.stage_agent_action(chat_id, "coding", action, label, params)
        return _text(
            f"✅ Vorgemerkt: {label}. Wird nach Philipps Bestätigung ausgeführt "
            "— du musst nicht warten."
        )

    return coding_tool


async def execute_write(action: str, params: dict) -> str:
    """Eine vorgemerkte coding-Schreibaktion ausführen."""
    if action == "backlog_write":
        ok = await add_backlog_item(
            params["project"], params["item"], params.get("priority", "P1")
        )
        return (
            f"✅ Backlog-Item in '{params['project']}' hinzugefügt: {params['item'][:60]}"
            if ok
            else f"❌ Backlog konnte nicht aktualisiert werden in '{params['project']}'."
        )
    return f"❌ Unbekannte coding-Aktion '{action}'."
