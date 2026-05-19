"""news-Tool — aktuelle AI-/Tech-News aus kuratierten RSS-Feeds. Read-only.

Dünner Wrapper um news_agent.get_ai_news: typisierte Parameter rein,
Text-Content raus. Keine Telegram-Seiteneffekte.
"""

import asyncio

from claude_agent_sdk import tool

from news_agent import get_ai_news

_DEFAULT_HOURS = 48
_MAX_ITEMS = 10


@tool(
    "news",
    "Aktuelle AI-/Tech-News aus kuratierten RSS-Feeds. "
    "hours (optional): Zeitfenster in Stunden, Standard 48.",
    {"hours": int},
)
async def news_tool(args: dict) -> dict:
    hours = args.get("hours") or _DEFAULT_HOURS
    news = await asyncio.to_thread(get_ai_news, hours, _MAX_ITEMS)
    text = news or f"Keine AI-News in den letzten {hours} h gefunden."
    return {"content": [{"type": "text", "text": text}]}
