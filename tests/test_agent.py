"""Tests für agents/agent.py."""

import asyncio

import agent
import app_state


def test_agent_enabled_default_off(monkeypatch):
    monkeypatch.delenv("JARVIS_AGENT_ENABLED", raising=False)
    assert agent.agent_enabled() is False


def test_agent_enabled_on(monkeypatch):
    monkeypatch.setenv("JARVIS_AGENT_ENABLED", "1")
    assert agent.agent_enabled() is True
    monkeypatch.setenv("JARVIS_AGENT_ENABLED", "true")
    assert agent.agent_enabled() is True


def test_system_prompt_includes_memory_context():
    prompt = agent.build_system_prompt("=== Erinnerungen ===\nPhilipp mag Tee\n\n")
    assert "Philipp mag Tee" in prompt
    assert "workspace" in prompt


def test_system_prompt_empty_memory():
    prompt = agent.build_system_prompt("")
    assert prompt.startswith("Du bist Jarvis")


def test_format_history_interleaves_roles():
    history = [
        {"role": "user", "content": "Frage 1"},
        {"role": "assistant", "content": "Antwort 1"},
    ]
    text = agent.format_history(history)
    assert "Philipp: Frage 1" in text
    assert "Jarvis: Antwort 1" in text


def test_format_history_empty():
    assert agent.format_history([]) == ""


def test_format_history_caps_turns():
    history = [{"role": "user", "content": f"m{i}"} for i in range(100)]
    text = agent.format_history(history)
    # 100 Einträge -> auf _HISTORY_TURNS*2 (=30) gekappt -> 29 Zeilenumbrüche
    assert text.count("\n") == (agent._HISTORY_TURNS * 2) - 1


def test_build_user_prompt_with_history():
    history = [{"role": "user", "content": "alt"}]
    prompt = agent.build_user_prompt(history, "neue Frage")
    assert "[Bisheriger Gesprächsverlauf]" in prompt
    assert "[Aktuelle Nachricht]" in prompt
    assert "neue Frage" in prompt


def test_build_user_prompt_no_history():
    assert agent.build_user_prompt([], "nur die Frage") == "nur die Frage"


def test_agent_enabled_all_truthy_values(monkeypatch):
    for val in ("1", "true", "yes", "on", "True", "YES", " 1 "):
        monkeypatch.setenv("JARVIS_AGENT_ENABLED", val)
        assert agent.agent_enabled() is True, f"Expected True for {val!r}"


def test_get_agent_lock_returns_same_lock_per_chat():
    app_state.agent_run_locks.clear()
    lock_a1 = app_state.get_agent_lock(111)
    lock_a2 = app_state.get_agent_lock(111)
    lock_b = app_state.get_agent_lock(222)
    assert lock_a1 is lock_a2
    assert lock_a1 is not lock_b
    assert isinstance(lock_a1, asyncio.Lock)
