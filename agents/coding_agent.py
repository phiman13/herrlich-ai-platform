# agents/coding_agent.py
import asyncio
import json
import logging
import os

try:
    from agents.db import SessionDB
    from agents.vps import (
        WORKSPACE,
        git_log,
        git_pull,
        git_push,
        list_projects,
        read_file,
        run_as_claude,
        write_file_and_commit,
    )
except ImportError:
    from db import SessionDB
    from vps import (
        WORKSPACE,
        git_log,
        git_pull,
        git_push,
        list_projects,
        read_file,
        run_as_claude,
        write_file_and_commit,
    )
from telegram import Bot

logger = logging.getLogger("jarvis.coding")

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
_db: SessionDB | None = None
_initialized = False
_init_lock = asyncio.Lock()


async def _ensure_init():
    global _initialized, _db
    async with _init_lock:
        if not _initialized:
            _db = SessionDB()
            await _db.init()
            _initialized = True


async def _check_and_clone(project: str) -> str:
    """Check GitHub and clone if not archived. Returns: 'cloned'|'archived'|'not_found'|'error'"""
    import json as _json
    github_token = os.environ.get("GITHUB_TOKEN", "")
    if not github_token:
        return "error"

    github_user = "phiman13"
    proc = await asyncio.create_subprocess_exec(
        "curl", "-sf", "-H", f"Authorization: token {github_token}",
        f"https://api.github.com/repos/{github_user}/{project}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        data = _json.loads(stdout.decode())
    except Exception:
        return "error"

    if data.get("message") == "Not Found":
        return "not_found"
    if data.get("archived", False):
        return "archived"

    clone_url = f"https://{github_user}:{github_token}@github.com/{github_user}/{project}.git"
    target = f"{WORKSPACE}/{project}"
    rc, _, _ = await run_as_claude(["git", "clone", clone_url, target])
    return "cloned" if rc == 0 else "error"


async def handle_coding_query(project: str, query_type: str) -> str:
    """Fast path: read files/git directly, no Claude Code needed."""
    await _ensure_init()
    projects = await list_projects()
    if project not in projects:
        status = await _check_and_clone(project)
        if status == "cloned":
            pass  # proceed with task
        elif status == "archived":
            return f"Projekt '{project}' ist archiviert und kann nicht geklont werden."
        elif status == "not_found":
            return f"Projekt '{project}' nicht gefunden auf GitHub.\nVerfügbare Projekte: {', '.join(projects)}"
        else:
            return f"Projekt '{project}' nicht im Workspace und Auto-Clone fehlgeschlagen.\nVerfügbare Projekte: {', '.join(projects)}"

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

        if "session_id" in event:
            session_id = event["session_id"]

        if etype == "assistant":
            for block in event.get("message", {}).get("content", []):
                if block.get("type") == "text":
                    messages.append(block["text"])

        if etype == "result" and event.get("result"):
            messages.append(event["result"])

    output = "\n".join(messages).strip() or "(Keine Ausgabe)"
    return session_id, output


async def _run_claude_action(
    project: str, task: str, existing_session: str | None
) -> tuple[str | None, str]:
    """Run Claude Code action. Returns (session_id, output)."""
    if not project or "/" in project or ".." in project:
        return None, f"Ungültiger Projektname: {project!r}"
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


async def add_backlog_item(project: str, item: str, priority: str = "P1") -> bool:
    """Add a new item to BACKLOG.md under the given priority section."""
    await _ensure_init()
    projects = await list_projects()
    if project not in projects:
        status = await _check_and_clone(project)
        if status != "cloned":
            return False
    content = await read_file(project, "BACKLOG.md")
    if content is None:
        content = f"# Backlog\n\n## {priority}\n"

    new_line = f"- [ ] {item}"

    section_header = f"## {priority}"
    if section_header in content:
        insert_pos = content.index(section_header) + len(section_header)
        newline_pos = content.index("\n", insert_pos)
        content = content[:newline_pos + 1] + new_line + "\n" + content[newline_pos + 1:]
    else:
        content += f"\n## {priority}\n{new_line}\n"

    success = await write_file_and_commit(
        project,
        "BACKLOG.md",
        content,
        f"backlog: {item[:60]}",
    )
    if success:
        await git_push(project)
    return success


async def run_coding_action(task: str, project: str, chat_id: int):
    """Full action flow with Telegram progress updates."""
    await _ensure_init()
    bot = Bot(token=TELEGRAM_TOKEN)

    projects = await list_projects()
    if project not in projects:
        status = await _check_and_clone(project)
        if status == "cloned":
            pass  # proceed with task
        elif status == "archived":
            await bot.send_message(
                chat_id=chat_id,
                text=f"❌ Projekt '{project}' ist archiviert und kann nicht geklont werden.",
            )
            return
        elif status == "not_found":
            await bot.send_message(
                chat_id=chat_id,
                text=f"❌ Projekt '{project}' nicht gefunden auf GitHub.\n\nVerfügbar: {', '.join(projects)}",
            )
            return
        else:
            await bot.send_message(
                chat_id=chat_id,
                text=f"❌ Projekt '{project}' nicht im Workspace und Auto-Clone fehlgeschlagen.\n\nVerfügbar: {', '.join(projects)}",
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

    if len(output) > 3800:
        output = output[:3800] + "\n\n[… gekürzt]"

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    keyboard = [[
        InlineKeyboardButton("📤 Pushen", callback_data=f"push:{project}"),
        InlineKeyboardButton("✓ OK", callback_data="dismiss"),
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await bot.edit_message_text(
        chat_id=chat_id,
        message_id=status_msg.message_id,
        text=f"✅ *{project}* — fertig\n\n{output}",
        parse_mode="Markdown",
        reply_markup=reply_markup,
    )
