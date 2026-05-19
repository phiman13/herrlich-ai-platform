"""Tests für agents/tools/weather_tool.py."""

import pytest

import tools.weather_tool as weather_tool_mod


@pytest.mark.asyncio
async def test_weather_tool_returns_forecast(monkeypatch):
    def fake_get_weather(period, time_of_day, location):
        return "☀️ 22°C, klar"

    monkeypatch.setattr(weather_tool_mod, "get_weather", fake_get_weather)
    result = await weather_tool_mod.weather_tool.handler(
        {"period": "today", "time_of_day": "", "location": ""}
    )
    assert result["content"][0]["text"] == "☀️ 22°C, klar"


@pytest.mark.asyncio
async def test_weather_tool_passes_params(monkeypatch):
    captured = {}

    def fake_get_weather(period, time_of_day, location):
        captured["args"] = (period, time_of_day, location)
        return "x"

    monkeypatch.setattr(weather_tool_mod, "get_weather", fake_get_weather)
    await weather_tool_mod.weather_tool.handler(
        {"period": "tomorrow", "time_of_day": "morning", "location": "Berlin"}
    )
    assert captured["args"] == ("tomorrow", "morning", "Berlin")


@pytest.mark.asyncio
async def test_weather_tool_defaults_to_today(monkeypatch):
    captured = {}

    def fake_get_weather(period, time_of_day, location):
        captured["args"] = (period, time_of_day, location)
        return "x"

    monkeypatch.setattr(weather_tool_mod, "get_weather", fake_get_weather)
    await weather_tool_mod.weather_tool.handler({})
    assert captured["args"] == ("today", None, None)
