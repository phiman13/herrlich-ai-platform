import asyncio


def test_save_and_get_recent(tmp_path):
    from agents.db import ConversationDB
    db = ConversationDB(str(tmp_path / "conv.db"))
    asyncio.run(db.init())
    asyncio.run(db.save(123, "user", "Hallo"))
    asyncio.run(db.save(123, "assistant", "Hallo zurück"))

    rows = asyncio.run(db.get_recent(123, n=20))
    assert len(rows) == 2
    assert rows[0] == {"role": "user", "content": "Hallo"}
    assert rows[1] == {"role": "assistant", "content": "Hallo zurück"}


def test_get_recent_respects_chat_id(tmp_path):
    from agents.db import ConversationDB
    db = ConversationDB(str(tmp_path / "conv.db"))
    asyncio.run(db.init())
    asyncio.run(db.save(111, "user", "Für chat 111"))
    asyncio.run(db.save(222, "user", "Für chat 222"))

    rows = asyncio.run(db.get_recent(111, n=20))
    assert len(rows) == 1
    assert rows[0]["content"] == "Für chat 111"


def test_get_recent_limits_to_n(tmp_path):
    from agents.db import ConversationDB
    db = ConversationDB(str(tmp_path / "conv.db"))
    asyncio.run(db.init())
    for i in range(25):
        asyncio.run(db.save(123, "user", f"Nachricht {i}"))

    rows = asyncio.run(db.get_recent(123, n=20))
    assert len(rows) == 20
    assert rows[0]["content"] == "Nachricht 5"   # älteste der letzten 20
    assert rows[-1]["content"] == "Nachricht 24"  # neueste


def test_get_recent_returns_chronological_order(tmp_path):
    from agents.db import ConversationDB
    db = ConversationDB(str(tmp_path / "conv.db"))
    asyncio.run(db.init())
    asyncio.run(db.save(123, "user", "erste"))
    asyncio.run(db.save(123, "assistant", "zweite"))
    asyncio.run(db.save(123, "user", "dritte"))

    rows = asyncio.run(db.get_recent(123, n=20))
    assert [r["content"] for r in rows] == ["erste", "zweite", "dritte"]
