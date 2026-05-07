# Jarvis Persistent User Profile — Design Spec

**Date:** 2026-05-07
**Status:** Approved

## Goal

Jarvis soll Philipp dauerhaft kennen: Beruf, Skills, Projekte, Interessen und Ziele werden in einem persistenten Markdown-Profil gespeichert, das nach jedem LLM-Gespräch automatisch aktualisiert wird. Parallel wird das Embedding-Modell auf Multilingual-E5 umgestellt und alle Memories werden immer injiziert (kein Semantic Threshold mehr).

## Features

### 1. Persistent User Profile

**Datei:** `/root/.jarvis/user_profile.md`

Jarvis erstellt diese Datei beim ersten Start mit leeren Abschnitten. Nach jedem LLM-Gespräch (personal/work/research) entscheidet Claude Haiku ob das Profil aktualisiert werden soll.

**Default-Inhalt:**
```markdown
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
```

**Neue Klasse `ProfileAgent` in `agents/profile_agent.py`:**

```python
class ProfileAgent:
    def load(self) -> str          # liest Datei, erstellt bei Bedarf
    async def update(self, conversation: str) -> None  # Haiku-Call + ggf. Datei schreiben
```

**Update-Logik:** Haiku bekommt aktuelles Profil + Gespräch. Gibt entweder das vollständig aktualisierte Profil zurück oder einen leeren String (= kein Update nötig). Nur bei nicht-leerem Return wird die Datei überschrieben. `update()` wird als Background-Task nach jedem LLM-Call gestartet.

**Injection:** Profil wird bei jedem LLM-Call für `_MEMORY_INTENTS` als erstes in den Kontext injiziert:

```
=== Philipps Profil ===
[Profil-Inhalt]

=== Erinnerungen ===
• [Memory 1]
• [Memory 2]
```

### 2. Multilingual Embeddings + Inject-All

**Modell-Wechsel:** `BAAI/bge-small-en-v1.5` → `intfloat/multilingual-e5-small` (fastembed drop-in, besser für Deutsch/Englisch).

**Retrieval-Logik:** `retrieve()` gibt alle Memories zurück (kein Similarity-Threshold mehr, kein Top-k). Embeddings werden nur noch für Deduplication beim Speichern genutzt (Threshold 0.90 bleibt).

**Migration:** Beim Start einmalig alle bestehenden Memories mit dem neuen Modell re-embedden. Eine Marker-Datei `/root/.jarvis/.embedding_model` verhindert doppelte Migrationen.

**Neue Methode `MemoryDB.update_embedding(id, bytes)`** in `db.py` für die Migration.

**Neue Methode `MemoryAgent.migrate_embeddings()`** in `memory_agent.py` — wird in `startup()` als `asyncio.create_task` gestartet.

## File Map

| File | Änderung |
|---|---|
| `agents/profile_agent.py` | Neu: `ProfileAgent` (load, update) |
| `agents/memory_agent.py` | Modell-Wechsel, `retrieve()` ohne Query, `migrate_embeddings()` |
| `agents/db.py` | `MemoryDB.update_embedding()` hinzufügen |
| `agents/main.py` | `_profile_agent` global, Injection, Update-Trigger, startup init |
| `tests/test_profile_agent.py` | Neu: 4 Tests |
| `tests/test_memory_agent.py` | Neu: 3 Tests |

## Data Flow

```
User schickt Nachricht
        ↓
_process_text()
        ↓
[intent in MEMORY_INTENTS]
        ↓
profile_agent.load()          ← immer (sync, schnell)
memory_agent.retrieve()       ← alle Memories (keine Threshold-Filterung)
        ↓
memory_context = Profil + Memories
        ↓
ask_claude(..., system=memory_context + ...)
        ↓
asyncio.create_task(profile_agent.update(conversation))  ← Background
asyncio.create_task(memory_agent.extract(...))            ← Background (bereits vorhanden)
asyncio.create_task(conversation_db.save(...))            ← Background (bereits vorhanden)
```

## Out of Scope

- Memory Summarization / Consolidation
- Manuelles Profil-Editing per Telegram-Command
- Mehrsprachige Profil-Sections
- Profil-Versioning / History
