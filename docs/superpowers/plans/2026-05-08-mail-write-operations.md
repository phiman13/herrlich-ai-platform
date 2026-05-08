# Mail Write Operations (Phase 4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add mail write operations (mark read/unread, archive, move, delete, reply, forward) to the Jarvis mail agent with smart-search identification and confirmation dialogs.

**Architecture:** Extend the existing `mail` intent in router.py with 6 new modes. `mail_agent.py` gets private write helpers and 7 new public methods. `main.py` gets a unified pending-state dict, a two-step search→confirm flow, and new callback handlers. No new files except a test file.

**Tech Stack:** Python 3.11, MS Graph API, python-telegram-bot, pytest, unittest.mock

---

## File Map

| File | Changes |
|---|---|
| `agents/microsoft_auth.py` | Replace `Mail.Read` with `Mail.ReadWrite` in SCOPES |
| `agents/mail_agent.py` | 3 private write helpers + 7 public methods |
| `tests/test_mail_write.py` | NEW — unit tests for all 7 methods |
| `agents/router.py` | Extend mail intent with 6 new modes + 5 new params |
| `agents/main.py` | Rename state dict, add `_last_mail_search`, add `_handle_mail_write`, `_show_mail_action_confirm`, 3 new callbacks |

---

## Task 1: OAuth Scope Update

**Files:**
- Modify: `agents/microsoft_auth.py:12`

**Background:** The existing token was issued with `Mail.Read`. MS Graph write operations (archive, move, delete, reply, forward) require `Mail.ReadWrite`. MSAL will not automatically upgrade the cached token — re-authentication via the browser OAuth flow will be required after deploy.

- [ ] **Step 1: Update SCOPES**

In `agents/microsoft_auth.py`, change line 12 from:
```python
SCOPES = ["Mail.Read", "Mail.Send", "Tasks.ReadWrite", "Tasks.ReadWrite.Shared"]
```
to:
```python
SCOPES = ["Mail.ReadWrite", "Mail.Send", "Tasks.ReadWrite", "Tasks.ReadWrite.Shared"]
```

- [ ] **Step 2: Commit**

```bash
git add agents/microsoft_auth.py
git commit -m "feat(auth): Mail.ReadWrite scope für schreibenden Mail-Zugriff"
```

---

## Task 2: Write failing tests for all new mail_agent methods

**Files:**
- Create: `tests/test_mail_write.py`

All tests in this task will fail until Task 3 and Task 4 implement the methods.

- [ ] **Step 1: Create test file**

```python
# tests/test_mail_write.py
import pytest
import requests as _requests
from unittest.mock import patch, MagicMock


@pytest.fixture
def agent():
    from agents.mail_agent import MailAgent
    return MailAgent()


def _ok(status=200):
    r = MagicMock()
    r.status_code = status
    r.raise_for_status = MagicMock()
    return r


def _err(status=403):
    r = MagicMock()
    r.status_code = status
    r.raise_for_status = MagicMock(side_effect=_requests.HTTPError(str(status)))
    return r


# --- get_mail_body ---

class TestGetMailBody:
    def test_strips_html_tags(self, agent):
        mock_data = {
            "id": "mail123",
            "subject": "Test Subject",
            "from": {"emailAddress": {"name": "Anna", "address": "anna@x.com"}},
            "receivedDateTime": "2026-05-08T10:00:00Z",
            "body": {"contentType": "html", "content": "<p>Hello <b>World</b></p>"},
        }
        with patch("agents.mail_agent.get_access_token", return_value="tok"), \
             patch("requests.get", return_value=MagicMock(status_code=200, json=lambda: mock_data)):
            result = agent.get_mail_body("mail123")
        assert result["subject"] == "Test Subject"
        assert result["sender_name"] == "Anna"
        assert result["sender_email"] == "anna@x.com"
        assert "<" not in result["body_text"]
        assert "Hello" in result["body_text"]
        assert "World" in result["body_text"]

    def test_returns_empty_body_text_if_no_body(self, agent):
        mock_data = {
            "id": "mail999",
            "subject": "No body",
            "from": {"emailAddress": {"name": "X", "address": "x@x.com"}},
            "receivedDateTime": "2026-05-08T10:00:00Z",
        }
        with patch("agents.mail_agent.get_access_token", return_value="tok"), \
             patch("requests.get", return_value=MagicMock(status_code=200, json=lambda: mock_data)):
            result = agent.get_mail_body("mail999")
        assert result["body_text"] == ""


# --- mark_read ---

class TestMarkRead:
    def test_mark_read_patches_correct_url_and_payload(self, agent):
        with patch("agents.mail_agent.get_access_token", return_value="tok"), \
             patch("requests.patch", return_value=_ok(200)) as mock_patch:
            result = agent.mark_read("mail123", is_read=True)
        assert result is True
        url = mock_patch.call_args[0][0]
        assert "mail123" in url
        assert mock_patch.call_args[1]["json"] == {"isRead": True}

    def test_mark_unread_sends_false(self, agent):
        with patch("agents.mail_agent.get_access_token", return_value="tok"), \
             patch("requests.patch", return_value=_ok(200)) as mock_patch:
            result = agent.mark_read("mail123", is_read=False)
        assert result is True
        assert mock_patch.call_args[1]["json"] == {"isRead": False}

    def test_returns_false_on_error(self, agent):
        with patch("agents.mail_agent.get_access_token", return_value="tok"), \
             patch("requests.patch", return_value=_err(403)):
            result = agent.mark_read("mail123")
        assert result is False


# --- archive ---

class TestArchive:
    def test_posts_to_archive_endpoint(self, agent):
        with patch("agents.mail_agent.get_access_token", return_value="tok"), \
             patch("requests.post", return_value=_ok(200)) as mock_post:
            result = agent.archive("mail456")
        assert result is True
        url = mock_post.call_args[0][0]
        assert "mail456" in url
        assert url.endswith("/archive")

    def test_returns_false_on_error(self, agent):
        with patch("agents.mail_agent.get_access_token", return_value="tok"), \
             patch("requests.post", return_value=_err(403)):
            result = agent.archive("mail456")
        assert result is False


# --- move ---

class TestMove:
    def test_posts_to_move_endpoint_with_destination(self, agent):
        with patch("agents.mail_agent.get_access_token", return_value="tok"), \
             patch("requests.post", return_value=_ok(200)) as mock_post:
            result = agent.move("mail789", "folder_abc")
        assert result is True
        url = mock_post.call_args[0][0]
        assert "mail789" in url
        assert url.endswith("/move")
        assert mock_post.call_args[1]["json"] == {"destinationId": "folder_abc"}

    def test_returns_false_on_error(self, agent):
        with patch("agents.mail_agent.get_access_token", return_value="tok"), \
             patch("requests.post", return_value=_err(404)):
            result = agent.move("mail789", "folder_abc")
        assert result is False


# --- delete ---

class TestDelete:
    def test_calls_delete_on_correct_url(self, agent):
        with patch("agents.mail_agent.get_access_token", return_value="tok"), \
             patch("requests.delete", return_value=_ok(204)) as mock_del:
            result = agent.delete("mail_xyz")
        assert result is True
        url = mock_del.call_args[0][0]
        assert "mail_xyz" in url

    def test_returns_false_on_error(self, agent):
        with patch("agents.mail_agent.get_access_token", return_value="tok"), \
             patch("requests.delete", return_value=_err(403)):
            result = agent.delete("mail_xyz")
        assert result is False


# --- reply ---

class TestReply:
    def test_posts_comment_to_reply_endpoint(self, agent):
        with patch("agents.mail_agent.get_access_token", return_value="tok"), \
             patch("requests.post", return_value=_ok(202)) as mock_post:
            result = agent.reply("mail_abc", "Danke, passt gut!")
        assert result is True
        url = mock_post.call_args[0][0]
        assert "mail_abc" in url
        assert url.endswith("/reply")
        assert mock_post.call_args[1]["json"] == {"comment": "Danke, passt gut!"}

    def test_returns_false_on_error(self, agent):
        with patch("agents.mail_agent.get_access_token", return_value="tok"), \
             patch("requests.post", return_value=_err(403)):
            result = agent.reply("mail_abc", "text")
        assert result is False


# --- forward ---

class TestForward:
    def test_sends_recipients_and_comment(self, agent):
        with patch("agents.mail_agent.get_access_token", return_value="tok"), \
             patch("requests.post", return_value=_ok(202)) as mock_post:
            result = agent.forward("mail_def", ["bob@example.com"], "Zur Info")
        assert result is True
        url = mock_post.call_args[0][0]
        assert "mail_def" in url
        assert url.endswith("/forward")
        payload = mock_post.call_args[1]["json"]
        assert payload["toRecipients"][0]["emailAddress"]["address"] == "bob@example.com"
        assert payload["comment"] == "Zur Info"

    def test_multiple_recipients(self, agent):
        with patch("agents.mail_agent.get_access_token", return_value="tok"), \
             patch("requests.post", return_value=_ok(202)) as mock_post:
            result = agent.forward("mail_def", ["a@x.com", "b@x.com"])
        assert result is True
        payload = mock_post.call_args[1]["json"]
        assert len(payload["toRecipients"]) == 2

    def test_empty_comment_is_allowed(self, agent):
        with patch("agents.mail_agent.get_access_token", return_value="tok"), \
             patch("requests.post", return_value=_ok(202)) as mock_post:
            result = agent.forward("mail_def", ["a@x.com"])
        assert result is True
        assert mock_post.call_args[1]["json"]["comment"] == ""

    def test_returns_false_on_error(self, agent):
        with patch("agents.mail_agent.get_access_token", return_value="tok"), \
             patch("requests.post", return_value=_err(403)):
            result = agent.forward("mail_def", ["b@x.com"])
        assert result is False
```

- [ ] **Step 2: Run tests to verify they all fail**

```bash
.venv/bin/pytest tests/test_mail_write.py -v
```

Expected: All tests FAIL with `AttributeError: 'MailAgent' object has no attribute ...`

---

## Task 3: Implement mail_agent.py — private helpers + get_mail_body + mark_read

**Files:**
- Modify: `agents/mail_agent.py`

Add three private write helpers and the first two new public methods after the existing `send_mail()` method (which ends around line 233).

- [ ] **Step 1: Add private write helpers after the `send_mail` method**

After the closing `return False` of `send_mail()`, add:

```python
    def _patch(self, path: str, json_data: dict) -> None:
        url = f"{GRAPH_BASE}{path}"
        r = requests.patch(url, headers=self._get_headers(), json=json_data, timeout=15)
        if r.status_code not in (200, 204):
            self.logger.error("Graph PATCH error: %s %s", r.status_code, r.text[:200])
            r.raise_for_status()

    def _post_action(self, path: str, json_data: dict | None = None) -> None:
        url = f"{GRAPH_BASE}{path}"
        r = requests.post(
            url, headers=self._get_headers(), json=json_data or {}, timeout=15
        )
        if r.status_code not in (200, 202, 204):
            self.logger.error("Graph POST error: %s %s", r.status_code, r.text[:200])
            r.raise_for_status()

    def _delete_req(self, path: str) -> None:
        url = f"{GRAPH_BASE}{path}"
        r = requests.delete(url, headers=self._get_headers(), timeout=15)
        if r.status_code not in (200, 204):
            self.logger.error("Graph DELETE error: %s %s", r.status_code, r.text[:200])
            r.raise_for_status()
```

- [ ] **Step 2: Add `get_mail_body` and `mark_read`**

Directly after the private helpers:

```python
    def get_mail_body(self, mail_id: str) -> dict:
        import re as _re

        data = self._get(
            f"/me/messages/{mail_id}",
            params={"$select": "id,subject,from,receivedDateTime,body"},
        )
        body_content = data.get("body", {}).get("content", "")
        body_text = _re.sub(r"<[^>]+>", " ", body_content)
        body_text = _re.sub(r"\s+", " ", body_text).strip()[:500]
        sender = data.get("from", {}).get("emailAddress", {})
        return {
            "id": data["id"],
            "subject": data.get("subject", "(kein Betreff)"),
            "sender_name": sender.get("name", ""),
            "sender_email": sender.get("address", ""),
            "received": data.get("receivedDateTime", ""),
            "body_text": body_text,
        }

    def mark_read(self, mail_id: str, is_read: bool = True) -> bool:
        try:
            self._patch(f"/me/messages/{mail_id}", {"isRead": is_read})
            return True
        except Exception as e:
            self.logger.error("mark_read fehlgeschlagen: %s", e)
            return False
```

- [ ] **Step 3: Run TestGetMailBody and TestMarkRead**

```bash
.venv/bin/pytest tests/test_mail_write.py::TestGetMailBody tests/test_mail_write.py::TestMarkRead -v
```

Expected: 5 tests PASS

- [ ] **Step 4: Commit**

```bash
git add agents/mail_agent.py tests/test_mail_write.py
git commit -m "feat(mail): private write helpers + get_mail_body + mark_read"
```

---

## Task 4: Implement mail_agent.py — archive, move, delete, reply, forward

**Files:**
- Modify: `agents/mail_agent.py`

Add the remaining 5 public methods after `mark_read`.

- [ ] **Step 1: Add archive, move, delete**

```python
    def archive(self, mail_id: str) -> bool:
        try:
            self._post_action(f"/me/messages/{mail_id}/archive")
            return True
        except Exception as e:
            self.logger.error("archive fehlgeschlagen: %s", e)
            return False

    def move(self, mail_id: str, destination_folder_id: str) -> bool:
        try:
            self._post_action(
                f"/me/messages/{mail_id}/move",
                {"destinationId": destination_folder_id},
            )
            return True
        except Exception as e:
            self.logger.error("move fehlgeschlagen: %s", e)
            return False

    def delete(self, mail_id: str) -> bool:
        try:
            self._delete_req(f"/me/messages/{mail_id}")
            return True
        except Exception as e:
            self.logger.error("delete fehlgeschlagen: %s", e)
            return False
```

- [ ] **Step 2: Run archive/move/delete tests**

```bash
.venv/bin/pytest tests/test_mail_write.py::TestArchive tests/test_mail_write.py::TestMove tests/test_mail_write.py::TestDelete -v
```

Expected: 6 tests PASS

- [ ] **Step 3: Add reply and forward**

```python
    def reply(self, mail_id: str, comment: str) -> bool:
        try:
            self._post_action(f"/me/messages/{mail_id}/reply", {"comment": comment})
            return True
        except Exception as e:
            self.logger.error("reply fehlgeschlagen: %s", e)
            return False

    def forward(
        self, mail_id: str, to_emails: list[str], comment: str = ""
    ) -> bool:
        try:
            self._post_action(
                f"/me/messages/{mail_id}/forward",
                {
                    "toRecipients": [
                        {"emailAddress": {"address": e}} for e in to_emails
                    ],
                    "comment": comment,
                },
            )
            return True
        except Exception as e:
            self.logger.error("forward fehlgeschlagen: %s", e)
            return False
```

- [ ] **Step 4: Run all test_mail_write.py tests**

```bash
.venv/bin/pytest tests/test_mail_write.py -v
```

Expected: All 19 tests PASS

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
.venv/bin/pytest tests/ -q --tb=short \
  --ignore=tests/test_briefing_agent.py \
  --ignore=tests/test_mail_send.py \
  --ignore=tests/test_tasks_agent.py
```

Expected: 86+ tests pass, 0 failures

- [ ] **Step 6: Commit**

```bash
git add agents/mail_agent.py
git commit -m "feat(mail): archive, move, delete, reply, forward"
```

---

## Task 5: Update router.py — new mail write modes

**Files:**
- Modify: `agents/router.py:159-188`

Replace the mail intent block in the `_SYSTEM_TEMPLATE` string. The old block starts at the line `5. "mail" — Anfragen zu Outlook-Mails...` and ends before `6. "personal"`.

- [ ] **Step 1: Replace mail intent in _SYSTEM_TEMPLATE**

Find this exact text in `_SYSTEM_TEMPLATE` (lines 159–188):

```
5. "mail" — Anfragen zu Outlook-Mails (Posteingang, Ordner, Suche). NUR LESEN, keine Aktionen wie verschieben oder löschen. Außer mode=compose.
   Verfügbare Ordner: {MAIL_FOLDERS}

   Beispiele:
   - "Was Wichtiges im Posteingang?" → quick_scan
   - "Was hab ich verpasst?" / "Ungelesene Mails" → unread
   - "Hat mir Anna geschrieben?" → search
   - "Mails von letzter Woche zum Thema X" → search
   - "Was steht im Ordner 'Steuern'?" → quick_scan mit folder_name
   - "Welche Ordner gibt es?" → list_folders
   - "Schreibe eine Mail an anna@beispiel.de ..." → compose

   Parameter:
   - mode: "quick_scan" | "unread" | "search" | "list_folders" | "compose"
   - count: integer oder null (Anzahl Mails, default je nach mode)
   - sender: string oder null (Filter nach Absender, falls genannt)
   - subject_contains: string oder null (Filter nach Betreff)
   - since_iso: ISO-8601 datetime oder null (nur Mails ab diesem Zeitpunkt, relativ zu {HEUTE_ISO})
   - folder_name: string oder null (spezifischer Ordner, einer aus: {MAIL_FOLDERS})
   - to_email: string oder null (Empfänger-Adresse, nur bei mode=compose)
   - subject: string oder null (Betreff, nur bei mode=compose)
   - body: string oder null (Mail-Text auf Deutsch, nur bei mode=compose)

   Mode-Bestimmung:
   - "Posteingang" / "Was Neues" / "Aktuelle Mails" → quick_scan
   - "Ungelesene" / "Was hab ich verpasst" / "Was ist neu" → unread
   - "Hat mir X geschrieben" / "Mails von X" / "zum Thema Y" → search
   - "Welche Ordner" / "Liste meiner Ordner" → list_folders
   - Ordnerangaben wie "im Ordner X" setzen folder_name, mode bleibt je nach Hauptfrage
   - "Schreibe/Sende eine Mail an ..." → compose (extrahiere to_email, subject, body aus dem Text)
```

Replace with:

```
5. "mail" — Anfragen zu Outlook-Mails: lesen, suchen und schreiben.
   Verfügbare Ordner: {MAIL_FOLDERS}

   Beispiele:
   - "Was Wichtiges im Posteingang?" → quick_scan
   - "Was hab ich verpasst?" / "Ungelesene Mails" → unread
   - "Hat mir Anna geschrieben?" → search
   - "Mails von letzter Woche zum Thema X" → search
   - "Was steht im Ordner 'Steuern'?" → quick_scan mit folder_name
   - "Welche Ordner gibt es?" → list_folders
   - "Schreibe eine Mail an anna@beispiel.de ..." → compose
   - "Markiere die Mail von Sparkasse als gelesen" → mark_read
   - "Markiere als ungelesen" → mark_unread
   - "Archiviere die letzte Mail von Anna" → archive
   - "Verschiebe die Mail über Rechnung in den Ordner Steuern" → move
   - "Lösche die Mail von Newsletter XY" → delete
   - "Antworte auf die Mail von Anna mit: Passt mir gut" → reply
   - "Leite die Rechnung von Müller weiter an chef@firma.de" → forward

   Parameter:
   - mode: "quick_scan" | "unread" | "search" | "list_folders" | "compose" | "mark_read" | "mark_unread" | "archive" | "move" | "delete" | "reply" | "forward"
   - count: integer oder null (Anzahl Mails, default je nach mode)
   - sender: string oder null (Filter nach Absender, falls genannt)
   - subject_contains: string oder null (Filter nach Betreff)
   - since_iso: ISO-8601 datetime oder null (nur Mails ab diesem Zeitpunkt, relativ zu {HEUTE_ISO})
   - folder_name: string oder null (spezifischer Ordner, einer aus: {MAIL_FOLDERS})
   - to_email: string oder null (Empfänger-Adresse, nur bei mode=compose)
   - subject: string oder null (Betreff, nur bei mode=compose)
   - body: string oder null (Mail-Text auf Deutsch, nur bei mode=compose)
   - mail_query: string oder null (Freitext-Beschreibung der Zielmail, z.B. "letzte Mail von Sparkasse" — MUSS gesetzt sein bei mode=mark_read/unread/archive/move/delete/reply/forward)
   - reply_text: string oder null (Antworttext, nur bei mode=reply)
   - forward_to: string oder null (Empfänger-E-Mail, nur bei mode=forward)
   - forward_text: string oder null (optionaler Begleittext, nur bei mode=forward)
   - destination_folder: string oder null (Zielordner-Name, nur bei mode=move)

   Mode-Bestimmung:
   - "Posteingang" / "Was Neues" / "Aktuelle Mails" → quick_scan
   - "Ungelesene" / "Was hab ich verpasst" / "Was ist neu" → unread
   - "Hat mir X geschrieben" / "Mails von X" / "zum Thema Y" → search
   - "Welche Ordner" / "Liste meiner Ordner" → list_folders
   - Ordnerangaben wie "im Ordner X" setzen folder_name, mode bleibt je nach Hauptfrage
   - "Schreibe/Sende eine Mail an ..." → compose (extrahiere to_email, subject, body aus dem Text)
   - "Als gelesen/ungelesen markieren" → mark_read/mark_unread (mail_query = Beschreibung der Zielmail)
   - "Archivieren / Verschieben / Löschen" → archive/move/delete (mail_query = Beschreibung der Zielmail)
   - "Antworte auf ... mit ..." → reply (mail_query = Zielmail-Beschreibung, reply_text = Antworttext)
   - "Leite ... weiter an ..." → forward (mail_query = Zielmail-Beschreibung, forward_to = Empfänger-E-Mail)
   - Bei Write-Modes: mail_query MUSS gesetzt sein — alles was die Zielmail identifiziert (Absender, Betreff, Zeit)
```

- [ ] **Step 2: Commit**

```bash
git add agents/router.py
git commit -m "feat(router): neue Mail-Write-Modes (mark_read/unread, archive, move, delete, reply, forward)"
```

---

## Task 6: main.py — State setup, rename _pending_mail_drafts

**Files:**
- Modify: `agents/main.py:1` (add import)
- Modify: `agents/main.py:82` (rename dict, add new dicts)
- Modify: `agents/main.py:233` (compose code in handle_mail)
- Modify: `agents/main.py:889` (handle_callback mail:send)
- Modify: `agents/main.py:908` (handle_callback mail:cancel)

- [ ] **Step 1: Add `import time` to the top of main.py**

After `import asyncio` (line 5), add:
```python
import time
```

- [ ] **Step 2: Replace the state dict declarations**

Find (line 82):
```python
_pending_mail_drafts: dict[int, dict] = {}
```

Replace with:
```python
_pending_mail_ops: dict[int, dict] = {}
_last_mail_search: dict[int, dict] = {}
```

- [ ] **Step 3: Update compose code in handle_mail()**

Find in `handle_mail()`:
```python
        _pending_mail_drafts[chat_id] = {
            "to_email": to_email,
            "subject": subject,
            "body": body,
        }
```

Replace with:
```python
        _pending_mail_ops[chat_id] = {
            "type": "compose",
            "to_email": to_email,
            "subject": subject,
            "body": body,
        }
```

- [ ] **Step 4: Update mail:send callback in handle_callback()**

Find in `handle_callback()`:
```python
    elif data == "mail:send":
        chat_id = query.message.chat_id
        draft = _pending_mail_drafts.pop(chat_id, None)
```

Replace with:
```python
    elif data == "mail:send":
        chat_id = query.message.chat_id
        draft = _pending_mail_ops.pop(chat_id, None)
```

- [ ] **Step 5: Update mail:cancel callback in handle_callback()**

Find:
```python
    elif data == "mail:cancel":
        chat_id = query.message.chat_id
        _pending_mail_drafts.pop(chat_id, None)
        await query.edit_message_text("❌ Entwurf verworfen.")
```

Replace with:
```python
    elif data == "mail:cancel":
        chat_id = query.message.chat_id
        _pending_mail_ops.pop(chat_id, None)
        await query.edit_message_text("❌ Entwurf verworfen.")
```

- [ ] **Step 6: Run full test suite to verify no regressions**

```bash
.venv/bin/pytest tests/ -q --tb=short \
  --ignore=tests/test_briefing_agent.py \
  --ignore=tests/test_mail_send.py \
  --ignore=tests/test_tasks_agent.py
```

Expected: 86+ tests pass, 0 failures

- [ ] **Step 7: Commit**

```bash
git add agents/main.py
git commit -m "refactor(main): _pending_mail_drafts → _pending_mail_ops, add _last_mail_search"
```

---

## Task 7: main.py — _handle_mail_write + _show_mail_action_confirm

**Files:**
- Modify: `agents/main.py`

Add two new async functions and wire them into `handle_mail()`. Add these functions directly after the existing `handle_mail()` function (after line ~309).

- [ ] **Step 1: Add `_WRITE_MODES` constant and early return in handle_mail()**

At the top of `handle_mail()`, after `mode = params.get("mode", "quick_scan")` and after the `if mode == "compose":` block (after its `return`), add:

```python
    _WRITE_MODES = {"mark_read", "mark_unread", "archive", "move", "delete", "reply", "forward"}
    if mode in _WRITE_MODES:
        await _handle_mail_write(chat_id, mode, params)
        return
```

- [ ] **Step 2: Add `_handle_mail_write` function after `handle_mail()`**

```python
async def _handle_mail_write(chat_id: int, mode: str, params: dict) -> None:
    bot = Bot(token=TELEGRAM_TOKEN)
    from mail_agent import MailAgent

    mail_query = (
        params.get("mail_query")
        or params.get("sender")
        or params.get("subject_contains")
        or ""
    )
    if not mail_query:
        await bot.send_message(
            chat_id=chat_id,
            text="Welche Mail meinst du? Bitte beschreibe sie genauer (z.B. 'letzte Mail von X').",
        )
        return

    agent = MailAgent()
    try:
        mails = await asyncio.to_thread(agent.smart_search, mail_query, 50)
    except Exception as e:
        logger.exception("_handle_mail_write: smart_search fehlgeschlagen")
        await bot.send_message(chat_id=chat_id, text=f"❌ Suche fehlgeschlagen: {e}")
        return

    if not mails:
        await bot.send_message(
            chat_id=chat_id,
            text=f"Keine passende Mail gefunden für '{mail_query}'.",
        )
        return

    if len(mails) > 5:
        await bot.send_message(
            chat_id=chat_id,
            text="Zu viele Treffer — bitte genauer beschreiben (Absender, Betreff oder Datum nennen).",
        )
        return

    if len(mails) == 1:
        await _show_mail_action_confirm(chat_id, mails[0], mode, params)
        return

    # 2–5 results: show numbered list with InlineKeyboard buttons
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    berlin = BERLIN
    lines = ["🔍 *Welche Mail?*\n"]
    keyboard = []
    for i, m in enumerate(mails):
        date_str = m.received.astimezone(berlin).strftime("%d.%m %H:%M")
        sender = (m.sender_name or m.sender_email or "?")[:30]
        subject = m.subject[:60]
        lines.append(f"{i + 1}. *{sender}* — {date_str}\n   _{subject}_")
        keyboard.append([InlineKeyboardButton(str(i + 1), callback_data=f"mail:select:{i}")])

    _last_mail_search[chat_id] = {
        "mails": mails,
        "mode": mode,
        "params": params,
        "timestamp": time.time(),
    }
    await bot.send_message(
        chat_id=chat_id,
        text="\n\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
```

- [ ] **Step 3: Add `_show_mail_action_confirm` function after `_handle_mail_write`**

```python
async def _show_mail_action_confirm(chat_id: int, mail, mode: str, params: dict) -> None:
    bot = Bot(token=TELEGRAM_TOKEN)
    from mail_agent import MailAgent
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    berlin = BERLIN
    date_str = mail.received.astimezone(berlin).strftime("%d.%m.%Y %H:%M")
    sender = mail.sender_name or mail.sender_email or "?"
    subject_clean = mail.subject.replace("*", "").replace("_", "")[:80]

    # mark_read / mark_unread: execute directly, no confirm dialog
    if mode == "mark_read":
        agent = MailAgent()
        ok = await asyncio.to_thread(agent.mark_read, mail.id, True)
        await bot.send_message(
            chat_id=chat_id,
            text="✅ Als gelesen markiert." if ok else "❌ Fehlgeschlagen.",
        )
        return

    if mode == "mark_unread":
        agent = MailAgent()
        ok = await asyncio.to_thread(agent.mark_read, mail.id, False)
        await bot.send_message(
            chat_id=chat_id,
            text="✅ Als ungelesen markiert." if ok else "❌ Fehlgeschlagen.",
        )
        return

    # All other modes: build confirm dialog
    action_labels = {
        "archive": "📦 Archivieren?",
        "move": "📁 Verschieben?",
        "delete": "🗑️ Löschen?",
        "reply": "↩️ Antworten?",
        "forward": "↪️ Weiterleiten?",
    }
    confirm_labels = {
        "archive": "✅ Archivieren",
        "move": "✅ Verschieben",
        "delete": "✅ Löschen",
        "reply": "✅ Senden",
        "forward": "✅ Senden",
    }
    title = action_labels.get(mode, "❓ Ausführen?")
    confirm_label = confirm_labels.get(mode, "✅ Ja")

    # Fetch full body preview for reply/forward
    body_preview = ""
    if mode in ("reply", "forward"):
        try:
            agent = MailAgent()
            full = await asyncio.to_thread(agent.get_mail_body, mail.id)
            if full.get("body_text"):
                body_preview = f"\n\n📄 _{full['body_text'][:200]}_"
        except Exception:
            pass

    if mode == "reply":
        reply_text = params.get("reply_text", "")
        text = (
            f"↩️ *Antwort auf:*\nVon: {sender}\nBetreff: {subject_clean}\nDatum: {date_str}"
            f"{body_preview}\n\n*Deine Antwort:*\n_{reply_text}_"
        )
    elif mode == "forward":
        forward_to = params.get("forward_to", "")
        forward_text = params.get("forward_text", "")
        text = (
            f"↪️ *Weiterleiten an:* {forward_to}\nBetreff: {subject_clean}\nVon: {sender}"
            f"{body_preview}"
            + (f"\n\n_{forward_text}_" if forward_text else "")
        )
    elif mode == "move":
        dest = params.get("destination_folder", "?")
        text = f"📁 *Verschieben nach '{dest}'?*\n\nVon: {sender}\nBetreff: {subject_clean}\nDatum: {date_str}"
    else:
        text = f"{title}\n\nVon: {sender}\nBetreff: {subject_clean}\nDatum: {date_str}"

    _pending_mail_ops[chat_id] = {
        "type": mode,
        "mail_id": mail.id,
        "subject": mail.subject,
        "sender": sender,
        **{
            k: params[k]
            for k in ("reply_text", "forward_to", "forward_text", "destination_folder")
            if k in params
        },
    }

    keyboard = [[
        InlineKeyboardButton(confirm_label, callback_data="mail:action:confirm"),
        InlineKeyboardButton("❌ Abbrechen", callback_data="mail:action:cancel"),
    ]]
    await bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/ -q --tb=short \
  --ignore=tests/test_briefing_agent.py \
  --ignore=tests/test_mail_send.py \
  --ignore=tests/test_tasks_agent.py
```

Expected: 86+ tests pass, 0 failures

- [ ] **Step 5: Commit**

```bash
git add agents/main.py
git commit -m "feat(main): _handle_mail_write + _show_mail_action_confirm"
```

---

## Task 8: main.py — New callbacks

**Files:**
- Modify: `agents/main.py` (inside `handle_callback()`)

Add three new elif branches at the end of `handle_callback()`, after the `elif data == "mail:cancel":` block.

- [ ] **Step 1: Add `mail:action:confirm` callback**

After the existing `mail:cancel` block, add:

```python
    elif data == "mail:action:confirm":
        chat_id = query.message.chat_id
        op = _pending_mail_ops.pop(chat_id, None)
        if op is None:
            await query.edit_message_text("⚠️ Keine ausstehende Aktion gefunden.")
            return
        from mail_agent import MailAgent

        agent = MailAgent()
        op_type = op["type"]
        mail_id = op["mail_id"]
        try:
            if op_type == "archive":
                ok = await asyncio.to_thread(agent.archive, mail_id)
                msg = "✅ Mail archiviert." if ok else "❌ Archivieren fehlgeschlagen."
            elif op_type == "delete":
                ok = await asyncio.to_thread(agent.delete, mail_id)
                msg = "✅ Mail gelöscht." if ok else "❌ Löschen fehlgeschlagen."
            elif op_type == "move":
                folder_name = op.get("destination_folder", "")
                folder = await asyncio.to_thread(agent.find_folder_by_name, folder_name)
                if folder is None:
                    await query.edit_message_text(
                        f"❌ Ordner '{folder_name}' nicht gefunden."
                    )
                    return
                ok = await asyncio.to_thread(agent.move, mail_id, folder.id)
                msg = (
                    f"✅ Mail verschoben nach '{folder_name}'."
                    if ok
                    else "❌ Verschieben fehlgeschlagen."
                )
            elif op_type == "reply":
                comment = op.get("reply_text", "")
                ok = await asyncio.to_thread(agent.reply, mail_id, comment)
                msg = "✅ Antwort gesendet." if ok else "❌ Antwort fehlgeschlagen."
            elif op_type == "forward":
                to_raw = op.get("forward_to", "")
                to_emails = [e.strip() for e in to_raw.split(",") if "@" in e]
                comment = op.get("forward_text", "")
                ok = await asyncio.to_thread(agent.forward, mail_id, to_emails, comment)
                msg = (
                    f"✅ Mail weitergeleitet an {to_raw}."
                    if ok
                    else "❌ Weiterleiten fehlgeschlagen."
                )
            else:
                msg = "❌ Unbekannte Aktion."
        except Exception as e:
            logger.exception("mail:action:confirm fehlgeschlagen")
            msg = f"❌ Fehler: {e}"
        await query.edit_message_text(msg)

    elif data == "mail:action:cancel":
        chat_id = query.message.chat_id
        _pending_mail_ops.pop(chat_id, None)
        _last_mail_search.pop(chat_id, None)
        await query.edit_message_text("❌ Abgebrochen.")

    elif data.startswith("mail:select:"):
        chat_id = query.message.chat_id
        entry = _last_mail_search.get(chat_id)
        if entry is None or (time.time() - entry["timestamp"]) > 180:
            _last_mail_search.pop(chat_id, None)
            await query.edit_message_text("⏱️ Auswahl abgelaufen — bitte nochmal.")
            return
        try:
            idx = int(data.split(":")[-1])
            mails = entry["mails"]
            if idx >= len(mails):
                await query.edit_message_text("❌ Ungültige Auswahl.")
                return
        except (ValueError, IndexError):
            await query.edit_message_text("❌ Ungültige Auswahl.")
            return
        mail = mails[idx]
        mode = entry["mode"]
        params = entry["params"]
        _last_mail_search.pop(chat_id, None)
        await query.edit_message_reply_markup(reply_markup=None)
        await _show_mail_action_confirm(chat_id, mail, mode, params)
```

- [ ] **Step 2: Run full test suite**

```bash
.venv/bin/pytest tests/ -q --tb=short \
  --ignore=tests/test_briefing_agent.py \
  --ignore=tests/test_mail_send.py \
  --ignore=tests/test_tasks_agent.py
```

Expected: 86+ tests pass, 0 failures

- [ ] **Step 3: Commit**

```bash
git add agents/main.py
git commit -m "feat(main): mail:action:confirm/cancel und mail:select callbacks"
```

---

## Task 9: Deploy + Re-Auth

**Background:** After deploying, the existing Microsoft OAuth token does NOT have `Mail.ReadWrite`. Write operations will fail with 401 until the user re-authenticates via the browser OAuth flow to grant the new scope.

- [ ] **Step 1: Push and deploy**

```bash
git push
ssh root@100.115.184.3 "cd /root/agents && git pull && systemctl restart jarvis"
```

Expected output: `Already up to date.` or fast-forward, then service restarts.

- [ ] **Step 2: Verify service is running**

```bash
ssh root@100.115.184.3 "systemctl is-active jarvis"
```

Expected: `active`

- [ ] **Step 3: Re-authenticate via browser**

Open in browser: `https://herrlich.dev/oauth/microsoft/login?secret=<OAUTH_LOGIN_SECRET>`

(Replace `<OAUTH_LOGIN_SECRET>` with the value from `/root/agents/.env` on the VPS — field `OAUTH_LOGIN_SECRET`.)

Expected: Microsoft login page → grant permissions including Mail.ReadWrite → redirect back with "✅ Microsoft-Login erfolgreich."

- [ ] **Step 4: Test a write operation via Telegram**

Send to @jarvis_herrlich_bot: `Markiere die letzte Mail von [bekannter Absender] als gelesen`

Expected: Jarvis sucht → findet Mail → "✅ Als gelesen markiert." (kein Confirm-Dialog nötig)

- [ ] **Step 5: Test a destructive operation**

Send: `Archiviere die letzte Mail von [bekannter Absender]`

Expected: Jarvis sucht → zeigt Confirm-Dialog → nach Klick "✅ Archivieren" → "✅ Mail archiviert."

- [ ] **Step 6: Update BACKLOG.md**

Mark "MS Graph Phase 4: Schreibender Mail-Zugriff" in BACKLOG.md als erledigt (in die Erledigt-Sektion).

```bash
git add BACKLOG.md
git commit -m "docs(backlog): MS Graph Phase 4 abgeschlossen"
git push
```
