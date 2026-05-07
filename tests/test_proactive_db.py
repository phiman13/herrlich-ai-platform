import asyncio
from datetime import datetime, timedelta, timezone


def test_reported_mails_deduplication(tmp_path):
    import sys

    sys.path.insert(0, "agents")
    from db import ProactiveDB

    db = ProactiveDB(str(tmp_path / "proactive.db"))
    asyncio.run(db.init())

    asyncio.run(db.mark_mails_reported(["id1", "id2"]))
    reported = asyncio.run(db.get_reported_mail_ids())

    assert "id1" in reported
    assert "id2" in reported
    assert "id3" not in reported


def test_reported_mails_ignores_duplicates(tmp_path):
    import sys

    sys.path.insert(0, "agents")
    from db import ProactiveDB

    db = ProactiveDB(str(tmp_path / "proactive.db"))
    asyncio.run(db.init())
    asyncio.run(db.mark_mails_reported(["id1"]))
    asyncio.run(db.mark_mails_reported(["id1"]))  # second call — must not raise
    reported = asyncio.run(db.get_reported_mail_ids())
    assert reported == {"id1"}


def test_reminded_tasks_tracks_last_reminded(tmp_path):
    import sys

    sys.path.insert(0, "agents")
    from db import ProactiveDB

    db = ProactiveDB(str(tmp_path / "proactive.db"))
    asyncio.run(db.init())

    assert asyncio.run(db.get_last_reminded("task_abc")) is None
    asyncio.run(db.mark_tasks_reminded(["task_abc"]))
    last = asyncio.run(db.get_last_reminded("task_abc"))
    assert last is not None
    assert (datetime.now(timezone.utc) - last).total_seconds() < 5


def test_memory_load_since(tmp_path):
    import sys

    sys.path.insert(0, "agents")
    from db import MemoryDB

    db = MemoryDB(str(tmp_path / "memories.db"))
    asyncio.run(db.init())

    # Insert one old memory (3 days ago) and one fresh
    old_ts = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    fresh_ts = datetime.now(timezone.utc).isoformat()

    async def insert_direct():
        import aiosqlite

        async with aiosqlite.connect(db.path) as conn:
            await conn.execute(
                "INSERT INTO memories (content, embedding, category, created_at, source) VALUES (?, ?, ?, ?, ?)",
                ("old memory", b"", "preference", old_ts, "test"),
            )
            await conn.execute(
                "INSERT INTO memories (content, embedding, category, created_at, source) VALUES (?, ?, ?, ?, ?)",
                ("fresh memory", b"", "preference", fresh_ts, "test"),
            )
            await conn.commit()

    asyncio.run(insert_direct())
    rows = asyncio.run(db.load_since(2))  # last 2 days only
    contents = [r["content"] for r in rows]
    assert "fresh memory" in contents
    assert "old memory" not in contents
