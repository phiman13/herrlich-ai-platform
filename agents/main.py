import os
import json
import logging
import asyncio
import subprocess
from fastapi import FastAPI, Request
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import anthropic

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
claude = anthropic.Anthropic()

app = FastAPI()
bot_app = Application.builder().token(TELEGRAM_TOKEN).build()

WORKSPACE = "/home/claude/workspace"

# Deduplizierung – verhindert doppelte Verarbeitung
processed_updates = set()

def detect_intent(text):
    t = text.lower()
    if any(k in t for k in ["code", "projekt", "github", "bug", "fix", "deploy", "test", "recipe", "backlog", "todo", "erstelle", "fixe", "changelog", "roadmap"]):
        return "coding"
    if any(k in t for k in ["meeting", "protokoll", "zusammenfassung", "kunde", "praesentation", "research", "fass", "analysiere"]):
        return "work"
    return "personal"

def detect_coding_mode(text):
    t = text.lower()
    if any(k in t for k in ["fixe", "baue", "erstelle", "implementiere", "refactor", "schreibe", "loesche", "aendere", "update", "add", "remove", "lösche", "delete", "entferne", "pull", "push", "git", "füge", "trage ein", "ergänze", "aktualisiere", "changelog", "roadmap"]):
        return "action"
    return "question"

def extract_project(text):
    if not os.path.exists(WORKSPACE):
        return "recipe-app"
    projects = os.listdir(WORKSPACE)
    for p in projects:
        if p.lower() in text.lower():
            return p
    return projects[0] if projects else "recipe-app"

def read_project_files(project):
    workspace = f"{WORKSPACE}/{project}"
    context = ""
    for filename in ["BACKLOG.md", "CLAUDE.md", "README.md", "TODO.md"]:
        filepath = os.path.join(workspace, filename)
        if os.path.exists(filepath):
            with open(filepath, "r") as f:
                content = f.read()
            if len(content) > 3000:
                content = content[:3000] + "\n[gekuerzt]"
            context += f"\n\n### {filename}:\n{content}"
    return context

async def ask_claude(chat_id, system, user, model="claude-haiku-4-5-20251001"):
    bot = Bot(token=TELEGRAM_TOKEN)
    try:
        response = claude.messages.create(
            model=model,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": user}]
        )
        answer = response.content[0].text
        if len(answer) > 4000:
            answer = answer[:4000] + "\n[...]"
        await bot.send_message(chat_id=chat_id, text=answer)
    except Exception as e:
        await bot.send_message(chat_id=chat_id, text=f"Fehler: {str(e)}")

async def run_claude_code(chat_id, project, task):
    bot = Bot(token=TELEGRAM_TOKEN)
    workspace = f"{WORKSPACE}/{project}"

    if not os.path.exists(workspace):
        await bot.send_message(chat_id=chat_id, text=f"Projekt '{project}' nicht gefunden.")
        return

    await bot.send_message(chat_id=chat_id, text=f"Claude Code startet in {project}...\nAufgabe: {task}")

    try:
        process = await asyncio.create_subprocess_exec(
            "sudo", "-u", "claude",
            "bash", "-c",
            f"cd {workspace} && PATH=/home/claude/.npm-global/bin:$PATH claude --dangerously-skip-permissions -p '{task}' --verbose --output-format stream-json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=300)
        output = stdout.decode("utf-8", errors="replace").strip()

        result_text = ""
        for line in output.split("\n"):
            try:
                data = json.loads(line)
                if data.get("type") == "result":
                    result_text = data.get("result", "")
            except:
                pass

        if process.returncode == 0:
            msg = f"Aufgabe abgeschlossen in {project}."
            if result_text:
                if len(result_text) > 3000:
                    result_text = result_text[:3000] + "\n[...]"
                msg += f"\n\n{result_text}"
            await bot.send_message(chat_id=chat_id, text=msg)

            diff = subprocess.run(
                ["sudo", "-u", "claude", "git", "diff", "--stat"],
                cwd=workspace, capture_output=True, text=True
            )
            if diff.stdout.strip() and len(diff.stdout) < 3000:
                await bot.send_message(
                    chat_id=chat_id,
                    text=f"Geaenderte Dateien:\n{diff.stdout.strip()}\n\nSag 'push {project}' zum Pushen."
                )
        else:
            error = stderr.decode("utf-8", errors="replace").strip()
            await bot.send_message(chat_id=chat_id, text=f"Fehler:\n{error[:1000] if error else 'Unbekannter Fehler'}")

    except asyncio.TimeoutError:
        process.kill()
        await bot.send_message(chat_id=chat_id, text="Timeout nach 5 Minuten.")
    except Exception as e:
        await bot.send_message(chat_id=chat_id, text=f"Fehler: {str(e)}")

async def git_push(chat_id, project):
    bot = Bot(token=TELEGRAM_TOKEN)
    workspace = f"{WORKSPACE}/{project}"
    try:
        subprocess.run(["sudo", "-u", "claude", "git", "add", "-A"], cwd=workspace)
        subprocess.run(["sudo", "-u", "claude", "git", "commit", "-m", "feat: Claude Code changes via Jarvis"], cwd=workspace)
        result = subprocess.run(["sudo", "-u", "claude", "git", "push"], cwd=workspace, capture_output=True, text=True)
        if result.returncode == 0:
            await bot.send_message(chat_id=chat_id, text=f"Gepusht zu GitHub.")
        else:
            await bot.send_message(chat_id=chat_id, text=f"Push fehlgeschlagen:\n{result.stderr}")
    except Exception as e:
        await bot.send_message(chat_id=chat_id, text=f"Fehler: {str(e)}")

async def start(update, context):
    await update.message.reply_text(
        "Hallo Philipp! Ich bin Jarvis.\n\n"
        "Coding (Frage): 'Was sind die Todos in recipe-app?'\n"
        "Coding (Aktion): 'Fixe den Login-Bug in recipe-app'\n"
        "Push: 'push recipe-app'\n"
        "Work: 'Fass mir diesen Text zusammen'\n"
        "Personal: 'Was sind gute Laufschuhe?'"
    )

async def handle_message(update, context):
    # Deduplizierung
    update_id = update.update_id
    if update_id in processed_updates:
        logger.info(f"Duplikat ignoriert: update_id={update_id}")
        return
    processed_updates.add(update_id)

    # Set nicht zu gross werden lassen
    if len(processed_updates) > 1000:
        processed_updates.clear()

    text = update.message.text
    chat_id = update.message.chat_id
    intent = detect_intent(text)
    logger.info(f"Intent: {intent} | update_id: {update_id} | Nachricht: {text}")

    if text.lower().startswith("push "):
        project = text[5:].strip()
        await update.message.reply_text(f"Pushe {project} zu GitHub...")
        await git_push(chat_id=chat_id, project=project)
        return

    if intent == "coding":
        project = extract_project(text)
        mode = detect_coding_mode(text)
        if mode == "action":
            asyncio.create_task(run_claude_code(chat_id=chat_id, project=project, task=text))
        else:
            await update.message.reply_text(f"Analysiere {project}...")
            project_context = read_project_files(project)
            await ask_claude(
                chat_id=chat_id,
                system="Du bist Jarvis, KI-Assistent fuer Philipp. Antworte auf Deutsch.",
                user=f"Projektdateien von '{project}':\n{project_context}\n\nFrage: {text}",
                model="claude-haiku-4-5-20251001"
            )

    elif intent == "work":
        await update.message.reply_text("Analysiere...")
        await ask_claude(
            chat_id=chat_id,
            system="Du bist Jarvis, KI-Assistent fuer Philipp (Projektmanager, Strategieberatung). Antworte praezise und strukturiert auf Deutsch.",
            user=text,
            model="claude-sonnet-4-6"
        )

    else:
        await update.message.reply_text("Denke nach...")
        await ask_claude(
            chat_id=chat_id,
            system="Du bist Jarvis, persoenlicher KI-Assistent fuer Philipp. Antworte hilfreich auf Deutsch.",
            user=text,
            model="claude-haiku-4-5-20251001"
        )

@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, bot_app.bot)
    await bot_app.process_update(update)
    return {"ok": True}

@app.get("/health")
async def health():
    return {"status": "ok", "service": "jarvis-gateway"}

@app.on_event("startup")
async def startup():
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    await bot_app.initialize()
    await bot_app.start()
    logger.info("Jarvis gestartet")

@app.on_event("shutdown")
async def shutdown():
    await bot_app.stop()
