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


def _do_read(rel_path: str) -> str:
    """Eine Datei im Workspace lesen. Strukturierter Fehlertext bei Problemen."""
    target = _resolve_in_workspace(rel_path)
    if target is None:
        return f"FEHLER: Pfad '{rel_path}' liegt außerhalb des Workspace."
    if not target.is_file():
        return f"FEHLER: '{rel_path}' ist keine Datei oder existiert nicht."
    data = target.read_bytes()
    if b"\x00" in data[:4096]:
        return (
            f"FEHLER: '{rel_path}' ist eine Binärdatei und kann nicht gelesen werden."
        )
    text = data.decode("utf-8", errors="replace")
    if len(text) > _MAX_FILE_BYTES:
        text = text[:_MAX_FILE_BYTES] + "\n[... gekürzt ...]"
    return text
