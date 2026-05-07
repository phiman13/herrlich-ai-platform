# agents/db.py
import aiosqlite
import os
from datetime import datetime, timedelta, timezone
from typing import Optional


class SessionDB:
    def __init__(self, path: str = "/root/.jarvis/sessions.db"):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)

    async def init(self):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS coding_sessions (
                    project TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    last_used TIMESTAMP NOT NULL
                )
            """)
            await db.commit()

    async def upsert_session(self, project: str, session_id: str):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
                INSERT INTO coding_sessions (project, session_id, last_used)
                VALUES (?, ?, ?)
                ON CONFLICT(project) DO UPDATE SET
                    session_id = excluded.session_id,
                    last_used = excluded.last_used
            """, (project, session_id, datetime.now(timezone.utc).isoformat()))
            await db.commit()

    async def get_session(self, project: str, ttl_hours: float = 2.0) -> Optional[str]:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=ttl_hours)).isoformat()
        async with aiosqlite.connect(self.path) as db:
            async with db.execute("""
                SELECT session_id FROM coding_sessions
                WHERE project = ? AND last_used > ?
            """, (project, cutoff)) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else None

    async def clear_session(self, project: str):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM coding_sessions WHERE project = ?", (project,))
            await db.commit()


class MemoryDB:
    def __init__(self, path: str = "/root/.jarvis/memories.db"):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)

    async def init(self):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    content   TEXT NOT NULL,
                    embedding BLOB NOT NULL,
                    category  TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    source    TEXT
                )
            """)
            await db.commit()

    async def save(self, content: str, embedding: bytes, category: str, source: str = ""):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO memories (content, embedding, category, created_at, source) "
                "VALUES (?, ?, ?, ?, ?)",
                (content, embedding, category,
                 datetime.now(timezone.utc).isoformat(), source),
            )
            await db.commit()

    async def load_all(self) -> list[dict]:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT id, content, embedding, category FROM memories"
            ) as cursor:
                rows = await cursor.fetchall()
        return [
            {"id": r[0], "content": r[1], "embedding": r[2], "category": r[3]}
            for r in rows
        ]

    async def get_recent(self, n: int = 20) -> list[dict]:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT id, content, category, created_at FROM memories "
                "ORDER BY id DESC LIMIT ?",
                (n,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [
            {"id": r[0], "content": r[1], "category": r[2], "created_at": r[3]}
            for r in rows
        ]

    async def delete(self, memory_id: int):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            await db.commit()

    async def get_latest_id(self) -> int | None:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT id FROM memories ORDER BY id DESC LIMIT 1"
            ) as cursor:
                row = await cursor.fetchone()
        return row[0] if row else None


class ConversationDB:
    def __init__(self, path: str = "/root/.jarvis/conversations.db"):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)

    async def init(self):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS chat_history (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id    INTEGER NOT NULL,
                    role       TEXT NOT NULL,
                    content    TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_chat_history_chat_id "
                "ON chat_history(chat_id, id)"
            )
            await db.commit()

    async def save(self, chat_id: int, role: str, content: str):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO chat_history (chat_id, role, content, created_at) "
                "VALUES (?, ?, ?, ?)",
                (chat_id, role, content, datetime.now(timezone.utc).isoformat()),
            )
            await db.commit()

    async def get_recent(self, chat_id: int, n: int = 20) -> list[dict]:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT role, content FROM ("
                "  SELECT id, role, content FROM chat_history"
                "  WHERE chat_id = ?"
                "  ORDER BY id DESC LIMIT ?"
                ") ORDER BY id ASC",
                (chat_id, n),
            ) as cursor:
                rows = await cursor.fetchall()
        return [{"role": r[0], "content": r[1]} for r in rows]
