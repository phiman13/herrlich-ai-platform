import os
import re
import sys
import json
import logging
import asyncio
import subprocess
from datetime import datetime, timedelta
from fastapi import FastAPI, Request
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import anthropic

from calendar_agent import CalendarAgent, BERLIN
from router import route_with_llm

calendar_agent = CalendarAgent()

_WEEKDAYS_DE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("jarvis")

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
claude = anthropic.Anthropic()

app = FastAPI()
bot_app = Application.builder().token(TELEGRAM_TOKEN).build()

WORKSPACE = "/home/claude/workspace"
processed_updates = set()

def detect_coding_mode(text):
    t = text.lower()
    if any(k in t for k in ["fixe", "baue", "erstelle", "implementiere", "refactor", "schreibe", "loesche", "aendere", "update", "add", "remove", "changelog", "roadmap", "füge", "trage ein", "ergänze", "aktualisiere", "lösche", "delete", "entferne"]):
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
    if not os.path.exists(workspace):
        return ""

    try:
        result = subprocess.run(
            ["git", "-C", workspace, "pull", "--quiet"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            logger.info(f"Auto-pull OK: {project}")
        else:
            logger.warning(
                f"Auto-pull failed for {project}: {result.stderr.strip()}"
            )
    except subprocess.TimeoutExpired:
        logger.warning(f"Auto-pull timeout for {project}")
    except Exception as e:
        logger.warning(f"Auto-pull error for {project}: {e}")

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

def detect_calendar_window(text):
    """Return (kind, start, end) or None. kind is 'today'/'tomorrow'/'week'/'next'.

    Order matters:
      1. "nächster termin"  -> next
      2. "diese woche"      -> week (from now until Sunday 23:59:59)
      3. "heute"            -> today (word boundary, wins over "morgen")
      4. "morgen"           -> tomorrow (word boundary, avoids "Guten Morgen")
    """
    t = text.lower()
    now = datetime.now(BERLIN)

    if "nächster termin" in t or "naechster termin" in t or "wann ist mein nächster" in t or "wann ist mein naechster" in t:
        return ("next", None, None)
    if "diese woche" in t or "woche kalender" in t or "termine woche" in t:
        start = now
        days_until_sunday = 6 - now.weekday()  # 0=Mo, 6=So
        sunday = (now + timedelta(days=days_until_sunday)).replace(
            hour=23, minute=59, second=59, microsecond=999999
        )
        return ("week", start, sunday)
    if re.search(r'\bheute\b', t) and ("was habe ich" in t or "termine" in t or "kalender" in t):
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        return ("today", start, end)
    if re.search(r'\bmorgen\b', t) and ("was habe ich" in t or "termine" in t or "kalender" in t):
        start = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        return ("tomorrow", start, end)
    return None


def _fmt_time(dt):
    return dt.strftime("%H:%M")


def _fmt_date(dt):
    return f"{_WEEKDAYS_DE[dt.weekday()]} {dt.strftime('%d.%m.')}"


def _fmt_time_or_allday(ev):
    if getattr(ev, "all_day", False):
        return "ganztägig"
    return ev.start.strftime("%H:%M")


def format_calendar_response(kind, events, query_start=None):
    if kind == "next":
        ev = events  # single event or None
        if ev is None:
            return "Kein kommender Termin gefunden."
        time_part = "ganztägig" if getattr(ev, "all_day", False) else f"um {ev.start.strftime('%H:%M')}"
        line = f"Nächster Termin: {_fmt_date(ev.start)} {time_part} — {ev.title}"
        if ev.location:
            line += f" ({ev.location})"
        return line

    if not events:
        label = {"today": "heute", "tomorrow": "morgen", "week": "diese Woche"}.get(kind, "")
        return f"Keine Termine {label}.".strip()

    if kind in ("today", "tomorrow"):
        lines = [f"{_fmt_time_or_allday(ev)} — {ev.title}" for ev in events]
        return "\n".join(lines)

    # week: group by effective start day (clamped to query_start for
    # multi-day events that began before the window)
    lines = []
    current_day = None
    for ev in events:
        effective_start = max(ev.start, query_start) if query_start else ev.start
        day_key = effective_start.date()
        if day_key != current_day:
            if lines:
                lines.append("")
            lines.append(_fmt_date(effective_start))
            current_day = day_key
        lines.append(f"  {_fmt_time_or_allday(ev)} — {ev.title}")
    return "\n".join(lines)


async def handle_calendar(chat_id, text, kind=None, start=None, end=None):
    bot = Bot(token=TELEGRAM_TOKEN)
    if start is None or end is None:
        if kind != "next":
            window = detect_calendar_window(text)
            if window is None:
                await bot.send_message(
                    chat_id=chat_id,
                    text="Konnte das Zeitfenster nicht bestimmen. Bitte konkreter fragen (z.B. 'heute', 'morgen', 'diese Woche', 'nächster Termin').",
                )
                return
            kind, start, end = window
    try:
        if kind == "next":
            ev = await asyncio.to_thread(calendar_agent.get_next_event)
            msg = format_calendar_response("next", ev)
        else:
            events = await asyncio.to_thread(calendar_agent.get_events, start, end)
            msg = format_calendar_response(kind, events, query_start=start)
        await bot.send_message(chat_id=chat_id, text=msg)
    except Exception as e:
        await bot.send_message(chat_id=chat_id, text=f"Kalender-Fehler: {str(e)}")


async def ask_claude(chat_id, system, user, model="claude-haiku-4-5-20251001", use_web_search=False):
    bot = Bot(token=TELEGRAM_TOKEN)
    try:
        kwargs = {
            "model": model,
            "max_tokens": 2048,
            "system": system,
            "messages": [{"role": "user", "content": user}]
        }
        if use_web_search:
            kwargs["tools"] = [{"type": "web_search_20250305", "name": "web_search"}]

        response = claude.messages.create(**kwargs)

        answer = ""
        for block in response.content:
            if hasattr(block, "text"):
                answer += block.text

        if not answer:
            answer = "Keine Antwort erhalten."
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
        subprocess.run(["sudo", "-u", "claude", "git", "pull", "--rebase", "origin", "main"], cwd=workspace)
        subprocess.run(["sudo", "-u", "claude", "git", "add", "-A"], cwd=workspace)
        result_commit = subprocess.run(
            ["sudo", "-u", "claude", "git", "commit", "-m", "feat: Claude Code changes via Jarvis"],
            cwd=workspace, capture_output=True, text=True
        )
        if "nothing to commit" in result_commit.stdout:
            await bot.send_message(chat_id=chat_id, text="Nichts zu pushen.")
            return
        result = subprocess.run(["sudo", "-u", "claude", "git", "push"], cwd=workspace, capture_output=True, text=True)
        if result.returncode == 0:
            await bot.send_message(chat_id=chat_id, text="Gepusht zu GitHub.")
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
        "Research: 'Recherchiere: ESG Pflichten 2026'\n"
        "Work: 'Fass mir diesen Text zusammen'\n"
        "Personal: 'Was sind gute Laufschuhe?'"
    )

async def handle_message(update, context):
    update_id = update.update_id
    if update_id in processed_updates:
        logger.info(f"Duplikat ignoriert: update_id={update_id}")
        return
    processed_updates.add(update_id)
    if len(processed_updates) > 1000:
        processed_updates.clear()

    text = update.message.text
    chat_id = update.message.chat_id

    if text.lower().startswith("push "):
        project = text[5:].strip()
        await update.message.reply_text(f"Pushe {project} zu GitHub...")
        await git_push(chat_id=chat_id, project=project)
        return

    result = await route_with_llm(text)
    intent = result["intent"]
    params = result["params"]
    logger.info(f"Intent: {intent} | Nachricht: {text}")

    if intent == "calendar":
        kind = params.get("kind")
        start_str = params.get("start")
        end_str = params.get("end")
        start = datetime.fromisoformat(start_str) if start_str else None
        end = datetime.fromisoformat(end_str) if end_str else None
        await handle_calendar(chat_id=chat_id, text=text, kind=kind, start=start, end=end)
        return

    if intent == "research":
        await update.message.reply_text("Recherchiere im Web...")
        await ask_claude(
            chat_id=chat_id,
            system="Du bist Jarvis, KI-Assistent fuer Philipp. Recherchiere im Internet und antworte praezise auf Deutsch mit Quellenangaben.",
            user=text,
            model="claude-sonnet-4-6",
            use_web_search=True
        )

    elif intent == "coding":
        project = params.get("project") or extract_project(text)
        mode = params.get("mode") or detect_coding_mode(text)
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
            model="claude-sonnet-4-6",
            use_web_search=True
        )

    else:
        await update.message.reply_text("Denke nach...")
        personal_system = (
            "Du bist Jarvis, persönlicher KI-Assistent für Philipp. Antworte hilfreich auf Deutsch.\n\n"
            "Wichtig zu deinen Fähigkeiten:\n"
            "- Du HAST Zugriff auf Philipps Apple-Kalender (über einen eigenen Calendar-Handler). "
            "Wenn die Frage nach Kalender oder Terminen klingt, antworte: "
            "\"Diese Frage hätte eigentlich an meinen Calendar-Handler gehen sollen — das war ein "
            "Routing-Fehler. Bitte stell die Frage nochmal mit klareren Worten wie 'Termine', "
            "'Kalender' oder 'wann habe ich Zeit'.\"\n"
            "- Du KANNST im Web recherchieren (über einen Research-Handler).\n"
            "- Du KANNST Code in Philipps Projekten ändern (über einen Coding-Handler).\n"
            "- Wenn die Frage zu einem dieser Bereiche passt, sag ehrlich, dass die Anfrage falsch "
            "geroutet wurde, statt zu halluzinieren.\n"
            "- Bei echten allgemeinen Fragen (Smalltalk, Wissensfragen ohne Tool-Bezug) antworte "
            "normal und hilfreich."
        )
        await ask_claude(
            chat_id=chat_id,
            system=personal_system,
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
