"""Tests für agents/tools/__init__.py — MCP-Server-Bau + Permission-Hook."""

import pytest
from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

import tools


def test_build_mcp_server_registers_tools():
    server = tools.build_mcp_server(0)
    assert server is not None
    assert "mcp__jarvis__workspace" in tools._ALLOWED_TOOL_NAMES
    assert "mcp__jarvis__weather" in tools._ALLOWED_TOOL_NAMES
    assert "mcp__jarvis__news" in tools._ALLOWED_TOOL_NAMES
    assert "mcp__jarvis__tasks" in tools._ALLOWED_TOOL_NAMES
    assert "mcp__jarvis__mail" in tools._ALLOWED_TOOL_NAMES
    assert "mcp__jarvis__calendar" in tools._ALLOWED_TOOL_NAMES


def test_write_executors_include_mail_and_calendar():
    assert "mail" in tools._WRITE_EXECUTORS
    assert "calendar" in tools._WRITE_EXECUTORS
    assert "tasks" in tools._WRITE_EXECUTORS


@pytest.mark.asyncio
async def test_permission_hook_allows_workspace():
    result = await tools.permission_hook(
        "mcp__jarvis__workspace", {"action": "read", "path": "x"}, None
    )
    assert isinstance(result, PermissionResultAllow)


@pytest.mark.asyncio
async def test_permission_hook_denies_unknown_tool():
    result = await tools.permission_hook("Bash", {}, None)
    assert isinstance(result, PermissionResultDeny)
    assert result.interrupt is False
