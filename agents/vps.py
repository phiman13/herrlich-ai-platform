import asyncio
import logging
import os
import tempfile
from pathlib import Path

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
    rc, stdout, _ = await run_as_claude(["git", "log", "--oneline", f"-{n}"], cwd=cwd)
    return stdout if rc == 0 else "git log failed"


async def git_pull(project: str) -> bool:
    """Pull latest changes. Returns True on success."""
    cwd = _safe_cwd(project)
    if not cwd:
        return False
    rc, _, _ = await run_as_claude(["git", "pull", "--quiet"], cwd=cwd)
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

    rc, _, _ = await run_as_claude(["git", "add", filename], cwd=cwd)
    if rc != 0:
        return False
    rc, _, _ = await run_as_claude(["git", "commit", "-m", commit_msg], cwd=cwd)
    return rc == 0


async def git_push(project: str) -> bool:
    """Push committed changes to origin. Returns True on success."""
    cwd = _safe_cwd(project)
    if not cwd:
        return False
    rc, _, _ = await run_as_claude(["git", "push"], cwd=cwd)
    return rc == 0
