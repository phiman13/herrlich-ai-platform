"""Tests für agents/tools/mail_tool.py."""

import pytest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import app_state
import tools.mail_tool as mail_tool_mod

BERLIN = ZoneInfo("Europe/Berlin")


def _make_mail(mail_id="m1", subject="Re: Meeting", is_read=False):
    from mail_agent import Mail

    return Mail(
        id=mail_id,
        subject=subject,
        sender_name="Max Muster",
        sender_email="max@example.com",
        received=datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc),
        is_read=is_read,
        preview="Vorschau...",
        folder="inbox",
        has_attachments=False,
    )


def _make_folder(name="Inbox", unread=2):
    from mail_agent import MailFolder

    return MailFolder(
        id="fid1",
        name=name,
        parent_id=None,
        child_count=0,
        unread_count=unread,
        total_count=10,
    )


class _MockAgent:
    def __init__(self, **methods):
        for name, fn in methods.items():
            setattr(self, name, fn)


# Read-only tests


@pytest.mark.asyncio
async def test_search_reads_immediately(monkeypatch):
    monkeypatch.setattr(
        mail_tool_mod,
        "MailAgent",
        lambda: _MockAgent(smart_search=lambda q, n: [_make_mail("m1", "Rechnung")]),
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
        mail_tool_mod,
        "MailAgent",
        lambda: _MockAgent(list_folders=lambda: [_make_folder("Posteingang", 3)]),
    )
    tool = mail_tool_mod.make_mail_tool(7)
    result = await tool.handler({"action": "list_folders"})
    assert "Posteingang" in result["content"][0]["text"]
    assert app_state.peek_pending(7) is None


@pytest.mark.asyncio
async def test_get_body_reads_immediately(monkeypatch):
    monkeypatch.setattr(
        mail_tool_mod,
        "MailAgent",
        lambda: _MockAgent(
            get_mail_body=lambda mid: {
                "sender_name": "Max",
                "sender_email": "max@e.de",
                "subject": "Re: Meeting",
                "received": "2026-05-19T12:00:00",
                "body_text": "Hallo Philipp, der Termin ...",
            }
        ),
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


@pytest.mark.asyncio
async def test_list_inbox_reads_immediately(monkeypatch):
    monkeypatch.setattr(
        mail_tool_mod,
        "MailAgent",
        lambda: _MockAgent(quick_scan=lambda n: [_make_mail("m2", "Newsletter")]),
    )
    tool = mail_tool_mod.make_mail_tool(7)
    result = await tool.handler({"action": "list_inbox"})
    assert "Newsletter" in result["content"][0]["text"]
    assert app_state.peek_pending(7) is None


# Write: stage only, don't execute


@pytest.mark.asyncio
async def test_archive_stages_not_executes(monkeypatch):
    app_state.pending_agent_actions.clear()
    called = []
    monkeypatch.setattr(
        mail_tool_mod,
        "MailAgent",
        lambda: _MockAgent(archive=lambda mid: called.append(mid) or True),
    )
    tool = mail_tool_mod.make_mail_tool(7)
    result = await tool.handler(
        {"action": "archive", "mail_id": "m1", "subject": "Re: Meeting"}
    )
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
        mail_tool_mod,
        "MailAgent",
        lambda: _MockAgent(send_mail=lambda *a: called.append(a) or True),
    )
    tool = mail_tool_mod.make_mail_tool(7)
    result = await tool.handler(
        {
            "action": "compose",
            "to_email": "x@y.de",
            "subject": "Hallo",
            "body": "Text hier",
        }
    )
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
        mail_tool_mod,
        "MailAgent",
        lambda: _MockAgent(delete=lambda mid: called.append(mid) or True),
    )
    tool = mail_tool_mod.make_mail_tool(7)
    result = await tool.handler(
        {"action": "delete", "mail_id": "m2", "subject": "Newsletter"}
    )
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


# execute_write


@pytest.mark.asyncio
async def test_execute_write_archive(monkeypatch):
    calls = []
    monkeypatch.setattr(
        mail_tool_mod,
        "MailAgent",
        lambda: _MockAgent(archive=lambda mid: calls.append(mid) or True),
    )
    msg = await mail_tool_mod.execute_write(
        "archive", {"mail_id": "m1", "subject": "X"}
    )
    assert calls == ["m1"]
    assert "✅" in msg


@pytest.mark.asyncio
async def test_execute_write_archive_failure(monkeypatch):
    monkeypatch.setattr(
        mail_tool_mod, "MailAgent", lambda: _MockAgent(archive=lambda mid: False)
    )
    msg = await mail_tool_mod.execute_write(
        "archive", {"mail_id": "m1", "subject": "X"}
    )
    assert "❌" in msg


@pytest.mark.asyncio
async def test_execute_write_compose(monkeypatch):
    calls = []
    monkeypatch.setattr(
        mail_tool_mod,
        "MailAgent",
        lambda: _MockAgent(send_mail=lambda to, s, b: calls.append((to, s, b)) or True),
    )
    msg = await mail_tool_mod.execute_write(
        "compose", {"to_email": "x@y.de", "subject": "Hallo", "body": "Text"}
    )
    assert calls == [("x@y.de", "Hallo", "Text")]
    assert "✅" in msg and "x@y.de" in msg


@pytest.mark.asyncio
async def test_execute_write_compose_failure(monkeypatch):
    monkeypatch.setattr(
        mail_tool_mod, "MailAgent", lambda: _MockAgent(send_mail=lambda *a: False)
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
        mail_tool_mod,
        "MailAgent",
        lambda: _MockAgent(
            find_folder_by_name=lambda n: folder_calls.append(n) or FakeFolder(),
            move=lambda mid, fid: move_calls.append((mid, fid)) or True,
        ),
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
        mail_tool_mod,
        "MailAgent",
        lambda: _MockAgent(find_folder_by_name=lambda n: None),
    )
    msg = await mail_tool_mod.execute_write(
        "move", {"mail_id": "m1", "destination_folder": "Nope", "subject": "X"}
    )
    assert "❌" in msg and "Nope" in msg


@pytest.mark.asyncio
async def test_execute_write_delete(monkeypatch):
    calls = []
    monkeypatch.setattr(
        mail_tool_mod,
        "MailAgent",
        lambda: _MockAgent(delete=lambda mid: calls.append(mid) or True),
    )
    msg = await mail_tool_mod.execute_write("delete", {"mail_id": "m1", "subject": "X"})
    assert calls == ["m1"]
    assert "✅" in msg


@pytest.mark.asyncio
async def test_execute_write_unknown_action():
    msg = await mail_tool_mod.execute_write("frobnicate", {})
    assert "Unbekannte" in msg


@pytest.mark.asyncio
async def test_list_unread_folder_not_found(monkeypatch):
    monkeypatch.setattr(
        mail_tool_mod,
        "MailAgent",
        lambda: _MockAgent(find_folder_by_name=lambda n: None),
    )
    tool = mail_tool_mod.make_mail_tool(7)
    result = await tool.handler(
        {"action": "list_unread", "folder_name": "Nichtvorhanden"}
    )
    text = result["content"][0]["text"]
    assert "FEHLER" in text
    assert "Nichtvorhanden" in text


@pytest.mark.asyncio
async def test_execute_write_forward_no_valid_email(monkeypatch):
    calls = []
    monkeypatch.setattr(
        mail_tool_mod,
        "MailAgent",
        lambda: _MockAgent(
            forward=lambda mid, tos, c: calls.append((mid, tos, c)) or True
        ),
    )
    msg = await mail_tool_mod.execute_write(
        "forward", {"mail_id": "m1", "to_email": "kein-at-zeichen", "comment": ""}
    )
    assert calls == []
    assert "❌" in msg
    assert "kein-at-zeichen" in msg


@pytest.mark.asyncio
async def test_execute_write_mark_read(monkeypatch):
    calls = []
    monkeypatch.setattr(
        mail_tool_mod,
        "MailAgent",
        lambda: _MockAgent(
            mark_read=lambda mid, flag: calls.append((mid, flag)) or True
        ),
    )
    msg = await mail_tool_mod.execute_write(
        "mark_read", {"mail_id": "m1", "subject": "X"}
    )
    assert calls == [("m1", True)]
    assert "✅" in msg


@pytest.mark.asyncio
async def test_execute_write_mark_unread(monkeypatch):
    calls = []
    monkeypatch.setattr(
        mail_tool_mod,
        "MailAgent",
        lambda: _MockAgent(
            mark_read=lambda mid, flag: calls.append((mid, flag)) or True
        ),
    )
    msg = await mail_tool_mod.execute_write(
        "mark_unread", {"mail_id": "m1", "subject": "X"}
    )
    assert calls == [("m1", False)]
    assert "✅" in msg
