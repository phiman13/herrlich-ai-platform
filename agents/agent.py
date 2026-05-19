"""Agentische Konversations-Runtime des agentischen Jarvis.

Ein zustandsloser SDK-Lauf pro Telegram-Nachricht. Der Router bleibt in Phase 2
vorgelagert; diese Runtime übernimmt die agentischen Intents (_AGENT_INTENTS in
dispatch.py).
"""

import asyncio
import logging
import os

from telegram import Bot
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)

import app_state
from tools import build_mcp_server, permission_hook
from app_state import _keep_typing

logger = logging.getLogger("jarvis.agent")

_DEFAULT_MODEL = "claude-sonnet-4-6"
_MAX_TURNS = 12
_HISTORY_TURNS = 15


def build_system_prompt(memory_context: str) -> str:
    """System-Prompt des Agenten — Rolle, Stil, Werkzeug-Hinweise.

    memory_context (Profil + Erinnerungen) wird vorangestellt.
    """
    base = (
        "Du bist Jarvis, der persönliche KI-Assistent von Philipp. "
        "Antworte hilfreich, präzise und auf Deutsch.\n\n"
        "Werkzeuge:\n"
        "- workspace: Liest und durchsucht Philipps Projekt-Code im Coding-Workspace "
        "(Projekte u.a.: recipe-app, herrlich-ai-platform, immo-radar, "
        "high-five-website, refurbish-business, cv-project). Nutze es für fundierte "
        "Fragen zu seinen Projekten — list/search/read, nicht raten.\n"
        "- weather: Wettervorhersage für Tutzing (Heimatort) oder einen "
        "genannten Ort.\n"
        "- news: Aktuelle AI-/Tech-News aus kuratierten RSS-Feeds.\n"
        "- WebSearch / WebFetch: Aktuelle Informationen aus dem Internet.\n\n"
        "Arbeitsweise: Bei Fragen zu Philipps Projekten oder Code zuerst den "
        "Workspace erkunden, dann fundiert antworten. Bei Fragen zu aktuellen "
        "Ereignissen das Web nutzen. Halte Antworten Telegram-tauglich kurz. "
        "Wenn du etwas nicht sicher weißt, sag es offen."
    )
    return (memory_context + base) if memory_context else base


def format_history(history: list[dict]) -> str:
    """Gesprächsverlauf als Klartext — auf die letzten ~15 Turns gekappt.

    history-Einträge: {"role": "user"|"assistant", "content": str}.
    """
    if not history:
        return ""
    recent = history[-(_HISTORY_TURNS * 2) :]
    lines = []
    for turn in recent:
        who = "Philipp" if turn.get("role") == "user" else "Jarvis"
        lines.append(f"{who}: {turn.get('content', '')}")
    return "\n".join(lines)


def build_user_prompt(history: list[dict], user_text: str) -> str:
    """Die User-Nachricht für den SDK-Lauf — History als Text eingebettet.

    History als separate Stream-Nachrichten zu senden lässt den Agenten alte
    Turns erneut beantworten (in Schritt A verifiziert) — daher als Text.
    """
    hist = format_history(history)
    if hist:
        return (
            "[Bisheriger Gesprächsverlauf]\n"
            + hist
            + "\n\n[Aktuelle Nachricht]\n"
            + user_text
        )
    return user_text


async def run_agent(
    chat_id: int,
    user_text: str,
    history: list[dict],
    memory_context: str,
) -> str:
    """Einen agentischen Turn fahren: Optionen bauen, SDK-Loop, Antwort senden.

    Pro Chat serialisiert (asyncio.Lock). Gibt den finalen Antworttext zurück.
    """
    async with app_state.get_agent_lock(chat_id):
        bot = Bot(token=app_state.TELEGRAM_TOKEN)
        stop = asyncio.Event()
        typing_task = asyncio.create_task(_keep_typing(chat_id, stop))
        final_text = ""
        try:
            opts_kwargs = dict(
                model=os.environ.get("JARVIS_AGENT_MODEL", _DEFAULT_MODEL),
                system_prompt=build_system_prompt(memory_context),
                mcp_servers={"jarvis": build_mcp_server()},
                # tools: beschränkt die eingebauten Werkzeuge (kein Bash/Edit/Read).
                # allowed_tools: auto-erlaubt — überspringt den can_use_tool-Hook.
                allowed_tools=["WebSearch", "WebFetch"],
                tools=["WebSearch", "WebFetch"],
                can_use_tool=permission_hook,
                max_turns=_MAX_TURNS,
                permission_mode="default",
                # ANTHROPIC_API_KEY für den CLI-Subprozess leeren — erzwingt
                # Abo-Auth (CLAUDE_CODE_OAUTH_TOKEN) statt API-Key-Billing.
                # Der jarvis-Prozess behält den Key für die alten Agenten.
                env={"ANTHROPIC_API_KEY": ""},
            )
            cli_path = os.environ.get("JARVIS_CLAUDE_CLI_PATH")
            if cli_path:
                opts_kwargs["cli_path"] = cli_path
            options = ClaudeAgentOptions(**opts_kwargs)

            prompt_text = build_user_prompt(history, user_text)

            async def _prompt_stream():
                yield {
                    "type": "user",
                    "message": {"role": "user", "content": prompt_text},
                }

            async for msg in query(prompt=_prompt_stream(), options=options):
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock) and block.text.strip():
                            final_text = block.text
                elif isinstance(msg, ResultMessage):
                    # ResultMessage kommt zuletzt — überschreibt den Zwischentext.
                    if msg.result:
                        final_text = msg.result
                    elif msg.is_error and not final_text:
                        final_text = "Der Agent konnte die Anfrage nicht abschließen."
        except Exception as e:
            logger.exception("Agent-Lauf fehlgeschlagen")
            final_text = f"Fehler: {e}"
        finally:
            stop.set()
            await typing_task

        if not final_text:
            final_text = "Keine Antwort erhalten."
        if len(final_text) > 4000:
            final_text = final_text[:4000] + "\n[...]"
        await bot.send_message(chat_id=chat_id, text=final_text)

    if app_state.memory_agent and not final_text.startswith("Fehler:"):
        asyncio.create_task(
            app_state.memory_agent.extract(user_text, final_text, source="agent")
        )
    return final_text
