# agents/news_agent.py
import calendar
import difflib
import logging
import time

import feedparser

logger = logging.getLogger("jarvis.news")

_FEEDS = [
    "https://tldr.tech/api/rss/ai",
    "https://the-decoder.com/feed/",
    "https://blog.google/technology/ai/rss/",
    "https://openai.com/news/rss.xml",
    "https://huggingface.co/blog/feed.xml",
    "https://www.technologyreview.com/topic/artificial-intelligence/feed/",
    "https://venturebeat.com/category/ai/feed/",
    "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "https://feeds.arstechnica.com/arstechnica/technology-lab",
    "https://techcrunch.com/category/artificial-intelligence/feed/",
    "http://arxiv.org/rss/cs.AI",
    "https://www.wired.com/feed/tag/ai/latest/rss",
    "https://www.lesswrong.com/feed.xml?view=community&karmaThreshold=50&tags=ai",
    "https://ai.googleblog.com/feeds/posts/default",
    "https://www.marktechpost.com/feed/",
]


def _is_recent(published_parsed, hours: int = 24) -> bool:
    if not published_parsed:
        return True  # Kein Datum → einschließen
    cutoff = time.time() - hours * 3600
    return calendar.timegm(published_parsed) > cutoff


def _normalize(title: str) -> str:
    return title.lower().strip()


def _dedup(entries: list) -> list:
    seen: list[str] = []
    result = []
    for entry in entries:
        norm = _normalize(entry.title)
        is_dup = any(
            difflib.SequenceMatcher(None, norm, s).ratio() > 0.75
            for s in seen
        )
        if not is_dup:
            seen.append(norm)
            result.append(entry)
    return result


def get_ai_news(hours: int = 24, max_items: int = 8) -> str:
    all_entries = []
    for url in _FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                if _is_recent(getattr(entry, "published_parsed", None), hours):
                    all_entries.append(entry)
        except Exception as e:
            logger.warning(f"Feed-Fehler {url}: {e}")

    if not all_entries:
        return ""

    deduped = _dedup(all_entries)[:max_items]
    lines = []
    for entry in deduped:
        source = getattr(entry, "source", {})
        source_name = getattr(source, "title", "") or _feed_domain(getattr(entry, "link", ""))
        title = entry.title[:100]
        lines.append(f"• {title} — {source_name}")

    return "\n".join(lines)


def _feed_domain(url: str) -> str:
    try:
        from urllib.parse import urlparse
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return ""
