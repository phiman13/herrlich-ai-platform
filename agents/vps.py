import asyncio
import logging
import os
import pwd

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
    rc, stdout, _ = await run_as_claude(["git", "log", "--oneline", f"-{n}"], cwd=cwd)
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

    try:
        with open(path, "w") as f:
            f.write(content)
        uid = pwd.getpwnam(CLAUDE_USER).pw_uid
        gid = pwd.getpwnam(CLAUDE_USER).pw_gid
        os.chown(path, uid, gid)
    except Exception as e:
        logger.error(f"write_file failed: {e}")
        return False

    rc, _, _ = await run_as_claude(["git", "add", filename], cwd=cwd)
    if rc != 0:
        return False
    rc, _, _ = await run_as_claude(["git", "commit", "-m", commit_msg], cwd=cwd)
    return rc == 0
