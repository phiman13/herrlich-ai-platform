import asyncio
import json
import numpy as np
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from agents.db import MemoryDB
from agents.memory_agent import MemoryAgent, MEMORY_INTENTS


@pytest.fixture
def db(tmp_path):
    d = MemoryDB(str(tmp_path / "mem.db"))
    asyncio.run(d.init())
    return d


def _make_agent(db):
    return MemoryAgent(db)


def _fake_embedding(text: str) -> np.ndarray:
    arr = np.zeros(1536, dtype=np.float32)
    arr[0] = 1.0
    return arr


def test_memory_intents_set():
    assert "personal" in MEMORY_INTENTS
    assert "work" in MEMORY_INTENTS
    assert "research" in MEMORY_INTENTS
    assert "calendar" not in MEMORY_INTENTS


def test_retrieve_returns_empty_when_no_memories(db):
    agent = _make_agent(db)
    with patch("agents.memory_agent._embed", side_effect=_fake_embedding):
        results = asyncio.run(agent.retrieve("was magst du"))
    assert results == []


def test_retrieve_returns_similar_memory(db):
    agent = _make_agent(db)
    vec = _fake_embedding("test")
    asyncio.run(db.save("Philipp mag Kaffee", vec.tobytes(), "preference", "test"))

    with patch("agents.memory_agent._embed", side_effect=_fake_embedding):
        results = asyncio.run(agent.retrieve("Kaffee"))

    assert len(results) == 1
    assert results[0] == "Philipp mag Kaffee"


def test_retrieve_filters_below_threshold(db):
    agent = _make_agent(db)
    # Store a memory with orthogonal embedding (similarity = 0)
    stored_vec = np.zeros(1536, dtype=np.float32)
    stored_vec[1] = 1.0  # different dimension from query
    asyncio.run(db.save("Unrelated fact", stored_vec.tobytes(), "event", "test"))

    query_vec = np.zeros(1536, dtype=np.float32)
    query_vec[0] = 1.0  # orthogonal to stored

    with patch("agents.memory_agent._embed", return_value=query_vec):
        results = asyncio.run(agent.retrieve("some query"))

    assert results == []


def test_extract_saves_facts(db):
    agent = _make_agent(db)
    haiku_response = MagicMock()
    haiku_response.content = [MagicMock(text='[{"content": "Philipp trinkt gerne Kaffee", "category": "preference"}]')]

    with patch("agents.memory_agent._embed", side_effect=_fake_embedding), \
         patch("agents.memory_agent._claude") as mock_claude:
        mock_claude.messages.create.return_value = haiku_response
        asyncio.run(agent.extract("Ich trinke gerne Kaffee", "Das klingt gut.", "test"))

    rows = asyncio.run(db.load_all())
    assert len(rows) == 1
    assert rows[0]["content"] == "Philipp trinkt gerne Kaffee"
    assert rows[0]["category"] == "preference"


def test_extract_ignores_empty_array(db):
    agent = _make_agent(db)
    haiku_response = MagicMock()
    haiku_response.content = [MagicMock(text="[]")]

    with patch("agents.memory_agent._embed", side_effect=_fake_embedding), \
         patch("agents.memory_agent._claude") as mock_claude:
        mock_claude.messages.create.return_value = haiku_response
        asyncio.run(agent.extract("Hey wie geht's?", "Gut, danke!", "test"))

    assert asyncio.run(db.load_all()) == []


def test_extract_handles_invalid_json(db):
    agent = _make_agent(db)
    haiku_response = MagicMock()
    haiku_response.content = [MagicMock(text="not json at all")]

    with patch("agents.memory_agent._embed", side_effect=_fake_embedding), \
         patch("agents.memory_agent._claude") as mock_claude:
        mock_claude.messages.create.return_value = haiku_response
        # Must not raise
        asyncio.run(agent.extract("Hey", "Jo", "test"))

    assert asyncio.run(db.load_all()) == []


def test_list_memories_formats_output(db):
    agent = _make_agent(db)
    vec = _fake_embedding("x")
    asyncio.run(db.save("Fact A", vec.tobytes(), "event", "test"))
    asyncio.run(db.save("Fact B", vec.tobytes(), "preference", "test"))

    result = asyncio.run(agent.list_memories())
    assert "Fact A" in result
    assert "Fact B" in result
    assert "preference" in result


def test_list_memories_empty(db):
    agent = _make_agent(db)
    result = asyncio.run(agent.list_memories())
    assert "keine" in result.lower() or "noch" in result.lower()


def test_delete_memory_by_query(db):
    agent = _make_agent(db)
    vec = _fake_embedding("Siemens")
    asyncio.run(db.save("Philipp hat Pitch bei Siemens", vec.tobytes(), "event", "test"))

    with patch("agents.memory_agent._embed", return_value=vec):
        result = asyncio.run(agent.delete_memory("Siemens"))

    assert "gelöscht" in result
    assert asyncio.run(db.load_all()) == []


def test_delete_latest_when_query_is_none(db):
    agent = _make_agent(db)
    vec = _fake_embedding("x")
    asyncio.run(db.save("Älterer Fakt", vec.tobytes(), "event", "test"))
    asyncio.run(db.save("Neuester Fakt", vec.tobytes(), "preference", "test"))

    result = asyncio.run(agent.delete_memory(None))
    assert "gelöscht" in result
    rows = asyncio.run(db.load_all())
    assert len(rows) == 1
    assert rows[0]["content"] == "Älterer Fakt"


def test_delete_returns_message_when_nothing_found(db):
    agent = _make_agent(db)
    orthogonal_vec = np.zeros(1536, dtype=np.float32)
    orthogonal_vec[1] = 1.0
    asyncio.run(db.save("Unrelated", orthogonal_vec.tobytes(), "event", "test"))

    query_vec = np.zeros(1536, dtype=np.float32)
    query_vec[0] = 1.0  # orthogonal → sim = 0, below threshold

    with patch("agents.memory_agent._embed", return_value=query_vec):
        result = asyncio.run(agent.delete_memory("xyz"))

    assert "nicht gefunden" in result
