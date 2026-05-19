# tests/test_briefing_agent.py
import pytest
from unittest.mock import patch

try:
    from agents.briefing_agent import build_briefing
except ImportError:
    from briefing_agent import build_briefing


@pytest.mark.asyncio
async def test_build_briefing_contains_all_sections():
    with (
        patch("agents.briefing_agent.get_weather", return_value="☀️ 20°C, klar"),
        patch(
            "agents.briefing_agent.get_ai_news",
            return_value="• GPT-5 released — OpenAI",
        ),
        patch(
            "agents.briefing_agent.get_github_summary", return_value="💻 GITHUB — 0 PRs"
        ),
        patch("agents.briefing_agent._get_open_tasks", return_value=""),
        patch(
            "agents.briefing_agent._get_calendar_today", return_value="10:00 Meeting"
        ),
        patch("agents.briefing_agent._get_mail_unread", return_value=""),
    ):
        result = await build_briefing()

    assert "Guten Morgen" in result
    assert "KALENDER" in result or "📅" in result
    assert "WETTER" in result or "☀️" in result
    assert "GPT-5" in result


@pytest.mark.asyncio
async def test_build_briefing_skips_empty_sections():
    with (
        patch("agents.briefing_agent.get_weather", return_value="☀️ 20°C"),
        patch("agents.briefing_agent.get_ai_news", return_value=""),
        patch("agents.briefing_agent.get_github_summary", return_value=""),
        patch("agents.briefing_agent._get_open_tasks", return_value=""),
        patch("agents.briefing_agent._get_calendar_today", return_value=""),
        patch("agents.briefing_agent._get_mail_unread", return_value=""),
    ):
        result = await build_briefing()
    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.asyncio
async def test_build_briefing_block_failure_does_not_crash():
    with (
        patch("agents.briefing_agent.get_weather", side_effect=Exception("API down")),
        patch("agents.briefing_agent.get_ai_news", return_value="• News item"),
        patch("agents.briefing_agent.get_github_summary", return_value=""),
        patch("agents.briefing_agent._get_open_tasks", return_value=""),
        patch("agents.briefing_agent._get_calendar_today", return_value=""),
        patch("agents.briefing_agent._get_mail_unread", return_value=""),
    ):
        result = await build_briefing()
    assert isinstance(result, str)
    assert "News item" in result
