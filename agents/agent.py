"""Agentische Konversations-Runtime — Phase 1 des agentischen Jarvis.

Ein zustandsloser SDK-Lauf pro Telegram-Nachricht. Der Router bleibt vorgelagert;
diese Runtime übernimmt personal/work/research, wenn JARVIS_AGENT_ENABLED gesetzt
ist.
"""

import logging
import os

logger = logging.getLogger("jarvis.agent")

_DEFAULT_MODEL = "claude-sonnet-4-6"
_MAX_TURNS = 12
_HISTORY_TURNS = 15


def agent_enabled() -> bool:
    """True, wenn der agentische Pfad per Feature-Flag aktiv ist."""
    return os.environ.get("JARVIS_AGENT_ENABLED", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


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
