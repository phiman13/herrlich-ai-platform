"""Tests für agents/tools/calendar_tool.py."""

import pytest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import app_state
import tools.calendar_tool as cal_tool_mod

BERLIN = ZoneInfo("Europe/Berlin")


def _make_event(event_id="ev1", title="Meeting"):
    from calendar_agent import Event

    return Event(
        id=event_id,
        title=title,
        start=datetime(2026, 5, 20, 10, 0, tzinfo=BERLIN),
        end=datetime(2026, 5, 20, 11, 0, tzinfo=BERLIN),
        location=None,
        calendar_name="Outlook",
        source="outlook",
    )


class _MockAgent:
    def __init__(self, **methods):
        for name, fn in methods.items():
            setattr(self, name, fn)


# Read-only tests


@pytest.mark.asyncio
async def test_list_reads_immediately(monkeypatch):
    monkeypatch.setattr(
        cal_tool_mod,
        "CalendarAgent",
        lambda: _MockAgent(get_events=lambda s, e: [_make_event("ev1", "Arzt")]),
    )
    tool = cal_tool_mod.make_calendar_tool(7)
    result = await tool.handler(
        {
            "action": "list",
            "start_iso": "2026-05-20T00:00:00",
            "end_iso": "2026-05-20T23:59:59",
        }
    )
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
        cal_tool_mod,
        "CalendarAgent",
        lambda: _MockAgent(get_next_event=lambda: _make_event("ev2", "Zahnarzt")),
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
        cal_tool_mod, "CalendarAgent", lambda: _MockAgent(get_next_event=lambda: None)
    )
    tool = cal_tool_mod.make_calendar_tool(7)
    result = await tool.handler({"action": "get_next"})
    assert "kein" in result["content"][0]["text"].lower()


@pytest.mark.asyncio
async def test_search_reads_immediately(monkeypatch):
    monkeypatch.setattr(
        cal_tool_mod,
        "CalendarAgent",
        lambda: _MockAgent(
            search_events=lambda q, s, e: [_make_event("ev3", "Teammeeting")]
        ),
    )
    tool = cal_tool_mod.make_calendar_tool(7)
    result = await tool.handler(
        {
            "action": "search",
            "query": "team",
            "start_iso": "2026-05-20T00:00:00",
            "end_iso": "2026-05-27T23:59:59",
        }
    )
    assert "Teammeeting" in result["content"][0]["text"]
    assert app_state.peek_pending(7) is None


@pytest.mark.asyncio
async def test_search_requires_query_and_dates():
    tool = cal_tool_mod.make_calendar_tool(7)
    result = await tool.handler({"action": "search", "query": "team"})
    assert result["content"][0]["text"].startswith("FEHLER")


# Write: stage only


@pytest.mark.asyncio
async def test_create_stages_not_executes(monkeypatch):
    app_state.pending_agent_actions.clear()
    called = []
    monkeypatch.setattr(
        cal_tool_mod,
        "CalendarAgent",
        lambda: _MockAgent(create_event=lambda *a: called.append(a)),
    )
    tool = cal_tool_mod.make_calendar_tool(7)
    result = await tool.handler(
        {
            "action": "create",
            "title": "Arzttermin",
            "start_iso": "2026-05-20T10:00:00",
            "end_iso": "2026-05-20T11:00:00",
        }
    )
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
        cal_tool_mod,
        "CalendarAgent",
        lambda: _MockAgent(delete_event=lambda eid: called.append(eid)),
    )
    tool = cal_tool_mod.make_calendar_tool(7)
    result = await tool.handler(
        {"action": "delete", "event_id": "ev1", "title": "Meeting"}
    )
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
    result = await tool.handler(
        {
            "action": "update",
            "event_id": "ev1",
            "title": "Meeting",
            "new_title": "Meeting (verschoben)",
            "new_start_iso": "2026-05-21T10:00:00",
        }
    )
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
async def test_delete_requires_event_id_and_title():
    app_state.pending_agent_actions.clear()
    tool = cal_tool_mod.make_calendar_tool(7)
    result = await tool.handler({"action": "delete", "title": "Meeting"})
    assert result["content"][0]["text"].startswith("FEHLER")


@pytest.mark.asyncio
async def test_unknown_action_is_error():
    tool = cal_tool_mod.make_calendar_tool(7)
    result = await tool.handler({"action": "frobnicate"})
    assert result["content"][0]["text"].startswith("FEHLER")


@pytest.mark.asyncio
async def test_update_requires_at_least_one_change():
    app_state.pending_agent_actions.clear()
    tool = cal_tool_mod.make_calendar_tool(7)
    result = await tool.handler(
        {
            "action": "update",
            "event_id": "ev1",
            "title": "Meeting",
        }
    )
    assert result["content"][0]["text"].startswith("FEHLER")
    assert "mindestens ein neues Feld" in result["content"][0]["text"]
    assert app_state.peek_pending(7) is None
    app_state.pending_agent_actions.clear()


# execute_write


@pytest.mark.asyncio
async def test_execute_write_create(monkeypatch):
    calls = []
    monkeypatch.setattr(
        cal_tool_mod,
        "CalendarAgent",
        lambda: _MockAgent(
            create_event=lambda title, s, e: calls.append((title, s, e))
        ),
    )
    msg = await cal_tool_mod.execute_write(
        "create",
        {
            "title": "Arzttermin",
            "start_iso": "2026-05-20T10:00:00",
            "end_iso": "2026-05-20T11:00:00",
        },
    )
    assert len(calls) == 1
    assert calls[0][0] == "Arzttermin"
    assert "✅" in msg


@pytest.mark.asyncio
async def test_execute_write_create_defaults_end_to_one_hour(monkeypatch):
    calls = []
    monkeypatch.setattr(
        cal_tool_mod,
        "CalendarAgent",
        lambda: _MockAgent(create_event=lambda title, s, e: calls.append((s, e))),
    )
    await cal_tool_mod.execute_write(
        "create",
        {
            "title": "Termin",
            "start_iso": "2026-05-20T14:00:00",
            "end_iso": None,
        },
    )
    assert len(calls) == 1
    start, end = calls[0]
    assert end - start == timedelta(hours=1)


@pytest.mark.asyncio
async def test_execute_write_create_exception(monkeypatch):
    def _raise(*a):
        raise RuntimeError("API-Fehler")

    monkeypatch.setattr(
        cal_tool_mod, "CalendarAgent", lambda: _MockAgent(create_event=_raise)
    )
    msg = await cal_tool_mod.execute_write(
        "create",
        {
            "title": "X",
            "start_iso": "2026-05-20T10:00:00",
            "end_iso": None,
        },
    )
    assert "❌" in msg


@pytest.mark.asyncio
async def test_execute_write_delete(monkeypatch):
    calls = []
    monkeypatch.setattr(
        cal_tool_mod,
        "CalendarAgent",
        lambda: _MockAgent(delete_event=lambda eid: calls.append(eid)),
    )
    msg = await cal_tool_mod.execute_write("delete", {"event_id": "ev1", "title": "X"})
    assert calls == ["ev1"]
    assert "✅" in msg


@pytest.mark.asyncio
async def test_execute_write_delete_exception(monkeypatch):
    def _raise(eid):
        raise RuntimeError("404")

    monkeypatch.setattr(
        cal_tool_mod, "CalendarAgent", lambda: _MockAgent(delete_event=_raise)
    )
    msg = await cal_tool_mod.execute_write("delete", {"event_id": "ev1", "title": "X"})
    assert "❌" in msg


@pytest.mark.asyncio
async def test_execute_write_update(monkeypatch):
    calls = []
    monkeypatch.setattr(
        cal_tool_mod,
        "CalendarAgent",
        lambda: _MockAgent(
            update_event=lambda eid, ns, ne, nt, nl: calls.append((eid, ns, ne, nt, nl))
        ),
    )
    msg = await cal_tool_mod.execute_write(
        "update",
        {
            "event_id": "ev1",
            "title": "Alt",
            "new_title": "Neu",
            "new_start_iso": None,
            "new_end_iso": None,
            "new_location": None,
        },
    )
    assert calls[0][0] == "ev1"
    assert calls[0][3] == "Neu"
    assert "✅" in msg


@pytest.mark.asyncio
async def test_execute_write_unknown_action():
    msg = await cal_tool_mod.execute_write("frobnicate", {})
    assert "Unbekannte" in msg
