import asyncio
import os
import subprocess
from telegram import Bot

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

async def run_coding_task(task: str, project: str, chat_id: int):
    bot = Bot(token=TELEGRAM_TOKEN)
    
    # Projekt-Pfad prüfen
    workspace = f"/root/workspace/{project}"
    if not os.path.exists(workspace):
        await bot.send_message(
            chat_id=chat_id,
            text=f"❌ Projekt '{project}' nicht gefunden in ~/workspace/\n"
                 f"Verfügbare Projekte: {os.listdir('/root/workspace/')}"
        )
        return

    await bot.send_message(
        chat_id=chat_id,
        text=f"🚀 Starte Claude Code in *{project}*\n\nAufgabe: {task}",
        parse_mode="Markdown"
    )

    # Claude Code in Docker starten
    cmd = [
        "docker", "run", "--rm",
        "--network", "host",
        "-v", f"{workspace}:/workspace",
        "-v", "/root/.claude:/root/.claude",
        "-e", f"ANTHROPIC_API_KEY={os.environ.get('ANTHROPIC_API_KEY', '')}",
        "-e", "CLAUDE_CODE_USE_BEDROCK=0",
        "claude-sandbox",
        "claude", "--dangerously-skip-permissions",
        "-p", task,
        "--output-format", "stream-json",
        "--verbose"
    ]

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        iteration = 0
        async for line in process.stdout:
            iteration += 1
            # Alle 5 Iterationen Update schicken
            if iteration % 5 == 0:
                await bot.send_message(
                    chat_id=chat_id,
                    text=f"⚙️ Iteration {iteration} – Claude Code arbeitet..."
                )

        await process.wait()

        await bot.send_message(
            chat_id=chat_id,
            text=f"✅ Aufgabe abgeschlossen in *{project}*\n\n"
                 f"Führe `git diff` aus um die Änderungen zu sehen.",
            parse_mode="Markdown"
        )

    except Exception as e:
        await bot.send_message(
            chat_id=chat_id,
            text=f"❌ Fehler: {str(e)}"
        )

