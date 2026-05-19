"""weather-Tool — Wettervorhersage via Open-Meteo. Read-only.

Dünner Wrapper um weather_agent.get_weather: typisierte Parameter rein,
Text-Content raus. Keine Telegram-Seiteneffekte.
"""

import asyncio

from claude_agent_sdk import tool

from weather_agent import get_weather


@tool(
    "weather",
    "Wettervorhersage für Tutzing (Philipps Heimatort) oder einen genannten Ort. "
    "period: 'today' (Standard), 'tomorrow' oder 'week'. "
    "time_of_day (optional): 'morning', 'noon', 'afternoon', 'evening', 'night'. "
    "location (optional): Ortsname; leer = Heimatort.",
    {"period": str, "time_of_day": str, "location": str},
)
async def weather_tool(args: dict) -> dict:
    period = (args.get("period") or "today").strip()
    time_of_day = (args.get("time_of_day") or "").strip() or None
    location = (args.get("location") or "").strip() or None
    result = await asyncio.to_thread(get_weather, period, time_of_day, location)
    return {"content": [{"type": "text", "text": result}]}
