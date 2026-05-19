"""Tests für agents/tools/news_tool.py."""

import pytest

import tools.news_tool as news_tool_mod


@pytest.mark.asyncio
async def test_news_tool_returns_news(monkeypatch):
    monkeypatch.setattr(
        news_tool_mod, "get_ai_news", lambda hours, max_items: "• Item 1 — Quelle"
    )
    result = await news_tool_mod.news_tool.handler({"hours": 24})
    assert "Item 1" in result["content"][0]["text"]


@pytest.mark.asyncio
async def test_news_tool_empty_feeds_message(monkeypatch):
    monkeypatch.setattr(news_tool_mod, "get_ai_news", lambda hours, max_items: "")
    result = await news_tool_mod.news_tool.handler({})
    assert "Keine AI-News" in result["content"][0]["text"]


@pytest.mark.asyncio
async def test_news_tool_default_hours(monkeypatch):
    captured = {}

    def fake_get_ai_news(hours, max_items):
        captured["hours"] = hours
        return "x"

    monkeypatch.setattr(news_tool_mod, "get_ai_news", fake_get_ai_news)
    await news_tool_mod.news_tool.handler({})
    assert captured["hours"] == 48
