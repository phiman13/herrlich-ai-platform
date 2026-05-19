"""Telegram message dispatch — routing-free orchestrator."""

import asyncio
import logging

from telegram import Update

import app_state
from voice_agent import transcribe
from agent import run_agent

logger = logging.getLogger("jarvis.dispatch")


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
    memory_context = ""
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

    history: list[dict] = []
    if app_state.conversation_db:
        try:
            history = await app_state.conversation_db.get_recent(chat_id, n=20)
        except Exception as e:
            logger.warning("History load failed: %s", e)

    answer = await run_agent(chat_id, text, history, memory_context)

    if app_state.conversation_db and answer and not answer.startswith("Fehler:"):
        try:
            await app_state.conversation_db.save(chat_id, "user", text)
            await app_state.conversation_db.save(chat_id, "assistant", answer)
        except Exception as e:
            logger.warning("History save failed: %s", e)

    if app_state.profile_agent and answer and not answer.startswith("Fehler:"):
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
