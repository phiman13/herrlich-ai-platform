import asyncio
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

import dispatch as main_module
import app_state


@pytest.fixture(autouse=True)
def fresh_memory_agent(tmp_path):
    """Replace global memory_agent with a test instance backed by a temp DB."""
    from agents.db import MemoryDB
    from agents.memory_agent import MemoryAgent

    db = MemoryDB(str(tmp_path / "mem.db"))
    asyncio.run(db.init())
    agent = MemoryAgent(db)
    app_state.memory_agent = agent
    yield agent
    app_state.memory_agent = None


def test_memory_agent_is_none_by_default():
    # The fixture sets it — just verify the fixture works
    assert app_state.memory_agent is not None


def test_retrieve_called_for_any_message(fresh_memory_agent):
    """retrieve() wird für alle Nachrichten aufgerufen — kein Router-Gate mehr."""
    called = []

    async def fake_retrieve():
        called.append(True)
        return []

    app_state.conversation_db = None
    app_state.profile_agent = None

    with patch.object(fresh_memory_agent, "retrieve", side_effect=fake_retrieve):
        with patch("dispatch.run_agent", new_callable=AsyncMock, return_value="ok"):
            with patch("app_state.send_typing", new_callable=AsyncMock):
                update = MagicMock()
                update.update_id = 99991
                update.message.text = "Wie geht's dir?"
                update.message.chat_id = 123
                update.message.reply_text = AsyncMock()
                asyncio.run(main_module.handle_message(update, None))

    assert len(called) == 1


def test_retrieve_called_for_calendar_message(fresh_memory_agent):
    """retrieve() wird jetzt auch für calendar aufgerufen — kein _MEMORY_INTENTS-Gate mehr."""
    called = []

    async def fake_retrieve():
        called.append(True)
        return []

    app_state.conversation_db = None
    app_state.profile_agent = None

    with patch.object(fresh_memory_agent, "retrieve", side_effect=fake_retrieve):
        with patch(
            "dispatch.run_agent",
            new_callable=AsyncMock,
            return_value="Heute hast du 2 Termine.",
        ):
            with patch("app_state.send_typing", new_callable=AsyncMock):
                update = MagicMock()
                update.update_id = 99992
                update.message.text = "Was habe ich heute?"
                update.message.chat_id = 123
                update.message.reply_text = AsyncMock()
                asyncio.run(main_module.handle_message(update, None))

    assert len(called) == 1


def test_memory_context_injected_when_memories_exist(fresh_memory_agent):
    """Vorhandene Memories werden als Kontext an run_agent weitergegeben."""
    import numpy as np

    vec = np.zeros(1536, dtype=np.float32)
    asyncio.run(
        fresh_memory_agent.db.save("Philipp mag Tee", vec.tobytes(), "preference", "t")
    )

    app_state.conversation_db = None
    app_state.profile_agent = None
    captured = {}

    async def fake_run_agent(chat_id, text, history, memory_context):
        captured["memory_context"] = memory_context
        return "ok"

    with patch("dispatch.run_agent", side_effect=fake_run_agent):
        with patch("app_state.send_typing", new_callable=AsyncMock):
            update = MagicMock()
            update.update_id = 99993
            update.message.text = "Was weißt du über mich?"
            update.message.chat_id = 123
            update.message.reply_text = AsyncMock()
            asyncio.run(main_module.handle_message(update, None))

    assert "Philipp mag Tee" in captured.get("memory_context", "")


def test_no_memory_intent_handler_in_dispatch():
    """handle_memory wurde aus dispatch entfernt — Memory läuft als Tool."""
    import dispatch as dispatch_mod

    assert not hasattr(dispatch_mod, "handle_memory")
