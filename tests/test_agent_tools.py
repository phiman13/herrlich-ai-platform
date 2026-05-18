"""Tests für agents/agent_tools.py."""

import agent_tools


def test_resolve_inside_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WORKSPACE_DIR", str(tmp_path))
    (tmp_path / "proj").mkdir()
    resolved = agent_tools._resolve_in_workspace("proj")
    assert resolved == (tmp_path / "proj").resolve()


def test_resolve_rejects_parent_traversal(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WORKSPACE_DIR", str(tmp_path))
    assert agent_tools._resolve_in_workspace("../secret") is None


def test_resolve_rejects_absolute_path(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WORKSPACE_DIR", str(tmp_path))
    assert agent_tools._resolve_in_workspace("/etc/passwd") is None


def test_resolve_root_itself_is_allowed(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WORKSPACE_DIR", str(tmp_path))
    assert agent_tools._resolve_in_workspace("") == tmp_path.resolve()
