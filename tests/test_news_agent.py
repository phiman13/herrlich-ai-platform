# tests/test_news_agent.py
import time
import pytest
from unittest.mock import patch, MagicMock

try:
    from agents.news_agent import get_ai_news, _dedup, _is_recent
except ImportError:
    from news_agent import get_ai_news, _dedup, _is_recent


def _make_entry(title, published_parsed=None):
    entry = MagicMock()
    entry.title = title
    entry.link = f"https://example.com/{title.replace(' ', '-')}"
    entry.published_parsed = published_parsed or time.gmtime()  # jetzt = recent
    return entry


def test_dedup_removes_similar_titles():
    entries = [
        _make_entry("GPT-5 released by OpenAI"),
        _make_entry("GPT-5 released by OpenAI today"),  # sehr ähnlich
        _make_entry("Claude 4 beats GPT-5 on benchmarks"),
    ]
    result = _dedup(entries)
    assert len(result) == 2


def test_dedup_keeps_different_titles():
    entries = [
        _make_entry("GPT-5 released"),
        _make_entry("Claude 4 announced"),
        _make_entry("Gemini Ultra 2 launch"),
    ]
    result = _dedup(entries)
    assert len(result) == 3


def test_is_recent_now():
    assert _is_recent(time.gmtime(), hours=24) is True


def test_is_recent_old():
    old = time.gmtime(time.time() - 48 * 3600)
    assert _is_recent(old, hours=24) is False


def test_get_ai_news_returns_string():
    fake_feed = MagicMock()
    fake_feed.entries = [_make_entry(f"AI News Item {i}") for i in range(3)]
    with patch("feedparser.parse", return_value=fake_feed):
        result = get_ai_news(hours=24, max_items=5)
    assert isinstance(result, str)
    assert len(result) > 0


def test_get_ai_news_empty_feeds():
    fake_feed = MagicMock()
    fake_feed.entries = []
    with patch("feedparser.parse", return_value=fake_feed):
        result = get_ai_news(hours=24, max_items=5)
    assert result == ""
