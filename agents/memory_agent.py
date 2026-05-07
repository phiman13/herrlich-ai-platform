import asyncio
import json
import logging

import numpy as np

import anthropic

try:
    from db import MemoryDB
except ImportError:
    from agents.db import MemoryDB

logger = logging.getLogger("jarvis.memory")

MEMORY_INTENTS = {"personal", "work", "research"}

_claude = anthropic.Anthropic()
_openai_client = None


def _get_openai():
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI
        _openai_client = OpenAI()
    return _openai_client


_EXTRACT_SYSTEM = (
    "Analysiere das folgende Gespräch und extrahiere 0–3 merkwürdige Fakten über Philipp. "
    "Ein Fakt ist nur dann merkenswert, wenn er in zukünftigen Gesprächen nützlich sein könnte. "
    "Kategorien: preference | event | person | project | intention\n\n"
    'Antworte AUSSCHLIESSLICH mit einem JSON-Array: [{"content": "...", "category": "..."}]\n'
    "Leeres Array [] wenn keine merkwürdigen Fakten vorhanden. KEIN erklärender Text."
)

_VALID_CATEGORIES = {"preference", "event", "person", "project", "intention"}


def _embed(text: str) -> np.ndarray:
    resp = _get_openai().embeddings.create(model="text-embedding-3-small", input=text)
    return np.array(resp.data[0].embedding, dtype=np.float32)


def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom < 1e-10:
        return 0.0
    return float(np.dot(a, b) / denom)


class MemoryAgent:
    def __init__(self, db: MemoryDB):
        self.db = db

    async def retrieve(self, query: str) -> list[str]:
        rows = await self.db.load_all()
        if not rows:
            return []
        query_vec = await asyncio.to_thread(_embed, query)
        scored: list[tuple[float, str]] = []
        for row in rows:
            mem_vec = np.frombuffer(row["embedding"], dtype=np.float32)
            sim = _cosine_sim(query_vec, mem_vec)
            if sim >= 0.65:
                scored.append((sim, row["content"]))
        scored.sort(reverse=True)
        return [content for _, content in scored[:5]]

    async def extract(self, user_msg: str, assistant_msg: str, source: str = ""):
        conversation = f"Philipp: {user_msg}\n\nJarvis: {assistant_msg}"
        try:
            resp = await asyncio.to_thread(
                _claude.messages.create,
                model="claude-haiku-4-5-20251001",
                max_tokens=300,
                temperature=0,
                system=_EXTRACT_SYSTEM,
                messages=[{"role": "user", "content": conversation}],
            )
            raw = resp.content[0].text.strip()
            facts = json.loads(raw)
            if not isinstance(facts, list):
                return
            for fact in facts[:3]:
                if not isinstance(fact, dict):
                    continue
                content = fact.get("content", "").strip()
                category = fact.get("category", "preference")
                if not content:
                    continue
                if category not in _VALID_CATEGORIES:
                    category = "preference"
                embedding = await asyncio.to_thread(_embed, content)
                await self.db.save(content, embedding.tobytes(), category, source)
                logger.info("Memory saved: [%s] %s", category, content)
        except Exception as e:
            logger.warning("Memory extraction failed: %s", e)

    async def list_memories(self) -> str:
        rows = await self.db.get_recent(20)
        if not rows:
            return "Ich habe noch keine Erinnerungen gespeichert."
        lines = ["\U0001f9e0 *Meine Erinnerungen:*\n"]
        for r in rows:
            lines.append(f"• [{r['category']}] {r['content']}")
        return "\n".join(lines)

    async def delete_memory(self, query: str | None) -> str:
        if query is None:
            mem_id = await self.db.get_latest_id()
            if mem_id is None:
                return "Keine Erinnerungen vorhanden."
            await self.db.delete(mem_id)
            return "✅ Letzte Erinnerung gelöscht."

        rows = await self.db.load_all()
        if not rows:
            return "Keine Erinnerungen vorhanden."
        query_vec = await asyncio.to_thread(_embed, query)
        best_sim, best_id, best_content = 0.0, None, ""
        for row in rows:
            mem_vec = np.frombuffer(row["embedding"], dtype=np.float32)
            sim = _cosine_sim(query_vec, mem_vec)
            if sim > best_sim:
                best_sim, best_id, best_content = sim, row["id"], row["content"]
        if best_id is None or best_sim < 0.65:
            return "Passende Erinnerung nicht gefunden."
        await self.db.delete(best_id)
        return f"✅ Erinnerung gelöscht: _{best_content}_"
