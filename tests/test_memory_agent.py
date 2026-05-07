import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import numpy as np


def test_retrieve_returns_all_memories():
    from agents.memory_agent import MemoryAgent

    mock_db = MagicMock()
    mock_db.load_all = AsyncMock(return_value=[
        {"id": 1, "content": "Philipp mag Golf", "embedding": b"", "category": "preference"},
        {"id": 2, "content": "Philipp ist Berater", "embedding": b"", "category": "person"},
        {"id": 3, "content": "Philipp lernt Python", "embedding": b"", "category": "preference"},
    ])

    agent = MemoryAgent(mock_db)
    result = asyncio.run(agent.retrieve())

    assert len(result) == 3
    assert "Philipp mag Golf" in result
    assert "Philipp ist Berater" in result
    assert "Philipp lernt Python" in result


def test_migrate_embeddings_updates_all_rows(tmp_path):
    from agents.memory_agent import MemoryAgent, CURRENT_MODEL

    mock_db = MagicMock()
    mock_db.load_all = AsyncMock(return_value=[
        {"id": 1, "content": "Philipp mag Golf", "embedding": b"\x00" * 4, "category": "preference"},
        {"id": 2, "content": "Philipp ist Berater", "embedding": b"\x00" * 4, "category": "person"},
    ])
    mock_db.update_embedding = AsyncMock()

    fake_vec = np.ones(384, dtype=np.float32)
    marker_path = str(tmp_path / ".embedding_model")

    with patch("agents.memory_agent._embed", return_value=fake_vec), \
         patch("agents.memory_agent.MARKER_FILE", marker_path):
        asyncio.run(MemoryAgent(mock_db).migrate_embeddings())

    assert mock_db.update_embedding.call_count == 2
    with open(marker_path) as f:
        assert f.read().strip() == CURRENT_MODEL


def test_migrate_embeddings_skips_when_already_migrated(tmp_path):
    from agents.memory_agent import MemoryAgent, CURRENT_MODEL

    marker_path = str(tmp_path / ".embedding_model")
    with open(marker_path, "w") as f:
        f.write(CURRENT_MODEL + "\n")

    mock_db = MagicMock()
    mock_db.load_all = AsyncMock(return_value=[])
    mock_db.update_embedding = AsyncMock()

    with patch("agents.memory_agent.MARKER_FILE", marker_path):
        asyncio.run(MemoryAgent(mock_db).migrate_embeddings())

    mock_db.update_embedding.assert_not_called()
