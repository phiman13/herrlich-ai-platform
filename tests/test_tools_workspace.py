"""Tests für agents/tools/workspace_tool.py."""

import tools.workspace_tool as agent_tools

import pytest


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


def test_do_read_returns_file_content(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WORKSPACE_DIR", str(tmp_path))
    (tmp_path / "hello.txt").write_text("Hallo Welt", encoding="utf-8")
    assert agent_tools._do_read("hello.txt") == "Hallo Welt"


def test_do_read_outside_workspace_is_error(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WORKSPACE_DIR", str(tmp_path))
    result = agent_tools._do_read("../secret")
    assert result.startswith("FEHLER:")


def test_do_read_missing_file_is_error(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WORKSPACE_DIR", str(tmp_path))
    result = agent_tools._do_read("nope.txt")
    assert result.startswith("FEHLER:")


def test_do_read_truncates_large_file(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WORKSPACE_DIR", str(tmp_path))
    (tmp_path / "big.txt").write_text("x" * 80_000, encoding="utf-8")
    result = agent_tools._do_read("big.txt")
    assert "[... gekürzt ...]" in result
    assert len(result) < 80_000


def test_do_read_binary_file_is_error(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WORKSPACE_DIR", str(tmp_path))
    (tmp_path / "img.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 10)
    result = agent_tools._do_read("img.png")
    assert result.startswith("FEHLER:")
    assert "Binärdatei" in result


def test_do_search_finds_matches(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WORKSPACE_DIR", str(tmp_path))
    (tmp_path / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("x = 2\n", encoding="utf-8")
    result = agent_tools._do_search("def foo")
    assert "a.py:1:" in result
    assert "b.py" not in result


def test_do_search_no_match(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WORKSPACE_DIR", str(tmp_path))
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    assert "Keine Treffer" in agent_tools._do_search("nichtdrin")


def test_do_search_skips_ignored_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WORKSPACE_DIR", str(tmp_path))
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "lib.js").write_text("needle", encoding="utf-8")
    (tmp_path / "src.js").write_text("needle", encoding="utf-8")
    result = agent_tools._do_search("needle")
    assert "src.js" in result
    assert "node_modules" not in result


def test_do_search_invalid_regex_is_error(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WORKSPACE_DIR", str(tmp_path))
    assert agent_tools._do_search("[unclosed").startswith("FEHLER:")


def test_do_search_outside_workspace_is_error(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WORKSPACE_DIR", str(tmp_path))
    result = agent_tools._do_search("needle", "../..")
    assert result.startswith("FEHLER:")


def test_do_list_shows_entries(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WORKSPACE_DIR", str(tmp_path))
    (tmp_path / "proj").mkdir()
    (tmp_path / "readme.md").write_text("x", encoding="utf-8")
    result = agent_tools._do_list("")
    assert "proj/" in result
    assert "readme.md" in result


def test_do_list_hides_dotfiles_and_skipdirs(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WORKSPACE_DIR", str(tmp_path))
    (tmp_path / ".git").mkdir()
    (tmp_path / ".env").write_text("x", encoding="utf-8")
    (tmp_path / "visible.txt").write_text("x", encoding="utf-8")
    result = agent_tools._do_list("")
    assert "visible.txt" in result
    assert ".git" not in result
    assert ".env" not in result


def test_do_list_non_directory_is_error(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WORKSPACE_DIR", str(tmp_path))
    assert agent_tools._do_list("nichtda").startswith("FEHLER:")


def test_do_list_empty_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WORKSPACE_DIR", str(tmp_path))
    (tmp_path / "empty").mkdir()
    assert agent_tools._do_list("empty") == "(leer)"


@pytest.mark.asyncio
async def test_workspace_tool_read(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WORKSPACE_DIR", str(tmp_path))
    (tmp_path / "f.txt").write_text("Inhalt", encoding="utf-8")
    result = await agent_tools.workspace_tool.handler(
        {"action": "read", "path": "f.txt", "query": ""}
    )
    assert result["content"][0]["text"] == "Inhalt"


@pytest.mark.asyncio
async def test_workspace_tool_unknown_action(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WORKSPACE_DIR", str(tmp_path))
    result = await agent_tools.workspace_tool.handler(
        {"action": "delete", "path": "f.txt", "query": ""}
    )
    assert result["content"][0]["text"].startswith("FEHLER:")


@pytest.mark.asyncio
async def test_workspace_tool_search_empty_query(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WORKSPACE_DIR", str(tmp_path))
    result = await agent_tools.workspace_tool.handler(
        {"action": "search", "path": "", "query": ""}
    )
    assert result["content"][0]["text"].startswith("FEHLER:")
