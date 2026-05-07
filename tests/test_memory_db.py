import asyncio
import numpy as np
import pytest
from agents.db import MemoryDB


@pytest.fixture
def db(tmp_path):
    return MemoryDB(str(tmp_path / "memories.db"))


def test_init_creates_table(db):
    asyncio.run(db.init())
    # If init() ran without error, the table exists
    rows = asyncio.run(db.load_all())
    assert rows == []


def test_save_and_load_all(db):
    asyncio.run(db.init())
    vec = np.zeros(1536, dtype=np.float32)
    asyncio.run(db.save("Philipp mag Kaffee", vec.tobytes(), "preference", "test"))
    rows = asyncio.run(db.load_all())
    assert len(rows) == 1
    assert rows[0]["content"] == "Philipp mag Kaffee"
    assert rows[0]["category"] == "preference"
    assert np.frombuffer(rows[0]["embedding"], dtype=np.float32).shape == (1536,)


def test_get_recent_returns_newest_first(db):
    asyncio.run(db.init())
    vec = np.zeros(1536, dtype=np.float32)
    asyncio.run(db.save("Fact A", vec.tobytes(), "event", "test"))
    asyncio.run(db.save("Fact B", vec.tobytes(), "event", "test"))
    rows = asyncio.run(db.get_recent(10))
    assert rows[0]["content"] == "Fact B"
    assert rows[1]["content"] == "Fact A"


def test_delete_removes_entry(db):
    asyncio.run(db.init())
    vec = np.zeros(1536, dtype=np.float32)
    asyncio.run(db.save("Vergiss mich", vec.tobytes(), "preference", "test"))
    mem_id = asyncio.run(db.get_latest_id())
    assert mem_id is not None
    asyncio.run(db.delete(mem_id))
    assert asyncio.run(db.load_all()) == []


def test_get_latest_id_returns_none_when_empty(db):
    asyncio.run(db.init())
    assert asyncio.run(db.get_latest_id()) is None
