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


def test_resolve_rejects_symlink_escape(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    secret_file = outside / "secret.txt"
    secret_file.write_text("top secret")

    # Symlink inside workspace pointing to the outside directory
    (workspace / "escape_link").symlink_to(outside)

    monkeypatch.setenv("JARVIS_WORKSPACE_DIR", str(workspace))
    assert agent_tools._resolve_in_workspace("escape_link/secret.txt") is None
