# agents/db.py
import aiosqlite
from datetime import datetime, timedelta
from typing import Optional


class SessionDB:
    def __init__(self, path: str = "/root/.jarvis/sessions.db"):
        self.path = path

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
            """, (project, session_id, datetime.utcnow().isoformat()))
            await db.commit()

    async def get_session(self, project: str, ttl_hours: float = 2.0) -> Optional[str]:
        cutoff = (datetime.utcnow() - timedelta(hours=ttl_hours)).isoformat()
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
