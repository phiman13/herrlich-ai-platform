# agents/coding_agent.py
import asyncio
import json
import logging
import os

from agents.db import SessionDB
from agents.vps import (
    WORKSPACE,
    git_log,
    git_pull,
    list_projects,
    read_file,
    run_as_claude,
    write_file_and_commit,
)

logger = logging.getLogger("jarvis.coding")


async def handle_coding_query(project: str, query_type: str) -> str:
    """Fast path: read files/git directly, no Claude Code needed."""
    projects = await list_projects()
    if project not in projects:
        return (
            f"Projekt '{project}' nicht gefunden.\n"
            f"Verfügbare Projekte: {', '.join(projects)}"
        )

    await git_pull(project)

    if query_type == "backlog":
        content = await read_file(project, "BACKLOG.md")
        if not content:
            content = await read_file(project, "TODO.md")
        return content or f"Kein BACKLOG.md oder TODO.md in {project} gefunden."

    if query_type == "git_log":
        return await git_log(project, n=15)

    if query_type == "readme":
        content = await read_file(project, "README.md")
        return content or f"Kein README.md in {project}."

    if query_type == "claude_md":
        content = await read_file(project, "CLAUDE.md")
        return content or f"Kein CLAUDE.md in {project}."

    return f"Unbekannter Query-Typ: {query_type}"
