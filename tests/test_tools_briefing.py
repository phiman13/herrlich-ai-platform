"""Tests für agents/tools/briefing_tool.py."""

import pytest
import tools.briefing_tool as briefing_tool_mod


@pytest.mark.asyncio
async def test_build_returns_briefing_text(monkeypatch):
    async def fake_briefing():
        return "Guten Morgen! Heute 22°C."

    monkeypatch.setattr(briefing_tool_mod, "_build_briefing", fake_briefing)
    result = await briefing_tool_mod.briefing_tool.handler({"action": "build"})
    assert "Guten Morgen" in result["content"][0]["text"]


@pytest.mark.asyncio
async def test_build_unknown_action_is_error(monkeypatch):
    async def fake_briefing():
        return "x"

    monkeypatch.setattr(briefing_tool_mod, "_build_briefing", fake_briefing)
    result = await briefing_tool_mod.briefing_tool.handler({"action": "frobnicate"})
    assert result["content"][0]["text"].startswith("FEHLER")


@pytest.mark.asyncio
async def test_build_empty_action_is_error(monkeypatch):
    async def fake_briefing():
        return "x"

    monkeypatch.setattr(briefing_tool_mod, "_build_briefing", fake_briefing)
    result = await briefing_tool_mod.briefing_tool.handler({})
    assert result["content"][0]["text"].startswith("FEHLER")
