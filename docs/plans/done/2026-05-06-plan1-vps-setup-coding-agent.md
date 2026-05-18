# VPS Setup + Coding Agent Neubau — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Coding Agent komplett neu bauen — Docker raus, direkt auf VPS als claude-user, persistente Sessions, Query/Action/Backlog-Write Split, alle 5 Repos im Workspace.

**Architecture:** Jarvis (root, systemd) ruft `sudo -u claude claude ...` direkt auf dem VPS auf. Sessions werden per Projekt in SQLite gespeichert (`--resume <session_id>` für Follow-ups). Schnelle Queries (Backlog lesen, git log) laufen ohne Claude Code direkt über Datei/Git-Zugriff.

**Tech Stack:** Python 3.11, asyncio, anthropic Claude CLI (`claude`), SQLite (aiosqlite), python-telegram-bot, paramiko nicht nötig (sudo direkt)

**VPS SSH:** `root@100.115.184.3` (Tailscale), alle Befehle werden direkt auf dem VPS ausgeführt. Jarvis läuft als root, claude-user hat `/home/claude/workspace/`.

---

## File Structure

```
agents/
  db.py                   NEU — SQLite session management (aiosqlite)
  vps.py                  NEU — subprocess helper (sudo -u claude)
  coding_agent.py         REWRITE — Query/Action/Backlog-Write
  main.py                 MODIFY — coding handler ersetzen, project discovery
  router.py               MODIFY — backlog_write mode + project list in context

scripts/
  setup-workspace.sh      NEU — repos klonen, PAT prüfen, artifacts aufräumen

tests/
  test_db.py              NEU
  test_coding_agent.py    NEU

config/
  caddy/Caddyfile         MODIFY — sync mit /etc/caddy/Caddyfile
```

---

## Task 1: VPS Workspace Setup (auf dem VPS ausführen)

**Ziel:** Alle 5 Repos geklont, Artifacts aufgeräumt, Caddyfile sync.

**Files:**
- Create: `scripts/setup-workspace.sh`

- [ ] **Step 1.1: Skript schreiben**

```bash
# scripts/setup-workspace.sh
#!/bin/bash
set -e

WORKSPACE="/home/claude/workspace"
GITHUB_USER="phiman13"
REPOS="recipe-app immo-radar refurbish-business herrlich-dev herrlich-ai-platform"

echo "=== Workspace Setup ==="

# PAT prüfen
if [ -z "$GITHUB_TOKEN" ] && [ -f /root/.env ]; then
    export $(grep -v '^#' /root/.env | xargs)
fi
if [ -z "$GITHUB_TOKEN" ]; then
    echo "ERROR: GITHUB_TOKEN nicht gesetzt. In /root/.env als GITHUB_TOKEN=ghp_... eintragen."
    exit 1
fi

# Git credential helper für PAT
git config --global credential.helper store
echo "https://${GITHUB_USER}:${GITHUB_TOKEN}@github.com" > /root/.git-credentials
chmod 600 /root/.git-credentials

# Workspace erstellen falls nicht vorhanden
mkdir -p "$WORKSPACE"
chown claude:claude "$WORKSPACE"

# Repos klonen oder updaten
for REPO in $REPOS; do
    TARGET="$WORKSPACE/$REPO"
    if [ -d "$TARGET/.git" ]; then
        echo "  UPDATE: $REPO"
        sudo -u claude git -C "$TARGET" pull --quiet
    else
        echo "  CLONE: $REPO"
        sudo -u claude git clone "https://${GITHUB_USER}:${GITHUB_TOKEN}@github.com/${GITHUB_USER}/${REPO}.git" "$TARGET"
    fi
done

# Caddyfile synchronisieren
REPO_CADDY="/root/herrlich-ai-platform/config/caddy/Caddyfile"
LIVE_CADDY="/etc/caddy/Caddyfile"
if [ -f "$LIVE_CADDY" ]; then
    cp "$LIVE_CADDY" "$REPO_CADDY"
    echo "  SYNC: Caddyfile -> Repo"
fi

# Artefakte in /root/ aufräumen
echo "=== Cleanup /root/ artifacts ==="
for ARTIFACT in "600" "700" "77" "CHMOD" "ECHO" "=2.1"; do
    TARGET="/root/$ARTIFACT"
    if [ -e "$TARGET" ]; then
        rm -rf "$TARGET"
        echo "  REMOVED: $TARGET"
    fi
done
# SSH-Key-Fragment Verzeichnis
for D in /root/AAAA*; do
    [ -e "$D" ] && rm -rf "$D" && echo "  REMOVED: $D"
done

echo "=== Done ==="
sudo -u claude ls "$WORKSPACE"
```

- [ ] **Step 1.2: Script ausführbar machen und committen**

```bash
chmod +x scripts/setup-workspace.sh
git add scripts/setup-workspace.sh
git commit -m "feat(setup): workspace setup script — clone repos, sync Caddyfile, cleanup"
```

- [ ] **Step 1.3: Auf VPS deployen und ausführen**

```bash
# Auf VPS (via SSH root@100.115.184.3):
cd /root/herrlich-ai-platform
git pull
bash scripts/setup-workspace.sh
```

Erwartete Ausgabe:
```
=== Workspace Setup ===
  UPDATE: recipe-app
  CLONE: immo-radar
  CLONE: refurbish-business
  CLONE: herrlich-dev
  CLONE: herrlich-ai-platform
  SYNC: Caddyfile -> Repo
=== Cleanup /root/ artifacts ===
  REMOVED: /root/600
  ...
=== Done ===
herrlich-ai-platform  herrlich-dev  immo-radar  recipe-app  refurbish-business
```

- [ ] **Step 1.4: Caddyfile-Änderung committen**

```bash
# Lokal (nach git pull):
git add config/caddy/Caddyfile
git commit -m "fix(caddy): sync Caddyfile mit live-Stand (code.herrlich.dev + refurbish)"
```

---

## Task 2: SQLite Session Manager (db.py)

**Files:**
- Create: `agents/db.py`
- Create: `tests/test_db.py`

- [ ] **Step 2.1: Test schreiben**

```python
# tests/test_db.py
import asyncio
import os
import pytest
from agents.db import SessionDB

@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    return SessionDB(db_path)

def test_upsert_and_get(db):
    asyncio.run(db.init())
    asyncio.run(db.upsert_session("recipe-app", "sess_abc123"))
    result = asyncio.run(db.get_session("recipe-app", ttl_hours=2))
    assert result == "sess_abc123"

def test_expired_session_returns_none(db):
    asyncio.run(db.init())
    asyncio.run(db.upsert_session("recipe-app", "sess_old"))
    # TTL von 0 Stunden → sofort abgelaufen
    result = asyncio.run(db.get_session("recipe-app", ttl_hours=0))
    assert result is None

def test_unknown_project_returns_none(db):
    asyncio.run(db.init())
    result = asyncio.run(db.get_session("nonexistent", ttl_hours=2))
    assert result is None

def test_upsert_overwrites(db):
    asyncio.run(db.init())
    asyncio.run(db.upsert_session("recipe-app", "sess_old"))
    asyncio.run(db.upsert_session("recipe-app", "sess_new"))
    result = asyncio.run(db.get_session("recipe-app", ttl_hours=2))
    assert result == "sess_new"
```

- [ ] **Step 2.2: Test laufen lassen — muss fehlschlagen**

```bash
cd agents
python -m pytest ../tests/test_db.py -v
```

Erwartet: `ModuleNotFoundError: No module named 'agents.db'`

- [ ] **Step 2.3: db.py implementieren**

```python
# agents/db.py
import aiosqlite
from datetime import datetime, timedelta

class SessionDB:
    def __init__(self, path: str = "/root/.jarvis/sessions.db"):
        self.path = path

    async def init(self):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS coding_sessions (
                    project TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    last_used TIMESTAMP NOT NULL
                )
            """)
            await db.commit()

    async def upsert_session(self, project: str, session_id: str):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
                INSERT INTO coding_sessions (project, session_id, last_used)
                VALUES (?, ?, ?)
                ON CONFLICT(project) DO UPDATE SET
                    session_id = excluded.session_id,
                    last_used = excluded.last_used
            """, (project, session_id, datetime.utcnow().isoformat()))
            await db.commit()

    async def get_session(self, project: str, ttl_hours: float = 2.0) -> str | None:
        cutoff = (datetime.utcnow() - timedelta(hours=ttl_hours)).isoformat()
        async with aiosqlite.connect(self.path) as db:
            async with db.execute("""
                SELECT session_id FROM coding_sessions
                WHERE project = ? AND last_used > ?
            """, (project, cutoff)) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else None

    async def clear_session(self, project: str):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM coding_sessions WHERE project = ?", (project,))
            await db.commit()
```

- [ ] **Step 2.4: Tests laufen lassen — müssen grün sein**

```bash
pip install aiosqlite
python -m pytest ../tests/test_db.py -v
```

Erwartet: 4 passed

- [ ] **Step 2.5: `aiosqlite` zu requirements.txt hinzufügen**

```
# agents/requirements.txt — Zeile hinzufügen:
aiosqlite>=0.19.0
```

- [ ] **Step 2.6: Commit**

```bash
git add agents/db.py tests/test_db.py agents/requirements.txt
git commit -m "feat(db): SQLite session manager für Coding Agent"
```

---

## Task 3: VPS Subprocess Helper (vps.py)

**Files:**
- Create: `agents/vps.py`
- Create: `tests/test_vps.py`

- [ ] **Step 3.1: Test schreiben**

```python
# tests/test_vps.py
import asyncio
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from agents.vps import run_as_claude, read_file, list_projects, git_log

def test_list_projects_parses_output():
    with patch("agents.vps.run_as_claude", new_callable=AsyncMock) as mock:
        mock.return_value = (0, "recipe-app\nimmo-radar\nrefurbish-business\n", "")
        result = asyncio.run(list_projects())
    assert result == ["immo-radar", "recipe-app", "refurbish-business"]

def test_list_projects_filters_hidden():
    with patch("agents.vps.run_as_claude", new_callable=AsyncMock) as mock:
        mock.return_value = (0, "recipe-app\n.cache\nimmo-radar\n", "")
        result = asyncio.run(list_projects())
    assert ".cache" not in result

def test_read_file_returns_content():
    with patch("agents.vps.run_as_claude", new_callable=AsyncMock) as mock:
        mock.return_value = (0, "# Backlog\n- item 1\n", "")
        result = asyncio.run(read_file("recipe-app", "BACKLOG.md"))
    assert "item 1" in result

def test_read_file_not_found():
    with patch("agents.vps.run_as_claude", new_callable=AsyncMock) as mock:
        mock.return_value = (1, "", "No such file")
        result = asyncio.run(read_file("recipe-app", "NONEXISTENT.md"))
    assert result is None
```

- [ ] **Step 3.2: Test laufen lassen — muss fehlschlagen**

```bash
python -m pytest ../tests/test_vps.py -v
```

Erwartet: `ModuleNotFoundError: No module named 'agents.vps'`

- [ ] **Step 3.3: vps.py implementieren**

```python
# agents/vps.py
import asyncio
import os
import logging

logger = logging.getLogger("jarvis.vps")

WORKSPACE = "/home/claude/workspace"
CLAUDE_USER = "claude"


async def run_as_claude(cmd: list[str], cwd: str | None = None) -> tuple[int, str, str]:
    """Run a command as claude-user via sudo. Returns (returncode, stdout, stderr)."""
    full_cmd = ["sudo", "-u", CLAUDE_USER, "--"] + cmd
    try:
        proc = await asyncio.create_subprocess_exec(
            *full_cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
        return proc.returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace")
    except asyncio.TimeoutError:
        logger.error(f"Timeout running {cmd}")
        return -1, "", "timeout"
    except Exception as e:
        logger.error(f"Error running {cmd}: {e}")
        return -1, "", str(e)


async def list_projects() -> list[str]:
    """List available projects in the workspace."""
    rc, stdout, _ = await run_as_claude(["ls", WORKSPACE])
    if rc != 0:
        return []
    return sorted([p.strip() for p in stdout.splitlines() if p.strip() and not p.startswith(".")])


async def read_file(project: str, filename: str) -> str | None:
    """Read a file from a project workspace. Returns None if not found."""
    path = f"{WORKSPACE}/{project}/{filename}"
    rc, stdout, _ = await run_as_claude(["cat", path])
    return stdout if rc == 0 else None


async def git_log(project: str, n: int = 10) -> str:
    """Get last n git commits for a project."""
    cwd = f"{WORKSPACE}/{project}"
    rc, stdout, _ = await run_as_claude(
        ["git", "log", f"--oneline", f"-{n}"], cwd=cwd
    )
    return stdout if rc == 0 else "git log failed"


async def git_pull(project: str) -> bool:
    """Pull latest changes. Returns True on success."""
    cwd = f"{WORKSPACE}/{project}"
    rc, _, _ = await run_as_claude(["git", "pull", "--quiet"], cwd=cwd)
    return rc == 0


async def write_file_and_commit(project: str, filename: str, content: str, commit_msg: str) -> bool:
    """Write a file and commit it. Used for backlog edits."""
    path = f"{WORKSPACE}/{project}/{filename}"
    cwd = f"{WORKSPACE}/{project}"

    # Write file as root (root can write to claude-user workspace)
    try:
        with open(path, "w") as f:
            f.write(content)
        # Fix ownership
        os.chown(path, pwd_uid(CLAUDE_USER), pwd_gid(CLAUDE_USER))
    except Exception as e:
        logger.error(f"write_file failed: {e}")
        return False

    # Commit as claude-user
    rc, _, stderr = await run_as_claude(
        ["git", "add", filename], cwd=cwd
    )
    if rc != 0:
        return False
    rc, _, stderr = await run_as_claude(
        ["git", "commit", "-m", commit_msg], cwd=cwd
    )
    return rc == 0


def pwd_uid(username: str) -> int:
    import pwd
    return pwd.getpwnam(username).pw_uid

def pwd_gid(username: str) -> int:
    import pwd
    return pwd.getpwnam(username).pw_gid
```

- [ ] **Step 3.4: Tests laufen lassen — müssen grün sein**

```bash
python -m pytest ../tests/test_vps.py -v
```

Erwartet: 4 passed

- [ ] **Step 3.5: Commit**

```bash
git add agents/vps.py tests/test_vps.py
git commit -m "feat(vps): subprocess helper für claude-user Kommandos"
```

---

## Task 4: Coding Agent — Query Mode

**Files:**
- Create: `agents/coding_agent.py` (Neubau, alte Datei ersetzen)
- Create: `tests/test_coding_agent.py`

- [ ] **Step 4.1: Test für Query-Mode schreiben**

```python
# tests/test_coding_agent.py
import asyncio
import pytest
from unittest.mock import patch, AsyncMock
from agents.coding_agent import handle_coding_query

@pytest.mark.asyncio
async def test_query_backlog():
    with patch("agents.coding_agent.read_file", new_callable=AsyncMock) as mock_read, \
         patch("agents.coding_agent.git_pull", new_callable=AsyncMock) as mock_pull:
        mock_pull.return_value = True
        mock_read.return_value = "# Backlog\n- [ ] Fix login\n- [ ] Add tests\n"
        result = await handle_coding_query("recipe-app", "backlog")
    assert "Fix login" in result
    assert "Add tests" in result

@pytest.mark.asyncio
async def test_query_git_log():
    with patch("agents.coding_agent.git_log", new_callable=AsyncMock) as mock_log, \
         patch("agents.coding_agent.git_pull", new_callable=AsyncMock) as mock_pull:
        mock_pull.return_value = True
        mock_log.return_value = "abc1234 Fix auth\ndef5678 Add tests\n"
        result = await handle_coding_query("recipe-app", "git_log")
    assert "abc1234" in result

@pytest.mark.asyncio
async def test_query_unknown_project():
    with patch("agents.coding_agent.list_projects", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = ["recipe-app", "immo-radar"]
        result = await handle_coding_query("nonexistent-project", "backlog")
    assert "nicht gefunden" in result.lower() or "verfügbare" in result.lower()
```

- [ ] **Step 4.2: Tests laufen lassen — müssen fehlschlagen**

```bash
python -m pytest ../tests/test_coding_agent.py::test_query_backlog -v
```

Erwartet: `ImportError` oder `AttributeError`

- [ ] **Step 4.3: coding_agent.py mit Query-Mode implementieren**

```python
# agents/coding_agent.py
import asyncio
import json
import logging
import os
import re
from telegram import Bot

from db import SessionDB
from vps import (
    WORKSPACE,
    git_log,
    git_pull,
    list_projects,
    read_file,
    run_as_claude,
    write_file_and_commit,
)

logger = logging.getLogger("jarvis.coding")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
_db = SessionDB()
_initialized = False


async def _ensure_init():
    global _initialized
    if not _initialized:
        await _db.init()
        _initialized = True


async def handle_coding_query(project: str, query_type: str) -> str:
    """Fast path: read files/git directly, no Claude Code."""
    await _ensure_init()

    projects = await list_projects()
    if project not in projects:
        return f"Projekt '{project}' nicht gefunden.\nVerfügbare Projekte: {', '.join(projects)}"

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
```

- [ ] **Step 4.4: pytest-asyncio installieren und Tests laufen lassen**

```bash
pip install pytest-asyncio
python -m pytest ../tests/test_coding_agent.py -v
```

Erwartet: 3 passed

- [ ] **Step 4.5: Commit**

```bash
git add agents/coding_agent.py tests/test_coding_agent.py
git commit -m "feat(coding): query mode — backlog/git-log direkt ohne Claude Code"
```

---

## Task 5: Coding Agent — Action Mode (Claude Code via sudo)

**Files:**
- Modify: `agents/coding_agent.py` — Action-Modus + Session-Handling hinzufügen

- [ ] **Step 5.1: Test für Action-Mode schreiben**

```python
# Zum bestehenden tests/test_coding_agent.py hinzufügen:

@pytest.mark.asyncio
async def test_action_parses_session_id():
    """Claude Code stream-json output enthält session_id im result-Event."""
    fake_output = (
        '{"type":"system","subtype":"init","session_id":"sess_abc123"}\n'
        '{"type":"assistant","message":{"content":[{"type":"text","text":"Done."}]}}\n'
        '{"type":"result","subtype":"success","session_id":"sess_abc123","result":"Fixed."}\n'
    )
    with patch("agents.coding_agent.run_as_claude", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = (0, fake_output, "")
        with patch("agents.coding_agent._db") as mock_db:
            mock_db.upsert_session = AsyncMock()
            session_id, output = await _run_claude_action(
                project="recipe-app",
                task="Fix the login bug",
                existing_session=None,
            )
    assert session_id == "sess_abc123"
    assert "Fixed." in output or "Done." in output

@pytest.mark.asyncio
async def test_action_uses_resume_when_session_exists():
    with patch("agents.coding_agent.run_as_claude", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = (0, '{"type":"result","session_id":"sess_xyz","result":"ok"}\n', "")
        with patch("agents.coding_agent._db") as mock_db:
            mock_db.upsert_session = AsyncMock()
            await _run_claude_action(
                project="recipe-app",
                task="Also add tests",
                existing_session="sess_existing",
            )
    call_args = mock_run.call_args[0][0]  # cmd list
    assert "--resume" in call_args
    assert "sess_existing" in call_args
```

- [ ] **Step 5.2: Tests laufen lassen — müssen fehlschlagen**

```bash
python -m pytest ../tests/test_coding_agent.py::test_action_parses_session_id -v
```

Erwartet: `ImportError` für `_run_claude_action`

- [ ] **Step 5.3: Action-Mode zu coding_agent.py hinzufügen**

```python
# agents/coding_agent.py — folgende Funktionen ergänzen:

def _parse_stream_json(raw: str) -> tuple[str | None, str]:
    """Parse stream-json output. Returns (session_id, human_readable_output)."""
    session_id = None
    messages = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        etype = event.get("type")

        # Session ID aus init oder result Event
        if "session_id" in event:
            session_id = event["session_id"]

        # Assistenten-Nachrichten sammeln
        if etype == "assistant":
            for block in event.get("message", {}).get("content", []):
                if block.get("type") == "text":
                    messages.append(block["text"])

        # Ergebnis
        if etype == "result" and event.get("result"):
            messages.append(event["result"])

    output = "\n".join(messages).strip() or "(Keine Ausgabe)"
    return session_id, output


async def _run_claude_action(
    project: str, task: str, existing_session: str | None
) -> tuple[str | None, str]:
    """Run Claude Code action. Returns (session_id, output)."""
    cwd = f"{WORKSPACE}/{project}"

    cmd = [
        "claude",
        "--dangerously-skip-permissions",
        "--output-format", "stream-json",
        "--print",
    ]
    if existing_session:
        cmd += ["--resume", existing_session]
    cmd += ["-p", task]

    rc, stdout, stderr = await run_as_claude(cmd, cwd=cwd)

    if rc != 0 and not stdout:
        return None, f"Claude Code Fehler (exit {rc}): {stderr[:500]}"

    session_id, output = _parse_stream_json(stdout)
    if session_id:
        await _db.upsert_session(project, session_id)

    return session_id, output


async def run_coding_action(task: str, project: str, chat_id: int):
    """Full action flow with Telegram progress updates."""
    await _ensure_init()
    bot = Bot(token=TELEGRAM_TOKEN)

    projects = await list_projects()
    if project not in projects:
        await bot.send_message(
            chat_id=chat_id,
            text=f"❌ Projekt '{project}' nicht gefunden.\n\nVerfügbar: {', '.join(projects)}",
        )
        return

    await git_pull(project)

    existing_session = await _db.get_session(project, ttl_hours=2)
    resume_text = " (Fortsetzung der Session)" if existing_session else ""

    status_msg = await bot.send_message(
        chat_id=chat_id,
        text=f"🚀 Starte Claude Code in *{project}*{resume_text}\n\n_{task}_",
        parse_mode="Markdown",
    )

    session_id, output = await _run_claude_action(project, task, existing_session)

    # Output ggf. kürzen (Telegram max 4096 Zeichen)
    if len(output) > 3800:
        output = output[:3800] + "\n\n[… gekürzt]"

    await bot.edit_message_text(
        chat_id=chat_id,
        message_id=status_msg.message_id,
        text=f"✅ *{project}* — fertig\n\n{output}",
        parse_mode="Markdown",
    )
```

- [ ] **Step 5.4: Tests laufen lassen — müssen grün sein**

```bash
python -m pytest ../tests/test_coding_agent.py -v
```

Erwartet: alle passed

- [ ] **Step 5.5: Commit**

```bash
git add agents/coding_agent.py tests/test_coding_agent.py
git commit -m "feat(coding): action mode — Claude Code via sudo, session persistence"
```

---

## Task 6: Coding Agent — Backlog Write Mode

**Files:**
- Modify: `agents/coding_agent.py` — Backlog-Write hinzufügen

- [ ] **Step 6.1: Test schreiben**

```python
# tests/test_coding_agent.py — ergänzen:

@pytest.mark.asyncio
async def test_backlog_add_item():
    existing = "# Backlog\n\n## P1\n- [ ] Fix login\n"
    with patch("agents.coding_agent.read_file", new_callable=AsyncMock) as mock_read, \
         patch("agents.coding_agent.write_file_and_commit", new_callable=AsyncMock) as mock_write, \
         patch("agents.coding_agent.git_pull", new_callable=AsyncMock):
        mock_read.return_value = existing
        mock_write.return_value = True
        result = await add_backlog_item("recipe-app", "Add dark mode", priority="P1")
    assert result is True
    written_content = mock_write.call_args[0][2]  # content argument
    assert "Add dark mode" in written_content
    assert "Fix login" in written_content  # existing items preserved
```

- [ ] **Step 6.2: Test laufen lassen — muss fehlschlagen**

```bash
python -m pytest ../tests/test_coding_agent.py::test_backlog_add_item -v
```

Erwartet: `ImportError` für `add_backlog_item`

- [ ] **Step 6.3: Backlog-Write zu coding_agent.py hinzufügen**

```python
# agents/coding_agent.py — ergänzen:

async def add_backlog_item(project: str, item: str, priority: str = "P1") -> bool:
    """Add a new item to BACKLOG.md under the given priority section."""
    content = await read_file(project, "BACKLOG.md")
    if content is None:
        content = f"# Backlog\n\n## {priority}\n"

    new_line = f"- [ ] {item}"

    # Unter die richtige P-Sektion einfügen
    section_header = f"## {priority}"
    if section_header in content:
        # Nach dem Header und einem optionalen Leerzeichen einfügen
        insert_pos = content.index(section_header) + len(section_header)
        # Bis zum Ende der Zeile springen
        newline_pos = content.index("\n", insert_pos)
        content = content[:newline_pos + 1] + new_line + "\n" + content[newline_pos + 1:]
    else:
        content += f"\n## {priority}\n{new_line}\n"

    return await write_file_and_commit(
        project=project,
        filename="BACKLOG.md",
        content=content,
        commit_msg=f"backlog: {item[:60]}",
    )
```

- [ ] **Step 6.4: Tests laufen lassen**

```bash
python -m pytest ../tests/test_coding_agent.py -v
```

Erwartet: alle passed

- [ ] **Step 6.5: Commit**

```bash
git add agents/coding_agent.py tests/test_coding_agent.py
git commit -m "feat(coding): backlog write — items hinzufügen via Telegram"
```

---

## Task 7: Router Update — neue Intent-Parameter

**Files:**
- Modify: `agents/router.py`

- [ ] **Step 7.1: router.py erweitern**

In `_SYSTEM_TEMPLATE` den bestehenden `coding`-Intent-Block ersetzen:

```python
# agents/router.py — _SYSTEM_TEMPLATE coding-Block ersetzen:

"""2. "coding" — Aufgaben oder Fragen zu Code-Projekten.
   Verfügbare Projekte: {PROJECT_LIST}

   Beispiele:
   - "Backlog von recipe-app?" → query, backlog
   - "Was hat sich zuletzt in immo-radar geändert?" → query, git_log
   - "Fixe den Login-Bug in recipe-app" → action
   - "Füge 'Dark Mode' zum Backlog von recipe-app hinzu" → backlog_write
   - "Schreibe Feature X in immo-radar" → action

   Parameter:
   - project: string (Projektname, einer aus: {PROJECT_LIST}) oder null
   - mode: "query" | "action" | "backlog_write"
   - query_type: "backlog" | "git_log" | "readme" | "claude_md" (nur bei mode=query)
   - backlog_item: string (der neue Eintrag, nur bei mode=backlog_write)
   - backlog_priority: "P1" | "P2" | "P3" (default: "P1", nur bei mode=backlog_write)
"""
```

Und `_build_system_prompt` anpassen:

```python
# agents/router.py

import asyncio
from vps import list_projects as _list_projects

_project_list_cache: list[str] = []

async def _get_project_list() -> list[str]:
    global _project_list_cache
    if not _project_list_cache:
        _project_list_cache = await _list_projects()
    return _project_list_cache

def _build_system_prompt(project_list: list[str]) -> str:
    heute = datetime.now(BERLIN).strftime("%Y-%m-%d")
    projects_str = ", ".join(project_list) if project_list else "recipe-app"
    return (
        _SYSTEM_TEMPLATE
        .replace("{HEUTE_ISO}", heute)
        .replace("{PROJECT_LIST}", projects_str)
    )

async def route_with_llm(text: str) -> dict:
    project_list = await _get_project_list()
    system = _build_system_prompt(project_list)
    # ... Rest unverändert
```

- [ ] **Step 7.2: Validierung im route_with_llm anpassen**

```python
# agents/router.py — intent-Validierung erweitern:
VALID_INTENTS = {"calendar", "coding", "research", "work", "mail", "personal", "news", "tasks"}

if parsed["intent"] not in VALID_INTENTS:
    raise ValueError(f"invalid intent: {parsed['intent']}")
```

- [ ] **Step 7.3: Commit**

```bash
git add agents/router.py
git commit -m "feat(router): coding mode/query_type params + news/tasks intents + dynamic project list"
```

---

## Task 8: main.py — Coding Handler ersetzen

**Files:**
- Modify: `agents/main.py`

- [ ] **Step 8.1: Import-Sektion in main.py aktualisieren**

```python
# agents/main.py — bestehende Imports anpassen:
# ALT: from coding_agent import run_coding_task
# NEU:
from coding_agent import (
    handle_coding_query,
    run_coding_action,
    add_backlog_item,
)
from vps import list_projects
```

- [ ] **Step 8.2: Coding-Handler in handle_message ersetzen**

Den bestehenden Block für `intent == "coding"` in `handle_message` vollständig ersetzen:

```python
# agents/main.py — coding-Handler Block:

elif intent == "coding":
    mode = params.get("mode", "action")
    project = params.get("project")

    # Projekt-Fallback: erstes verfügbares
    if not project:
        projects = await list_projects()
        project = projects[0] if projects else "recipe-app"

    if mode == "query":
        query_type = params.get("query_type", "backlog")
        await update.message.reply_text("🔍 Lese...")
        result = await handle_coding_query(project, query_type)
        await update.message.reply_text(
            f"📁 *{project}* — {query_type}\n\n{result[:4000]}",
            parse_mode="Markdown",
        )

    elif mode == "backlog_write":
        item = params.get("backlog_item", text)
        priority = params.get("backlog_priority", "P1")
        success = await add_backlog_item(project, item, priority)
        if success:
            await update.message.reply_text(
                f"✅ Backlog-Item hinzugefügt in *{project}*:\n_{item}_",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(f"❌ Konnte Backlog nicht aktualisieren.")

    else:  # action
        asyncio.create_task(run_coding_action(text, project, chat_id))
        # run_coding_action schickt selbst Telegram-Updates
```

- [ ] **Step 8.3: Startup: DB und Project-Cache initialisieren**

```python
# agents/main.py — startup-Funktion ergänzen:
@app.on_event("startup")
async def startup():
    # DB initialisieren
    from coding_agent import _db, _ensure_init
    await _ensure_init()
    # Project-Cache wärmen
    from vps import list_projects as lp
    projects = await lp()
    logger.info(f"Workspace projects: {projects}")
    # ... Rest unverändert
```

- [ ] **Step 8.4: Alten `detect_coding_mode` und `extract_project` entfernen**

Die Funktionen `detect_coding_mode(text)` und `extract_project(text)` in `main.py` löschen — Logik ist jetzt im Router.

- [ ] **Step 8.5: Commit**

```bash
git add agents/main.py
git commit -m "feat(main): replace coding handler — query/action/backlog_write via new coding_agent"
```

---

## Task 9: Deploy auf VPS und Integration Test

**Ziel:** Neuen Code deployen, manuell testen.

- [ ] **Step 9.1: Code auf VPS deployen**

```bash
# Auf VPS (root@100.115.184.3):
cd /root/herrlich-ai-platform
git pull
pip install -r agents/requirements.txt
systemctl restart jarvis
systemctl status jarvis  # muss "active (running)" zeigen
```

- [ ] **Step 9.2: Logs prüfen**

```bash
journalctl -u jarvis -f --no-pager | head -20
```

Erwartet: `Workspace projects: ['herrlich-ai-platform', 'herrlich-dev', 'immo-radar', 'recipe-app', 'refurbish-business']`

- [ ] **Step 9.3: Telegram — Query-Test**

Sende an @jarvis_herrlich_bot: `"Backlog recipe-app"`

Erwartet: Inhalt von `recipe-app/BACKLOG.md` als Antwort in ~1 Sekunde.

- [ ] **Step 9.4: Telegram — Backlog-Write-Test**

Sende: `"Füge 'Test-Item vom Plan' zum Backlog von recipe-app hinzu"`

Erwartet: `✅ Backlog-Item hinzugefügt in recipe-app: Test-Item vom Plan`

Verifizieren:
```bash
grep "Test-Item" /home/claude/workspace/recipe-app/BACKLOG.md
```

- [ ] **Step 9.5: Telegram — Action-Test**

Sende: `"Was macht die Datei BACKLOG.md in recipe-app?"` (als question/query)

Erwartet: Claude Code Antwort nach 30–60 Sekunden.

- [ ] **Step 9.6: sudo-Berechtigung prüfen (falls Step 9.3–9.5 mit Permission-Fehler scheitern)**

```bash
# Auf VPS — falls sudo -u claude ohne Passwort nicht funktioniert:
echo "root ALL=(claude) NOPASSWD: ALL" >> /etc/sudoers.d/jarvis-claude
chmod 440 /etc/sudoers.d/jarvis-claude
# Dann Step 9.3 wiederholen
```

- [ ] **Step 9.7: Abschluss-Commit**

```bash
git add .
git commit -m "fix(deploy): post-deploy adjustments after VPS integration test"
```

---

## Bekannte Risiken & Mitigations

| Risiko | Mitigation |
|---|---|
| `sudo -u claude` ohne NOPASSWD blockiert | Step 9.6: sudoers-Eintrag anlegen |
| GitHub PAT fehlt | `setup-workspace.sh` bricht mit klarer Fehlermeldung ab |
| stream-json Format weicht ab | `_parse_stream_json` loggt alle unbekannten Event-Typen, gibt "(Keine Ausgabe)" statt zu crashen |
| Session-ID nicht im Output | Neue Session wird gestartet, kein Crash |
| VPS-Workspace Schreibrechte | `write_file_and_commit` korrigiert Ownership via `chown` |
