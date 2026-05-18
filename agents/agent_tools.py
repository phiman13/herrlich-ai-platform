"""Agent-SDK-Werkzeuge — der workspace-Tool, der MCP-Server, das Permission-Gate.

Sicherheitsmodell: der workspace-Tool liest ausschließlich unterhalb von
JARVIS_WORKSPACE_DIR. _resolve_in_workspace lehnt jeden Pfad ab, der den Root
verlässt (Parent-Traversal, absolute Pfade).
"""

import os
import re
from pathlib import Path

from claude_agent_sdk import create_sdk_mcp_server, tool

_MAX_FILE_CHARS = 60_000
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
    if len(text) > _MAX_FILE_CHARS:
        text = text[:_MAX_FILE_CHARS] + "\n[... gekürzt ...]"
    return text


def _do_search(pattern: str, rel_path: str = "") -> str:
    """Regex-Suche über Dateien im Workspace (rekursiv ab rel_path)."""
    base = _resolve_in_workspace(rel_path or ".")
    if base is None or not base.exists():
        return f"FEHLER: Suchpfad '{rel_path}' ist ungültig."
    try:
        rx = re.compile(pattern)
    except re.error as e:
        return f"FEHLER: Ungültiges Suchmuster: {e}"
    root = _workspace_root()
    hits: list[str] = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fn in sorted(filenames):
            fp = Path(dirpath) / fn
            try:
                with open(fp, "r", encoding="utf-8", errors="ignore") as fh:
                    for lineno, line in enumerate(fh, 1):
                        if rx.search(line):
                            hits.append(
                                f"{fp.relative_to(root)}:{lineno}: {line.strip()[:200]}"
                            )
                            if len(hits) >= _SEARCH_MAX_HITS:
                                hits.append("[... weitere Treffer abgeschnitten ...]")
                                return "\n".join(hits)
            except (OSError, UnicodeError):
                continue
    return "\n".join(hits) if hits else f"Keine Treffer für '{pattern}'."


def _do_list(rel_path: str = "") -> str:
    """Ein Verzeichnis im Workspace auflisten (Dotfiles + Skip-Dirs ausgeblendet)."""
    target = _resolve_in_workspace(rel_path or ".")
    if target is None or not target.is_dir():
        return f"FEHLER: '{rel_path}' ist kein Verzeichnis."
    entries: list[str] = []
    for child in sorted(target.iterdir()):
        if child.name in _SKIP_DIRS or child.name.startswith("."):
            continue
        entries.append(f"{child.name}/" if child.is_dir() else child.name)
    return "\n".join(entries) if entries else "(leer)"


@tool(
    "workspace",
    "Liest und durchsucht Dateien in Philipps Coding-Workspace. "
    "action='read': Datei lesen (path = relativer Pfad). "
    "action='search': Regex-Suche (query = Muster, path = optionaler Unterordner). "
    "action='list': Verzeichnis auflisten (path = relativer Pfad, leer = Workspace-Wurzel).",
    {"action": str, "path": str, "query": str},
)
async def workspace_tool(args: dict) -> dict:
    action = (args.get("action") or "").strip()
    path = (args.get("path") or "").strip()
    query = (args.get("query") or "").strip()
    if action == "read":
        result = _do_read(path)
    elif action == "search":
        result = _do_search(query, path)
    elif action == "list":
        result = _do_list(path)
    else:
        result = f"FEHLER: Unbekannte action '{action}'. Erlaubt: read, search, list."
    return {"content": [{"type": "text", "text": result}]}


def build_mcp_server():
    """In-Process-MCP-Server mit dem workspace-Tool."""
    return create_sdk_mcp_server(name="jarvis", version="1.0.0", tools=[workspace_tool])
