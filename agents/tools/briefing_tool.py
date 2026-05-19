"""briefing-Tool — Morgenbriefing abrufen. Read-only, statisch.

Kein chat_id nötig, da keine Schreib-Aktionen.
"""

from claude_agent_sdk import tool

from briefing_agent import build_briefing as _build_briefing


@tool(
    "briefing",
    "Morgenbriefing abrufen — Wetter, Kalender, offene Tasks, wichtige Mails, "
    "GitHub-Aktivität und News. action='build': Briefing jetzt erstellen.",
    {"action": str},
)
async def briefing_tool(args: dict) -> dict:
    action = (args.get("action") or "").strip()
    if action == "build":
        result = await _build_briefing()
        return {"content": [{"type": "text", "text": result}]}
    return {
        "content": [
            {
                "type": "text",
                "text": f"FEHLER: Unbekannte action '{action}'. Erlaubt: build.",
            }
        ]
    }
