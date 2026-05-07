import asyncio
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

import agents.main as main_module


@pytest.fixture(autouse=True)
def fresh_memory_agent(tmp_path):
    """Replace global memory_agent with a test instance backed by a temp DB."""
    from agents.db import MemoryDB
    from agents.memory_agent import MemoryAgent
    db = MemoryDB(str(tmp_path / "mem.db"))
    asyncio.run(db.init())
    agent = MemoryAgent(db)
    main_module._memory_agent = agent
    yield agent
    main_module._memory_agent = None


def test_memory_agent_is_none_by_default():
    # The fixture sets it — just verify the fixture works
    assert main_module._memory_agent is not None


def test_retrieve_called_for_personal_intent(fresh_memory_agent):
    """retrieve() is called when intent is personal."""
    called_with = []

    async def fake_retrieve(query: str):
        called_with.append(query)
        return []

    with patch.object(fresh_memory_agent, "retrieve", side_effect=fake_retrieve):
        with patch("agents.main.route_with_llm", return_value={
            "intent": "personal", "confidence": 8, "params": {}, "reasoning": "test"
        }):
            with patch("agents.main.ask_claude", new_callable=AsyncMock, return_value="ok"):
                update = MagicMock()
                update.update_id = 99991
                update.message.text = "Wie geht's dir?"
                update.message.chat_id = 123
                update.message.reply_text = AsyncMock()
                asyncio.run(main_module.handle_message(update, None))

    assert len(called_with) == 1
    assert called_with[0] == "Wie geht's dir?"


def test_retrieve_not_called_for_calendar_intent(fresh_memory_agent):
    """retrieve() is NOT called for calendar intent."""
    called = []

    async def fake_retrieve(query):
        called.append(query)
        return []

    with patch.object(fresh_memory_agent, "retrieve", side_effect=fake_retrieve):
        with patch("agents.main.route_with_llm", return_value={
            "intent": "calendar", "confidence": 9,
            "params": {"mode": "read", "kind": "today", "start": None, "end": None,
                       "title": None, "calendar_name": None},
            "reasoning": "test",
        }):
            with patch("agents.main.handle_calendar", new_callable=AsyncMock):
                update = MagicMock()
                update.update_id = 99992
                update.message.text = "Was habe ich heute?"
                update.message.chat_id = 123
                update.message.reply_text = AsyncMock()
                asyncio.run(main_module.handle_message(update, None))

    assert called == []


def test_memory_list_intent_handler(fresh_memory_agent):
    """memory intent with mode=list calls list_memories and replies."""
    import numpy as np
    vec = np.zeros(1536, dtype=np.float32)
    asyncio.run(fresh_memory_agent.db.save("Philipp mag Tee", vec.tobytes(), "preference", "t"))

    with patch("agents.main.route_with_llm", return_value={
        "intent": "memory", "confidence": 9,
        "params": {"mode": "list", "query": None},
        "reasoning": "test",
    }):
        update = MagicMock()
        update.update_id = 99993
        update.message.text = "Was weißt du über mich?"
        update.message.chat_id = 123
        update.message.reply_text = AsyncMock()
        asyncio.run(main_module.handle_message(update, None))

    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "Philipp mag Tee" in reply_text


def test_memory_delete_intent_handler(fresh_memory_agent):
    """memory intent with mode=delete calls delete_memory and replies."""
    import numpy as np
    vec = np.zeros(1536, dtype=np.float32)
    vec[0] = 1.0
    asyncio.run(fresh_memory_agent.db.save("Siemens Pitch", vec.tobytes(), "event", "t"))

    with patch("agents.main.route_with_llm", return_value={
        "intent": "memory", "confidence": 9,
        "params": {"mode": "delete", "query": "Siemens"},
        "reasoning": "test",
    }):
        with patch("agents.memory_agent._embed", return_value=vec):
            update = MagicMock()
            update.update_id = 99994
            update.message.text = "Vergiss Siemens"
            update.message.chat_id = 123
            update.message.reply_text = AsyncMock()
            asyncio.run(main_module.handle_message(update, None))

    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "gelöscht" in reply_text
