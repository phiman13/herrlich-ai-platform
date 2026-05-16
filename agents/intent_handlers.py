"""Lean intent handlers — coding, tasks, news, weather, briefing, reminders, memory."""

import logging
import os
import asyncio

from telegram import Bot

import app_state
import router
from coding_agent import handle_coding_query, run_coding_action, add_backlog_item
from vps import list_projects
from news_agent import get_ai_news
from tasks_agent import (
    get_tasks,
    add_task,
    complete_task,
    create_list,
    delete_list,
    rename_list,
)
from weather_agent import get_weather
from briefing_agent import build_briefing

logger = logging.getLogger("jarvis.intent_handlers")


async def send_briefing():
    chat_id_str = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not chat_id_str:
        logger.warning("TELEGRAM_CHAT_ID nicht gesetzt — Briefing übersprungen")
        return
    bot = Bot(token=os.environ["TELEGRAM_BOT_TOKEN"])
    try:
        msg = await build_briefing()
        try:
            await bot.send_message(
                chat_id=int(chat_id_str), text=msg, parse_mode="Markdown"
            )
        except Exception:
            await bot.send_message(chat_id=int(chat_id_str), text=msg)
    except Exception as e:
        logger.exception(f"Briefing-Fehler: {e}")


async def handle_coding(chat_id: int, text: str, params: dict, update) -> None:
    from dispatch import _conv_complete

    mode = params.get("mode", "action")
    project = params.get("project")

    if not project:
        projects = await list_projects()
        project = projects[0] if projects else "recipe-app"

    if mode == "query":
        query_type = params.get("query_type", "backlog")
        await update.message.reply_text("🔍 Lese...")
        query_result = await handle_coding_query(project, query_type)
        await update.message.reply_text(
            f"📁 *{project}* — {query_type}\n\n{query_result[:4000]}",
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
            await update.message.reply_text("❌ Konnte Backlog nicht aktualisieren.")

    else:  # action
        asyncio.create_task(run_coding_action(text, project, chat_id))
    _conv_complete(chat_id, f"Coding {mode} ({project})")


async def handle_reminder_write(chat_id: int, params: dict, update) -> None:
    from dispatch import _conv_complete

    title = params.get("title", "")
    due_date_str = params.get("due_date")
    due_time_str = params.get("due_time")
    list_name = params.get("list_name") or os.environ.get("REMINDER_TODO_LIST", "Tasks")
    if not title:
        await update.message.reply_text("Kein Titel angegeben.")
        return
    try:
        ok = await asyncio.to_thread(
            add_task, list_name, title, due_date_str, due_time_str
        )
        if ok:
            due_str = (
                f" (fällig: {due_date_str}{' ' + due_time_str if due_time_str else ''})"
                if due_date_str
                else ""
            )
            msg = f"✅ Erinnerung '{title}'{due_str} in To-Do gespeichert."
            await update.message.reply_text(msg)
            _conv_complete(chat_id, msg)
        else:
            await update.message.reply_text(
                f"❌ Liste '{list_name}' nicht gefunden. Verfügbare Listen mit 'Zeig mir alle To-Do-Listen'."
            )
            _conv_complete(chat_id, f"Erinnerung '{title}' nicht erstellt")
    except Exception as e:
        logger.exception("reminder_write fehlgeschlagen")
        await update.message.reply_text(
            f"❌ Erinnerung konnte nicht erstellt werden: {e}"
        )
        _conv_complete(chat_id, "Erinnerung fehlgeschlagen")
    return


async def handle_news(chat_id: int, update) -> None:
    from dispatch import _conv_complete

    await update.message.reply_text("📰 Lade AI-News...")
    news = await asyncio.to_thread(get_ai_news, 48, 10)
    await update.message.reply_text(
        f"📰 *AI NEWS — letzte 48h*\n\n{news or 'Keine News gefunden.'}",
        parse_mode="Markdown",
    )
    _conv_complete(chat_id, "AI-News angezeigt")


async def handle_tasks(chat_id: int, params: dict, update) -> None:
    from dispatch import _conv_complete

    mode = params.get("mode", "read")
    list_name = params.get("list_name")
    item = params.get("item")

    if mode == "read":
        task_result = await asyncio.to_thread(get_tasks, list_name)
        await update.message.reply_text(
            task_result or "Keine offenen Tasks.", parse_mode="Markdown"
        )

    elif mode == "write" and item:
        if not list_name:
            await update.message.reply_text("Welche Liste? (z.B. 'Einkaufsliste')")
        else:
            success = await asyncio.to_thread(add_task, list_name, item)
            if success:
                await update.message.reply_text(
                    f"✅ '{item}' zu *{list_name}* hinzugefügt.",
                    parse_mode="Markdown",
                )
            else:
                await update.message.reply_text("❌ Konnte Task nicht hinzufügen.")

    elif mode == "complete" and item:
        if not list_name:
            await update.message.reply_text("Welche Liste?")
        else:
            success = await asyncio.to_thread(complete_task, list_name, item)
            if success:
                await update.message.reply_text(
                    f"✅ '{item}' in *{list_name}* als erledigt markiert.",
                    parse_mode="Markdown",
                )
            else:
                await update.message.reply_text(
                    "❌ Task nicht gefunden oder bereits erledigt."
                )

    elif mode == "create_list" and list_name:
        success = await asyncio.to_thread(create_list, list_name)
        if success:
            router._todo_lists_cache = ([], 0.0)
            await update.message.reply_text(
                f"✅ Liste *{list_name}* angelegt.", parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("❌ Liste konnte nicht angelegt werden.")

    elif mode == "delete_list" and list_name:
        success = await asyncio.to_thread(delete_list, list_name)
        if success:
            router._todo_lists_cache = ([], 0.0)
            await update.message.reply_text(
                f"✅ Liste *{list_name}* gelöscht.", parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                f"❌ Liste '{list_name}' nicht gefunden oder konnte nicht gelöscht werden."
            )

    elif mode == "rename_list":
        new_name = params.get("new_name")
        if not list_name or not new_name:
            await update.message.reply_text("Bitte alter und neuer Listenname angeben.")
        else:
            success = await asyncio.to_thread(rename_list, list_name, new_name)
            if success:
                router._todo_lists_cache = ([], 0.0)
                await update.message.reply_text(
                    f"✅ Liste *{list_name}* → *{new_name}* umbenannt.",
                    parse_mode="Markdown",
                )
            else:
                await update.message.reply_text(
                    f"❌ Liste '{list_name}' nicht gefunden oder Umbenennung fehlgeschlagen."
                )
    tasks_list_label = list_name or "Tasks"
    _conv_complete(chat_id, f"Tasks {mode} ({tasks_list_label})")


async def handle_weather(chat_id: int, params: dict, update) -> None:
    from dispatch import _conv_complete

    period = params.get("period", "today")
    time_of_day = params.get("time_of_day")
    location = params.get("location")
    period_label = {
        "today": "heute",
        "tomorrow": "morgen",
        "week": "diese Woche",
    }.get(period, period)
    weather = await asyncio.to_thread(get_weather, period, time_of_day, location)
    await update.message.reply_text(
        f"🌤️ *Wetter {period_label}:*\n{weather}", parse_mode="Markdown"
    )
    _conv_complete(chat_id, f"Wetter {period_label} angezeigt")


async def handle_briefing(chat_id: int, update) -> None:
    from dispatch import _conv_complete

    await update.message.reply_text("⏳ Briefing wird erstellt...")
    msg = await build_briefing()
    await update.message.reply_text(msg, parse_mode="Markdown")
    _conv_complete(chat_id, "Morgenbriefing angezeigt")


async def handle_memory(chat_id: int, params: dict, update) -> None:
    from dispatch import _conv_complete

    mode = params.get("mode", "list")
    query = params.get("query")
    if not app_state.memory_agent:
        await update.message.reply_text("Memory-System nicht initialisiert.")
        return
    if mode == "delete":
        msg = await app_state.memory_agent.delete_memory(query)
    else:
        msg = await app_state.memory_agent.list_memories()
    await update.message.reply_text(msg, parse_mode="Markdown")
    _conv_complete(chat_id, f"Erinnerungen {mode}")
