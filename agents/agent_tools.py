"""Agent-SDK-Werkzeuge — der workspace-Tool, der MCP-Server, das Permission-Gate.

Sicherheitsmodell: der workspace-Tool liest ausschließlich unterhalb von
JARVIS_WORKSPACE_DIR. _resolve_in_workspace lehnt jeden Pfad ab, der den Root
verlässt (Parent-Traversal, absolute Pfade).
"""

import os
from pathlib import Path

_MAX_FILE_BYTES = 60_000
_SEARCH_MAX_HITS = 60
_SKIP_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    "dist",
    "build",
    ".next",
    ".worktrees",
}


def _workspace_root() -> Path:
    """Der Workspace-Root — konfigurierbar via JARVIS_WORKSPACE_DIR."""
    return Path(
        os.environ.get("JARVIS_WORKSPACE_DIR", os.path.expanduser("~/Code"))
    ).resolve()


def _resolve_in_workspace(rel_path: str) -> Path | None:
    """rel_path relativ zum Workspace-Root auflösen.

    Gibt None zurück, wenn der aufgelöste Pfad den Root verlässt.
    """
    root = _workspace_root()
    candidate = (root / rel_path).resolve()
    if candidate == root or root in candidate.parents:
        return candidate
    return None
