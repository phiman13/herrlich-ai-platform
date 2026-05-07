# Jarvis Persistent User Profile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Jarvis kennt Philipp dauerhaft — ein auto-gepflegtes Markdown-Profil wird immer in jeden LLM-Call injiziert, das Embedding-Modell wird auf Multilingual-E5 umgestellt, und alle Memories werden immer (statt nur Top-k) injiziert.

**Architecture:** `ProfileAgent` in neuem `agents/profile_agent.py` verwaltet `/root/.jarvis/user_profile.md` (load sync, update async via Haiku). `MemoryAgent.retrieve()` gibt alle Memories zurück. `MemoryAgent.migrate_embeddings()` re-embedded bestehende Memories beim Start. `_process_text` in `main.py` injiziert Profil + alle Memories + History in dieser Reihenfolge.

**Tech Stack:** aiosqlite (vorhanden), anthropic Haiku (vorhanden), fastembed `intfloat/multilingual-e5-small` (Drop-in für vorhandenes fastembed)

---

## File Map

| File | Änderung |
|---|---|
| `agents/profile_agent.py` | Neu: `ProfileAgent` (load, update) |
| `agents/memory_agent.py` | Modell → multilingual-e5-small; `retrieve()` ohne Query-Param; `migrate_embeddings()` |
| `agents/db.py` | `MemoryDB.update_embedding(id, bytes)` hinzufügen |
| `agents/main.py` | `_profile_agent` global; neuer Injection-Block in `_process_text`; Update-Trigger; `startup()` erweitern |
| `tests/test_profile_agent.py` | Neu: 4 Tests |
| `tests/test_memory_agent.py` | Neu: 3 Tests |
| `tests/test_chat_quality_main.py` | 1 neuen Integration-Test anhängen |

---

### Task 1: ProfileAgent

**Files:**
- Create: `agents/profile_agent.py`
- Test: `tests/test_profile_agent.py`

- [ ] **Step 1: Failing tests schreiben**

Erstelle `tests/test_profile_agent.py`:

```python
import asyncio
from unittest.mock import MagicMock, patch


def test_load_creates_default_profile(tmp_path):
    from agents.profile_agent import ProfileAgent
    agent = ProfileAgent(str(tmp_path / "profile.md"))
    content = agent.load()
    assert "# Philipp" in content
    assert "Beruf & Rolle" in content
    assert (tmp_path / "profile.md").exists()


def test_load_returns_existing_profile(tmp_path):
    profile_path = tmp_path / "profile.md"
    profile_path.write_text("# Mein Profil\n## Beruf\nEntwickler\n")
    from agents.profile_agent import ProfileAgent
    agent = ProfileAgent(str(profile_path))
    content = agent.load()
    assert content == "# Mein Profil\n## Beruf\nEntwickler\n"


def test_update_writes_when_haiku_returns_content(tmp_path):
    from agents.profile_agent import ProfileAgent
    agent = ProfileAgent(str(tmp_path / "profile.md"))
    agent.load()  # create default

    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text="# Philipp — Benutzerprofil\n## Beruf & Rolle\nEntwickler\n")]

    with patch("agents.profile_agent._claude") as mock_claude:
        mock_claude.messages.create.return_value = mock_resp
        asyncio.run(agent.update("Philipp: Ich bin Entwickler.\nJarvis: Super!"))

    updated = (tmp_path / "profile.md").read_text()
    assert "Entwickler" in updated


def test_update_skips_when_haiku_returns_empty(tmp_path):
    from agents.profile_agent import ProfileAgent
    agent = ProfileAgent(str(tmp_path / "profile.md"))
    original = agent.load()

    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text="")]

    with patch("agents.profile_agent._claude") as mock_claude:
        mock_claude.messages.create.return_value = mock_resp
        asyncio.run(agent.update("Philipp: Wie ist das Wetter?\nJarvis: Gut."))

    unchanged = (tmp_path / "profile.md").read_text()
    assert unchanged == original
```

- [ ] **Step 2: Tests laufen lassen — müssen FAIL**

```bash
/Users/philippherrlich/Documents/04_Sonstiges/01_Coding/herrlich-ai-platform/.worktrees/plan3-smart-routing/.venv/bin/pytest tests/test_profile_agent.py -v
```

Erwartete Ausgabe: `ImportError: No module named 'agents.profile_agent'`

- [ ] **Step 3: `agents/profile_agent.py` implementieren**

Erstelle `agents/profile_agent.py`:

```python
import asyncio
import logging
import os

import anthropic

logger = logging.getLogger("jarvis.profile")

PROFILE_PATH = "/root/.jarvis/user_profile.md"

_DEFAULT_PROFILE = """\
# Philipp — Benutzerprofil

## Beruf & Rolle
*Noch keine Informationen*

## Fähigkeiten & Werkzeuge
*Noch keine Informationen*

## Projekte
*Noch keine Informationen*

## Interessen & Hobbys
*Noch keine Informationen*

## Kommunikationsstil
*Noch keine Informationen*

## Laufende Ziele
*Noch keine Informationen*
"""

_UPDATE_SYSTEM = (
    "Du pflegst das Benutzerprofil von Philipp für seinen persönlichen KI-Assistenten Jarvis.\n"
    "Dir wird ein Gespräch und das aktuelle Profil gezeigt.\n"
    "Entscheide: Enthält das Gespräch neue, relevante Informationen über Philipp "
    "(Beruf, Skills, Projekte, Interessen, Ziele, Kommunikationsstil)?\n"
    "Wenn JA: Gib das vollständig aktualisierte Profil zurück (exakt gleiche Markdown-Struktur).\n"
    "Wenn NEIN: Gib einen leeren String zurück.\n"
    "WICHTIG: Nur faktische Informationen über Philipp aufnehmen. "
    "Kein erklärender Text außerhalb des Profils."
)

_claude = anthropic.Anthropic()


class ProfileAgent:
    def __init__(self, path: str = PROFILE_PATH):
        self.path = path
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)

    def load(self) -> str:
        if not os.path.exists(self.path):
            with open(self.path, "w", encoding="utf-8") as f:
                f.write(_DEFAULT_PROFILE)
        with open(self.path, encoding="utf-8") as f:
            return f.read()

    async def update(self, conversation: str) -> None:
        current = self.load()
        prompt = f"Aktuelles Profil:\n{current}\n\nGespräch:\n{conversation}"
        try:
            resp = await asyncio.to_thread(
                _claude.messages.create,
                model="claude-haiku-4-5-20251001",
                max_tokens=1000,
                temperature=0,
                system=_UPDATE_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            updated = ""
            for block in resp.content:
                if hasattr(block, "text"):
                    updated += block.text
            updated = updated.strip()
            if updated and updated != current.strip():
                with open(self.path, "w", encoding="utf-8") as f:
                    f.write(updated + "\n")
                logger.info("User profile updated")
        except Exception as e:
            logger.warning("Profile update failed: %s", e)
```

- [ ] **Step 4: Tests laufen lassen — müssen PASS**

```bash
/Users/philippherrlich/Documents/04_Sonstiges/01_Coding/herrlich-ai-platform/.worktrees/plan3-smart-routing/.venv/bin/pytest tests/test_profile_agent.py -v
```

Erwartete Ausgabe: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add agents/profile_agent.py tests/test_profile_agent.py
git commit -m "feat(memory): ProfileAgent — persistentes Benutzerprofil"
```

---

### Task 2: Memory System Upgrade

**Files:**
- Modify: `agents/db.py`
- Modify: `agents/memory_agent.py`
- Test: `tests/test_memory_agent.py`

- [ ] **Step 1: Failing tests schreiben**

Erstelle `tests/test_memory_agent.py`:

```python
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import numpy as np


def test_retrieve_returns_all_memories():
    from agents.memory_agent import MemoryAgent

    mock_db = MagicMock()
    mock_db.load_all = AsyncMock(return_value=[
        {"id": 1, "content": "Philipp mag Golf", "embedding": b"", "category": "preference"},
        {"id": 2, "content": "Philipp ist Berater", "embedding": b"", "category": "person"},
        {"id": 3, "content": "Philipp lernt Python", "embedding": b"", "category": "preference"},
    ])

    agent = MemoryAgent(mock_db)
    result = asyncio.run(agent.retrieve())

    assert len(result) == 3
    assert "Philipp mag Golf" in result
    assert "Philipp ist Berater" in result
    assert "Philipp lernt Python" in result


def test_migrate_embeddings_updates_all_rows(tmp_path):
    from agents.memory_agent import MemoryAgent, CURRENT_MODEL

    mock_db = MagicMock()
    mock_db.load_all = AsyncMock(return_value=[
        {"id": 1, "content": "Philipp mag Golf", "embedding": b"\x00" * 4, "category": "preference"},
        {"id": 2, "content": "Philipp ist Berater", "embedding": b"\x00" * 4, "category": "person"},
    ])
    mock_db.update_embedding = AsyncMock()

    fake_vec = np.ones(384, dtype=np.float32)
    marker_path = str(tmp_path / ".embedding_model")

    with patch("agents.memory_agent._embed", return_value=fake_vec), \
         patch("agents.memory_agent.MARKER_FILE", marker_path):
        asyncio.run(MemoryAgent(mock_db).migrate_embeddings())

    assert mock_db.update_embedding.call_count == 2
    with open(marker_path) as f:
        assert f.read().strip() == CURRENT_MODEL


def test_migrate_embeddings_skips_when_already_migrated(tmp_path):
    from agents.memory_agent import MemoryAgent, CURRENT_MODEL

    marker_path = str(tmp_path / ".embedding_model")
    with open(marker_path, "w") as f:
        f.write(CURRENT_MODEL + "\n")

    mock_db = MagicMock()
    mock_db.load_all = AsyncMock(return_value=[])
    mock_db.update_embedding = AsyncMock()

    with patch("agents.memory_agent.MARKER_FILE", marker_path):
        asyncio.run(MemoryAgent(mock_db).migrate_embeddings())

    mock_db.update_embedding.assert_not_called()
```

- [ ] **Step 2: Tests laufen lassen — müssen FAIL**

```bash
/Users/philippherrlich/Documents/04_Sonstiges/01_Coding/herrlich-ai-platform/.worktrees/plan3-smart-routing/.venv/bin/pytest tests/test_memory_agent.py -v
```

Erwartete Ausgabe: `ImportError` oder `AttributeError` — `retrieve()` hat noch `query`-Param, `migrate_embeddings` existiert nicht.

- [ ] **Step 3: `MemoryDB.update_embedding` in `agents/db.py` hinzufügen**

Füge folgende Methode ans Ende der `MemoryDB`-Klasse (nach `get_latest_id`) in `agents/db.py` an:

```python
    async def update_embedding(self, memory_id: int, embedding: bytes):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE memories SET embedding = ? WHERE id = ?",
                (embedding, memory_id),
            )
            await db.commit()
```

- [ ] **Step 4: `agents/memory_agent.py` anpassen**

**4a.** Ändere das Embedding-Modell und füge Konstanten hinzu (Zeile 19-27 ersetzen):

```python
CURRENT_MODEL = "intfloat/multilingual-e5-small"
MARKER_FILE = "/root/.jarvis/.embedding_model"

_embedding_model = None


def _get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        from fastembed import TextEmbedding
        _embedding_model = TextEmbedding(CURRENT_MODEL)
    return _embedding_model
```

**4b.** Ändere `retrieve()` — entferne `query`-Parameter, gib alle Memories zurück:

```python
    async def retrieve(self) -> list[str]:
        rows = await self.db.load_all()
        return [row["content"] for row in rows]
```

**4c.** Füge `migrate_embeddings()` nach `retrieve()` hinzu:

```python
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
```

- [ ] **Step 5: Tests laufen lassen — müssen PASS**

```bash
/Users/philippherrlich/Documents/04_Sonstiges/01_Coding/herrlich-ai-platform/.worktrees/plan3-smart-routing/.venv/bin/pytest tests/test_memory_agent.py tests/test_conversation_db.py -v
```

Erwartete Ausgabe: 7 passed.

- [ ] **Step 6: Commit**

```bash
git add agents/db.py agents/memory_agent.py tests/test_memory_agent.py
git commit -m "feat(memory): multilingual embeddings + inject-all retrieval + migration"
```

---

### Task 3: Integration in main.py

**Files:**
- Modify: `agents/main.py`
- Modify: `tests/test_chat_quality_main.py` (1 neuen Test anhängen)

- [ ] **Step 1: Neuen Integration-Test schreiben**

Hänge folgenden Test **ans Ende** von `tests/test_chat_quality_main.py` an:

```python
def test_profile_content_injected_for_personal_intent():
    mock_profile = MagicMock()
    mock_profile.load.return_value = "## Beruf & Rolle\nStrategischer Berater\n"
    main_module._profile_agent = mock_profile

    with patch("agents.main.route_with_llm", return_value={
        "intent": "personal", "confidence": 9, "params": {}, "reasoning": "test"
    }):
        with patch("agents.main.ask_claude", new_callable=AsyncMock, return_value="ok") as mock_ask:
            with patch("agents.main.send_typing", new_callable=AsyncMock):
                update = MagicMock()
                update.update_id = 88881
                update.message.text = "Was soll ich tun?"
                update.message.chat_id = 456
                update.message.reply_text = AsyncMock()
                asyncio.run(main_module.handle_message(update, None))

    main_module._profile_agent = None
    system_arg = mock_ask.call_args.kwargs.get("system", "")
    assert "Strategischer Berater" in system_arg
```

- [ ] **Step 2: Test laufen lassen — muss FAIL**

```bash
/Users/philippherrlich/Documents/04_Sonstiges/01_Coding/herrlich-ai-platform/.worktrees/plan3-smart-routing/.venv/bin/pytest tests/test_chat_quality_main.py::test_profile_content_injected_for_personal_intent -v
```

Erwartete Ausgabe: `AssertionError` — `_profile_agent` existiert als Global noch nicht, oder Profil-Inhalt nicht im system-String.

- [ ] **Step 3: `_profile_agent` Global hinzufügen**

In `agents/main.py` nach `_conversation_db = None  # initialized in startup()` (ca. Zeile 64):

```python
_profile_agent = None    # initialized in startup()
```

- [ ] **Step 4: Memory-Context-Block in `_process_text` ersetzen**

Ersetze den gesamten bisherigen Block:

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

durch:

```python
    memory_context = ""
    if intent in _MEMORY_INTENTS:
        if _profile_agent:
            try:
                profile = _profile_agent.load()
                memory_context += f"=== Philipps Profil ===\n{profile}\n\n"
            except Exception as e:
                logger.warning("Profile load failed: %s", e)
        if _memory_agent:
            try:
                memories = await _memory_agent.retrieve()
                if memories:
                    bullet_list = "\n".join(f"• {m}" for m in memories)
                    memory_context += f"=== Erinnerungen ===\n{bullet_list}\n\n"
            except Exception as e:
                logger.warning("Memory retrieval failed: %s", e)
```

- [ ] **Step 5: Profile-Update-Trigger ans Ende von `_process_text` anhängen**

Füge direkt nach dem bestehenden History-Save-Block (nach `logger.warning("History save failed: ...")`) ein:

```python
    if _profile_agent and intent in _HISTORY_INTENTS and answer and not answer.startswith("Fehler:"):
        conversation = f"Philipp: {text}\n\nJarvis: {answer}"
        asyncio.create_task(_profile_agent.update(conversation))
```

- [ ] **Step 6: `startup()` erweitern**

**6a.** Ändere die `global`-Zeile in `startup()`:

```python
    global _memory_agent, _conversation_db, _profile_agent
```

**6b.** Füge direkt nach `logger.info("ConversationDB initialisiert")` ein:

```python
    from profile_agent import ProfileAgent
    _profile_agent = ProfileAgent()
    _profile_agent.load()
    logger.info("ProfileAgent initialisiert")
    asyncio.create_task(_memory_agent.migrate_embeddings())
```

- [ ] **Step 7: Alle Tests laufen lassen — müssen PASS**

```bash
/Users/philippherrlich/Documents/04_Sonstiges/01_Coding/herrlich-ai-platform/.worktrees/plan3-smart-routing/.venv/bin/pytest tests/test_profile_agent.py tests/test_memory_agent.py tests/test_chat_quality_main.py tests/test_conversation_db.py tests/test_main_memory.py -v
```

Erwartete Ausgabe: mind. 20 passed, 0 failed. (test_keep_typing_stops_on_event dauert ~4s — erwartet.)

- [ ] **Step 8: Commit + Push**

```bash
git add agents/main.py tests/test_chat_quality_main.py
git commit -m "feat(memory): profile + inject-all integration in _process_text + startup"
git push
```

---

### Task 4: VPS deployen und testen

- [ ] **Step 1: Deployen**

```bash
ssh root@100.115.184.3 "cd /root/agents && git pull && systemctl restart jarvis"
```

- [ ] **Step 2: Logs prüfen**

```bash
ssh root@100.115.184.3 "journalctl -u jarvis -n 30 --no-pager"
```

Erwartete Ausgabe: `ProfileAgent initialisiert` + `Memory embeddings migrated to intfloat/multilingual-e5-small` + `Jarvis gestartet` ohne Fehler. (Migration läuft als Background-Task, erscheint kurz nach dem Start.)

- [ ] **Step 3: Cross-Kontext testen**

Sende in Telegram:
1. *„Ich bin strategischer Unternehmensberater und spezialisiert auf digitale Transformation"*
2. Warte 5 Sekunden (Profil-Update läuft im Hintergrund)
3. *„Welche Frameworks sind für meine Arbeit am relevantesten?"*

Erwartete Antwort auf Nachricht 3: Jarvis nennt Business-Frameworks (McKinsey 7S, Porter's Five Forces, Digital Maturity Models etc.) — weil er aus dem Profil weiß, dass Philipp Unternehmensberater ist.

- [ ] **Step 4: Profil-Datei prüfen**

```bash
ssh root@100.115.184.3 "cat /root/.jarvis/user_profile.md"
```

Erwartete Ausgabe: Profil enthält die neu gelernte Information über Beruf und Spezialisierung.
