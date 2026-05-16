# Code-Gesundheit Phase 1 — Sicherheitsnetz — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pending-Ops bekommen ein 10-Minuten-TTL, und die ungetesteten kritischen `main.py`-Pfade (`handle_callback`, `github_webhook`) bekommen ein Charakterisierungs-Testnetz — als Voraussetzung für den `main.py`-Split in Phase 2.

**Architecture:** Phase 1 ist nicht-strukturell — kein Code wird verschoben. `main.py` bekommt eine `_PENDING_OP_TTL`-Konstante, einen `_pending_op_expired`-Helper, `staged_at`-Zeitstempel an 5 Staging-Stellen und Ablaufprüfungen in 3 Ausführungs-Callbacks. Neue Testdateien `test_callback_main.py` und `test_github_webhook.py` schreiben das Verhalten fest.

**Tech Stack:** Python 3.11 · pytest · `unittest.mock` (AsyncMock/MagicMock) · FastAPI

**Spec:** `docs/superpowers/specs/2026-05-16-codehealth-phase1-sicherheitsnetz-design.md`

**Tests lokal ausführen:**
```bash
PYTHONPATH=agents .venv/bin/pytest tests/ -q --tb=short \
  --ignore=tests/test_briefing_agent.py \
  --ignore=tests/test_mail_send.py \
  --ignore=tests/test_tasks_agent.py
```

---

## Task 1: Pending-Ops-TTL-Fix (TDD)

Confirm-Buttons sollen nach 10 Minuten ablaufen. Tests zuerst (Ablauf-Tests schlagen fehl, weil der alte Code abgelaufene Ops ausführt), dann der Fix.

**Files:**
- Create: `tests/test_callback_main.py`
- Modify: `agents/main.py`

- [ ] **Step 1: `tests/test_callback_main.py` mit Harness + 6 TTL-Tests anlegen**

```python
# tests/test_callback_main.py
import asyncio
import time
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import agents.main as main


def _make_cbq(data, chat_id=123):
    """Build a mock Telegram callback-query Update for handle_callback."""
    query = MagicMock()
    query.data = data
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.edit_message_reply_markup = AsyncMock()
    query.message = MagicMock()
    query.message.chat_id = chat_id
    query.message.reply_text = AsyncMock()
    update = MagicMock()
    update.callback_query = query
    return update


def _edited(update):
    """Return the text passed to edit_message_text."""
    return update.callback_query.edit_message_text.call_args[0][0]


@pytest.fixture(autouse=True)
def _clear_state():
    _dicts = (
        main._pending_mail_ops,
        main._pending_calendar_ops,
        main._last_mail_search,
        main._last_calendar_search,
    )
    for d in _dicts:
        d.clear()
    yield
    for d in _dicts:
        d.clear()


# --- TTL: expired pending ops must NOT execute ---

def test_mail_send_expired_op_is_rejected():
    main._pending_mail_ops[123] = {
        "type": "compose", "to_email": "a@b.de", "subject": "S", "body": "B",
        "staged_at": time.time() - 700,
    }
    update = _make_cbq("mail:send")
    with patch("mail_agent.MailAgent") as MockAgent:
        asyncio.run(main.handle_callback(update, None))
    MockAgent.assert_not_called()
    assert "Abgelaufen" in _edited(update)


def test_mail_action_confirm_expired_op_is_rejected():
    main._pending_mail_ops[123] = {
        "type": "archive", "mail_id": "m1", "subject": "S", "sender": "X",
        "staged_at": time.time() - 700,
    }
    update = _make_cbq("mail:action:confirm")
    with patch("mail_agent.MailAgent") as MockAgent:
        asyncio.run(main.handle_callback(update, None))
    MockAgent.assert_not_called()
    assert "Abgelaufen" in _edited(update)


def test_cal_action_confirm_expired_op_is_rejected():
    main._pending_calendar_ops[123] = {
        "type": "create", "title": "T",
        "start": datetime(2026, 6, 1, 10, 0), "end": datetime(2026, 6, 1, 11, 0),
        "staged_at": time.time() - 700,
    }
    update = _make_cbq("cal:action:confirm")
    with patch("agents.main.calendar_agent") as mock_cal:
        asyncio.run(main.handle_callback(update, None))
    mock_cal.create_event.assert_not_called()
    assert "Abgelaufen" in _edited(update)


# --- TTL: fresh pending ops DO execute ---

def test_mail_send_fresh_op_is_sent():
    main._pending_mail_ops[123] = {
        "type": "compose", "to_email": "a@b.de", "subject": "S", "body": "B",
        "staged_at": time.time(),
    }
    update = _make_cbq("mail:send")
    with patch("mail_agent.MailAgent") as MockAgent:
        MockAgent.return_value.send_mail.return_value = True
        asyncio.run(main.handle_callback(update, None))
    MockAgent.return_value.send_mail.assert_called_once()
    assert "gesendet" in _edited(update)


def test_mail_action_confirm_fresh_op_executes():
    main._pending_mail_ops[123] = {
        "type": "archive", "mail_id": "m1", "subject": "S", "sender": "X",
        "staged_at": time.time(),
    }
    update = _make_cbq("mail:action:confirm")
    with patch("mail_agent.MailAgent") as MockAgent:
        MockAgent.return_value.archive.return_value = True
        asyncio.run(main.handle_callback(update, None))
    MockAgent.return_value.archive.assert_called_once_with("m1")
    assert "archiviert" in _edited(update)


def test_cal_action_confirm_fresh_op_executes():
    main._pending_calendar_ops[123] = {
        "type": "delete", "event_id": "e1", "title": "Zahnarzt",
        "staged_at": time.time(),
    }
    update = _make_cbq("cal:action:confirm")
    with patch("agents.main.calendar_agent") as mock_cal:
        asyncio.run(main.handle_callback(update, None))
    mock_cal.delete_event.assert_called_once_with("e1")
    assert "abgesagt" in _edited(update)
```

- [ ] **Step 2: Tests laufen lassen — die 3 Ablauf-Tests müssen fehlschlagen**

Run: `PYTHONPATH=agents .venv/bin/pytest tests/test_callback_main.py -v`
Expected: die 3 `*_expired_*`-Tests FAIL (der alte Code führt abgelaufene Ops aus), die 3 `*_fresh_*`-Tests PASS.

- [ ] **Step 3: Konstante + Helper in `agents/main.py` ergänzen**

Edit `agents/main.py` — ersetze:
```python
_last_calendar_search: dict[int, dict] = {}
```
mit:
```python
_last_calendar_search: dict[int, dict] = {}

_PENDING_OP_TTL = 600  # Sekunden — Confirm-Buttons älter als 10 Min gelten als abgelaufen


def _pending_op_expired(op: dict) -> bool:
    """True wenn eine Pending-Op älter als _PENDING_OP_TTL ist."""
    return time.time() - op.get("staged_at", 0) > _PENDING_OP_TTL
```

- [ ] **Step 4: `staged_at` an Staging-Stelle 1 — `handle_mail` Compose**

Edit `agents/main.py` — ersetze:
```python
        _pending_mail_ops[chat_id] = {
            "type": "compose",
            "to_email": to_email,
            "subject": subject,
            "body": body,
        }
```
mit:
```python
        _pending_mail_ops[chat_id] = {
            "type": "compose",
            "to_email": to_email,
            "subject": subject,
            "body": body,
            "staged_at": time.time(),
        }
```

- [ ] **Step 5: `staged_at` an Staging-Stelle 2 — `_show_mail_action_confirm`**

Edit `agents/main.py` — ersetze:
```python
    _pending_mail_ops[chat_id] = {
        "type": mode,
        "mail_id": mail.id,
        "subject": mail.subject,
        "sender": sender,
        **{
```
mit:
```python
    _pending_mail_ops[chat_id] = {
        "type": mode,
        "mail_id": mail.id,
        "subject": mail.subject,
        "sender": sender,
        "staged_at": time.time(),
        **{
```

- [ ] **Step 6: `staged_at` an Staging-Stelle 3 — `handle_calendar` Write-Branch**

Edit `agents/main.py` — ersetze:
```python
        _pending_calendar_ops[chat_id] = {
            "type": "create",
            "title": title,
            "start": start,
            "end": end,
        }
```
mit:
```python
        _pending_calendar_ops[chat_id] = {
            "type": "create",
            "title": title,
            "start": start,
            "end": end,
            "staged_at": time.time(),
        }
```

- [ ] **Step 7: `staged_at` an Staging-Stelle 4 — `_show_calendar_action_confirm` (delete)**

Edit `agents/main.py` — ersetze:
```python
        _pending_calendar_ops[chat_id] = {
            "type": "delete",
            "event_id": event.id,
            "title": event.title,
        }
```
mit:
```python
        _pending_calendar_ops[chat_id] = {
            "type": "delete",
            "event_id": event.id,
            "title": event.title,
            "staged_at": time.time(),
        }
```

- [ ] **Step 8: `staged_at` an Staging-Stelle 5 — `_show_calendar_action_confirm` (update)**

Edit `agents/main.py` — ersetze:
```python
        _pending_calendar_ops[chat_id] = {
            "type": "update",
            "event_id": event.id,
            "title": new_title or event.title,
            "new_start": new_start,
            "new_end": new_end,
            "new_title": new_title,
            "new_location": new_location,
        }
```
mit:
```python
        _pending_calendar_ops[chat_id] = {
            "type": "update",
            "event_id": event.id,
            "title": new_title or event.title,
            "new_start": new_start,
            "new_end": new_end,
            "new_title": new_title,
            "new_location": new_location,
            "staged_at": time.time(),
        }
```

- [ ] **Step 9: Ablaufprüfung in `mail:send`**

Edit `agents/main.py` — ersetze:
```python
        draft = _pending_mail_ops.pop(chat_id, None)
        if draft is None:
            await query.edit_message_text("⚠️ Kein Entwurf mehr vorhanden.")
            return
        from mail_agent import MailAgent
```
mit:
```python
        draft = _pending_mail_ops.pop(chat_id, None)
        if draft is None:
            await query.edit_message_text("⚠️ Kein Entwurf mehr vorhanden.")
            return
        if _pending_op_expired(draft):
            await query.edit_message_text("⏱️ Abgelaufen — bitte nochmal.")
            return
        from mail_agent import MailAgent
```

- [ ] **Step 10: Ablaufprüfung in `mail:action:confirm`**

Edit `agents/main.py` — ersetze:
```python
        op = _pending_mail_ops.pop(chat_id, None)
        if op is None:
            await query.edit_message_text("⚠️ Keine ausstehende Aktion gefunden.")
            return
        from mail_agent import MailAgent
```
mit:
```python
        op = _pending_mail_ops.pop(chat_id, None)
        if op is None:
            await query.edit_message_text("⚠️ Keine ausstehende Aktion gefunden.")
            return
        if _pending_op_expired(op):
            await query.edit_message_text("⏱️ Abgelaufen — bitte nochmal.")
            return
        from mail_agent import MailAgent
```

- [ ] **Step 11: Ablaufprüfung in `cal:action:confirm`**

Edit `agents/main.py` — ersetze:
```python
        op = _pending_calendar_ops.pop(chat_id, None)
        if op is None:
            await query.edit_message_text("⚠️ Keine ausstehende Aktion gefunden.")
            return
        try:
```
mit:
```python
        op = _pending_calendar_ops.pop(chat_id, None)
        if op is None:
            await query.edit_message_text("⚠️ Keine ausstehende Aktion gefunden.")
            return
        if _pending_op_expired(op):
            await query.edit_message_text("⏱️ Abgelaufen — bitte nochmal.")
            return
        try:
```

- [ ] **Step 12: Tests laufen lassen — alle 6 müssen bestehen**

Run: `PYTHONPATH=agents .venv/bin/pytest tests/test_callback_main.py -v`
Expected: 6 passed.

- [ ] **Step 13: Komplette Suite**

Run:
```bash
PYTHONPATH=agents .venv/bin/pytest tests/ -q --tb=short \
  --ignore=tests/test_briefing_agent.py \
  --ignore=tests/test_mail_send.py \
  --ignore=tests/test_tasks_agent.py
```
Expected: PASS.

- [ ] **Step 14: Commit**

```bash
git add agents/main.py tests/test_callback_main.py
git commit -m "feat(callback): 10-Min-TTL für Pending-Confirm-Ops

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: `handle_callback` Mail-Branch-Charakterisierung

Charakterisierungs-Tests für die Mail-Callbacks und den Mail-Stage→Confirm-Roundtrip. Diese Tests schreiben das aktuelle Verhalten fest — sie bestehen sofort gegen den vorhandenen Code.

**Files:**
- Modify: `tests/test_callback_main.py`

- [ ] **Step 1: Mail-Branch-Tests ans Ende von `tests/test_callback_main.py` anhängen**

```python
# --- Mail callback branches (characterization) ---

def test_mail_cancel_discards_draft():
    main._pending_mail_ops[123] = {"type": "compose", "staged_at": time.time()}
    update = _make_cbq("mail:cancel")
    asyncio.run(main.handle_callback(update, None))
    assert 123 not in main._pending_mail_ops
    assert "verworfen" in _edited(update)


def test_mail_send_no_draft_warns():
    update = _make_cbq("mail:send")
    asyncio.run(main.handle_callback(update, None))
    assert "Kein Entwurf" in _edited(update)


def test_mail_action_confirm_no_op_warns():
    update = _make_cbq("mail:action:confirm")
    asyncio.run(main.handle_callback(update, None))
    assert "Keine ausstehende Aktion" in _edited(update)


@pytest.mark.parametrize(
    "op_type,method,extra,expect",
    [
        ("delete", "delete", {}, "gelöscht"),
        ("reply", "reply", {"reply_text": "ok"}, "Antwort gesendet"),
        ("forward", "forward", {"forward_to": "x@y.de"}, "weitergeleitet"),
    ],
)
def test_mail_action_confirm_executes(op_type, method, extra, expect):
    main._pending_mail_ops[123] = {
        "type": op_type, "mail_id": "m1", "subject": "S", "sender": "X",
        "staged_at": time.time(), **extra,
    }
    update = _make_cbq("mail:action:confirm")
    with patch("mail_agent.MailAgent") as MockAgent:
        getattr(MockAgent.return_value, method).return_value = True
        asyncio.run(main.handle_callback(update, None))
    getattr(MockAgent.return_value, method).assert_called_once()
    assert expect in _edited(update)


def test_mail_action_confirm_move():
    main._pending_mail_ops[123] = {
        "type": "move", "mail_id": "m1", "subject": "S", "sender": "X",
        "destination_folder": "Steuern", "staged_at": time.time(),
    }
    update = _make_cbq("mail:action:confirm")
    with patch("mail_agent.MailAgent") as MockAgent:
        folder = MagicMock()
        folder.id = "f1"
        MockAgent.return_value.find_folder_by_name.return_value = folder
        MockAgent.return_value.move.return_value = True
        asyncio.run(main.handle_callback(update, None))
    MockAgent.return_value.move.assert_called_once_with("m1", "f1")
    assert "verschoben" in _edited(update)


def test_mail_action_cancel_clears_state():
    main._pending_mail_ops[123] = {"type": "archive", "staged_at": time.time()}
    main._last_mail_search[123] = {"mails": [], "timestamp": time.time()}
    update = _make_cbq("mail:action:cancel")
    asyncio.run(main.handle_callback(update, None))
    assert 123 not in main._pending_mail_ops
    assert 123 not in main._last_mail_search
    assert "Abgebrochen" in _edited(update)


def test_mail_select_expired_search_warns():
    main._last_mail_search[123] = {
        "mails": [MagicMock()], "mode": "archive", "params": {},
        "timestamp": time.time() - 300,
    }
    update = _make_cbq("mail:select:0")
    asyncio.run(main.handle_callback(update, None))
    assert "abgelaufen" in _edited(update).lower()


def test_mail_select_picks_mail_and_shows_confirm():
    mail = MagicMock()
    mail.id = "m1"
    mail.subject = "S"
    mail.sender_name = "X"
    mail.sender_email = "x@y.de"
    main._last_mail_search[123] = {
        "mails": [mail], "mode": "archive", "params": {},
        "timestamp": time.time(),
    }
    update = _make_cbq("mail:select:0")
    with patch("agents.main._show_mail_action_confirm", new_callable=AsyncMock) as mock_show:
        asyncio.run(main.handle_callback(update, None))
    mock_show.assert_awaited_once()
    assert mock_show.await_args[0][1] is mail
    assert 123 not in main._last_mail_search


def test_mail_action_roundtrip_archive():
    """Stage via _show_mail_action_confirm → confirm via handle_callback."""
    from zoneinfo import ZoneInfo

    mail = MagicMock()
    mail.id = "m99"
    mail.subject = "Rechnung"
    mail.sender_name = "Stadtwerke"
    mail.sender_email = "sw@x.de"
    mail.received = datetime(2026, 5, 1, 9, 0, tzinfo=ZoneInfo("Europe/Berlin"))
    with patch("agents.main.Bot"):
        asyncio.run(main._show_mail_action_confirm(123, mail, "archive", {}))
    assert main._pending_mail_ops[123]["type"] == "archive"
    assert main._pending_mail_ops[123]["mail_id"] == "m99"
    assert "staged_at" in main._pending_mail_ops[123]

    update = _make_cbq("mail:action:confirm")
    with patch("mail_agent.MailAgent") as MockAgent:
        MockAgent.return_value.archive.return_value = True
        asyncio.run(main.handle_callback(update, None))
    MockAgent.return_value.archive.assert_called_once_with("m99")
```

- [ ] **Step 2: Tests laufen lassen**

Run: `PYTHONPATH=agents .venv/bin/pytest tests/test_callback_main.py -v`
Expected: alle Tests grün (die 6 aus Task 1 + die neuen). Falls ein Charakterisierungs-Test einen echten Bug aufdeckt: melden, nicht einbetonieren.

- [ ] **Step 3: Commit**

```bash
git add tests/test_callback_main.py
git commit -m "test(callback): Charakterisierungs-Tests für Mail-Callbacks

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: `handle_callback` Kalender-Branch-Charakterisierung + push/dismiss

Charakterisierungs-Tests für die Kalender-Callbacks, `push:`/`dismiss` und den Kalender-Stage→Confirm-Roundtrip.

**Files:**
- Modify: `tests/test_callback_main.py`

- [ ] **Step 1: Kalender-/push-Tests ans Ende von `tests/test_callback_main.py` anhängen**

```python
# --- push / dismiss / calendar callback branches (characterization) ---

def test_push_triggers_git_push():
    update = _make_cbq("push:immo-radar")
    with patch("vps.git_push", new_callable=AsyncMock, return_value=True) as mock_push:
        asyncio.run(main.handle_callback(update, None))
    mock_push.assert_awaited_once_with("immo-radar")
    update.callback_query.message.reply_text.assert_awaited()


def test_dismiss_removes_keyboard():
    update = _make_cbq("dismiss")
    asyncio.run(main.handle_callback(update, None))
    update.callback_query.edit_message_reply_markup.assert_awaited_once()


def test_cal_action_confirm_create_executes():
    main._pending_calendar_ops[123] = {
        "type": "create", "title": "Zahnarzt",
        "start": datetime(2026, 6, 1, 10, 0), "end": datetime(2026, 6, 1, 11, 0),
        "staged_at": time.time(),
    }
    update = _make_cbq("cal:action:confirm")
    with patch("agents.main.calendar_agent") as mock_cal:
        asyncio.run(main.handle_callback(update, None))
    mock_cal.create_event.assert_called_once()
    assert "erstellt" in _edited(update)


def test_cal_action_confirm_update_executes():
    main._pending_calendar_ops[123] = {
        "type": "update", "event_id": "e1", "title": "Zahnarzt",
        "new_start": datetime(2026, 6, 1, 15, 0),
        "new_end": datetime(2026, 6, 1, 16, 0),
        "new_title": None, "new_location": None,
        "staged_at": time.time(),
    }
    update = _make_cbq("cal:action:confirm")
    with patch("agents.main.calendar_agent") as mock_cal:
        asyncio.run(main.handle_callback(update, None))
    mock_cal.update_event.assert_called_once()
    assert "geändert" in _edited(update)


def test_cal_action_confirm_no_op_warns():
    update = _make_cbq("cal:action:confirm")
    asyncio.run(main.handle_callback(update, None))
    assert "Keine ausstehende Aktion" in _edited(update)


def test_cal_action_cancel_clears_state():
    main._pending_calendar_ops[123] = {"type": "create", "staged_at": time.time()}
    main._last_calendar_search[123] = {"events": [], "timestamp": time.time()}
    update = _make_cbq("cal:action:cancel")
    asyncio.run(main.handle_callback(update, None))
    assert 123 not in main._pending_calendar_ops
    assert 123 not in main._last_calendar_search
    assert "Abgebrochen" in _edited(update)


def test_cal_select_expired_search_warns():
    main._last_calendar_search[123] = {
        "events": [MagicMock()], "mode": "delete", "params": {},
        "timestamp": time.time() - 300,
    }
    update = _make_cbq("cal:select:0")
    asyncio.run(main.handle_callback(update, None))
    assert "abgelaufen" in _edited(update).lower()


def test_cal_select_picks_event_and_shows_confirm():
    event = MagicMock()
    main._last_calendar_search[123] = {
        "events": [event], "mode": "delete", "params": {},
        "timestamp": time.time(),
    }
    update = _make_cbq("cal:select:0")
    with patch(
        "agents.main._show_calendar_action_confirm", new_callable=AsyncMock
    ) as mock_show:
        asyncio.run(main.handle_callback(update, None))
    mock_show.assert_awaited_once()
    assert mock_show.await_args[0][1] is event
    assert 123 not in main._last_calendar_search


def test_calendar_create_roundtrip():
    """Stage via handle_calendar write → confirm via handle_callback."""
    start = datetime(2026, 6, 1, 10, 0)
    with patch("agents.main.Bot"):
        asyncio.run(
            main.handle_calendar(123, "x", mode="write", title="Zahnarzt", start=start)
        )
    assert main._pending_calendar_ops[123]["type"] == "create"
    assert "staged_at" in main._pending_calendar_ops[123]

    update = _make_cbq("cal:action:confirm")
    with patch("agents.main.calendar_agent") as mock_cal:
        asyncio.run(main.handle_callback(update, None))
    mock_cal.create_event.assert_called_once()
```

- [ ] **Step 2: Tests laufen lassen**

Run: `PYTHONPATH=agents .venv/bin/pytest tests/test_callback_main.py -v`
Expected: alle Tests grün. Falls ein Test einen echten Bug aufdeckt: melden, nicht einbetonieren.

- [ ] **Step 3: Commit**

```bash
git add tests/test_callback_main.py
git commit -m "test(callback): Charakterisierungs-Tests für Kalender-Callbacks + push/dismiss

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: `github_webhook` HMAC-Tests

Die HMAC-Signatur-Validierung des GitHub-Webhooks ist ungetestet. Alle git/rsync/docker-Seiteneffekte werden gemockt.

**Files:**
- Create: `tests/test_github_webhook.py`

- [ ] **Step 1: `tests/test_github_webhook.py` anlegen**

```python
# tests/test_github_webhook.py
import asyncio
import hashlib
import hmac
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

import agents.main as main

_SECRET = "testsecret"


def _make_request(body: bytes, headers: dict):
    req = MagicMock()
    req.body = AsyncMock(return_value=body)
    req.headers = headers  # plain dict — .get() works like Headers
    return req


def _sign(body: bytes, secret: str = _SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _push_body(repo="immo-radar", ref="refs/heads/main") -> bytes:
    return json.dumps({"ref": ref, "repository": {"name": repo}}).encode()


def test_invalid_signature_rejected():
    body = _push_body()
    req = _make_request(
        body, {"X-Hub-Signature-256": "sha256=deadbeef", "X-GitHub-Event": "push"}
    )
    with patch.dict(os.environ, {"GITHUB_WEBHOOK_SECRET": _SECRET}):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(main.github_webhook(req))
    assert exc.value.status_code == 403


def test_missing_signature_rejected_when_secret_set():
    body = _push_body()
    req = _make_request(body, {"X-GitHub-Event": "push"})
    with patch.dict(os.environ, {"GITHUB_WEBHOOK_SECRET": _SECRET}):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(main.github_webhook(req))
    assert exc.value.status_code == 403


def test_no_secret_skips_validation():
    """Ohne GITHUB_WEBHOOK_SECRET findet keine Signaturprüfung statt."""
    body = _push_body(repo="not-configured")
    req = _make_request(body, {"X-GitHub-Event": "push"})
    with patch.dict(os.environ, {"GITHUB_WEBHOOK_SECRET": ""}):
        result = asyncio.run(main.github_webhook(req))
    # kein 403; unkonfiguriertes Repo wird sauber übersprungen
    assert result["ok"] is True


def test_valid_signature_processes_push():
    body = _push_body(repo="immo-radar")
    req = _make_request(
        body, {"X-Hub-Signature-256": _sign(body), "X-GitHub-Event": "push"}
    )
    with (
        patch.dict(
            os.environ, {"GITHUB_WEBHOOK_SECRET": _SECRET, "TELEGRAM_CHAT_ID": ""}
        ),
        patch("os.path.isdir", return_value=True),
        patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="Updated", stderr="")),
        patch("subprocess.Popen"),
    ):
        result = asyncio.run(main.github_webhook(req))
    assert result["ok"] is True
    assert result["repo"] == "immo-radar"
    assert result["pulled"] is True


def test_non_push_event_skipped():
    body = _push_body()
    req = _make_request(
        body, {"X-Hub-Signature-256": _sign(body), "X-GitHub-Event": "ping"}
    )
    with patch.dict(os.environ, {"GITHUB_WEBHOOK_SECRET": _SECRET}):
        result = asyncio.run(main.github_webhook(req))
    assert result.get("skipped")
```

- [ ] **Step 2: Tests laufen lassen**

Run: `PYTHONPATH=agents .venv/bin/pytest tests/test_github_webhook.py -v`
Expected: 5 passed.

- [ ] **Step 3: Komplette Suite**

Run:
```bash
PYTHONPATH=agents .venv/bin/pytest tests/ -q --tb=short \
  --ignore=tests/test_briefing_agent.py \
  --ignore=tests/test_mail_send.py \
  --ignore=tests/test_tasks_agent.py
```
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_github_webhook.py
git commit -m "test(webhook): HMAC-Validierungs-Tests für github_webhook

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: Deploy & Verifikation

- [ ] **Step 1: Pushen — löst Auto-Deploy via GitHub-Webhook aus**

```bash
git push
```

- [ ] **Step 2: Deploy prüfen** (falls Tailscale erreichbar)

```bash
ssh root@100.115.184.3 "cd /opt/herrlich-ai-platform && git log --oneline -1 && systemctl is-active jarvis"
```
Erwartet: jüngster Commit, Service `active`.

- [ ] **Step 3: TTL live gegenprüfen**

In Telegram (@jarvis_herrlich_bot): „Erstelle Termin TTL-Test morgen 9 Uhr" → der Confirm-Dialog erscheint. **Nicht** tippen, 10+ Minuten warten, dann „✅ Erstellen" tippen → erwartet: „⏱️ Abgelaufen — bitte nochmal." statt Termin-Erstellung. Danach denselben Befehl erneut, sofort bestätigen → Termin wird erstellt. Test-Termin in Outlook wieder löschen.

---

## Self-Review

**Spec-Coverage:**
- TTL-Konstante `_PENDING_OP_TTL = 600` + `_pending_op_expired`-Helper → Task 1 Step 3 ✅
- `staged_at` an allen 4 Staging-Stellen (5 Dict-Literale) → Task 1 Steps 4–8 ✅
- Ablaufprüfung in `mail:send` / `mail:action:confirm` / `cal:action:confirm` → Task 1 Steps 9–11 ✅
- Cancel-Callbacks ohne Prüfung → unverändert gelassen (Task 1 fasst sie nicht an) ✅
- `handle_callback` alle Branches: push/dismiss (T3), mail:send (T1+T2), mail:cancel (T2), mail:action:confirm alle 5 Typen (T1 archive, T2 delete/reply/forward/move), mail:action:cancel (T2), mail:select (T2), cal:action:confirm create/update/delete (T1 delete, T3 create/update), cal:action:cancel (T3), cal:select (T3) ✅
- TTL-Verhalten getestet (expired + fresh) → Task 1 ✅
- Stage→Confirm-Roundtrips Mail + Kalender → Task 2 + Task 3 ✅
- `github_webhook` HMAC gültig/ungültig/fehlend → Task 4 ✅
- Charakterisierungs-Hinweis (Bug melden statt einbetonieren) → in Tasks 2 + 3 als Step-Hinweis ✅

Keine Lücken.

**Placeholder-Scan:** Keine TBD/TODO; jeder Code-Step enthält vollständigen Code.

**Typ-Konsistenz:**
- `_pending_op_expired(op: dict) -> bool` — in Task 1 definiert, in den 3 Callback-Prüfungen aufgerufen.
- `staged_at` — Schlüssel-Name identisch in allen 5 Staging-Dicts und im Helper (`op.get("staged_at", 0)`).
- Test-Harness `_make_cbq` / `_edited` / `_clear_state` — in Task 1 in `test_callback_main.py` definiert, in Tasks 2 + 3 (gleiche Datei) genutzt.
- Patch-Ziele: `mail_agent.MailAgent` (funktionslokaler `from mail_agent import`), `agents.main.calendar_agent` (Modul-Singleton), `vps.git_push` (funktionslokaler Import), `agents.main.Bot` — konsistent über alle Tests.
