import asyncio
import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger("jarvis.vps")

WORKSPACE = "/home/claude/workspace"
CLAUDE_USER = "claude"


async def run_as_claude(cmd: list[str], cwd: str | None = None) -> tuple[int, str, str]:
    """Run a command as claude-user via sudo. Returns (returncode, stdout, stderr).

    cwd wird per `sudo --chdir` gesetzt, nicht über den Subprozess: Python würde
    sonst noch als jarvis ins Verzeichnis wechseln — jarvis darf /home/claude
    (drwxr-x---) aber nicht betreten. `sudo --chdir` wechselt erst als claude.
    """
    full_cmd = ["sudo"]
    if cwd:
        full_cmd += ["--chdir", cwd]
    full_cmd += ["-u", CLAUDE_USER, "--"] + cmd
    try:
        proc = await asyncio.create_subprocess_exec(
            *full_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
        return (
            proc.returncode,
            stdout.decode(errors="replace"),
            stderr.decode(errors="replace"),
        )
    except asyncio.TimeoutError:
        logger.error(f"Timeout running {cmd}")
        return -1, "", "timeout"
    except Exception as e:
        logger.error(f"Error running {cmd}: {e}")
        return -1, "", str(e)


def _safe_path(project: str, filename: str) -> str | None:
    """Returns resolved path if safe, None if path traversal detected."""
    base = Path(WORKSPACE).resolve()
    target = (base / project / filename).resolve()
    if not str(target).startswith(str(base)):
        return None
    return str(target)


def _safe_cwd(project: str) -> str | None:
    """Validate project name and return safe cwd path."""
    base = Path(WORKSPACE).resolve()
    resolved = (base / project).resolve()
    if not str(resolved).startswith(str(base)):
        return None
    return str(resolved)


async def list_projects() -> list[str]:
    """List available projects in the workspace."""
    rc, stdout, _ = await run_as_claude(["ls", WORKSPACE])
    if rc != 0:
        return []
    return sorted(
        [p.strip() for p in stdout.splitlines() if p.strip() and not p.startswith(".")]
    )


async def read_file(project: str, filename: str) -> str | None:
    """Read a file from a project workspace. Returns None if not found."""
    path = _safe_path(project, filename)
    if path is None:
        logger.warning(f"Path traversal attempt: {project}/{filename}")
        return None
    rc, stdout, _ = await run_as_claude(["cat", path])
    return stdout if rc == 0 else None


async def git_log(project: str, n: int = 10) -> str:
    """Get last n git commits for a project."""
    cwd = _safe_cwd(project)
    if not cwd:
        return "Ungültiger Projektname."
    rc, stdout, _ = await run_as_claude(["git", "-C", cwd, "log", "--oneline", f"-{n}"])
    return stdout if rc == 0 else "git log failed"


async def git_pull(project: str, ff_only: bool = False) -> bool:
    """Pull latest changes. Returns True on success.

    ff_only=True: nur Fast-Forward — verwirft/merged nie etwas, schlägt bei
    Divergenz still fehl. Für den Hintergrund-Sync, der nichts kaputtmachen darf.
    """
    cwd = _safe_cwd(project)
    if not cwd:
        return False
    cmd = ["git", "-C", cwd, "pull", "--quiet"]
    if ff_only:
        cmd.append("--ff-only")
    rc, _, _ = await run_as_claude(cmd)
    return rc == 0


async def write_file_and_commit(
    project: str, filename: str, content: str, commit_msg: str
) -> bool:
    """Write a file and commit it. Used for backlog edits."""
    cwd = _safe_cwd(project)
    if not cwd:
        logger.warning(f"Path traversal attempt in project: {project!r}")
        return False
    path = _safe_path(project, filename)
    if path is None:
        logger.warning(f"Path traversal attempt: {project}/{filename}")
        return False

    # Jarvis runs unprivileged and cannot write into claude's workspace
    # directly (/home/claude is drwxr-x---). Stage the content in a temp file,
    # then copy it into place AS claude via sudo — keeps the file claude-owned.
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".jarvis", delete=False) as tf:
            tf.write(content)
            tmp_path = tf.name
        os.chmod(tmp_path, 0o644)  # claude (running cp) must be able to read it
    except Exception as e:
        logger.error(f"write_file failed: {e}")
        return False
    try:
        rc, _, err = await run_as_claude(["cp", tmp_path, path])
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    if rc != 0:
        logger.error(f"cp to workspace failed: {err}")
        return False

    rc, _, _ = await run_as_claude(["git", "-C", cwd, "add", filename])
    if rc != 0:
        return False
    rc, _, _ = await run_as_claude(["git", "-C", cwd, "commit", "-m", commit_msg])
    return rc == 0


async def git_push(project: str) -> bool:
    """Push committed changes to origin. Returns True on success."""
    cwd = _safe_cwd(project)
    if not cwd:
        return False
    rc, _, _ = await run_as_claude(["git", "-C", cwd, "push"])
    return rc == 0


async def git_commit_all(project: str, message: str) -> bool:
    """Staget + committet alle Änderungen. True wenn ein Commit entstand,
    False wenn nichts zu committen war oder bei Fehler."""
    cwd = _safe_cwd(project)
    if not cwd:
        return False
    rc, out, _ = await run_as_claude(["git", "-C", cwd, "status", "--porcelain"])
    if rc != 0 or not out.strip():
        return False  # nichts zu committen → kein Leer-Commit
    rc, _, _ = await run_as_claude(["git", "-C", cwd, "add", "-A"])
    if rc != 0:
        return False
    rc, _, _ = await run_as_claude(["git", "-C", cwd, "commit", "-m", message])
    return rc == 0
