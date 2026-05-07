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
CURRENT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
MARKER_FILE = "/root/.jarvis/.embedding_model"

_embedding_model = None


def _get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        from fastembed import TextEmbedding
        _embedding_model = TextEmbedding(CURRENT_MODEL)
    return _embedding_model


_EXTRACT_SYSTEM = (
    "Analysiere das folgende Gespräch und extrahiere 0–3 merkwürdige Fakten über Philipp. "
    "Ein Fakt ist nur dann merkenswert, wenn er in zukünftigen Gesprächen nützlich sein könnte. "
    "Kategorien: preference | event | person | project | intention\n\n"
    'Antworte AUSSCHLIESSLICH mit einem JSON-Array: [{"content": "...", "category": "..."}]\n'
    "Leeres Array [] wenn keine merkwürdigen Fakten vorhanden. KEIN erklärender Text."
)

_VALID_CATEGORIES = {"preference", "event", "person", "project", "intention"}

_CATEGORY_EMOJI = {
    "preference": "⭐",
    "event": "📅",
    "person": "👤",
    "project": "🛠️",
    "intention": "🎯",
}


def _embed(text: str) -> np.ndarray:
    model = _get_embedding_model()
    return np.array(next(model.embed([text])), dtype=np.float32)


def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom < 1e-10:
        return 0.0
    return float(np.dot(a, b) / denom)


class MemoryAgent:
    def __init__(self, db: MemoryDB):
        self.db = db

    async def retrieve(self) -> list[str]:
        rows = await self.db.load_all()
        return [row["content"] for row in rows]

    async def migrate_embeddings(self) -> None:
        try:
            with open(MARKER_FILE) as f:
                if f.read().strip() == CURRENT_MODEL:
                    return
        except FileNotFoundError:
            pass
        rows = await self.db.load_all()
        for row in rows:
            new_embedding = await asyncio.to_thread(_embed, row["content"])
            await self.db.update_embedding(row["id"], new_embedding.tobytes())
        with open(MARKER_FILE, "w") as f:
            f.write(CURRENT_MODEL + "\n")
        logger.info("Memory embeddings migrated to %s (%d memories)", CURRENT_MODEL, len(rows))

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
            raw = ""
            for block in resp.content:
                if hasattr(block, "text"):
                    raw += block.text
            raw = raw.strip()
            if not raw:
                return
            # Haiku sometimes wraps JSON in preamble text — extract the array
            if not raw.startswith("["):
                import re
                m = re.search(r"\[.*\]", raw, re.DOTALL)
                if not m:
                    logger.debug("Memory extraction: no JSON array in response: %r", raw[:120])
                    return
                raw = m.group(0)
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
                existing = await self.db.load_all()
                duplicate = any(
                    _cosine_sim(embedding, np.frombuffer(r["embedding"], dtype=np.float32)) >= 0.90
                    for r in existing
                )
                if duplicate:
                    logger.debug("Memory skipped (duplicate): %s", content)
                    continue
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
            emoji = _CATEGORY_EMOJI.get(r["category"], "•")
            lines.append(f"{emoji} {r['content']}")
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
