"""Tests für den Write-Confirm-Pending-Store in app_state."""

import time

import app_state


def _clear():
    app_state.pending_agent_actions.clear()


def test_stage_and_peek():
    _clear()
    app_state.stage_agent_action(1, "tasks", "add", "Task X anlegen", {"title": "X"})
    entry = app_state.peek_pending(1)
    assert entry is not None
    assert isinstance(entry["id"], int)
    assert len(entry["actions"]) == 1
    assert entry["actions"][0]["tool"] == "tasks"
    assert entry["actions"][0]["label"] == "Task X anlegen"
    # peek entnimmt nicht
    assert app_state.peek_pending(1) is not None


def test_stage_appends_within_same_set():
    _clear()
    app_state.stage_agent_action(1, "tasks", "add", "A", {})
    id1 = app_state.peek_pending(1)["id"]
    app_state.stage_agent_action(1, "tasks", "complete", "B", {})
    entry = app_state.peek_pending(1)
    assert len(entry["actions"]) == 2
    assert entry["id"] == id1  # gleicher Lauf -> gleiches Set


def test_take_with_matching_id_consumes():
    _clear()
    app_state.stage_agent_action(1, "tasks", "add", "A", {})
    pid = app_state.peek_pending(1)["id"]
    taken = app_state.take_pending_actions(1, pid)
    assert len(taken) == 1
    assert app_state.peek_pending(1) is None


def test_take_with_wrong_id_returns_empty_and_keeps():
    _clear()
    app_state.stage_agent_action(1, "tasks", "add", "A", {})
    pid = app_state.peek_pending(1)["id"]
    assert app_state.take_pending_actions(1, pid + 999) == []
    # falsche ID -> Eintrag bleibt unangetastet
    assert app_state.peek_pending(1) is not None


def test_new_set_after_clear_gets_new_id():
    _clear()
    app_state.stage_agent_action(1, "tasks", "add", "A", {})
    id1 = app_state.peek_pending(1)["id"]
    app_state.clear_pending_actions(1)
    app_state.stage_agent_action(1, "tasks", "add", "B", {})
    id2 = app_state.peek_pending(1)["id"]
    assert id2 != id1
    # alter Button (id1) greift nicht mehr, neuer schon
    assert app_state.take_pending_actions(1, id1) == []
    assert len(app_state.take_pending_actions(1, id2)) == 1


def test_clear_discards():
    _clear()
    app_state.stage_agent_action(1, "tasks", "add", "A", {})
    app_state.clear_pending_actions(1)
    assert app_state.peek_pending(1) is None


def test_expired_set_ignored():
    _clear()
    app_state.pending_agent_actions[1] = {
        "id": 999,
        "actions": [{"tool": "tasks", "action": "add", "label": "alt", "params": {}}],
        "staged_at": time.time() - app_state._PENDING_OP_TTL - 1,
    }
    assert app_state.peek_pending(1) is None
    assert app_state.take_pending_actions(1, 999) == []


def test_per_chat_isolation():
    _clear()
    app_state.stage_agent_action(1, "tasks", "add", "Chat1", {})
    app_state.stage_agent_action(2, "tasks", "add", "Chat2", {})
    assert app_state.peek_pending(1)["actions"][0]["label"] == "Chat1"
    assert app_state.peek_pending(2)["actions"][0]["label"] == "Chat2"
