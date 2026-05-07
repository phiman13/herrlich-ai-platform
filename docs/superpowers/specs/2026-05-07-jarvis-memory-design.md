# Jarvis Memory — Design Spec

**Date:** 2026-05-07
**Status:** Approved

## Goal

Jarvis remembers facts and events across conversations and uses them silently to give better answers — without the user having to repeat context.

## What Gets Stored

After each conversation turn, a lightweight Claude Haiku call analyzes the exchange and extracts 0–3 memorable facts. A fact is stored only if it is genuinely useful to recall in future conversations. Categories:

- **Preferences** — `"Philipp mag kurze, direkte Antworten ohne Small-Talk"`
- **Events** — `"Philipp hat am 12.05. einen Pitch bei Siemens zum Thema ESG"`
- **People/Relationships** — `"Philipps Therapeut heißt Dr. Müller, Termin jeden Donnerstag"`
- **Projects/Context** — `"recipe-app ist eine PWA + React Native App für Philipps eigene Rezepte"`
- **Stated intentions** — `"Philipp plant, immo-radar auf Tutzing PLZ 82327 zu beschränken"`

Trivial turns (calendar lookups, task reads, small-talk with no new information) produce no memories.

## Storage

New SQLite table in `/root/.jarvis/memories.db` (separate file from sessions.db for clarity):

```sql
CREATE TABLE memories (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    content  TEXT NOT NULL,
    embedding BLOB NOT NULL,          -- numpy float32 array, 1536 dims, stored as bytes
    category TEXT NOT NULL,           -- preference | event | person | project | intention
    created_at TEXT NOT NULL,         -- ISO-8601
    source   TEXT                     -- brief label of originating conversation turn
);
```

Embeddings: OpenAI `text-embedding-3-small` (1536 dims, ~$0.02/1M tokens). For expected usage (hundreds of memories), total cost is under $1/month.

New env var required on VPS: `OPENAI_API_KEY`.

## Retrieval

Before processing each user message:

1. Embed the user's message via OpenAI `text-embedding-3-small`
2. Load all memory embeddings from SQLite (small dataset — fits in memory)
3. Compute cosine similarity between query embedding and all stored embeddings
4. Return top-5 memories with similarity ≥ 0.65
5. Inject as a short context block into the system prompt for the active handler

**Injection scope:** Only `personal`, `work`, `research` intents — where open-ended context helps. NOT injected into `calendar`, `tasks`, `mail`, `coding`, `news`, `briefing` — deterministic handlers where memory adds noise.

Injected prefix (invisible to user, prepended to system prompt):

```
Kontext aus früheren Gesprächen mit Philipp:
• Philipp mag kurze, direkte Antworten ohne Small-Talk
• Philipp hat am 12.05. einen Pitch bei Siemens zum Thema ESG
```

## Extraction

After each assistant response (async, non-blocking — does not add latency to the reply):

1. Call Claude Haiku with the user message + assistant response
2. Prompt: extract 0–3 memorable facts as a JSON array `[{"content": "...", "category": "..."}]`
3. If array is empty, do nothing
4. For each extracted fact: embed via OpenAI, store in SQLite

Extraction runs as a background `asyncio.create_task()` — user receives the reply immediately, memory is saved in the background.

## Memory Management (via Router)

New router intent: `memory`

```json
{
  "intent": "memory",
  "params": {
    "mode": "list" | "delete",
    "query": "string | null"
  }
}
```

Router examples:
- `"Was weißt du über mich?"` → mode=list
- `"Was hast du dir gemerkt?"` → mode=list
- `"Zeig mir deine Erinnerungen"` → mode=list
- `"Vergiss was ich über Siemens gesagt habe"` → mode=delete, query="Siemens"
- `"Vergiss das"` → mode=delete, query=null (deletes most recent memory)

**list:** Returns the 20 most recent memories formatted as a readable list.

**delete:** Embeds the query, finds the most similar memory (similarity ≥ 0.65), deletes it. If query is null, deletes the most recently created memory. Confirms deletion to user.

## File Map

| File | Change |
|---|---|
| `agents/memory_agent.py` | New: `MemoryAgent` class with `extract()`, `retrieve()`, `list_memories()`, `delete_memory()` |
| `agents/db.py` | Add `MemoryDB` class (separate from `SessionDB`) with `init()`, `save()`, `load_all_embeddings()`, `delete()` |
| `agents/router.py` | Add `memory` to `_SYSTEM_TEMPLATE` and `VALID_INTENTS` |
| `agents/main.py` | Wire retrieval before routing + extraction after response + memory intent handler |
| `requirements.txt` | Add `openai`, `numpy` |

## Dependencies

- `openai>=1.0` — embedding API
- `numpy>=1.24` — cosine similarity computation
- `OPENAI_API_KEY` env var on VPS

## Out of Scope

- Memory decay / automatic expiry (memories persist until deleted)
- Cross-session summarization
- Memory editing (only list + delete)
- Injection into deterministic handlers (calendar, tasks, mail, coding, news, briefing)
