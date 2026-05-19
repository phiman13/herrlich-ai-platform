# mail + calendar als Write-Tools — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Konvertiere die `mail` und `calendar` Intents von direkten Handlern zu Agenten-Tools, die das Write-Confirm-Schema aus Plan 3 nutzen.

**Architecture:** Zwei neue Tool-Module (`mail_tool.py`, `calendar_tool.py`) folgen exakt dem `tasks_tool.py`-Muster: `make_<name>_tool(chat_id)` Factory + `execute_write(action, params)` + `_WRITE_ACTIONS`-Set. Read-Aktionen laufen sofort via `asyncio.to_thread`; Write-Aktionen landen in `app_state.pending_agent_actions`. Nach Verdrahtung in `dispatch.py` werden die alten Handler-Callbacks aus `callbacks.py` und die Handler-Dateien selbst gelöscht.

**Tech Stack:** Python 3.11, asyncio.to_thread, claude_agent_sdk.tool, pytest-asyncio, MailAgent (MS Graph / requests), CalendarAgent (MS Graph / httpx)

---

## Datei-Überblick

**Neu:**
- `agents/tools/mail_tool.py` — mail-Tool Factory + execute_write
- `agents/tools/calendar_tool.py` — calendar-Tool Factory + execute_write
- `tests/test_tools_mail.py` — Unit-Tests mail_tool
- `tests/test_tools_calendar.py` — Unit-Tests calendar_tool

**Geändert:**
- `agents/tools/__init__.py` — mail_tool + calendar_tool registrieren
- `agents/dispatch.py` — mail + calendar in `_AGENT_INTENTS` + `_HISTORY_INTENTS`; alte Handler-Importe löschen
- `agents/agent.py` — System-Prompt: mail + calendar Werkzeug-Hinweise
- `agents/callbacks.py` — alte `mail:*` + `cal:*` Callbacks entfernen
- `agents/app_state.py` — `pending_mail_ops`, `pending_calendar_ops`, `last_mail_search`, `last_calendar_search`, `_pending_op_expired` entfernen
- `CLAUDE.md` — Callbacks-Tabelle + Pending-State-Tabelle aktualisieren

**Gelöscht:**
- `agents/mail_handler.py`
- `agents/calendar_handler.py`
- `tests/test_mail_write.py`
- `tests/test_mail_send.py`
- `tests/test_calendar_write.py`
- `tests/test_calendar_modify.py`
- `tests/test_callback_main.py` (testet alte mail/cal-Callbacks — vollständig löschen)

**Prüfen (nicht automatisch löschen):**
- `tests/test_calendar_read.py` — prüfen ob es calendar_agent.py direkt testet (behalten) oder calendar_handler.py importiert (löschen)
- `tests/test_dispatch_main.py` — mail/calendar-Dispatch-Tests entfernen die den alten Handler prüfen

---

## Task 1: `mail_tool.py` + Tests

**Files:**
- Create: `agents/tools/mail_tool.py`
- Create: `tests/test_tools_mail.py`

**Aktionen — Read (sofort):**
- `search` (query, count=20) → `MailAgent().smart_search(query, count)`
- `list_unread` (count=20, folder_name optional) → `MailAgent().get_inbox_unread(count)` oder `get_unread(count, folder_id)` wenn folder_name gesetzt
- `list_inbox` (count=10) → `MailAgent().quick_scan(count)`
- `list_folders` → `MailAgent().list_folders()`
- `get_body` (mail_id) → `MailAgent().get_mail_body(mail_id)`

**Aktionen — Write (vormerken):**
- `compose` (to_email, subject, body) → `MailAgent().send_mail(to_email, subject, body)`
- `reply` (mail_id, comment, subject) → `MailAgent().reply(mail_id, comment)`
- `forward` (mail_id, to_email, comment, subject) → `MailAgent().forward(mail_id, [to_email], comment)`
- `archive` (mail_id, subject) → `MailAgent().archive(mail_id)`
- `move` (mail_id, destination_folder, subject) → `find_folder_by_name` + `move`
- `delete` (mail_id, subject) → `MailAgent().delete(mail_id)`
- `mark_read` (mail_id, subject) → `MailAgent().mark_read(mail_id, True)`
- `mark_unread` (mail_id, subject) → `MailAgent().mark_read(mail_id, False)`

`subject` bei Write-Aktionen ist rein für das Label (Confirm-Dialog), nicht für die API.

- [ ] **Step 1: Failenden Test schreiben (staged-not-executes)**

Datei `tests/test_tools_mail.py` anlegen:

```python
"""Tests für agents/tools/mail_tool.py."""

import pytest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import app_state
import tools.mail_tool as mail_tool_mod

BERLIN = ZoneInfo("Europe/Berlin")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_mail(mail_id="m1", subject="Re: Meeting", is_read=False):
    from mail_agent import Mail
    return Mail(
        id=mail_id, subject=subject,
        sender_name="Max Muster", sender_email="max@example.com",
        received=datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc),
        is_read=is_read, preview="Vorschau...",
        folder="inbox", has_attachments=False,
    )


def _make_folder(name="Inbox", unread=2):
    from mail_agent import MailFolder
    return MailFolder(id="fid1", name=name, parent_id=None,
                      child_count=0, unread_count=unread, total_count=10)


class _MockAgent:
    """Konfigurierbarer Mock für MailAgent."""
    def __init__(self, **methods):
        for name, fn in methods.items():
            setattr(self, name, fn)


# ── Read-only: sofort ausführen ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_search_reads_immediately(monkeypatch):
    monkeypatch.setattr(
        mail_tool_mod, "MailAgent",
        lambda: _MockAgent(smart_search=lambda q, n: [_make_mail("m1", "Rechnung")])
    )
    tool = mail_tool_mod.make_mail_tool(7)
    result = await tool.handler({"action": "search", "query": "rechnung"})
    text = result["content"][0]["text"]
    assert "m1" in text
    assert "Rechnung" in text
    assert app_state.peek_pending(7) is None


@pytest.mark.asyncio
async def test_search_requires_query():
    tool = mail_tool_mod.make_mail_tool(7)
    result = await tool.handler({"action": "search"})
    assert result["content"][0]["text"].startswith("FEHLER")


@pytest.mark.asyncio
async def test_list_folders_reads_immediately(monkeypatch):
    monkeypatch.setattr(
        mail_tool_mod, "MailAgent",
        lambda: _MockAgent(list_folders=lambda: [_make_folder("Posteingang", 3)])
    )
    tool = mail_tool_mod.make_mail_tool(7)
    result = await tool.handler({"action": "list_folders"})
    assert "Posteingang" in result["content"][0]["text"]
    assert app_state.peek_pending(7) is None


@pytest.mark.asyncio
async def test_get_body_reads_immediately(monkeypatch):
    monkeypatch.setattr(
        mail_tool_mod, "MailAgent",
        lambda: _MockAgent(get_mail_body=lambda mid: {
            "sender_name": "Max", "sender_email": "max@e.de",
            "subject": "Re: Meeting", "received": "2026-05-19T12:00:00",
            "body_text": "Hallo Philipp, der Termin ...",
        })
    )
    tool = mail_tool_mod.make_mail_tool(7)
    result = await tool.handler({"action": "get_body", "mail_id": "abc123"})
    assert "Hallo Philipp" in result["content"][0]["text"]
    assert app_state.peek_pending(7) is None


@pytest.mark.asyncio
async def test_get_body_requires_mail_id():
    tool = mail_tool_mod.make_mail_tool(7)
    result = await tool.handler({"action": "get_body"})
    assert result["content"][0]["text"].startswith("FEHLER")


# ── Write: nur vormerken, nicht ausführen ─────────────────────────────────────

@pytest.mark.asyncio
async def test_archive_stages_not_executes(monkeypatch):
    app_state.pending_agent_actions.clear()
    called = []
    monkeypatch.setattr(
        mail_tool_mod, "MailAgent",
        lambda: _MockAgent(archive=lambda mid: called.append(mid) or True)
    )
    tool = mail_tool_mod.make_mail_tool(7)
    result = await tool.handler({
        "action": "archive", "mail_id": "m1", "subject": "Re: Meeting"
    })
    assert called == []
    assert "vorgemerkt" in result["content"][0]["text"].lower()
    entry = app_state.peek_pending(7)
    assert entry is not None
    a = entry["actions"][0]
    assert a["tool"] == "mail"
    assert a["action"] == "archive"
    assert a["params"]["mail_id"] == "m1"
    app_state.pending_agent_actions.clear()


@pytest.mark.asyncio
async def test_compose_stages_not_executes(monkeypatch):
    app_state.pending_agent_actions.clear()
    called = []
    monkeypatch.setattr(
        mail_tool_mod, "MailAgent",
        lambda: _MockAgent(send_mail=lambda *a: called.append(a) or True)
    )
    tool = mail_tool_mod.make_mail_tool(7)
    result = await tool.handler({
        "action": "compose", "to_email": "x@y.de",
        "subject": "Hallo", "body": "Text hier"
    })
    assert called == []
    assert "vorgemerkt" in result["content"][0]["text"].lower()
    entry = app_state.peek_pending(7)
    assert entry["actions"][0]["action"] == "compose"
    assert entry["actions"][0]["params"]["to_email"] == "x@y.de"
    app_state.pending_agent_actions.clear()


@pytest.mark.asyncio
async def test_delete_stages_not_executes(monkeypatch):
    app_state.pending_agent_actions.clear()
    called = []
    monkeypatch.setattr(
        mail_tool_mod, "MailAgent",
        lambda: _MockAgent(delete=lambda mid: called.append(mid) or True)
    )
    tool = mail_tool_mod.make_mail_tool(7)
    result = await tool.handler({
        "action": "delete", "mail_id": "m2", "subject": "Newsletter"
    })
    assert called == []
    assert "vorgemerkt" in result["content"][0]["text"].lower()
    app_state.pending_agent_actions.clear()


@pytest.mark.asyncio
async def test_archive_requires_mail_id():
    app_state.pending_agent_actions.clear()
    tool = mail_tool_mod.make_mail_tool(7)
    result = await tool.handler({"action": "archive", "subject": "X"})
    assert result["content"][0]["text"].startswith("FEHLER")
    assert app_state.peek_pending(7) is None


@pytest.mark.asyncio
async def test_compose_requires_to_email_and_body():
    app_state.pending_agent_actions.clear()
    tool = mail_tool_mod.make_mail_tool(7)
    result = await tool.handler({"action": "compose", "to_email": "x@y.de"})
    assert result["content"][0]["text"].startswith("FEHLER")
    assert app_state.peek_pending(7) is None


@pytest.mark.asyncio
async def test_unknown_action_is_error():
    tool = mail_tool_mod.make_mail_tool(7)
    result = await tool.handler({"action": "frobnicate"})
    assert result["content"][0]["text"].startswith("FEHLER")


# ── execute_write ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_execute_write_archive(monkeypatch):
    calls = []
    monkeypatch.setattr(
        mail_tool_mod, "MailAgent",
        lambda: _MockAgent(archive=lambda mid: calls.append(mid) or True)
    )
    msg = await mail_tool_mod.execute_write(
        "archive", {"mail_id": "m1", "subject": "X"}
    )
    assert calls == ["m1"]
    assert "✅" in msg


@pytest.mark.asyncio
async def test_execute_write_archive_failure(monkeypatch):
    monkeypatch.setattr(
        mail_tool_mod, "MailAgent",
        lambda: _MockAgent(archive=lambda mid: False)
    )
    msg = await mail_tool_mod.execute_write(
        "archive", {"mail_id": "m1", "subject": "X"}
    )
    assert "❌" in msg


@pytest.mark.asyncio
async def test_execute_write_compose(monkeypatch):
    calls = []
    monkeypatch.setattr(
        mail_tool_mod, "MailAgent",
        lambda: _MockAgent(send_mail=lambda to, s, b: calls.append((to, s, b)) or True)
    )
    msg = await mail_tool_mod.execute_write(
        "compose", {"to_email": "x@y.de", "subject": "Hallo", "body": "Text"}
    )
    assert calls == [("x@y.de", "Hallo", "Text")]
    assert "✅" in msg and "x@y.de" in msg


@pytest.mark.asyncio
async def test_execute_write_compose_failure(monkeypatch):
    monkeypatch.setattr(
        mail_tool_mod, "MailAgent",
        lambda: _MockAgent(send_mail=lambda *a: False)
    )
    msg = await mail_tool_mod.execute_write(
        "compose", {"to_email": "x@y.de", "subject": "H", "body": "T"}
    )
    assert "❌" in msg and "x@y.de" in msg


@pytest.mark.asyncio
async def test_execute_write_move_resolves_folder(monkeypatch):
    class FakeFolder:
        id = "fid_xyz"
    folder_calls, move_calls = [], []
    monkeypatch.setattr(
        mail_tool_mod, "MailAgent",
        lambda: _MockAgent(
            find_folder_by_name=lambda n: folder_calls.append(n) or FakeFolder(),
            move=lambda mid, fid: move_calls.append((mid, fid)) or True,
        )
    )
    msg = await mail_tool_mod.execute_write(
        "move", {"mail_id": "m1", "destination_folder": "Newsletter", "subject": "X"}
    )
    assert folder_calls == ["Newsletter"]
    assert move_calls == [("m1", "fid_xyz")]
    assert "✅" in msg


@pytest.mark.asyncio
async def test_execute_write_move_folder_not_found(monkeypatch):
    monkeypatch.setattr(
        mail_tool_mod, "MailAgent",
        lambda: _MockAgent(find_folder_by_name=lambda n: None)
    )
    msg = await mail_tool_mod.execute_write(
        "move", {"mail_id": "m1", "destination_folder": "Nope", "subject": "X"}
    )
    assert "❌" in msg and "Nope" in msg


@pytest.mark.asyncio
async def test_execute_write_delete(monkeypatch):
    calls = []
    monkeypatch.setattr(
        mail_tool_mod, "MailAgent",
        lambda: _MockAgent(delete=lambda mid: calls.append(mid) or True)
    )
    msg = await mail_tool_mod.execute_write(
        "delete", {"mail_id": "m1", "subject": "X"}
    )
    assert calls == ["m1"]
    assert "✅" in msg


@pytest.mark.asyncio
async def test_execute_write_unknown_action():
    msg = await mail_tool_mod.execute_write("frobnicate", {})
    assert "Unbekannte" in msg
```

- [ ] **Step 2: Test laufen lassen — muss scheitern**

```bash
PYTHONPATH=agents .venv/bin/pytest tests/test_tools_mail.py -v
```

Erwartetes Ergebnis: `ImportError` oder `ModuleNotFoundError` (Modul existiert noch nicht).

- [ ] **Step 3: `agents/tools/mail_tool.py` implementieren**

```python
"""mail-Tool — Mails suchen, lesen und schreiben.

Read-Aktionen (search/list_unread/list_inbox/list_folders/get_body) laufen
sofort. Write-Aktionen werden via app_state.stage_agent_action vorgemerkt
und erst nach Philipps Bestätigung durch execute_write ausgeführt.
"""

import asyncio

from claude_agent_sdk import tool

import app_state
from mail_agent import MailAgent

_WRITE_ACTIONS = {
    "compose", "reply", "forward", "archive", "move", "delete",
    "mark_read", "mark_unread",
}


def _label(action: str, params: dict) -> str:
    subj = (params.get("subject") or "")[:60]
    to = params.get("to_email", "")
    dest = params.get("destination_folder", "?")
    if action == "compose":
        return f"Mail an '{to}' senden: {subj}"
    if action == "reply":
        return f"Auf Mail '{subj}' antworten"
    if action == "forward":
        return f"Mail '{subj}' weiterleiten an '{to}'"
    if action == "archive":
        return f"Mail '{subj}' archivieren"
    if action == "move":
        return f"Mail '{subj}' nach '{dest}' verschieben"
    if action == "delete":
        return f"Mail '{subj}' löschen"
    if action == "mark_read":
        return f"Mail '{subj}' als gelesen markieren"
    if action == "mark_unread":
        return f"Mail '{subj}' als ungelesen markieren"
    return action


def _missing_fields(action: str, params: dict) -> str:
    required = {
        "compose": ("to_email", "subject", "body"),
        "reply": ("mail_id", "comment"),
        "forward": ("mail_id", "to_email"),
        "archive": ("mail_id",),
        "move": ("mail_id", "destination_folder"),
        "delete": ("mail_id",),
        "mark_read": ("mail_id",),
        "mark_unread": ("mail_id",),
    }[action]
    return ", ".join(f for f in required if not params.get(f))


def _format_mails(mails) -> str:
    if not mails:
        return "Keine Mails gefunden."
    from zoneinfo import ZoneInfo
    berlin = ZoneInfo("Europe/Berlin")
    parts = [f"📬 {len(mails)} Mail(s):\n"]
    for m in mails:
        unread = "🔵 " if not m.is_read else ""
        date_str = m.received.astimezone(berlin).strftime("%d.%m. %H:%M")
        sender = (m.sender_name or m.sender_email or "?")[:40]
        parts.append(
            f"{unread}ID: {m.id}\n"
            f"Von: {sender} | {date_str}\n"
            f"Betreff: {m.subject[:80]}\n"
            f"Vorschau: {m.preview[:120]}"
        )
    return "\n\n".join(parts)


def _text(msg: str) -> dict:
    return {"content": [{"type": "text", "text": msg}]}


def make_mail_tool(chat_id: int):
    """Baut das mail-Tool für einen Lauf — chat_id für das Vormerken."""

    @tool(
        "mail",
        "E-Mails suchen, lesen und schreiben. "
        "action='search' (query, count=20): Mails suchen — Ergebnis enthält IDs. "
        "action='list_unread' (count=20, folder_name optional): Ungelesene Mails. "
        "action='list_inbox' (count=10): Neueste Inbox-Mails. "
        "action='list_folders': Alle Mail-Ordner. "
        "action='get_body' (mail_id): Volltext einer Mail. "
        "action='compose' (to_email, subject, body): Neue Mail senden. "
        "action='reply' (mail_id, comment, subject): Mail beantworten. "
        "action='forward' (mail_id, to_email, comment, subject): Weiterleiten. "
        "action='archive' (mail_id, subject): Archivieren. "
        "action='move' (mail_id, destination_folder, subject): Verschieben. "
        "action='delete' (mail_id, subject): Löschen. "
        "action='mark_read' (mail_id, subject): Als gelesen markieren. "
        "action='mark_unread' (mail_id, subject): Als ungelesen markieren. "
        "Bei Write-Aktionen: subject = Mail-Betreff (nur für den Confirm-Dialog). "
        "Write-Aktionen werden vorgemerkt und erst nach Philipps Bestätigung "
        "ausgeführt — sag ihm, was du vorbereitet hast.",
        {
            "action": str,
            "query": str,
            "count": int,
            "folder_name": str,
            "mail_id": str,
            "to_email": str,
            "subject": str,
            "body": str,
            "comment": str,
            "destination_folder": str,
        },
    )
    async def mail_tool(args: dict) -> dict:
        action = (args.get("action") or "").strip()

        # ── Read-Aktionen ──────────────────────────────────────────────────
        if action == "search":
            query = (args.get("query") or "").strip()
            if not query:
                return _text("FEHLER: action='search' braucht: query.")
            count = int(args.get("count") or 20)
            agent = MailAgent()
            mails = await asyncio.to_thread(agent.smart_search, query, count)
            return _text(_format_mails(mails))

        if action == "list_unread":
            count = int(args.get("count") or 20)
            folder_name = (args.get("folder_name") or "").strip() or None
            agent = MailAgent()
            if folder_name:
                folder = await asyncio.to_thread(agent.find_folder_by_name, folder_name)
                folder_id = folder.id if folder else None
                mails = await asyncio.to_thread(agent.get_unread, count, folder_id)
            else:
                mails = await asyncio.to_thread(agent.get_inbox_unread, count)
            return _text(_format_mails(mails))

        if action == "list_inbox":
            count = int(args.get("count") or 10)
            agent = MailAgent()
            mails = await asyncio.to_thread(agent.quick_scan, count)
            return _text(_format_mails(mails))

        if action == "list_folders":
            agent = MailAgent()
            folders = await asyncio.to_thread(agent.list_folders)
            if not folders:
                return _text("Keine Ordner gefunden.")
            lines = ["📁 Mail-Ordner:\n"]
            for f in folders:
                unread = f" ({f.unread_count} ungelesen)" if f.unread_count else ""
                lines.append(f"• {f.name}{unread}")
            return _text("\n".join(lines))

        if action == "get_body":
            mail_id = (args.get("mail_id") or "").strip()
            if not mail_id:
                return _text("FEHLER: action='get_body' braucht: mail_id.")
            agent = MailAgent()
            data = await asyncio.to_thread(agent.get_mail_body, mail_id)
            text = (
                f"Von: {data['sender_name']} <{data['sender_email']}>\n"
                f"Betreff: {data['subject']}\n"
                f"Datum: {data['received']}\n\n"
                f"{data['body_text']}"
            )
            return _text(text)

        if action not in _WRITE_ACTIONS:
            return _text(
                f"FEHLER: Unbekannte action '{action}'. Erlaubt: search, "
                "list_unread, list_inbox, list_folders, get_body, compose, reply, "
                "forward, archive, move, delete, mark_read, mark_unread."
            )

        # ── Write-Aktionen: Pflichtfelder prüfen + vormerken ───────────────
        params = {
            "mail_id": (args.get("mail_id") or "").strip(),
            "to_email": (args.get("to_email") or "").strip(),
            "subject": (args.get("subject") or "").strip(),
            "body": (args.get("body") or "").strip(),
            "comment": (args.get("comment") or "").strip(),
            "destination_folder": (args.get("destination_folder") or "").strip(),
        }
        missing = _missing_fields(action, params)
        if missing:
            return _text(f"FEHLER: action='{action}' braucht: {missing}.")
        label = _label(action, params)
        app_state.stage_agent_action(chat_id, "mail", action, label, params)
        return _text(
            f"✅ Vorgemerkt: {label}. Wird nach Philipps Bestätigung ausgeführt "
            "— du musst nicht warten."
        )

    return mail_tool


async def execute_write(action: str, params: dict) -> str:
    """Eine vorgemerkte mail-Schreibaktion ausführen."""
    agent = MailAgent()

    if action == "compose":
        ok = await asyncio.to_thread(
            agent.send_mail, params["to_email"], params["subject"], params["body"]
        )
        return (
            f"✅ Mail an '{params['to_email']}' gesendet."
            if ok
            else f"❌ Mail an '{params['to_email']}' konnte nicht gesendet werden."
        )

    if action == "reply":
        ok = await asyncio.to_thread(agent.reply, params["mail_id"], params["comment"])
        return "✅ Antwort gesendet." if ok else "❌ Antwort fehlgeschlagen."

    if action == "forward":
        to_emails = [e.strip() for e in params["to_email"].split(",") if "@" in e]
        comment = params.get("comment", "")
        ok = await asyncio.to_thread(agent.forward, params["mail_id"], to_emails, comment)
        return (
            f"✅ Mail weitergeleitet an '{params['to_email']}'."
            if ok
            else "❌ Weiterleiten fehlgeschlagen."
        )

    if action == "archive":
        ok = await asyncio.to_thread(agent.archive, params["mail_id"])
        return "✅ Mail archiviert." if ok else "❌ Archivieren fehlgeschlagen."

    if action == "move":
        folder = await asyncio.to_thread(
            agent.find_folder_by_name, params["destination_folder"]
        )
        if folder is None:
            return f"❌ Ordner '{params['destination_folder']}' nicht gefunden."
        ok = await asyncio.to_thread(agent.move, params["mail_id"], folder.id)
        return (
            f"✅ Mail nach '{params['destination_folder']}' verschoben."
            if ok
            else "❌ Verschieben fehlgeschlagen."
        )

    if action == "delete":
        ok = await asyncio.to_thread(agent.delete, params["mail_id"])
        return "✅ Mail gelöscht." if ok else "❌ Löschen fehlgeschlagen."

    if action == "mark_read":
        ok = await asyncio.to_thread(agent.mark_read, params["mail_id"], True)
        return "✅ Als gelesen markiert." if ok else "❌ Fehlgeschlagen."

    if action == "mark_unread":
        ok = await asyncio.to_thread(agent.mark_read, params["mail_id"], False)
        return "✅ Als ungelesen markiert." if ok else "❌ Fehlgeschlagen."

    return f"❌ Unbekannte mail-Aktion '{action}'."
```

- [ ] **Step 4: Tests laufen lassen — müssen grün sein**

```bash
PYTHONPATH=agents .venv/bin/pytest tests/test_tools_mail.py -v
```

Erwartetes Ergebnis: alle Tests grün.

- [ ] **Step 5: Gesamte Suite grün**

```bash
PYTHONPATH=agents .venv/bin/pytest tests/ -q --tb=short \
  --ignore=tests/test_briefing_agent.py \
  --ignore=tests/test_mail_send.py \
  --ignore=tests/test_tasks_agent.py
```

- [ ] **Step 6: Commit**

```bash
git add agents/tools/mail_tool.py tests/test_tools_mail.py
git commit -m "feat(tools): mail-Tool — search/list/read + compose/reply/forward/archive/move/delete/mark"
```

---

## Task 2: `calendar_tool.py` + Tests

**Files:**
- Create: `agents/tools/calendar_tool.py`
- Create: `tests/test_tools_calendar.py`

**Aktionen — Read (sofort):**
- `list` (start_iso, end_iso) → `CalendarAgent().get_events(start, end)` — gibt Event-IDs zurück
- `search` (query, start_iso, end_iso) → `CalendarAgent().search_events(query, start, end)`
- `get_next` → `CalendarAgent().get_next_event()`

**Aktionen — Write (vormerken):**
- `create` (title, start_iso, end_iso, location optional) → `CalendarAgent().create_event(...)`
- `update` (event_id, title, new_title optional, new_start_iso optional, new_end_iso optional, new_location optional) → `CalendarAgent().update_event(...)`
- `delete` (event_id, title) → `CalendarAgent().delete_event(event_id)`

`end_iso` bei `create` ist optional — Default: `start_iso` + 1 Stunde.
`title` bei `update`/`delete` ist rein für das Label.

- [ ] **Step 1: Failenden Test schreiben**

Datei `tests/test_tools_calendar.py` anlegen:

```python
"""Tests für agents/tools/calendar_tool.py."""

import pytest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import app_state
import tools.calendar_tool as cal_tool_mod

BERLIN = ZoneInfo("Europe/Berlin")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_event(event_id="ev1", title="Meeting"):
    from calendar_agent import Event
    return Event(
        id=event_id, title=title,
        start=datetime(2026, 5, 20, 10, 0, tzinfo=BERLIN),
        end=datetime(2026, 5, 20, 11, 0, tzinfo=BERLIN),
        location=None, calendar_name="Outlook", source="outlook",
    )


class _MockAgent:
    def __init__(self, **methods):
        for name, fn in methods.items():
            setattr(self, name, fn)


# ── Read-only: sofort ausführen ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_reads_immediately(monkeypatch):
    monkeypatch.setattr(
        cal_tool_mod, "CalendarAgent",
        lambda: _MockAgent(get_events=lambda s, e: [_make_event("ev1", "Arzt")])
    )
    tool = cal_tool_mod.make_calendar_tool(7)
    result = await tool.handler({
        "action": "list",
        "start_iso": "2026-05-20T00:00:00",
        "end_iso": "2026-05-20T23:59:59",
    })
    text = result["content"][0]["text"]
    assert "ev1" in text
    assert "Arzt" in text
    assert app_state.peek_pending(7) is None


@pytest.mark.asyncio
async def test_list_requires_start_and_end():
    tool = cal_tool_mod.make_calendar_tool(7)
    result = await tool.handler({"action": "list", "start_iso": "2026-05-20T00:00:00"})
    assert result["content"][0]["text"].startswith("FEHLER")


@pytest.mark.asyncio
async def test_get_next_reads_immediately(monkeypatch):
    monkeypatch.setattr(
        cal_tool_mod, "CalendarAgent",
        lambda: _MockAgent(get_next_event=lambda: _make_event("ev2", "Zahnarzt"))
    )
    tool = cal_tool_mod.make_calendar_tool(7)
    result = await tool.handler({"action": "get_next"})
    text = result["content"][0]["text"]
    assert "ev2" in text
    assert "Zahnarzt" in text
    assert app_state.peek_pending(7) is None


@pytest.mark.asyncio
async def test_get_next_none(monkeypatch):
    monkeypatch.setattr(
        cal_tool_mod, "CalendarAgent",
        lambda: _MockAgent(get_next_event=lambda: None)
    )
    tool = cal_tool_mod.make_calendar_tool(7)
    result = await tool.handler({"action": "get_next"})
    assert "kein" in result["content"][0]["text"].lower()


@pytest.mark.asyncio
async def test_search_reads_immediately(monkeypatch):
    monkeypatch.setattr(
        cal_tool_mod, "CalendarAgent",
        lambda: _MockAgent(
            search_events=lambda q, s, e: [_make_event("ev3", "Teammeeting")]
        )
    )
    tool = cal_tool_mod.make_calendar_tool(7)
    result = await tool.handler({
        "action": "search", "query": "team",
        "start_iso": "2026-05-20T00:00:00",
        "end_iso": "2026-05-27T23:59:59",
    })
    assert "Teammeeting" in result["content"][0]["text"]
    assert app_state.peek_pending(7) is None


# ── Write: nur vormerken, nicht ausführen ─────────────────────────────────────

@pytest.mark.asyncio
async def test_create_stages_not_executes(monkeypatch):
    app_state.pending_agent_actions.clear()
    called = []
    monkeypatch.setattr(
        cal_tool_mod, "CalendarAgent",
        lambda: _MockAgent(create_event=lambda *a: called.append(a))
    )
    tool = cal_tool_mod.make_calendar_tool(7)
    result = await tool.handler({
        "action": "create",
        "title": "Arzttermin",
        "start_iso": "2026-05-20T10:00:00",
        "end_iso": "2026-05-20T11:00:00",
    })
    assert called == []
    assert "vorgemerkt" in result["content"][0]["text"].lower()
    entry = app_state.peek_pending(7)
    assert entry is not None
    a = entry["actions"][0]
    assert a["tool"] == "calendar"
    assert a["action"] == "create"
    assert a["params"]["title"] == "Arzttermin"
    app_state.pending_agent_actions.clear()


@pytest.mark.asyncio
async def test_delete_stages_not_executes(monkeypatch):
    app_state.pending_agent_actions.clear()
    called = []
    monkeypatch.setattr(
        cal_tool_mod, "CalendarAgent",
        lambda: _MockAgent(delete_event=lambda eid: called.append(eid))
    )
    tool = cal_tool_mod.make_calendar_tool(7)
    result = await tool.handler({
        "action": "delete", "event_id": "ev1", "title": "Meeting"
    })
    assert called == []
    assert "vorgemerkt" in result["content"][0]["text"].lower()
    entry = app_state.peek_pending(7)
    assert entry["actions"][0]["params"]["event_id"] == "ev1"
    app_state.pending_agent_actions.clear()


@pytest.mark.asyncio
async def test_update_stages_not_executes(monkeypatch):
    app_state.pending_agent_actions.clear()
    monkeypatch.setattr(cal_tool_mod, "CalendarAgent", lambda: _MockAgent())
    tool = cal_tool_mod.make_calendar_tool(7)
    result = await tool.handler({
        "action": "update",
        "event_id": "ev1",
        "title": "Meeting",
        "new_title": "Meeting (verschoben)",
        "new_start_iso": "2026-05-21T10:00:00",
    })
    assert "vorgemerkt" in result["content"][0]["text"].lower()
    a = app_state.peek_pending(7)["actions"][0]
    assert a["action"] == "update"
    assert a["params"]["new_title"] == "Meeting (verschoben)"
    app_state.pending_agent_actions.clear()


@pytest.mark.asyncio
async def test_create_requires_title_and_start():
    app_state.pending_agent_actions.clear()
    tool = cal_tool_mod.make_calendar_tool(7)
    result = await tool.handler({"action": "create", "title": "Termin"})
    assert result["content"][0]["text"].startswith("FEHLER")
    assert app_state.peek_pending(7) is None


@pytest.mark.asyncio
async def test_delete_requires_event_id():
    app_state.pending_agent_actions.clear()
    tool = cal_tool_mod.make_calendar_tool(7)
    result = await tool.handler({"action": "delete", "title": "Meeting"})
    assert result["content"][0]["text"].startswith("FEHLER")


@pytest.mark.asyncio
async def test_unknown_action_is_error():
    tool = cal_tool_mod.make_calendar_tool(7)
    result = await tool.handler({"action": "frobnicate"})
    assert result["content"][0]["text"].startswith("FEHLER")


# ── execute_write ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_execute_write_create(monkeypatch):
    calls = []
    monkeypatch.setattr(
        cal_tool_mod, "CalendarAgent",
        lambda: _MockAgent(create_event=lambda title, s, e: calls.append((title, s, e)))
    )
    msg = await cal_tool_mod.execute_write("create", {
        "title": "Arzttermin",
        "start_iso": "2026-05-20T10:00:00",
        "end_iso": "2026-05-20T11:00:00",
    })
    assert len(calls) == 1
    assert calls[0][0] == "Arzttermin"
    assert "✅" in msg


@pytest.mark.asyncio
async def test_execute_write_create_defaults_end_to_one_hour(monkeypatch):
    calls = []
    monkeypatch.setattr(
        cal_tool_mod, "CalendarAgent",
        lambda: _MockAgent(create_event=lambda title, s, e: calls.append((s, e)))
    )
    await cal_tool_mod.execute_write("create", {
        "title": "Termin",
        "start_iso": "2026-05-20T14:00:00",
        "end_iso": None,
    })
    assert len(calls) == 1
    start, end = calls[0]
    assert end - start == timedelta(hours=1)


@pytest.mark.asyncio
async def test_execute_write_create_exception(monkeypatch):
    monkeypatch.setattr(
        cal_tool_mod, "CalendarAgent",
        lambda: _MockAgent(create_event=lambda *a: (_ for _ in ()).throw(RuntimeError("API-Fehler")))
    )
    msg = await cal_tool_mod.execute_write("create", {
        "title": "X", "start_iso": "2026-05-20T10:00:00", "end_iso": None,
    })
    assert "❌" in msg


@pytest.mark.asyncio
async def test_execute_write_delete(monkeypatch):
    calls = []
    monkeypatch.setattr(
        cal_tool_mod, "CalendarAgent",
        lambda: _MockAgent(delete_event=lambda eid: calls.append(eid))
    )
    msg = await cal_tool_mod.execute_write("delete", {"event_id": "ev1", "title": "X"})
    assert calls == ["ev1"]
    assert "✅" in msg


@pytest.mark.asyncio
async def test_execute_write_delete_exception(monkeypatch):
    monkeypatch.setattr(
        cal_tool_mod, "CalendarAgent",
        lambda: _MockAgent(delete_event=lambda eid: (_ for _ in ()).throw(RuntimeError("404")))
    )
    msg = await cal_tool_mod.execute_write("delete", {"event_id": "ev1", "title": "X"})
    assert "❌" in msg


@pytest.mark.asyncio
async def test_execute_write_update(monkeypatch):
    calls = []
    monkeypatch.setattr(
        cal_tool_mod, "CalendarAgent",
        lambda: _MockAgent(
            update_event=lambda eid, ns, ne, nt, nl: calls.append((eid, ns, ne, nt, nl))
        )
    )
    msg = await cal_tool_mod.execute_write("update", {
        "event_id": "ev1", "title": "Alt",
        "new_title": "Neu", "new_start_iso": None,
        "new_end_iso": None, "new_location": None,
    })
    assert calls[0][0] == "ev1"
    assert calls[0][3] == "Neu"
    assert "✅" in msg


@pytest.mark.asyncio
async def test_execute_write_unknown_action():
    msg = await cal_tool_mod.execute_write("frobnicate", {})
    assert "Unbekannte" in msg
```

- [ ] **Step 2: Test laufen lassen — muss scheitern**

```bash
PYTHONPATH=agents .venv/bin/pytest tests/test_tools_calendar.py -v
```

- [ ] **Step 3: `agents/tools/calendar_tool.py` implementieren**

```python
"""calendar-Tool — Termine lesen und schreiben.

Read-Aktionen laufen sofort via asyncio.to_thread. Write-Aktionen (create/
update/delete) werden via app_state.stage_agent_action vorgemerkt und erst
nach Philipps Bestätigung durch execute_write ausgeführt.
"""

import asyncio
from datetime import datetime, timedelta

from claude_agent_sdk import tool
from zoneinfo import ZoneInfo

import app_state
from calendar_agent import CalendarAgent

BERLIN = ZoneInfo("Europe/Berlin")

_WRITE_ACTIONS = {"create", "update", "delete"}


def _parse_iso(s) -> datetime | None:
    """ISO-String → timezone-aware Berlin-datetime. None wenn leer/None."""
    if not s:
        return None
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=BERLIN)
    return dt


def _label(action: str, params: dict) -> str:
    title = (params.get("title") or "")[:60]
    if action == "create":
        start = (params.get("start_iso") or "")[:16].replace("T", " ")
        return f"Termin '{title}' anlegen ({start})"
    if action == "update":
        return f"Termin '{title}' ändern"
    if action == "delete":
        return f"Termin '{title}' absagen"
    return action


def _missing_fields(action: str, params: dict) -> str:
    required = {
        "create": ("title", "start_iso"),
        "update": ("event_id", "title"),
        "delete": ("event_id", "title"),
    }[action]
    return ", ".join(f for f in required if not params.get(f))


def _format_events(events) -> str:
    if not events:
        return "Keine Termine gefunden."
    parts = [f"📅 {len(events)} Termin(e):\n"]
    for ev in events:
        start = ev.start.strftime("%d.%m.%Y %H:%M")
        end = ev.end.strftime("%H:%M")
        location = f" ({ev.location})" if ev.location else ""
        parts.append(f"ID: {ev.id}\n{start}–{end} — {ev.title}{location}")
    return "\n\n".join(parts)


def _text(msg: str) -> dict:
    return {"content": [{"type": "text", "text": msg}]}


def make_calendar_tool(chat_id: int):
    """Baut das calendar-Tool für einen Lauf."""

    @tool(
        "calendar",
        "Outlook-Kalender lesen und schreiben. "
        "action='list' (start_iso, end_iso): Termine in einem Zeitfenster — gibt IDs zurück. "
        "action='search' (query, start_iso, end_iso): Termine nach Stichwort suchen. "
        "action='get_next': Nächster anstehender Termin. "
        "action='create' (title, start_iso, end_iso optional, location optional): "
        "Termin anlegen (end_iso-Default: start + 1 Stunde). "
        "action='update' (event_id, title, new_title optional, new_start_iso optional, "
        "new_end_iso optional, new_location optional): Termin ändern. "
        "action='delete' (event_id, title): Termin absagen. "
        "Alle start/end-Parameter als ISO 8601 (z.B. '2026-05-20T10:00:00'). "
        "title bei update/delete ist der aktuelle Titel (nur für den Confirm-Dialog). "
        "Write-Aktionen werden vorgemerkt und erst nach Philipps Bestätigung ausgeführt "
        "— sag ihm, was du vorbereitet hast.",
        {
            "action": str,
            "query": str,
            "start_iso": str,
            "end_iso": str,
            "event_id": str,
            "title": str,
            "location": str,
            "new_title": str,
            "new_start_iso": str,
            "new_end_iso": str,
            "new_location": str,
        },
    )
    async def calendar_tool(args: dict) -> dict:
        action = (args.get("action") or "").strip()
        agent = CalendarAgent()

        # ── Read-Aktionen ──────────────────────────────────────────────────
        if action == "list":
            start = _parse_iso(args.get("start_iso"))
            end = _parse_iso(args.get("end_iso"))
            if not start or not end:
                return _text("FEHLER: action='list' braucht: start_iso, end_iso.")
            events = await asyncio.to_thread(agent.get_events, start, end)
            return _text(_format_events(events))

        if action == "search":
            query = (args.get("query") or "").strip()
            start = _parse_iso(args.get("start_iso"))
            end = _parse_iso(args.get("end_iso"))
            if not query or not start or not end:
                return _text("FEHLER: action='search' braucht: query, start_iso, end_iso.")
            events = await asyncio.to_thread(agent.search_events, query, start, end)
            return _text(_format_events(events))

        if action == "get_next":
            event = await asyncio.to_thread(agent.get_next_event)
            if event is None:
                return _text("Kein kommender Termin gefunden.")
            start = event.start.strftime("%d.%m.%Y %H:%M")
            end = event.end.strftime("%H:%M")
            location = f" ({event.location})" if event.location else ""
            return _text(f"ID: {event.id}\n{start}–{end} — {event.title}{location}")

        if action not in _WRITE_ACTIONS:
            return _text(
                f"FEHLER: Unbekannte action '{action}'. Erlaubt: list, search, "
                "get_next, create, update, delete."
            )

        # ── Write-Aktionen: Pflichtfelder prüfen + vormerken ───────────────
        params = {
            "title": (args.get("title") or "").strip(),
            "start_iso": (args.get("start_iso") or "").strip(),
            "end_iso": (args.get("end_iso") or "").strip() or None,
            "location": (args.get("location") or "").strip() or None,
            "event_id": (args.get("event_id") or "").strip(),
            "new_title": (args.get("new_title") or "").strip() or None,
            "new_start_iso": (args.get("new_start_iso") or "").strip() or None,
            "new_end_iso": (args.get("new_end_iso") or "").strip() or None,
            "new_location": (args.get("new_location") or "").strip() or None,
        }
        missing = _missing_fields(action, params)
        if missing:
            return _text(f"FEHLER: action='{action}' braucht: {missing}.")
        label = _label(action, params)
        app_state.stage_agent_action(chat_id, "calendar", action, label, params)
        return _text(
            f"✅ Vorgemerkt: {label}. Wird nach Philipps Bestätigung ausgeführt "
            "— du musst nicht warten."
        )

    return calendar_tool


async def execute_write(action: str, params: dict) -> str:
    """Eine vorgemerkte calendar-Schreibaktion ausführen."""
    agent = CalendarAgent()

    if action == "create":
        start = _parse_iso(params["start_iso"])
        end = _parse_iso(params.get("end_iso")) or (start + timedelta(hours=1))
        try:
            await asyncio.to_thread(agent.create_event, params["title"], start, end)
            return f"✅ Termin '{params['title']}' angelegt ({start.strftime('%d.%m.%Y %H:%M')})."
        except Exception as e:
            return f"❌ Termin konnte nicht angelegt werden: {e}"

    if action == "update":
        new_start = _parse_iso(params.get("new_start_iso"))
        new_end = _parse_iso(params.get("new_end_iso"))
        try:
            await asyncio.to_thread(
                agent.update_event,
                params["event_id"],
                new_start,
                new_end,
                params.get("new_title"),
                params.get("new_location"),
            )
            return f"✅ Termin '{params['title']}' geändert."
        except Exception as e:
            return f"❌ Termin konnte nicht geändert werden: {e}"

    if action == "delete":
        try:
            await asyncio.to_thread(agent.delete_event, params["event_id"])
            return f"✅ Termin '{params['title']}' abgesagt."
        except Exception as e:
            return f"❌ Termin konnte nicht abgesagt werden: {e}"

    return f"❌ Unbekannte calendar-Aktion '{action}'."
```

Wichtig für `test_execute_write_create_exception`: CalendarAgent().create_event wirft eine Exception. Die Implementierung muss try/except haben.

Hinweis zu `test_execute_write_create_exception`: Der Generator-Trick `(_ for _ in ()).throw(RuntimeError(...))` funktioniert nicht direkt in Lambda. Stattdessen in Step 1 die Tests anpassen:

```python
# Alternative für Exception-Mock in Lambda:
def _raise_api_error(*a):
    raise RuntimeError("API-Fehler")

monkeypatch.setattr(
    cal_tool_mod, "CalendarAgent",
    lambda: _MockAgent(create_event=_raise_api_error)
)
```

Entsprechend auch für `test_execute_write_delete_exception`. Beim Schreiben der Tests (Step 1) bereits diese Form verwenden.

- [ ] **Step 4: Tests laufen lassen**

```bash
PYTHONPATH=agents .venv/bin/pytest tests/test_tools_calendar.py -v
```

Erwartetes Ergebnis: alle Tests grün.

- [ ] **Step 5: Gesamte Suite**

```bash
PYTHONPATH=agents .venv/bin/pytest tests/ -q --tb=short \
  --ignore=tests/test_briefing_agent.py \
  --ignore=tests/test_mail_send.py \
  --ignore=tests/test_tasks_agent.py
```

- [ ] **Step 6: Commit**

```bash
git add agents/tools/calendar_tool.py tests/test_tools_calendar.py
git commit -m "feat(tools): calendar-Tool — list/search/get_next + create/update/delete"
```

---

## Task 3: Verdrahtung

**Files:**
- Modify: `agents/tools/__init__.py`
- Modify: `agents/dispatch.py`
- Modify: `agents/agent.py`

Keine neuen Tests — die Verdrahtungs-Tests stecken in `test_tools_registry.py` und `test_agent_dispatch.py` die bereits existieren.

- [ ] **Step 1: `agents/tools/__init__.py` — mail_tool + calendar_tool registrieren**

Aktuelle `__init__.py` lesen, dann diese Änderungen vornehmen:

1. Import hinzufügen (nach `from . import tasks_tool`):
```python
from . import mail_tool
from . import calendar_tool
```

2. `_WRITE_EXECUTORS` erweitern:
```python
_WRITE_EXECUTORS: dict = {
    "tasks": tasks_tool.execute_write,
    "mail": mail_tool.execute_write,
    "calendar": calendar_tool.execute_write,
}
```

3. `_all_tools` erweitern:
```python
def _all_tools(chat_id: int) -> list:
    return _STATIC_TOOLS + [
        tasks_tool.make_tasks_tool(chat_id),
        mail_tool.make_mail_tool(chat_id),
        calendar_tool.make_calendar_tool(chat_id),
    ]
```

- [ ] **Step 2: `test_tools_registry.py` — neue Tools prüfen**

In der bestehenden Datei `tests/test_tools_registry.py`:
- Prüfen ob `mail` und `calendar` in `_ALLOWED_TOOL_NAMES` sind
- Prüfen ob `execute_pending_action` für `mail` und `calendar` die richtigen Executors findet

```bash
PYTHONPATH=agents .venv/bin/pytest tests/test_tools_registry.py -v
```

Falls Tests fehlen, diese zwei hinzufügen:

```python
def test_mail_and_calendar_in_allowed_tools():
    import tools
    assert "mcp__jarvis__mail" in tools._ALLOWED_TOOL_NAMES
    assert "mcp__jarvis__calendar" in tools._ALLOWED_TOOL_NAMES


def test_write_executors_have_mail_and_calendar():
    import tools
    assert "mail" in tools._WRITE_EXECUTORS
    assert "calendar" in tools._WRITE_EXECUTORS
```

- [ ] **Step 3: `agents/dispatch.py` — mail + calendar in `_AGENT_INTENTS`**

In `dispatch.py`:

1. Imports bereinigen — folgende Zeilen entfernen:
```python
from mail_handler import handle_mail_intent
from calendar_handler import handle_calendar_intent
```

2. `_HISTORY_INTENTS` erweitern:
```python
_HISTORY_INTENTS = {
    "personal", "work", "research",
    "weather", "news",
    "tasks", "reminder_write",
    "mail", "calendar",
}
```

3. `_AGENT_INTENTS` erweitern:
```python
_AGENT_INTENTS = {
    "personal", "work", "research",
    "weather", "news",
    "tasks", "reminder_write",
    "mail", "calendar",
}
```

4. Die alten `elif`-Branches entfernen (sie sind nach dem `if intent in _AGENT_INTENTS`-Block dead code):
```python
# ENTFERNEN:
elif intent == "calendar":
    await handle_calendar_intent(chat_id, text, params)
    return
elif intent == "mail":
    await handle_mail_intent(chat_id, text, params)
    return
```

- [ ] **Step 4: `agents/agent.py` — System-Prompt erweitern**

In `build_system_prompt()` die Werkzeug-Liste um mail + calendar ergänzen.

Bestehende tools-Liste (in `base`):
```
"- tasks: MS-To-Do-Listen lesen und ändern ..."
"- WebSearch / WebFetch: ..."
```

Erweitern zu:
```python
"- tasks: MS-To-Do-Listen lesen und ändern (Tasks/Erinnerungen anlegen, "
"abhaken, Listen verwalten). Schreib-Aktionen werden vorgemerkt.\n"
"- mail: E-Mails suchen (action='search'), lesen (list_unread/list_inbox/"
"list_folders/get_body) und schreiben (compose/reply/forward/archive/move/"
"delete/mark_read/mark_unread). Für Write-Aktionen zuerst die Mail via search "
"finden (gibt mail_id zurück), dann mit der mail_id die Aktion vormerken. "
"Schreib-Aktionen werden vorgemerkt und erst nach Philipps Bestätigung ausgeführt.\n"
"- calendar: Outlook-Kalender lesen (list/search/get_next) und schreiben "
"(create/update/delete). Für update/delete zuerst via search die event_id "
"ermitteln. Schreib-Aktionen werden vorgemerkt.\n"
"- WebSearch / WebFetch: Aktuelle Informationen aus dem Internet.\n\n"
```

- [ ] **Step 5: `test_agent_dispatch.py` — mail + calendar-Routing prüfen**

Prüfen ob die Routing-Tests für mail und calendar existieren. Falls nicht, zwei Tests hinzufügen (nach bestehendem Muster in `test_agent_dispatch.py`):

```python
@pytest.mark.asyncio
async def test_mail_routes_to_agent(monkeypatch):
    """mail-Intent läuft durch run_agent, nicht mehr durch handle_mail_intent."""
    ran = []
    monkeypatch.setattr("dispatch.run_agent", AsyncMock(side_effect=lambda *a, **k: ran.append(a) or "ok"))
    # sicherstellen dass handle_mail_intent nicht mehr importiert ist
    import dispatch as dispatch_mod
    assert not hasattr(dispatch_mod, "handle_mail_intent")
    await dispatch_mod._process_text("Zeig mir meine Mails", 42, _fake_update(42))
    # run_agent wurde aufgerufen (mail ist in _AGENT_INTENTS)
    # (der Router-Mock muss mail zurückgeben)


@pytest.mark.asyncio
async def test_calendar_routes_to_agent(monkeypatch):
    """calendar-Intent läuft durch run_agent."""
    import dispatch as dispatch_mod
    assert not hasattr(dispatch_mod, "handle_calendar_intent")
```

Hinweis: Die exakten Test-Implementierungen hängen vom bestehenden Muster in `test_agent_dispatch.py` ab — diese Datei zuerst lesen und das bestehende Muster für `tasks` / `weather` übernehmen.

- [ ] **Step 6: Gesamte Suite**

```bash
PYTHONPATH=agents .venv/bin/pytest tests/ -q --tb=short \
  --ignore=tests/test_briefing_agent.py \
  --ignore=tests/test_mail_send.py \
  --ignore=tests/test_tasks_agent.py
```

Erwartetes Ergebnis: alle Tests grün.

- [ ] **Step 7: Commit**

```bash
git add agents/tools/__init__.py agents/dispatch.py agents/agent.py tests/test_tools_registry.py tests/test_agent_dispatch.py
git commit -m "feat(dispatch): mail + calendar → _AGENT_INTENTS; tools-Registry + System-Prompt erweitert"
```

---

## Task 4: Cleanup — Handler, Callbacks, app_state, alte Tests

**Files:**
- Modify: `agents/callbacks.py` — alte mail/cal-Callbacks entfernen
- Modify: `agents/app_state.py` — alten mail/cal-Pending-State entfernen
- Delete: `agents/mail_handler.py`
- Delete: `agents/calendar_handler.py`
- Delete: `tests/test_mail_write.py`
- Delete: `tests/test_mail_send.py`
- Delete: `tests/test_calendar_write.py`
- Delete: `tests/test_calendar_modify.py`
- Delete: `tests/test_callback_main.py`
- Modify: `tests/test_calendar_read.py` (prüfen + ggf. behalten)
- Modify: `tests/test_dispatch_main.py` (mail/cal-Tests entfernen)
- Modify: `CLAUDE.md`

- [ ] **Step 1: `callbacks.py` bereinigen**

Folgende Imports entfernen:
```python
from calendar_handler import calendar_agent, _show_calendar_action_confirm
from mail_handler import _show_mail_action_confirm
```

Folgende Callback-Branches komplett entfernen (inkl. `elif data == ...:`):
- `elif data == "mail:send":` — kompletter Block
- `elif data == "mail:cancel":` — kompletter Block
- `elif data == "mail:action:confirm":` — kompletter Block
- `elif data == "mail:action:cancel":` — kompletter Block
- `elif data.startswith("mail:select:"):` — kompletter Block
- `elif data == "cal:action:confirm":` — kompletter Block
- `elif data == "cal:action:cancel":` — kompletter Block
- `elif data.startswith("cal:select:"):` — kompletter Block

Nach dem Entfernen darf `callbacks.py` nur noch `push:`, `dismiss`, `agent:confirm:` und `agent:cancel:` Branches haben.

Außerdem `import time` prüfen — nur behalten wenn noch anderswo in der Datei verwendet (nach Cleanup ggf. nicht mehr nötig).

- [ ] **Step 2: `app_state.py` bereinigen**

Folgende Einträge aus `app_state.py` entfernen:
- `pending_mail_ops: dict[int, dict] = {}` (oder wie auch immer deklariert)
- `pending_calendar_ops: dict[int, dict] = {}`
- `last_mail_search: dict[int, dict] = {}`
- `last_calendar_search: dict[int, dict] = {}`
- `_pending_op_expired(op)` Funktion — prüfen ob noch anderswo verwendet

Hinweis: Zuerst `app_state.py` lesen und alle Referenzen auf diese Symbole suchen. Die Funktion `_pending_op_expired` wird nach Cleanup nur noch in den entfernten Callbacks verwendet — sie kann gelöscht werden.

Exportiert `app_state.py` diese Symbole in `__init__.py` oder ähnlichem? Überprüfen.

- [ ] **Step 3: Alte Handler-Dateien löschen**

```bash
rm agents/mail_handler.py
rm agents/calendar_handler.py
```

Sicherstellen dass kein Import mehr auf diese Dateien zeigt:
```bash
grep -r "mail_handler\|calendar_handler" agents/ tests/
```

Nur `CLAUDE.md` und ggf. Kommentare dürfen noch Erwähnungen enthalten.

- [ ] **Step 4: Alte Test-Dateien prüfen und löschen**

`test_calendar_read.py` zuerst lesen: wenn es `from calendar_handler import ...` oder `from calendar_agent import CalendarAgent` und dann Methoden über den alten Handler testet → löschen. Wenn es `CalendarAgent` direkt testet (unit-level) → behalten und anpassen.

Prüfen und dann ausführen:
```bash
# Dateien die definitiv gelöscht werden:
rm tests/test_mail_write.py
rm tests/test_mail_send.py
rm tests/test_calendar_write.py
rm tests/test_calendar_modify.py
rm tests/test_callback_main.py
```

`test_dispatch_main.py` lesen: Einträge die `handle_mail_intent` oder `handle_calendar_intent` testen → entfernen. Einträge die andere Intents testen → behalten.

- [ ] **Step 5: Gesamte Suite — alle grün**

```bash
PYTHONPATH=agents .venv/bin/pytest tests/ -q --tb=short \
  --ignore=tests/test_briefing_agent.py \
  --ignore=tests/test_tasks_agent.py
```

Hinweis: `test_mail_send.py` ist jetzt gelöscht, also nicht mehr in der ignore-Liste nötig.

Erwartetes Ergebnis: alle Tests grün (mindestens so viele wie vorher, plus neue mail/calendar Tool-Tests).

- [ ] **Step 6: `CLAUDE.md` aktualisieren**

Folgende Abschnitte anpassen:

1. **Architektur-Diagramm** — `mail` und `calendar` aus den Handler-Zeilen entfernen, da sie jetzt agentisch laufen (unter `personal/work/research` → `run_agent` stehen)

2. **Pending-State-Tabelle** — `_pending_mail_ops`, `_pending_calendar_ops`, `_last_mail_search`, `_last_calendar_search` entfernen

3. **Callbacks-Tabelle** — folgende Zeilen entfernen:
   - `mail:send / mail:cancel`
   - `mail:action:confirm / mail:action:cancel`
   - `mail:select:{n}`
   - `cal:action:confirm / cal:action:cancel`
   - `cal:select:{n}`

4. **Agent-Intents** — `mail` und `calendar` als agentisch markieren

- [ ] **Step 7: Commit + Push**

```bash
git add -A
git commit -m "refactor(phase2): mail + calendar vollständig agentisch — Handler + alte Callbacks entfernt"
git push
```

Nach Push deployt der GitHub-Webhook automatisch auf den VPS.

---

## Smoke-Test nach Deploy (manuell via Telegram)

1. **Mail lesen:** „Zeig mir meine neuesten Mails" → Agent nutzt `mail` Tool, keine Buttons
2. **Mail schreiben:** „Schreib eine kurze Test-Mail an philipp.herrlich@googlemail.com" → Agent stages compose → ✅-Button erscheint → Confirm → Mail ankommt
3. **Mail archivieren:** „Archiviere die Test-Mail von mir" → Agent sucht via `search`, dann stages `archive` → Confirm
4. **Termin lesen:** „Was habe ich diese Woche für Termine?" → `calendar list` → sofort
5. **Termin anlegen:** „Leg morgen um 10 Uhr einen Test-Termin an" → stages `create` → Confirm → Outlook-Eintrag erscheint
6. **Termin löschen:** „Lösch den Test-Termin wieder" → Agent sucht via `search`, dann stages `delete` → Confirm
7. **Kombiniert:** „Schreib Max eine Mail und leg danach einen Termin mit ihm an" → beide Actions gebündelt → ein Confirm-Button für beide
