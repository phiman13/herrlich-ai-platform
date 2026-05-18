# Agentischer Jarvis — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Der Gesprächspfad (`personal`/`work`/`research`) wird hinter einem Feature-Flag von einem echten Agenten (Claude Agent SDK) mit Werkzeugen `workspace` (Datei-/Code-Lesen) und `web` bedient.

**Architecture:** Additiv und ohne Downtime. Der Router bleibt; klassifiziert er `personal`/`work`/`research` **und** ist `JARVIS_AGENT_ENABLED` gesetzt, läuft die Nachricht durch `run_agent()` — sonst durch die heutigen `chat_handler`-Funktionen. Pro Nachricht ein frischer, zustandsloser SDK-Lauf (`query()`), Gesprächsverlauf wird als Text in den Prompt eingebettet. Werkzeuge: ein In-Process-MCP-Server (`workspace`, sandboxed auf einen Workspace-Root) plus die eingebauten `WebSearch`/`WebFetch`. Ein `can_use_tool`-Hook ist das Sicherheits-Gate.

**Tech Stack:** Python 3.11+ · `claude-agent-sdk` 0.2.82 · FastAPI/python-telegram-bot (bestehend) · pytest

---

## Schritt A — SDK-Verifikation (abgeschlossen, hands-on)

Diese Fakten wurden mit `claude-agent-sdk==0.2.82` real verifiziert — der Plan baut darauf auf:

- **Auth:** Läuft **ohne `ANTHROPIC_API_KEY`** — das SDK startet die `claude`-CLI, die ihre OAuth-/Abo-Credentials nutzt. Headless (VPS): `claude setup-token` erzeugt einen Token für `CLAUDE_CODE_OAUTH_TOKEN`.
- **Runtime:** Das SDK spawnt die `claude`-CLI als Subprozess → Node.js + Claude Code CLI müssen installiert sein.
- **`query()`:** `query(prompt=<async-iterable>, options=ClaudeAgentOptions(...))` → async-iterator über `SystemMessage`/`AssistantMessage`/`ResultMessage`.
- **Custom Tools:** `@tool(name, description, input_schema)` + `create_sdk_mcp_server(name, version, tools)`. Voller Tool-Name = `mcp__<server>__<tool>`.
- **Permission-Gate:** `can_use_tool` **erfordert Streaming-Input** (async-iterable, kein String). Es feuert **nur für Tools, die nicht in `allowed_tools` stehen**. Rückgabe: `PermissionResultAllow(updated_input=...)` oder `PermissionResultDeny(message=..., interrupt=False)`.
- **History:** Werden frühere Turns als separate Stream-Nachrichten gesendet, beantwortet der Agent sie erneut (Token-Verschwendung). Verifiziert sauber: **History als Text in eine einzige User-Nachricht einbetten** → ein Modell-Turn, korrekte Antwort.
- **Ergebnis:** `ResultMessage.result` enthält den finalen Antworttext; `.total_cost_usd`, `.num_turns`, `.is_error` sind verfügbar.
- **Eingebaute Tools:** `ClaudeAgentOptions.tools=["WebSearch","WebFetch"]` beschränkt den Built-in-Toolset (kein `Bash`/`Edit`/`Read` für den Agenten).
- **Isolation:** `setting_sources` default `None` → das SDK lädt **keine** `CLAUDE.md`/`settings.json` des Entwicklers. Gewollt.
- **Session/Compaction:** `query()` ist zustandslos (ein Lauf pro Nachricht) — passt zum restart-festen Design. Compaction macht die CLI im Lauf automatisch; zusätzlich wird die eingespeiste History auf ~15 Turns gekappt. Kein eigener Konfigurationsbedarf.

---

## File Structure

**Neue Dateien:**
- `agents/agent_tools.py` — Der `workspace`-Tool (Datei lesen/suchen/listen, sandboxed), die MCP-Server-Factory und der `can_use_tool`-Permission-Hook. Verantwortung: *Werkzeuge + Gate*.
- `agents/agent.py` — Die Agenten-Runtime: Feature-Flag, System-Prompt, History-Formatierung, `run_agent()` (der SDK-Loop). Verantwortung: *ein Agenten-Lauf*.
- `tests/test_agent_tools.py` — Tests für `agent_tools.py`.
- `tests/test_agent.py` — Tests für `agent.py`.
- `tests/test_agent_dispatch.py` — Tests für die Dispatch-Verdrahtung.
- `tests/test_agent_live.py` — Opt-in End-to-End-Smoke-Test (echtes SDK, per `JARVIS_LIVE_TESTS` aktiviert).

**Geänderte Dateien:**
- `agents/requirements.txt` — `claude-agent-sdk` aufnehmen.
- `agents/app_state.py` — Per-Chat-Lock für Lauf-Serialisierung.
- `agents/dispatch.py` — Feature-Flag-Verzweigung in `_process_text()`.
- `.env.example` — neue Umgebungsvariablen.
- `CLAUDE.md` — Architektur-/Env-/VPS-Doku.

**Unverändert:** `router.py`, `chat_handler.py` (bleibt der Flag-aus-Pfad), alle `*_agent.py`, `proactive_agent.py`, `main.py`.

---

## Konventionen für alle Tasks

- Tests laufen aus dem Worktree-Verzeichnis. `<REPO>` = `/Users/philippherrlich/Code/herrlich-ai-platform`; die `conftest.py` macht den Pfad-Fixup auf den Worktree.
- **Volle Suite** (Baseline: **169 passed**):
  ```
  PYTHONPATH=agents <REPO>/.venv/bin/pytest tests/ -q --tb=short \
    --ignore=tests/test_briefing_agent.py \
    --ignore=tests/test_mail_send.py \
    --ignore=tests/test_tasks_agent.py
  ```
  Die drei ignorierten Dateien brauchen Live-APIs/Credentials und schlagen lokal ohne diese fehl — das ist vorbestehend und erwartet, **nicht** durch diese Tasks verursacht.
- `claude-agent-sdk` ist im venv bereits installiert (Verifikation Schritt A). Falls nicht: `<REPO>/.venv/bin/pip install claude-agent-sdk`.
- Commits auf Deutsch, Typ-Präfix (`feat`/`test`/`chore`/`docs`).
- Nach jedem Task: gesamte Suite grün halten (Baseline: 169 Tests).

---

### Task 1: Abhängigkeit — `claude-agent-sdk`

**Files:**
- Modify: `agents/requirements.txt`

- [ ] **Step 1: `claude-agent-sdk` in requirements.txt aufnehmen**

In `agents/requirements.txt` nach der Zeile `anthropic==0.94.0` eine neue Zeile einfügen:

```
claude-agent-sdk==0.2.82
```

- [ ] **Step 2: Installation + Import verifizieren**

Run: `<REPO>/.venv/bin/pip install -r agents/requirements.txt && <REPO>/.venv/bin/python -c "import claude_agent_sdk; print(claude_agent_sdk.__version__)"`
Expected: Ausgabe `0.2.82`, kein Fehler.

- [ ] **Step 3: Baseline-Suite läuft weiter**

Run: die volle Suite (siehe Konventionen — mit `--ignore` der Live-API-Tests).
Expected: PASS (169 passed — die neue Abhängigkeit bricht nichts).

- [ ] **Step 4: Commit**

```bash
git add agents/requirements.txt
git commit -m "chore(agent): claude-agent-sdk als Abhängigkeit aufnehmen"
```

---

### Task 2: `agent_tools.py` — Workspace-Sandbox

Sicherheitskritisch: alle Datei-Zugriffe des Agenten werden auf einen Workspace-Root eingegrenzt. `_resolve_in_workspace` lehnt jeden Pfad ab, der den Root verlässt.

**Files:**
- Create: `agents/agent_tools.py`
- Test: `tests/test_agent_tools.py`

- [ ] **Step 1: Failing Test schreiben**

Create `tests/test_agent_tools.py`:

```python
"""Tests für agents/agent_tools.py."""

import os
from pathlib import Path

import pytest

import agent_tools


def test_resolve_inside_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WORKSPACE_DIR", str(tmp_path))
    (tmp_path / "proj").mkdir()
    resolved = agent_tools._resolve_in_workspace("proj")
    assert resolved == (tmp_path / "proj").resolve()


def test_resolve_rejects_parent_traversal(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WORKSPACE_DIR", str(tmp_path))
    assert agent_tools._resolve_in_workspace("../secret") is None


def test_resolve_rejects_absolute_path(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WORKSPACE_DIR", str(tmp_path))
    assert agent_tools._resolve_in_workspace("/etc/passwd") is None


def test_resolve_root_itself_is_allowed(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WORKSPACE_DIR", str(tmp_path))
    assert agent_tools._resolve_in_workspace("") == tmp_path.resolve()
```

- [ ] **Step 2: Test ausführen — schlägt fehl**

Run: `PYTHONPATH=agents <REPO>/.venv/bin/pytest tests/test_agent_tools.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent_tools'`.

- [ ] **Step 3: `agent_tools.py` mit der Sandbox anlegen**

Create `agents/agent_tools.py`:

```python
"""Agent-SDK-Werkzeuge — der workspace-Tool, der MCP-Server, das Permission-Gate.

Sicherheitsmodell: der workspace-Tool liest ausschließlich unterhalb von
JARVIS_WORKSPACE_DIR. _resolve_in_workspace lehnt jeden Pfad ab, der den Root
verlässt (Parent-Traversal, absolute Pfade).
"""

import os
import re
from pathlib import Path

_MAX_FILE_CHARS = 60_000
_SEARCH_MAX_HITS = 60
_SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__",
    "dist", "build", ".next", ".worktrees",
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
```

- [ ] **Step 4: Test ausführen — grün**

Run: `PYTHONPATH=agents <REPO>/.venv/bin/pytest tests/test_agent_tools.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add agents/agent_tools.py tests/test_agent_tools.py
git commit -m "feat(agent): Workspace-Sandbox für den Datei-Tool"
```

---

### Task 3: `agent_tools.py` — `_do_read`

**Files:**
- Modify: `agents/agent_tools.py`
- Test: `tests/test_agent_tools.py`

- [ ] **Step 1: Failing Test schreiben**

In `tests/test_agent_tools.py` anhängen:

```python
def test_do_read_returns_file_content(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WORKSPACE_DIR", str(tmp_path))
    (tmp_path / "hello.txt").write_text("Hallo Welt", encoding="utf-8")
    assert agent_tools._do_read("hello.txt") == "Hallo Welt"


def test_do_read_outside_workspace_is_error(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WORKSPACE_DIR", str(tmp_path))
    result = agent_tools._do_read("../secret")
    assert result.startswith("FEHLER:")


def test_do_read_missing_file_is_error(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WORKSPACE_DIR", str(tmp_path))
    result = agent_tools._do_read("nope.txt")
    assert result.startswith("FEHLER:")


def test_do_read_truncates_large_file(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WORKSPACE_DIR", str(tmp_path))
    (tmp_path / "big.txt").write_text("x" * 80_000, encoding="utf-8")
    result = agent_tools._do_read("big.txt")
    assert "[... gekürzt ...]" in result
    assert len(result) < 80_000
```

- [ ] **Step 2: Test ausführen — schlägt fehl**

Run: `PYTHONPATH=agents <REPO>/.venv/bin/pytest tests/test_agent_tools.py -q -k do_read`
Expected: FAIL — `AttributeError: module 'agent_tools' has no attribute '_do_read'`.

- [ ] **Step 3: `_do_read` implementieren**

In `agents/agent_tools.py` ans Ende anhängen:

```python
def _do_read(rel_path: str) -> str:
    """Eine Datei im Workspace lesen. Strukturierter Fehlertext bei Problemen."""
    target = _resolve_in_workspace(rel_path)
    if target is None:
        return f"FEHLER: Pfad '{rel_path}' liegt außerhalb des Workspace."
    if not target.is_file():
        return f"FEHLER: '{rel_path}' ist keine Datei oder existiert nicht."
    data = target.read_bytes()
    if b"\x00" in data[:4096]:
        return f"FEHLER: '{rel_path}' ist eine Binärdatei und kann nicht gelesen werden."
    text = data.decode("utf-8", errors="replace")
    if len(text) > _MAX_FILE_CHARS:
        text = text[:_MAX_FILE_CHARS] + "\n[... gekürzt ...]"
    return text
```

- [ ] **Step 4: Test ausführen — grün**

Run: `PYTHONPATH=agents <REPO>/.venv/bin/pytest tests/test_agent_tools.py -q -k do_read`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add agents/agent_tools.py tests/test_agent_tools.py
git commit -m "feat(agent): workspace _do_read — Datei lesen mit Sandbox"
```

---

### Task 4: `agent_tools.py` — `_do_search`

**Files:**
- Modify: `agents/agent_tools.py`
- Test: `tests/test_agent_tools.py`

- [ ] **Step 1: Failing Test schreiben**

In `tests/test_agent_tools.py` anhängen:

```python
def test_do_search_finds_matches(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WORKSPACE_DIR", str(tmp_path))
    (tmp_path / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("x = 2\n", encoding="utf-8")
    result = agent_tools._do_search("def foo")
    assert "a.py:1:" in result
    assert "b.py" not in result


def test_do_search_no_match(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WORKSPACE_DIR", str(tmp_path))
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    assert "Keine Treffer" in agent_tools._do_search("nichtdrin")


def test_do_search_skips_ignored_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WORKSPACE_DIR", str(tmp_path))
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "lib.js").write_text("needle", encoding="utf-8")
    (tmp_path / "src.js").write_text("needle", encoding="utf-8")
    result = agent_tools._do_search("needle")
    assert "src.js" in result
    assert "node_modules" not in result


def test_do_search_invalid_regex_is_error(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WORKSPACE_DIR", str(tmp_path))
    assert agent_tools._do_search("[unclosed").startswith("FEHLER:")
```

- [ ] **Step 2: Test ausführen — schlägt fehl**

Run: `PYTHONPATH=agents <REPO>/.venv/bin/pytest tests/test_agent_tools.py -q -k do_search`
Expected: FAIL — `AttributeError: ... '_do_search'`.

- [ ] **Step 3: `_do_search` implementieren**

In `agents/agent_tools.py` ans Ende anhängen:

```python
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
```

- [ ] **Step 4: Test ausführen — grün**

Run: `PYTHONPATH=agents <REPO>/.venv/bin/pytest tests/test_agent_tools.py -q -k do_search`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add agents/agent_tools.py tests/test_agent_tools.py
git commit -m "feat(agent): workspace _do_search — Regex-Suche im Workspace"
```

---

### Task 5: `agent_tools.py` — `_do_list`

**Files:**
- Modify: `agents/agent_tools.py`
- Test: `tests/test_agent_tools.py`

- [ ] **Step 1: Failing Test schreiben**

In `tests/test_agent_tools.py` anhängen:

```python
def test_do_list_shows_entries(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WORKSPACE_DIR", str(tmp_path))
    (tmp_path / "proj").mkdir()
    (tmp_path / "readme.md").write_text("x", encoding="utf-8")
    result = agent_tools._do_list("")
    assert "proj/" in result
    assert "readme.md" in result


def test_do_list_hides_dotfiles_and_skipdirs(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WORKSPACE_DIR", str(tmp_path))
    (tmp_path / ".git").mkdir()
    (tmp_path / ".env").write_text("x", encoding="utf-8")
    (tmp_path / "visible.txt").write_text("x", encoding="utf-8")
    result = agent_tools._do_list("")
    assert "visible.txt" in result
    assert ".git" not in result
    assert ".env" not in result


def test_do_list_non_directory_is_error(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WORKSPACE_DIR", str(tmp_path))
    assert agent_tools._do_list("nichtda").startswith("FEHLER:")
```

- [ ] **Step 2: Test ausführen — schlägt fehl**

Run: `PYTHONPATH=agents <REPO>/.venv/bin/pytest tests/test_agent_tools.py -q -k do_list`
Expected: FAIL — `AttributeError: ... '_do_list'`.

- [ ] **Step 3: `_do_list` implementieren**

In `agents/agent_tools.py` ans Ende anhängen:

```python
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
```

- [ ] **Step 4: Test ausführen — grün**

Run: `PYTHONPATH=agents <REPO>/.venv/bin/pytest tests/test_agent_tools.py -q -k do_list`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add agents/agent_tools.py tests/test_agent_tools.py
git commit -m "feat(agent): workspace _do_list — Verzeichnis auflisten"
```

---

### Task 6: `agent_tools.py` — `workspace_tool` + MCP-Server

Der `@tool`-dekorierte `workspace_tool` verteilt auf `_do_read`/`_do_search`/`_do_list` und liefert das MCP-Content-Format. `build_mcp_server()` registriert ihn.

**Files:**
- Modify: `agents/agent_tools.py`
- Test: `tests/test_agent_tools.py`

- [ ] **Step 1: Failing Test schreiben**

In `tests/test_agent_tools.py` anhängen:

```python
@pytest.mark.asyncio
async def test_workspace_tool_read(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WORKSPACE_DIR", str(tmp_path))
    (tmp_path / "f.txt").write_text("Inhalt", encoding="utf-8")
    result = await agent_tools.workspace_tool.handler(
        {"action": "read", "path": "f.txt", "query": ""}
    )
    assert result["content"][0]["text"] == "Inhalt"


@pytest.mark.asyncio
async def test_workspace_tool_unknown_action(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WORKSPACE_DIR", str(tmp_path))
    result = await agent_tools.workspace_tool.handler(
        {"action": "delete", "path": "f.txt", "query": ""}
    )
    assert result["content"][0]["text"].startswith("FEHLER:")


def test_build_mcp_server_registers_workspace():
    server = agent_tools.build_mcp_server()
    assert server is not None
```

(Top of file bereits `import pytest` — vorhanden seit Task 2.)

- [ ] **Step 2: Test ausführen — schlägt fehl**

Run: `PYTHONPATH=agents <REPO>/.venv/bin/pytest tests/test_agent_tools.py -q -k "workspace_tool or mcp_server"`
Expected: FAIL — `AttributeError: ... 'workspace_tool'`.

- [ ] **Step 3: `workspace_tool` + `build_mcp_server` implementieren**

Am **Anfang** von `agents/agent_tools.py` den Import ergänzen (unter `from pathlib import Path`):

```python
from claude_agent_sdk import tool, create_sdk_mcp_server
```

In `agents/agent_tools.py` ans Ende anhängen:

```python
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
```

- [ ] **Step 4: Test ausführen — grün**

Run: `PYTHONPATH=agents <REPO>/.venv/bin/pytest tests/test_agent_tools.py -q`
Expected: PASS (alle agent_tools-Tests).

- [ ] **Step 5: Commit**

```bash
git add agents/agent_tools.py tests/test_agent_tools.py
git commit -m "feat(agent): workspace_tool + MCP-Server-Factory"
```

---

### Task 7: `agent_tools.py` — Permission-Hook

Das Sicherheits-Gate. Phase 1 hat nur Lese-Werkzeuge: der Hook erlaubt den `workspace`-Tool und lehnt alles Unerwartete ab (Defense-in-Depth). Phase 2 ergänzt hier die Schreib-/Confirm-Logik.

**Files:**
- Modify: `agents/agent_tools.py`
- Test: `tests/test_agent_tools.py`

- [ ] **Step 1: Failing Test schreiben**

In `tests/test_agent_tools.py` anhängen:

```python
from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny


@pytest.mark.asyncio
async def test_permission_hook_allows_workspace():
    result = await agent_tools.permission_hook(
        "mcp__jarvis__workspace", {"action": "read", "path": "x"}, None
    )
    assert isinstance(result, PermissionResultAllow)


@pytest.mark.asyncio
async def test_permission_hook_denies_unknown_tool():
    result = await agent_tools.permission_hook("Bash", {"command": "rm -rf /"}, None)
    assert isinstance(result, PermissionResultDeny)
    assert result.interrupt is False
```

- [ ] **Step 2: Test ausführen — schlägt fehl**

Run: `PYTHONPATH=agents <REPO>/.venv/bin/pytest tests/test_agent_tools.py -q -k permission_hook`
Expected: FAIL — `AttributeError: ... 'permission_hook'`.

- [ ] **Step 3: `permission_hook` implementieren**

Den Import-Block am Anfang von `agents/agent_tools.py` erweitern:

```python
from claude_agent_sdk import (
    tool,
    create_sdk_mcp_server,
    PermissionResultAllow,
    PermissionResultDeny,
)
```

In `agents/agent_tools.py` ans Ende anhängen:

```python
_WORKSPACE_TOOL_NAME = "mcp__jarvis__workspace"


async def permission_hook(tool_name: str, tool_input: dict, context) -> object:
    """can_use_tool-Gate. Phase 1: nur der Lese-Tool workspace ist freigegeben.

    Feuert nur für Tools, die NICHT in allowed_tools stehen (WebSearch/WebFetch
    sind dort gelistet → auto-erlaubt). Phase 2 erweitert dies um Schreib-/
    Confirm-Aktionen.
    """
    if tool_name == _WORKSPACE_TOOL_NAME:
        return PermissionResultAllow(updated_input=tool_input)
    return PermissionResultDeny(
        message=f"Werkzeug '{tool_name}' ist nicht freigegeben.",
        interrupt=False,
    )
```

- [ ] **Step 4: Test ausführen — grün**

Run: `PYTHONPATH=agents <REPO>/.venv/bin/pytest tests/test_agent_tools.py -q`
Expected: PASS (alle agent_tools-Tests).

- [ ] **Step 5: Commit**

```bash
git add agents/agent_tools.py tests/test_agent_tools.py
git commit -m "feat(agent): Permission-Hook — workspace erlauben, Rest ablehnen"
```

---

### Task 8: `agent.py` — Reine Funktionen (Flag, Prompt, History)

Erstellt `agent.py` mit den deterministischen, gut testbaren Bausteinen: Feature-Flag, System-Prompt, History-Formatierung, User-Prompt-Bau.

**Files:**
- Create: `agents/agent.py`
- Test: `tests/test_agent.py`

- [ ] **Step 1: Failing Test schreiben**

Create `tests/test_agent.py`:

```python
"""Tests für agents/agent.py."""

import pytest

import agent


def test_agent_enabled_default_off(monkeypatch):
    monkeypatch.delenv("JARVIS_AGENT_ENABLED", raising=False)
    assert agent.agent_enabled() is False


def test_agent_enabled_on(monkeypatch):
    monkeypatch.setenv("JARVIS_AGENT_ENABLED", "1")
    assert agent.agent_enabled() is True
    monkeypatch.setenv("JARVIS_AGENT_ENABLED", "true")
    assert agent.agent_enabled() is True


def test_system_prompt_includes_memory_context():
    prompt = agent.build_system_prompt("=== Erinnerungen ===\nPhilipp mag Tee\n\n")
    assert "Philipp mag Tee" in prompt
    assert "workspace" in prompt


def test_system_prompt_empty_memory():
    prompt = agent.build_system_prompt("")
    assert prompt.startswith("Du bist Jarvis")


def test_format_history_interleaves_roles():
    history = [
        {"role": "user", "content": "Frage 1"},
        {"role": "assistant", "content": "Antwort 1"},
    ]
    text = agent.format_history(history)
    assert "Philipp: Frage 1" in text
    assert "Jarvis: Antwort 1" in text


def test_format_history_empty():
    assert agent.format_history([]) == ""


def test_format_history_caps_turns():
    history = [{"role": "user", "content": f"m{i}"} for i in range(100)]
    text = agent.format_history(history)
    assert text.count("\n") < 60  # auf ~15 Turns (= 30 Zeilen) gekappt


def test_build_user_prompt_with_history():
    history = [{"role": "user", "content": "alt"}]
    prompt = agent.build_user_prompt(history, "neue Frage")
    assert "[Bisheriger Gesprächsverlauf]" in prompt
    assert "[Aktuelle Nachricht]" in prompt
    assert "neue Frage" in prompt


def test_build_user_prompt_no_history():
    assert agent.build_user_prompt([], "nur die Frage") == "nur die Frage"
```

- [ ] **Step 2: Test ausführen — schlägt fehl**

Run: `PYTHONPATH=agents <REPO>/.venv/bin/pytest tests/test_agent.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent'`.

- [ ] **Step 3: `agent.py` mit den reinen Funktionen anlegen**

Create `agents/agent.py`:

```python
"""Agentische Konversations-Runtime — Phase 1 des agentischen Jarvis.

Ein zustandsloser SDK-Lauf pro Telegram-Nachricht. Der Router bleibt vorgelagert;
diese Runtime übernimmt personal/work/research, wenn JARVIS_AGENT_ENABLED gesetzt
ist.
"""

import logging
import os

logger = logging.getLogger("jarvis.agent")

_DEFAULT_MODEL = "claude-sonnet-4-6"
_MAX_TURNS = 12
_HISTORY_TURNS = 15


def agent_enabled() -> bool:
    """True, wenn der agentische Pfad per Feature-Flag aktiv ist."""
    return os.environ.get("JARVIS_AGENT_ENABLED", "0").strip().lower() in (
        "1", "true", "yes", "on",
    )


def build_system_prompt(memory_context: str) -> str:
    """System-Prompt des Agenten — Rolle, Stil, Werkzeug-Hinweise.

    memory_context (Profil + Erinnerungen) wird vorangestellt.
    """
    base = (
        "Du bist Jarvis, der persönliche KI-Assistent von Philipp. "
        "Antworte hilfreich, präzise und auf Deutsch.\n\n"
        "Werkzeuge:\n"
        "- workspace: Liest und durchsucht Philipps Projekt-Code im Coding-Workspace "
        "(Projekte u.a.: recipe-app, herrlich-ai-platform, immo-radar, "
        "high-five-website, refurbish-business, cv-project). Nutze es für fundierte "
        "Fragen zu seinen Projekten — list/search/read, nicht raten.\n"
        "- WebSearch / WebFetch: Aktuelle Informationen aus dem Internet.\n\n"
        "Arbeitsweise: Bei Fragen zu Philipps Projekten oder Code zuerst den "
        "Workspace erkunden, dann fundiert antworten. Bei Fragen zu aktuellen "
        "Ereignissen das Web nutzen. Halte Antworten Telegram-tauglich kurz. "
        "Wenn du etwas nicht sicher weißt, sag es offen."
    )
    return (memory_context + base) if memory_context else base


def format_history(history: list[dict]) -> str:
    """Gesprächsverlauf als Klartext — auf die letzten ~15 Turns gekappt.

    history-Einträge: {"role": "user"|"assistant", "content": str}.
    """
    if not history:
        return ""
    recent = history[-(_HISTORY_TURNS * 2):]
    lines = []
    for turn in recent:
        who = "Philipp" if turn.get("role") == "user" else "Jarvis"
        lines.append(f"{who}: {turn.get('content', '')}")
    return "\n".join(lines)


def build_user_prompt(history: list[dict], user_text: str) -> str:
    """Die User-Nachricht für den SDK-Lauf — History als Text eingebettet.

    History als separate Stream-Nachrichten zu senden lässt den Agenten alte
    Turns erneut beantworten (in Schritt A verifiziert) — daher als Text.
    """
    hist = format_history(history)
    if hist:
        return (
            "[Bisheriger Gesprächsverlauf]\n" + hist
            + "\n\n[Aktuelle Nachricht]\n" + user_text
        )
    return user_text
```

- [ ] **Step 4: Test ausführen — grün**

Run: `PYTHONPATH=agents <REPO>/.venv/bin/pytest tests/test_agent.py -q`
Expected: PASS (9 passed).

- [ ] **Step 5: Commit**

```bash
git add agents/agent.py tests/test_agent.py
git commit -m "feat(agent): Flag, System-Prompt und History-Formatierung"
```

---

### Task 9: `app_state.py` — Per-Chat-Lauf-Lock

Ein agentischer Lauf dauert länger als die heutigen Handler. Eine zweite Nachricht im selben Chat wird per `asyncio.Lock` serialisiert (Design: „pro Chat serialisiert").

**Files:**
- Modify: `agents/app_state.py`
- Test: `tests/test_agent.py`

- [ ] **Step 1: Failing Test schreiben**

In `tests/test_agent.py` anhängen:

```python
import asyncio
import app_state


def test_get_agent_lock_returns_same_lock_per_chat():
    app_state.agent_run_locks.clear()
    lock_a1 = app_state.get_agent_lock(111)
    lock_a2 = app_state.get_agent_lock(111)
    lock_b = app_state.get_agent_lock(222)
    assert lock_a1 is lock_a2
    assert lock_a1 is not lock_b
    assert isinstance(lock_a1, asyncio.Lock)
```

- [ ] **Step 2: Test ausführen — schlägt fehl**

Run: `PYTHONPATH=agents <REPO>/.venv/bin/pytest tests/test_agent.py -q -k agent_lock`
Expected: FAIL — `AttributeError: module 'app_state' has no attribute 'agent_run_locks'`.

- [ ] **Step 3: Lock-Registry in `app_state.py` ergänzen**

In `agents/app_state.py` nach dem Block `processed_updates: set = set()` (Zeile ~25) einfügen:

```python
# Per-Chat-Locks — serialisieren agentische Läufe innerhalb eines Chats.
agent_run_locks: dict[int, asyncio.Lock] = {}


def get_agent_lock(chat_id: int) -> asyncio.Lock:
    """Den (lazy erzeugten) asyncio.Lock für einen Chat zurückgeben."""
    lock = agent_run_locks.get(chat_id)
    if lock is None:
        lock = asyncio.Lock()
        agent_run_locks[chat_id] = lock
    return lock
```

(`import asyncio` steht bereits oben in `app_state.py`.)

- [ ] **Step 4: Test ausführen — grün**

Run: `PYTHONPATH=agents <REPO>/.venv/bin/pytest tests/test_agent.py -q -k agent_lock`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add agents/app_state.py tests/test_agent.py
git commit -m "feat(agent): Per-Chat-Lock zur Lauf-Serialisierung"
```

---

### Task 10: `agent.py` — `run_agent()` (der SDK-Loop)

Der Kern: baut `ClaudeAgentOptions`, fährt den `query()`-Loop, extrahiert die finale Antwort, schickt sie an Telegram. In Tests wird `query` gemockt — kein CLI-Start.

**Files:**
- Modify: `agents/agent.py`
- Test: `tests/test_agent.py`

- [ ] **Step 1: Failing Test schreiben**

In `tests/test_agent.py` anhängen:

```python
from unittest.mock import AsyncMock, MagicMock, patch
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock


def _fake_assistant(text):
    msg = MagicMock(spec=AssistantMessage)
    block = MagicMock(spec=TextBlock)
    block.text = text
    msg.content = [block]
    return msg


def _fake_result(result_text, is_error=False):
    msg = MagicMock(spec=ResultMessage)
    msg.result = result_text
    msg.is_error = is_error
    return msg


@pytest.mark.asyncio
async def test_run_agent_returns_result_text():
    async def fake_query(*, prompt, options=None, transport=None):
        yield _fake_assistant("Zwischentext")
        yield _fake_result("Die finale Antwort.")

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()
    app_state.agent_run_locks.clear()
    with patch("agent.query", fake_query), \
         patch("agent.Bot", return_value=mock_bot), \
         patch("agent._keep_typing", new=AsyncMock()):
        answer = await agent.run_agent(555, "Hallo", [], "")

    assert answer == "Die finale Antwort."
    mock_bot.send_message.assert_awaited_once()
    assert mock_bot.send_message.call_args.kwargs["text"] == "Die finale Antwort."


@pytest.mark.asyncio
async def test_run_agent_handles_query_exception():
    async def boom(*, prompt, options=None, transport=None):
        raise RuntimeError("CLI weg")
        yield  # pragma: no cover

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()
    app_state.agent_run_locks.clear()
    with patch("agent.query", boom), \
         patch("agent.Bot", return_value=mock_bot), \
         patch("agent._keep_typing", new=AsyncMock()):
        answer = await agent.run_agent(555, "Hallo", [], "")

    assert answer.startswith("Fehler:")
    mock_bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_agent_serializes_per_chat():
    order = []

    async def slow_query(*, prompt, options=None, transport=None):
        order.append("start")
        await asyncio.sleep(0.05)
        order.append("end")
        yield _fake_result("ok")

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()
    app_state.agent_run_locks.clear()
    with patch("agent.query", slow_query), \
         patch("agent.Bot", return_value=mock_bot), \
         patch("agent._keep_typing", new=AsyncMock()):
        await asyncio.gather(
            agent.run_agent(777, "A", [], ""),
            agent.run_agent(777, "B", [], ""),
        )

    # Serialisiert: erst beide Schritte von Lauf 1, dann Lauf 2 — kein Interleaving.
    assert order == ["start", "end", "start", "end"]
```

- [ ] **Step 2: Test ausführen — schlägt fehl**

Run: `PYTHONPATH=agents <REPO>/.venv/bin/pytest tests/test_agent.py -q -k run_agent`
Expected: FAIL — `AttributeError: module 'agent' has no attribute 'run_agent'`.

- [ ] **Step 3: `run_agent` implementieren**

Den Import-Block am Anfang von `agents/agent.py` erweitern (`import logging`/`import os` bleiben):

```python
import asyncio
import logging
import os

from telegram import Bot
from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
    TextBlock,
)

import app_state
from app_state import _keep_typing
from agent_tools import build_mcp_server, permission_hook
```

In `agents/agent.py` ans Ende anhängen:

```python
async def run_agent(
    chat_id: int,
    user_text: str,
    history: list[dict],
    memory_context: str,
) -> str:
    """Einen agentischen Turn fahren: Optionen bauen, SDK-Loop, Antwort senden.

    Pro Chat serialisiert (asyncio.Lock). Gibt den finalen Antworttext zurück.
    """
    async with app_state.get_agent_lock(chat_id):
        bot = Bot(token=app_state.TELEGRAM_TOKEN)
        stop = asyncio.Event()
        typing_task = asyncio.create_task(_keep_typing(chat_id, stop))
        final_text = ""
        try:
            opts_kwargs = dict(
                model=os.environ.get("JARVIS_AGENT_MODEL", _DEFAULT_MODEL),
                system_prompt=build_system_prompt(memory_context),
                mcp_servers={"jarvis": build_mcp_server()},
                allowed_tools=["WebSearch", "WebFetch"],
                tools=["WebSearch", "WebFetch"],
                can_use_tool=permission_hook,
                max_turns=_MAX_TURNS,
                permission_mode="default",
            )
            cli_path = os.environ.get("JARVIS_CLAUDE_CLI_PATH")
            if cli_path:
                opts_kwargs["cli_path"] = cli_path
            options = ClaudeAgentOptions(**opts_kwargs)

            prompt_text = build_user_prompt(history, user_text)

            async def _prompt_stream():
                yield {
                    "type": "user",
                    "message": {"role": "user", "content": prompt_text},
                }

            async for msg in query(prompt=_prompt_stream(), options=options):
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock) and block.text.strip():
                            final_text = block.text
                elif isinstance(msg, ResultMessage):
                    if msg.result:
                        final_text = msg.result
                    elif msg.is_error and not final_text:
                        final_text = "Der Agent konnte die Anfrage nicht abschließen."
        except Exception as e:
            logger.exception("Agent-Lauf fehlgeschlagen")
            final_text = f"Fehler: {e}"
        finally:
            stop.set()
            await typing_task

        if not final_text:
            final_text = "Keine Antwort erhalten."
        if len(final_text) > 4000:
            final_text = final_text[:4000] + "\n[...]"
        await bot.send_message(chat_id=chat_id, text=final_text)

    if app_state.memory_agent and not final_text.startswith("Fehler:"):
        asyncio.create_task(
            app_state.memory_agent.extract(user_text, final_text, source="agent")
        )
    return final_text
```

- [ ] **Step 4: Test ausführen — grün**

Run: `PYTHONPATH=agents <REPO>/.venv/bin/pytest tests/test_agent.py -q`
Expected: PASS (alle agent-Tests).

- [ ] **Step 5: Commit**

```bash
git add agents/agent.py tests/test_agent.py
git commit -m "feat(agent): run_agent — der SDK-Loop mit Telegram-Ausgabe"
```

---

### Task 11: `dispatch.py` — Feature-Flag-Verdrahtung

`_process_text` routet `personal`/`work`/`research` an `run_agent`, wenn das Flag an ist — sonst an die bisherigen Handler. Bei Flag aus ist das Verhalten bit-identisch zu heute.

**Files:**
- Modify: `agents/dispatch.py`
- Test: `tests/test_agent_dispatch.py`

- [ ] **Step 1: Failing Test schreiben**

Create `tests/test_agent_dispatch.py`:

```python
"""Tests für die Feature-Flag-Verdrahtung in dispatch._process_text."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app_state
import dispatch


def _routing(intent):
    return {"intent": intent, "params": {}, "confidence": 8, "reasoning": ""}


@pytest.mark.asyncio
async def test_personal_routed_to_agent_when_flag_on():
    app_state.conversation_db = None
    app_state.profile_agent = None
    app_state.memory_agent = None
    update = MagicMock()
    with patch("dispatch.route_with_llm", new=AsyncMock(return_value=_routing("personal"))), \
         patch("dispatch.agent_enabled", return_value=True), \
         patch("dispatch.run_agent", new=AsyncMock(return_value="Agent-Antwort")) as mock_run, \
         patch("dispatch.handle_personal", new=AsyncMock()) as mock_personal:
        await dispatch._process_text("Hallo", 123, update)
    mock_run.assert_awaited_once()
    mock_personal.assert_not_awaited()


@pytest.mark.asyncio
async def test_personal_routed_to_legacy_handler_when_flag_off():
    app_state.conversation_db = None
    app_state.profile_agent = None
    app_state.memory_agent = None
    update = MagicMock()
    with patch("dispatch.route_with_llm", new=AsyncMock(return_value=_routing("personal"))), \
         patch("dispatch.agent_enabled", return_value=False), \
         patch("dispatch.run_agent", new=AsyncMock()) as mock_run, \
         patch("dispatch.handle_personal", new=AsyncMock(return_value="Klassik")) as mock_personal:
        await dispatch._process_text("Hallo", 123, update)
    mock_personal.assert_awaited_once()
    mock_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_weather_never_routed_to_agent():
    app_state.conversation_db = None
    app_state.profile_agent = None
    app_state.memory_agent = None
    update = MagicMock()
    with patch("dispatch.route_with_llm", new=AsyncMock(return_value=_routing("weather"))), \
         patch("dispatch.agent_enabled", return_value=True), \
         patch("dispatch.run_agent", new=AsyncMock()) as mock_run, \
         patch("dispatch.handle_weather", new=AsyncMock()) as mock_weather:
        await dispatch._process_text("Wetter morgen?", 123, update)
    mock_weather.assert_awaited_once()
    mock_run.assert_not_awaited()
```

- [ ] **Step 2: Test ausführen — schlägt fehl**

Run: `PYTHONPATH=agents <REPO>/.venv/bin/pytest tests/test_agent_dispatch.py -q`
Expected: FAIL — `ImportError: cannot import name 'run_agent'` bzw. die Asserts schlagen fehl, weil noch nicht verdrahtet.

- [ ] **Step 3: `dispatch.py` verdrahten**

In `agents/dispatch.py` den Import-Block (nach `from chat_handler import ...`, Zeile ~18) ergänzen:

```python
from agent import run_agent, agent_enabled
```

Direkt nach `_HISTORY_INTENTS = {"personal", "work", "research"}` (Zeile ~33) ergänzen:

```python
_AGENT_INTENTS = {"personal", "work", "research"}
```

Den Verzweigungsblock in `_process_text` — heute Zeilen 91–120, beginnend mit `if intent == "calendar":` bis `answer = await handle_personal(...)` — **vollständig** ersetzen durch:

```python
    if intent in _AGENT_INTENTS and agent_enabled():
        answer = await run_agent(chat_id, text, history, memory_context)
    elif intent == "calendar":
        await handle_calendar_intent(chat_id, text, params)
        return
    elif intent == "mail":
        await handle_mail_intent(chat_id, text, params)
        return
    elif intent == "research":
        answer = await handle_research(chat_id, text, memory_context, history)
    elif intent == "coding":
        await handle_coding(chat_id, text, params, update)
    elif intent == "reminder_write":
        await handle_reminder_write(chat_id, params, update)
        return
    elif intent == "work":
        answer = await handle_work(chat_id, text, memory_context, history)
    elif intent == "news":
        await handle_news(chat_id, update)
    elif intent == "tasks":
        await handle_tasks(chat_id, params, update)
    elif intent == "weather":
        await handle_weather(chat_id, params, update)
    elif intent == "briefing":
        await handle_briefing(chat_id, update)
    elif intent == "memory":
        await handle_memory(chat_id, params, update)
        return
    else:
        answer = await handle_personal(chat_id, text, memory_context, history)
```

(Die bisherigen freistehenden `if intent == "calendar"` / `if intent == "mail"` werden Teil **einer** `if/elif`-Kette. Verhalten bei Flag aus: identisch zu heute.)

- [ ] **Step 4: Test ausführen — grün**

Run: `PYTHONPATH=agents <REPO>/.venv/bin/pytest tests/test_agent_dispatch.py tests/test_dispatch_main.py -q`
Expected: PASS (neue Tests + bestehende Dispatch-Tests).

- [ ] **Step 5: Gesamte Suite grün**

Run: die volle Suite (siehe Konventionen).
Expected: PASS (Baseline 169 + neue Tests).

- [ ] **Step 6: Commit**

```bash
git add agents/dispatch.py tests/test_agent_dispatch.py
git commit -m "feat(agent): Feature-Flag-Verdrahtung in dispatch._process_text"
```

---

### Task 12: Opt-in Live-Smoke-Test

Ein echter End-to-End-Lauf gegen das SDK (startet die `claude`-CLI, kostet Tokens). Per `JARVIS_LIVE_TESTS` aktiviert — sonst geskippt, daher kein `--ignore` nötig.

**Files:**
- Create: `tests/test_agent_live.py`

- [ ] **Step 1: Live-Smoke-Test schreiben**

Create `tests/test_agent_live.py`:

```python
"""Opt-in End-to-End-Smoke-Test für den agentischen Pfad.

Aktivieren mit:  JARVIS_LIVE_TESTS=1 PYTHONPATH=agents <venv>/bin/pytest tests/test_agent_live.py -v
Voraussetzung: Claude Code CLI installiert + per OAuth/Abo authentifiziert.
"""

import os
from pathlib import Path

import pytest

import agent

_LIVE = os.environ.get("JARVIS_LIVE_TESTS", "").strip() not in ("", "0", "false")
pytestmark = pytest.mark.skipif(not _LIVE, reason="JARVIS_LIVE_TESTS nicht gesetzt")


@pytest.mark.asyncio
async def test_agent_reads_workspace_file(tmp_path, monkeypatch):
    """Der Agent soll eine bekannte Workspace-Datei lesen und ihren Inhalt nennen."""
    monkeypatch.setenv("JARVIS_WORKSPACE_DIR", str(tmp_path))
    secret = "Apfelstrudel-7421"
    (tmp_path / "notiz.txt").write_text(
        f"Das geheime Codewort lautet {secret}.", encoding="utf-8"
    )

    sent = {}

    class _Bot:
        def __init__(self, *a, **k):
            pass

        async def send_message(self, chat_id, text):
            sent["text"] = text

    monkeypatch.setattr(agent, "Bot", _Bot)

    # Typing-Indikator ausschalten — sonst würde _keep_typing mit dem
    # Test-Telegram-Token echte API-Calls versuchen und fehlschlagen.
    async def _noop_keep_typing(chat_id, stop_event):
        return

    monkeypatch.setattr(agent, "_keep_typing", _noop_keep_typing)

    answer = await agent.run_agent(
        chat_id=999,
        user_text="Lies die Datei notiz.txt im Workspace und nenne mir das Codewort.",
        history=[],
        memory_context="",
    )
    assert secret in answer
    assert secret in sent.get("text", "")
```

- [ ] **Step 2: Standard-Suite verifizieren (Live-Test wird geskippt)**

Run: die volle Suite (siehe Konventionen).
Expected: PASS — `test_agent_live.py` erscheint als `skipped`, die übrige Suite grün.

- [ ] **Step 3: Live-Test ausführen (lokal, CLI vorhanden)**

Run: `JARVIS_LIVE_TESTS=1 PYTHONPATH=agents <REPO>/.venv/bin/pytest tests/test_agent_live.py -v --tb=short`
Expected: PASS — der Agent liest die Datei und nennt `Apfelstrudel-7421`.
(Schlägt der Test fehl, weil `ANTHROPIC_API_KEY` gesetzt ist und du Abo-Auth willst: für diesen Lauf `env -u ANTHROPIC_API_KEY ...` voranstellen.)

- [ ] **Step 4: Commit**

```bash
git add tests/test_agent_live.py
git commit -m "test(agent): Opt-in Live-Smoke-Test für den End-to-End-Lauf"
```

---

### Task 13: Dokumentation — `.env.example`, `CLAUDE.md`, VPS-Vorbereitung

**Files:**
- Modify: `.env.example`
- Modify: `CLAUDE.md`

- [ ] **Step 1: `.env.example` ergänzen**

`.env.example` vollständig ersetzen durch:

```
TELEGRAM_BOT_TOKEN=your-value-here
ANTHROPIC_API_KEY=your-value-here

# Agentischer Pfad (Phase 1) — Feature-Flag, default aus
JARVIS_AGENT_ENABLED=0
# Modell für den Agenten (default: claude-sonnet-4-6; auf Opus umstellbar)
JARVIS_AGENT_MODEL=claude-sonnet-4-6
# Workspace-Root, den der workspace-Tool lesen darf (muss vom jarvis-User lesbar sein)
JARVIS_WORKSPACE_DIR=/opt
# Optional: expliziter Pfad zur claude-CLI, falls nicht auf dem Service-PATH
JARVIS_CLAUDE_CLI_PATH=
# OAuth-Token der Claude Code CLI (headless) — via `claude setup-token` erzeugt
CLAUDE_CODE_OAUTH_TOKEN=your-value-here
```

- [ ] **Step 2: `CLAUDE.md` — Environment-Tabelle ergänzen**

In `CLAUDE.md` in der Tabelle „Environment Variables" nach der Zeile `GROQ_API_KEY` diese Zeilen einfügen:

```
| `JARVIS_AGENT_ENABLED` | ❌ | Feature-Flag agentischer Pfad (Default: `0` = heutiger Pfad) |
| `JARVIS_AGENT_MODEL` | ❌ | Modell für den Agenten (Default: `claude-sonnet-4-6`) |
| `JARVIS_WORKSPACE_DIR` | ❌ | Workspace-Root für den `workspace`-Tool (Default: `~/Code`) |
| `JARVIS_CLAUDE_CLI_PATH` | ❌ | Expliziter Pfad zur `claude`-CLI, falls nicht auf PATH |
| `CLAUDE_CODE_OAUTH_TOKEN` | ❌ | OAuth-Token der Claude Code CLI (headless, Abo-Auth) |
```

- [ ] **Step 3: `CLAUDE.md` — Abschnitt „Agentischer Pfad (Phase 1)" einfügen**

In `CLAUDE.md` direkt vor dem Abschnitt `## Stack` einfügen:

````markdown
## Agentischer Pfad (Phase 1) — Feature-Flag

`personal`/`work`/`research` laufen — wenn `JARVIS_AGENT_ENABLED=1` — durch einen
echten Agenten (`agents/agent.py`, Claude Agent SDK) statt durch die Single-shot-
`chat_handler`-Funktionen. Der Router bleibt vorgelagert; strukturierte Intents
(`mail`, `calendar`, …) sind unverändert. Flag aus = Verhalten exakt wie bisher.

- `agents/agent.py` — `run_agent()`: ein zustandsloser SDK-Lauf pro Nachricht,
  History als Text eingebettet, Antwort an Telegram. Pro Chat serialisiert.
- `agents/agent_tools.py` — `workspace`-Tool (Datei lesen/suchen/listen, sandboxed
  auf `JARVIS_WORKSPACE_DIR`), MCP-Server, `can_use_tool`-Permission-Hook.
- Werkzeuge: `workspace` + die eingebauten `WebSearch`/`WebFetch`. Built-in
  `Bash`/`Edit`/`Read` sind für den Agenten deaktiviert.

### Auth & Runtime

Das Agent SDK startet die `claude`-CLI als Subprozess — sie nutzt OAuth/Abo-Auth
(kein `ANTHROPIC_API_KEY` nötig). Voraussetzungen auf dem VPS:

1. Node.js + Claude Code CLI: `npm install -g @anthropic-ai/claude-code`
2. Headless-Auth für den `jarvis`-User: `claude setup-token` ausführen, den Token
   als `CLAUDE_CODE_OAUTH_TOKEN` in `/var/lib/jarvis/.env` eintragen.
3. `JARVIS_WORKSPACE_DIR` auf ein vom `jarvis`-User lesbares Verzeichnis mit den
   Projekt-Klonen setzen (z. B. `/opt`).
4. Falls `claude` nicht auf dem Service-PATH liegt: `JARVIS_CLAUDE_CLI_PATH` setzen.
5. `JARVIS_AGENT_ENABLED` bleibt zunächst `0` — erst nach manueller Verifikation
   per Telegram auf `1` stellen und `jarvis` neu starten.

Live-Smoke-Test: `JARVIS_LIVE_TESTS=1 PYTHONPATH=agents .venv/bin/pytest tests/test_agent_live.py -v`
````

- [ ] **Step 4: Gesamte Suite grün**

Run: die volle Suite (siehe Konventionen).
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add .env.example CLAUDE.md
git commit -m "docs(agent): Env-Variablen + Phase-1-Architektur + VPS-Vorbereitung"
```

---

## Golden-Set — manuelle Verifikation (Flag an, über Telegram)

Nach lokalem Grün und vor dem produktiven Scharfschalten manuell durchspielen
(`JARVIS_AGENT_ENABLED=1`). Jedes Szenario muss nachweislich funktionieren:

1. **Projekt-Code-Frage:** „Welche Werkzeuge nutzt der Router in Jarvis?" → der
   Agent erkundet den Workspace (`list`/`search`/`read`) und antwortet fundiert.
2. **Aktuelle Information:** „Was ist das neueste Claude-Modell?" → Web-Suche.
3. **Trivial/schnell:** „Schreib mir einen kurzen Geburtstagsgruß" → direkte
   Antwort ohne Tool-Calls.
4. **Konversation mit History:** Eine Folgefrage, die sich auf die vorige Antwort
   bezieht („und mach ihn etwas formeller") → der Agent nutzt den Verlauf.
5. **Regressions-Basislinie:** Strukturierte Aufgaben (Wetter, Erinnerung,
   Mail-Lesen) laufen unverändert über die Handler — kein Verhaltens- oder
   Latenz-Regress.

---

## Phase-1-Abschluss — Definition of Done

- [ ] Alle 13 Tasks committet, gesamte Suite grün (Baseline 169 + neue Tests).
- [ ] Live-Smoke-Test (`test_agent_live.py`) lokal grün.
- [ ] Golden-Set manuell über Telegram verifiziert (Flag an, lokal/VPS).
- [ ] `CLAUDE.md` + `.env.example` aktualisiert.
- [ ] Code auf `main` gemergt; `JARVIS_AGENT_ENABLED=0` in Produktion (Deploy
      schlummert wirkungslos, bis der VPS vorbereitet und das Flag manuell
      gestellt wird).
- [ ] `BACKLOG.md`: P1-Eintrag auf „Phase 1 erledigt, Phase 2 offen" anpassen.

**Bewusst nicht in Phase 1** (siehe Design, YAGNI): Handler→Tools-Konvertierung,
Write-Confirm-Fluss, `router.py`-Entfall — das ist Phase 2/3, eigene Pläne.
