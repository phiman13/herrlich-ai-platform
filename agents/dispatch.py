"""Telegram message dispatch — routing, the _process_text orchestrator, entry handlers."""

import asyncio
import logging

from telegram import Update

import app_state
from app_state import (
    _conv_append_user,
    _conv_complete,
    _conv_to_prev_texts,
)
from router import route_with_llm
from voice_agent import transcribe
from mail_handler import handle_mail_intent
from calendar_handler import handle_calendar_intent
from chat_handler import handle_research, handle_work, handle_personal
from agent import run_agent, agent_enabled
from intent_handlers import (
    handle_coding,
    handle_reminder_write,
    handle_news,
    handle_tasks,
    handle_weather,
    handle_briefing,
    handle_memory,
)

logger = logging.getLogger("jarvis.dispatch")


_MEMORY_INTENTS = {"personal", "work", "research"}
_HISTORY_INTENTS = {"personal", "work", "research"}
# Intents, die der agentische Pfad übernimmt (wenn JARVIS_AGENT_ENABLED).
# Bewusst eine eigene Menge — deckt sich aktuell mit _MEMORY_INTENTS /
# _HISTORY_INTENTS, kann in Phase 2 aber divergieren.
_AGENT_INTENTS = {"personal", "work", "research"}


async def start(update, context):
    await update.message.reply_text(
        "Hallo Philipp! Ich bin Jarvis.\n\n"
        "Coding (Frage): 'Was sind die Todos in recipe-app?'\n"
        "Coding (Aktion): 'Fixe den Login-Bug in recipe-app'\n"
        "Research: 'Recherchiere: ESG Pflichten 2026'\n"
        "Work: 'Fass mir diesen Text zusammen'\n"
        "Personal: 'Was sind gute Laufschuhe?'"
    )


async def _process_text(text: str, chat_id: int, update: Update) -> None:
    prev = _conv_to_prev_texts(chat_id)
    _conv_append_user(chat_id, text)
    routing = await route_with_llm(text, prev_texts=prev or None)
    intent = routing["intent"]
    params = routing["params"]

    confidence = routing["confidence"]
    if confidence < 5:
        msg = (
            "Ich bin mir nicht ganz sicher, was du meinst. "
            "Bitte präzisiere: Kalender, Mail, Task-Liste, Coding oder etwas anderes?"
        )
        await update.message.reply_text(msg)
        _conv_complete(chat_id, msg)
        return

    memory_context = ""
    if intent in _MEMORY_INTENTS:
        if app_state.profile_agent:
            try:
                profile = app_state.profile_agent.load()
                memory_context += f"=== Philipps Profil ===\n{profile}\n\n"
            except Exception as e:
                logger.warning("Profile load failed: %s", e)
        if app_state.memory_agent:
            try:
                memories = await app_state.memory_agent.retrieve()
                if memories:
                    bullet_list = "\n".join(f"• {m}" for m in memories)
                    memory_context += f"=== Erinnerungen ===\n{bullet_list}\n\n"
            except Exception as e:
                logger.warning("Memory retrieval failed: %s", e)

    logger.info(f"Intent: {intent} | Nachricht: {text}")

    answer: str = ""
    history: list[dict] = []
    if app_state.conversation_db and intent in _HISTORY_INTENTS:
        try:
            history = await app_state.conversation_db.get_recent(chat_id, n=20)
        except Exception as e:
            logger.warning("History load failed: %s", e)

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

    if answer and not answer.startswith("Fehler:"):
        _conv_complete(chat_id, answer[:180])

    if (
        app_state.conversation_db
        and intent in _HISTORY_INTENTS
        and answer
        and not answer.startswith("Fehler:")
    ):
        try:
            await app_state.conversation_db.save(chat_id, "user", text)
            await app_state.conversation_db.save(chat_id, "assistant", answer)
        except Exception as e:
            logger.warning("History save failed: %s", e)

    if (
        app_state.profile_agent
        and intent in _HISTORY_INTENTS
        and answer
        and not answer.startswith("Fehler:")
    ):
        conversation = f"Philipp: {text}\n\nJarvis: {answer}"
        asyncio.create_task(app_state.profile_agent.update(conversation))


async def handle_message(update, context):
    update_id = update.update_id
    if update_id in app_state.processed_updates:
        logger.info(f"Duplikat ignoriert: update_id={update_id}")
        return
    app_state.processed_updates.add(update_id)
    if len(app_state.processed_updates) > 1000:
        app_state.processed_updates.clear()

    text = update.message.text
    chat_id = update.message.chat_id
    await _process_text(text, chat_id, update)


async def handle_voice(update, context):
    update_id = update.update_id
    if update_id in app_state.processed_updates:
        logger.info(f"Duplikat ignoriert: update_id={update_id}")
        return
    app_state.processed_updates.add(update_id)
    if len(app_state.processed_updates) > 1000:
        app_state.processed_updates.clear()

    chat_id = update.message.chat_id
    try:
        voice_file = await update.message.voice.get_file()
        ogg_bytes = bytes(await voice_file.download_as_bytearray())
        text = await transcribe(ogg_bytes)
    except Exception as e:
        logger.warning("Voice transcription failed: %s", e)
        await update.message.reply_text(
            "❌ Sprachnachricht konnte nicht transkribiert werden."
        )
        return

    await _process_text(text, chat_id, update)
