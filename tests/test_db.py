# tests/test_db.py
import asyncio
import os
import pytest
from agents.db import SessionDB

@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    return SessionDB(db_path)

def test_upsert_and_get(db):
    asyncio.run(db.init())
    asyncio.run(db.upsert_session("recipe-app", "sess_abc123"))
    result = asyncio.run(db.get_session("recipe-app", ttl_hours=2))
    assert result == "sess_abc123"

def test_expired_session_returns_none(db):
    asyncio.run(db.init())
    asyncio.run(db.upsert_session("recipe-app", "sess_old"))
    result = asyncio.run(db.get_session("recipe-app", ttl_hours=0))
    assert result is None

def test_unknown_project_returns_none(db):
    asyncio.run(db.init())
    result = asyncio.run(db.get_session("nonexistent", ttl_hours=2))
    assert result is None

def test_upsert_overwrites(db):
    asyncio.run(db.init())
    asyncio.run(db.upsert_session("recipe-app", "sess_old"))
    asyncio.run(db.upsert_session("recipe-app", "sess_new"))
    result = asyncio.run(db.get_session("recipe-app", ttl_hours=2))
    assert result == "sess_new"

def test_db_creates_parent_directory(tmp_path):
    nested_path = str(tmp_path / "deep" / "nested" / "dirs" / "test.db")
    db = SessionDB(nested_path)
    asyncio.run(db.init())
    assert os.path.exists(nested_path)
