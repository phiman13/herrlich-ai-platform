# Jarvis Memory — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Jarvis silently extracts and recalls facts about Philipp across conversations using vector embeddings.

**Architecture:** After each assistant turn, a background Haiku call extracts 0–3 memorable facts and stores them in SQLite with OpenAI embeddings. Before each user message in personal/work/research intents, the top-5 semantically similar memories are retrieved and injected silently into the system prompt. A new `memory` router intent lets Philipp list or delete memories.

**Tech Stack:** `openai>=1.0` (embeddings: text-embedding-3-small, 1536 dims), `numpy>=1.24` (cosine similarity), `aiosqlite` (already present), `anthropic` (extraction via claude-haiku-4-5-20251001)

---

## File Map

| File | Change |
|---|---|
| `agents/requirements.txt` | Add `openai>=1.0`, `numpy>=1.24` |
| `agents/db.py` | Add `MemoryDB` class |
| `agents/memory_agent.py` | New: `MemoryAgent` + `MEMORY_INTENTS` constant |
| `agents/router.py` | Add `memory` intent to `_SYSTEM_TEMPLATE` + `VALID_INTENTS` |
| `agents/main.py` | Wire retrieval + extraction + memory intent handler |
| `tests/conftest.py` | Add `OPENAI_API_KEY` env var default |
| `tests/test_memory_db.py` | New: MemoryDB CRUD tests |
| `tests/test_memory_agent.py` | New: retrieve, extract, list, delete tests |
| `tests/test_router_memory.py` | New: router classification for memory queries |
| `tests/test_main_memory.py` | New: retrieval injection + extraction wiring |

---

## Task 1: Add Dependencies

**Files:**
- Modify: `agents/requirements.txt`
- Modify: `tests/conftest.py`

- [ ] **Step 1: Add packages to requirements.txt**

Add these two lines at the end of `agents/requirements.txt` (after `apscheduler>=3.10.4`):

```
openai>=1.0
numpy>=1.24
```

- [ ] **Step 2: Add OPENAI_API_KEY to conftest**

In `tests/conftest.py`, inside `pytest_configure()`, after the existing `os.environ.setdefault("TELEGRAM_BOT_TOKEN", ...)` line, add:

```python
    os.environ.setdefault("OPENAI_API_KEY", "test_key_for_tests")
```

- [ ] **Step 3: Install packages**

Run on the VPS after pushing (or locally if `pip` available):

```bash
pip install openai numpy
```

- [ ] **Step 4: Verify import works in tests**

```bash
cd agents && python -c "import openai; import numpy; print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add agents/requirements.txt tests/conftest.py
git commit -m "feat(memory): add openai + numpy deps"
```

---

## Task 2: MemoryDB

**Files:**
- Modify: `agents/db.py`
- Create: `tests/test_memory_db.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_memory_db.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /path/to/repo && pytest tests/test_memory_db.py -v
```

Expected: `ImportError: cannot import name 'MemoryDB' from 'agents.db'`

- [ ] **Step 3: Implement MemoryDB in db.py**

Append to `agents/db.py` (after the `SessionDB` class):

```python


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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_memory_db.py -v
```

Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add agents/db.py tests/test_memory_db.py
git commit -m "feat(memory): add MemoryDB with embedding storage"
```

---

## Task 3: MemoryAgent

**Files:**
- Create: `agents/memory_agent.py`
- Create: `tests/test_memory_agent.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_memory_agent.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_memory_agent.py -v
```

Expected: `ModuleNotFoundError: No module named 'agents.memory_agent'`

- [ ] **Step 3: Create agents/memory_agent.py**

Create `agents/memory_agent.py`:

```python
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
            return "Keine passende Erinnerung gefunden."
        await self.db.delete(best_id)
        return f"✅ Erinnerung gelöscht: _{best_content}_"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_memory_agent.py -v
```

Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add agents/memory_agent.py tests/test_memory_agent.py
git commit -m "feat(memory): implement MemoryAgent with extract/retrieve/list/delete"
```

---

## Task 4: Router — memory intent

**Files:**
- Modify: `agents/router.py`
- Create: `tests/test_router_memory.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_router_memory.py`:

```python
import asyncio
import json
import pytest
from unittest.mock import patch

from agents.router import route_with_llm


def _mock_claude(intent: str, mode: str, query=None):
    params = {"mode": mode}
    if query is not None:
        params["query"] = query
    else:
        params["query"] = None
    payload = json.dumps({
        "intent": intent,
        "confidence": 9,
        "params": params,
        "reasoning": "test",
    })
    from unittest.mock import MagicMock
    mock = MagicMock()
    mock.content = [MagicMock(text=payload)]
    return mock


def test_list_memories_intent():
    with patch("agents.router._call_claude_sync",
               return_value=json.dumps({
                   "intent": "memory",
                   "confidence": 9,
                   "params": {"mode": "list", "query": None},
                   "reasoning": "test",
               })):
        result = asyncio.run(route_with_llm("Was weißt du über mich?"))
    assert result["intent"] == "memory"
    assert result["params"]["mode"] == "list"


def test_delete_memory_intent():
    with patch("agents.router._call_claude_sync",
               return_value=json.dumps({
                   "intent": "memory",
                   "confidence": 9,
                   "params": {"mode": "delete", "query": "Siemens"},
                   "reasoning": "test",
               })):
        result = asyncio.run(route_with_llm("Vergiss was ich über Siemens gesagt habe"))
    assert result["intent"] == "memory"
    assert result["params"]["mode"] == "delete"
    assert result["params"]["query"] == "Siemens"


def test_memory_is_valid_intent():
    with patch("agents.router._call_claude_sync",
               return_value=json.dumps({
                   "intent": "memory",
                   "confidence": 9,
                   "params": {"mode": "list", "query": None},
                   "reasoning": "test",
               })):
        result = asyncio.run(route_with_llm("Erinnerungen zeigen"))
    # Should not fall back to personal (memory is now a valid intent)
    assert result["intent"] == "memory"
    assert result["confidence"] != 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_router_memory.py -v
```

Expected: all 3 fail with `assert result['intent'] == 'memory'` because `"memory"` is not in `VALID_INTENTS` and the router falls back to `_FALLBACK`.

- [ ] **Step 3: Add memory intent to router.py**

In `agents/router.py`, locate `_SYSTEM_TEMPLATE`. After the `"briefing"` intent block (item 9) and before `## Output-Format`, add this new entry:

```
10. "memory" — Jarvis-Erinnerungen abrufen oder löschen.
   Beispiele:
   - "Was weißt du über mich?" → mode=list
   - "Was hast du dir gemerkt?" → mode=list
   - "Zeig mir deine Erinnerungen" → mode=list
   - "Vergiss was ich über Siemens gesagt habe" → mode=delete, query="Siemens"
   - "Vergiss das" → mode=delete, query=null (löscht die neueste Erinnerung)

   Parameter:
   - mode: "list" | "delete"
   - query: string oder null (was gelöscht werden soll; null = neueste Erinnerung)

```

Then update the `"intent"` line in the Output-Format section from:

```
  "intent": "calendar" | "coding" | "research" | "work" | "mail" | "personal" | "news" | "tasks" | "briefing",
```

to:

```
  "intent": "calendar" | "coding" | "research" | "work" | "mail" | "personal" | "news" | "tasks" | "briefing" | "memory",
```

Then in `route_with_llm()`, update the `VALID_INTENTS` check from:

```python
        if parsed["intent"] not in {"calendar", "coding", "research", "work", "mail", "personal", "news", "tasks", "briefing"}:
```

to:

```python
        if parsed["intent"] not in {"calendar", "coding", "research", "work", "mail", "personal", "news", "tasks", "briefing", "memory"}:
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_router_memory.py -v
```

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add agents/router.py tests/test_router_memory.py
git commit -m "feat(memory): add memory intent to router"
```

---

## Task 5: Wire main.py

**Files:**
- Modify: `agents/main.py`
- Create: `tests/test_main_memory.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_main_memory.py`:

```python
import asyncio
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

import agents.main as main_module


@pytest.fixture(autouse=True)
def fresh_memory_agent(tmp_path):
    """Replace global memory_agent with a test instance backed by a temp DB."""
    from agents.db import MemoryDB
    from agents.memory_agent import MemoryAgent
    db = MemoryDB(str(tmp_path / "mem.db"))
    asyncio.run(db.init())
    agent = MemoryAgent(db)
    main_module._memory_agent = agent
    yield agent
    main_module._memory_agent = None


def test_memory_agent_is_none_by_default():
    # Before startup, _memory_agent may be None in a fresh import
    # The fixture sets it — just verify the fixture works
    assert main_module._memory_agent is not None


def test_retrieve_called_for_personal_intent(fresh_memory_agent):
    """retrieve() is called when intent is personal."""
    import numpy as np
    called_with = []

    async def fake_retrieve(query: str):
        called_with.append(query)
        return []

    with patch.object(fresh_memory_agent, "retrieve", side_effect=fake_retrieve):
        with patch("agents.main.route_with_llm", return_value={
            "intent": "personal", "confidence": 8, "params": {}, "reasoning": "test"
        }):
            with patch("agents.main.ask_claude", new_callable=AsyncMock, return_value="ok"):
                update = MagicMock()
                update.update_id = 99991
                update.message.text = "Wie geht's dir?"
                update.message.chat_id = 123
                update.message.reply_text = AsyncMock()
                asyncio.run(main_module.handle_message(update, None))

    assert len(called_with) == 1
    assert called_with[0] == "Wie geht's dir?"


def test_retrieve_not_called_for_calendar_intent(fresh_memory_agent):
    """retrieve() is NOT called for calendar intent."""
    called = []

    async def fake_retrieve(query):
        called.append(query)
        return []

    with patch.object(fresh_memory_agent, "retrieve", side_effect=fake_retrieve):
        with patch("agents.main.route_with_llm", return_value={
            "intent": "calendar", "confidence": 9,
            "params": {"mode": "read", "kind": "today", "start": None, "end": None,
                       "title": None, "calendar_name": None},
            "reasoning": "test",
        }):
            with patch("agents.main.handle_calendar", new_callable=AsyncMock):
                update = MagicMock()
                update.update_id = 99992
                update.message.text = "Was habe ich heute?"
                update.message.chat_id = 123
                update.message.reply_text = AsyncMock()
                asyncio.run(main_module.handle_message(update, None))

    assert called == []


def test_memory_list_intent_handler(fresh_memory_agent):
    """memory intent with mode=list calls list_memories and replies."""
    import numpy as np
    vec = np.zeros(1536, dtype=np.float32)
    asyncio.run(fresh_memory_agent.db.save("Philipp mag Tee", vec.tobytes(), "preference", "t"))

    with patch("agents.main.route_with_llm", return_value={
        "intent": "memory", "confidence": 9,
        "params": {"mode": "list", "query": None},
        "reasoning": "test",
    }):
        with patch("agents.main.Bot") as MockBot:
            mock_bot = MagicMock()
            mock_bot.send_message = AsyncMock()
            MockBot.return_value = mock_bot

            update = MagicMock()
            update.update_id = 99993
            update.message.text = "Was weißt du über mich?"
            update.message.chat_id = 123
            update.message.reply_text = AsyncMock()
            asyncio.run(main_module.handle_message(update, None))

    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "Philipp mag Tee" in reply_text


def test_memory_delete_intent_handler(fresh_memory_agent):
    """memory intent with mode=delete calls delete_memory and replies."""
    import numpy as np
    vec = np.zeros(1536, dtype=np.float32)
    vec[0] = 1.0
    asyncio.run(fresh_memory_agent.db.save("Siemens Pitch", vec.tobytes(), "event", "t"))

    with patch("agents.main.route_with_llm", return_value={
        "intent": "memory", "confidence": 9,
        "params": {"mode": "delete", "query": "Siemens"},
        "reasoning": "test",
    }):
        with patch("agents.memory_agent._embed", return_value=vec):
            update = MagicMock()
            update.update_id = 99994
            update.message.text = "Vergiss Siemens"
            update.message.chat_id = 123
            update.message.reply_text = AsyncMock()
            asyncio.run(main_module.handle_message(update, None))

    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "gelöscht" in reply_text
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_main_memory.py -v
```

Expected: multiple failures — `_memory_agent` attribute missing, no memory intent handler, etc.

- [ ] **Step 3: Wire MemoryDB + MemoryAgent into main.py**

**3a. Add module-level globals** — in `agents/main.py`, after the `_pending_mail_drafts` line, add:

```python
_memory_agent = None  # initialized in startup()
```

**3b. Update startup()** — in the `startup()` function, after `await _ensure_init()`, add:

```python
    global _memory_agent
    from db import MemoryDB
    from memory_agent import MemoryAgent
    _memory_db = MemoryDB()
    await _memory_db.init()
    _memory_agent = MemoryAgent(_memory_db)
    logger.info("MemoryDB initialisiert")
```

**3c. Return answer from ask_claude()** — at the end of `ask_claude()`, change from (implicit `None` return) to add `return answer` as the last line of the function body.

The current function ends with:
```python
    except Exception as e:
        await bot.send_message(chat_id=chat_id, text=f"Fehler: {str(e)}")
```

Add after the entire try/except block:

```python
    return answer
```

Wait — `answer` is scoped inside the `try` block. Restructure to return cleanly:

Replace the entire `ask_claude` function with:

```python
async def ask_claude(chat_id, system, user, model="claude-haiku-4-5-20251001", use_web_search=False) -> str:
    bot = Bot(token=TELEGRAM_TOKEN)
    answer = ""
    try:
        kwargs = {
            "model": model,
            "max_tokens": 2048,
            "system": system,
            "messages": [{"role": "user", "content": user}]
        }
        if use_web_search:
            kwargs["tools"] = [{"type": "web_search_20250305", "name": "web_search"}]

        response = claude.messages.create(**kwargs)

        for block in response.content:
            if hasattr(block, "text"):
                answer += block.text

        if not answer:
            answer = "Keine Antwort erhalten."
        if len(answer) > 4000:
            answer = answer[:4000] + "\n[...]"
        await bot.send_message(chat_id=chat_id, text=answer)
    except Exception as e:
        answer = f"Fehler: {str(e)}"
        await bot.send_message(chat_id=chat_id, text=answer)
    return answer
```

**3d. Add import for MEMORY_INTENTS** — at the top of `handle_message()` (or as a module-level import), the constant is defined in `memory_agent.py`. Add to the top of `main.py` in the import section (alongside the other try/except imports pattern — but since memory_agent imports openai which requires the API key, use a lazy import inside startup instead of module-level):

Actually, the constant `MEMORY_INTENTS` is just a Python set and doesn't trigger the OpenAI import. Add a module-level constant directly in `main.py` to avoid the import dependency at module load time:

After `_memory_agent = None`, add:

```python
_MEMORY_INTENTS = {"personal", "work", "research"}
```

**3e. Add retrieval before routing** — in `handle_message()`, after the confidence check (the `if confidence < 5: return` block), add retrieval:

```python
    memory_context = ""
    if _memory_agent and intent in _MEMORY_INTENTS:
        try:
            memories = await _memory_agent.retrieve(text)
            if memories:
                bullet_list = "\n".join(f"• {m}" for m in memories)
                memory_context = (
                    f"Kontext aus früheren Gesprächen mit Philipp:\n{bullet_list}\n\n"
                )
        except Exception as e:
            logger.warning("Memory retrieval failed: %s", e)
```

**3f. Inject memory_context into system prompts** — for the `research` intent, replace the `ask_claude` call:

From:
```python
        await ask_claude(
            chat_id=chat_id,
            system="Du bist Jarvis, KI-Assistent fuer Philipp. Recherchiere im Internet und antworte praezise auf Deutsch mit Quellenangaben.",
            user=text,
            model="claude-sonnet-4-6",
            use_web_search=True
        )
```

To:
```python
        answer = await ask_claude(
            chat_id=chat_id,
            system=memory_context + "Du bist Jarvis, KI-Assistent fuer Philipp. Recherchiere im Internet und antworte praezise auf Deutsch mit Quellenangaben.",
            user=text,
            model="claude-sonnet-4-6",
            use_web_search=True
        )
        if _memory_agent:
            asyncio.create_task(_memory_agent.extract(text, answer, source="research"))
```

For the `work` intent, replace the `ask_claude` call similarly:

```python
        answer = await ask_claude(
            chat_id=chat_id,
            system=memory_context + "Du bist Jarvis, KI-Assistent fuer Philipp (Projektmanager, Strategieberatung). Antworte praezise und strukturiert auf Deutsch.",
            user=text,
            model="claude-sonnet-4-6",
            use_web_search=True
        )
        if _memory_agent:
            asyncio.create_task(_memory_agent.extract(text, answer, source="work"))
```

For the `personal` intent (the `else` branch), replace:

```python
        await ask_claude(
            chat_id=chat_id,
            system=personal_system,
            user=text,
            model="claude-haiku-4-5-20251001"
        )
```

With:

```python
        answer = await ask_claude(
            chat_id=chat_id,
            system=memory_context + personal_system,
            user=text,
            model="claude-haiku-4-5-20251001"
        )
        if _memory_agent:
            asyncio.create_task(_memory_agent.extract(text, answer, source="personal"))
```

**3g. Add memory intent handler** — in `handle_message()`, after the `briefing` intent block (`elif intent == "briefing":`), and before the final `else:` block, add:

```python
    elif intent == "memory":
        mode = params.get("mode", "list")
        query = params.get("query")
        if not _memory_agent:
            await update.message.reply_text("Memory-System nicht initialisiert.")
            return
        if mode == "delete":
            msg = await _memory_agent.delete_memory(query)
        else:
            msg = await _memory_agent.list_memories()
        await update.message.reply_text(msg, parse_mode="Markdown")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_main_memory.py -v
```

Expected: 5 passed

- [ ] **Step 5: Run the full test suite**

```bash
pytest tests/ -v
```

Expected: all tests pass (existing tests + new memory tests)

- [ ] **Step 6: Commit**

```bash
git add agents/main.py tests/test_main_memory.py
git commit -m "feat(memory): wire retrieval, extraction, and memory intent into main"
```

---

## Final Integration Check

After all tasks are merged and deployed:

- [ ] Set `OPENAI_API_KEY` on VPS:
  ```bash
  echo "OPENAI_API_KEY=sk-..." >> /etc/jarvis.env
  systemctl restart jarvis
  ```
- [ ] Test listing: send "Was weißt du über mich?" — Jarvis should respond with memory list (or "noch keine Erinnerungen")
- [ ] Have a personal conversation, then ask again — new facts should appear
- [ ] Test delete: "Vergiss den letzten Fakt" — Jarvis confirms deletion
- [ ] Test retrieval injection: tell Jarvis a preference ("Ich mag kurze Antworten"), then ask a general question — answer should respect the stated preference

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Covered by |
|---|---|
| SQLite `memories` table (id, content, embedding, category, created_at, source) | Task 2 — MemoryDB.init() |
| OpenAI text-embedding-3-small, 1536 dims, float32 bytes | Task 3 — `_embed()` |
| Retrieval: embed query, cosine ≥ 0.65, top-5 | Task 3 — `retrieve()` |
| Injection scope: personal, work, research only | Task 5 — `_MEMORY_INTENTS` check |
| Context prefix format | Task 5 — `memory_context` string |
| Extraction: async background, Haiku, JSON array | Task 3 — `extract()` + Task 5 — `create_task()` |
| `memory` router intent, mode=list/delete | Task 4 — router.py |
| list: 20 most recent memories | Task 3 — `list_memories()` |
| delete by query (similarity ≥ 0.65) or null = latest | Task 3 — `delete_memory()` |
| `OPENAI_API_KEY` env var | Task 1 + Final Integration Check |

All spec requirements covered. No placeholders.
