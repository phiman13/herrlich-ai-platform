"""Opt-in End-to-End-Smoke-Test für den agentischen Pfad.

Aktivieren mit:  JARVIS_LIVE_TESTS=1 PYTHONPATH=agents <venv>/bin/pytest tests/test_agent_live.py -v
Voraussetzung: Claude Code CLI installiert + per OAuth/Abo authentifiziert.
"""

import os

import pytest

import agent

_LIVE = os.environ.get("JARVIS_LIVE_TESTS", "").strip() not in ("", "0", "false")
pytestmark = pytest.mark.skipif(not _LIVE, reason="JARVIS_LIVE_TESTS nicht gesetzt")


@pytest.mark.asyncio
async def test_agent_reads_workspace_file(tmp_path, monkeypatch):
    """Der Agent soll eine bekannte Workspace-Datei lesen und ihren Inhalt nennen."""
    monkeypatch.setenv("JARVIS_WORKSPACE_DIR", str(tmp_path))
    secret = "Apfelstrudel-7421"
    (tmp_path / "notiz.txt").write_text(
        f"Das geheime Codewort lautet {secret}.", encoding="utf-8"
    )

    sent = {}

    class _Bot:
        def __init__(self, *a, **k):
            pass

        async def send_message(self, chat_id, text):
            sent["text"] = text

    monkeypatch.setattr(agent, "Bot", _Bot)

    # Typing-Indikator ausschalten — sonst würde _keep_typing mit dem
    # Test-Telegram-Token echte API-Calls versuchen und fehlschlagen.
    async def _noop_keep_typing(chat_id, stop_event):
        return

    monkeypatch.setattr(agent, "_keep_typing", _noop_keep_typing)

    answer = await agent.run_agent(
        chat_id=999,
        user_text="Lies die Datei notiz.txt im Workspace und nenne mir das Codewort.",
        history=[],
        memory_context="",
    )
    assert secret in answer
    assert secret in sent.get("text", "")
