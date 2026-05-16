"""LLM-chat handlers — research, work, personal intents via Claude."""

import logging
import asyncio
import anthropic
from telegram import Bot
import app_state

logger = logging.getLogger("jarvis.chat_handler")

claude = anthropic.Anthropic()


async def ask_claude(
    chat_id,
    system,
    user,
    model="claude-haiku-4-5-20251001",
    use_web_search=False,
    history: list[dict] | None = None,
) -> str:
    bot = Bot(token=app_state.TELEGRAM_TOKEN)
    answer = ""
    try:
        kwargs = {
            "model": model,
            "max_tokens": 2048,
            "system": system,
            "messages": [*(history or []), {"role": "user", "content": user}],
        }
        if use_web_search:
            kwargs["tools"] = [{"type": "web_search_20250305", "name": "web_search"}]

        response = claude.messages.create(**kwargs)

        for block in response.content:
            if hasattr(block, "text"):
                answer += block.text

        if not answer:
            answer = "Keine Antwort erhalten."
        if len(answer) > 4000:
            answer = answer[:4000] + "\n[...]"
        await bot.send_message(chat_id=chat_id, text=answer)
    except Exception as e:
        answer = f"Fehler: {str(e)}"
        await bot.send_message(chat_id=chat_id, text=answer)
    return answer


async def handle_research(
    chat_id: int, text: str, memory_context: str, history: list[dict]
) -> str:
    from main import _keep_typing

    stop = asyncio.Event()
    typing_task = asyncio.create_task(_keep_typing(chat_id, stop))
    try:
        answer = await ask_claude(
            chat_id=chat_id,
            system=memory_context
            + "Du bist Jarvis, KI-Assistent fuer Philipp. Recherchiere im Internet und antworte praezise auf Deutsch mit Quellenangaben.",
            user=text,
            model="claude-sonnet-4-6",
            use_web_search=True,
            history=history,
        )
    finally:
        stop.set()
        await typing_task
    if app_state.memory_agent:
        asyncio.create_task(
            app_state.memory_agent.extract(text, answer, source="research")
        )
    return answer


async def handle_work(
    chat_id: int, text: str, memory_context: str, history: list[dict]
) -> str:
    from main import _keep_typing

    stop = asyncio.Event()
    typing_task = asyncio.create_task(_keep_typing(chat_id, stop))
    try:
        answer = await ask_claude(
            chat_id=chat_id,
            system=memory_context
            + "Du bist Jarvis, KI-Assistent fuer Philipp (Projektmanager, Strategieberatung). Antworte praezise und strukturiert auf Deutsch.",
            user=text,
            model="claude-sonnet-4-6",
            use_web_search=True,
            history=history,
        )
    finally:
        stop.set()
        await typing_task
    if app_state.memory_agent:
        asyncio.create_task(app_state.memory_agent.extract(text, answer, source="work"))
    return answer


async def handle_personal(
    chat_id: int, text: str, memory_context: str, history: list[dict]
) -> str:
    from main import _keep_typing

    personal_system = (
        "Du bist Jarvis, persönlicher KI-Assistent für Philipp. Antworte hilfreich auf Deutsch.\n\n"
        "Deine tatsächlichen Fähigkeiten:\n"
        "- Kalender: Outlook-Kalender lesen und Termine erstellen (mit Bestätigung)\n"
        "- Mail: MS365-Posteingang lesen, durchsuchen, Mails schreiben\n"
        "- Tasks: MS To Do Listen lesen und verwalten\n"
        "- Wetter: aktuelle Wetterdaten und Vorhersage für Tutzing/München\n"
        "- KI-News: aktuelle Nachrichten aus der AI-Welt\n"
        "- Web-Recherche: aktuelle Informationen aus dem Internet\n"
        "- Coding: Claude Code auf VPS-Projekten ausführen (recipe-app, immo-radar etc.)\n"
        "- Morning Briefing: tägliche Zusammenfassung\n"
        "- Erinnerungen: persönliche Fakten und Präferenzen speichern/abrufen\n\n"
        "Wenn eine Frage zu einem dieser Bereiche gehört aber hierher geroutet wurde, sag das ehrlich "
        "('Das war ein Routing-Fehler — frag nochmal klarer') statt zu halluzinieren. "
        "Bei echten allgemeinen Fragen (Smalltalk, Wissensfragen ohne Tool-Bezug) antworte normal."
    )
    stop = asyncio.Event()
    typing_task = asyncio.create_task(_keep_typing(chat_id, stop))
    try:
        answer = await ask_claude(
            chat_id=chat_id,
            system=memory_context + personal_system,
            user=text,
            model="claude-sonnet-4-6",
            history=history,
        )
    finally:
        stop.set()
        await typing_task
    if app_state.memory_agent:
        asyncio.create_task(
            app_state.memory_agent.extract(text, answer, source="personal")
        )
    return answer
