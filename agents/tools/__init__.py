"""Agent-SDK-Werkzeuge — Registry, MCP-Server-Bau, Permission-Gate.

Ein Modul pro Fähigkeit (workspace_tool, ab Plan 2: weather_tool, news_tool, …).
build_mcp_server versammelt alle Tools zu einem In-Process-MCP-Server;
permission_hook ist die Allowlist der freigegebenen MCP-Tool-Namen.
"""

from claude_agent_sdk import (
    McpSdkServerConfig,
    PermissionResultAllow,
    PermissionResultDeny,
    create_sdk_mcp_server,
)

# Tool-Objekte unter privatem Alias importieren — sonst überschattet der
# re-exportierte Name das gleichnamige Submodul (tools.workspace_tool).
from .workspace_tool import workspace_tool as _workspace_capability
from .weather_tool import weather_tool as _weather_capability
from .news_tool import news_tool as _news_capability
from . import tasks_tool

_MCP_SERVER_NAME = "jarvis"

# Read-only Tools sind module-level; chat-skopierte Tools (tasks) werden pro
# Lauf gebaut, weil sie chat_id zum Vormerken von Schreibaktionen brauchen.
_STATIC_TOOLS = [_workspace_capability, _weather_capability, _news_capability]


def _all_tools(chat_id: int) -> list:
    """Alle Tool-Objekte für einen Lauf."""
    return _STATIC_TOOLS + [tasks_tool.make_tasks_tool(chat_id)]


# Allowlist — aus einem Probe-Build; chat_id ist für die Namen irrelevant.
_ALLOWED_TOOL_NAMES = {f"mcp__{_MCP_SERVER_NAME}__{t.name}" for t in _all_tools(0)}


def build_mcp_server(chat_id: int) -> McpSdkServerConfig:
    """In-Process-MCP-Server mit allen Jarvis-Tools für einen Chat."""
    return create_sdk_mcp_server(
        name=_MCP_SERVER_NAME, version="1.0.0", tools=_all_tools(chat_id)
    )


# Executor-Registry — tool-name -> execute_write(action, params) -> str.
_WRITE_EXECUTORS: dict = {"tasks": tasks_tool.execute_write}


async def execute_pending_action(action: dict) -> str:
    """Eine vorgemerkte Schreibaktion ausführen — dispatcht ans Tool-Modul.

    action: {"tool", "action", "label", "params"}. Gibt eine Ergebnis-Zeile zurück.
    """
    executor = _WRITE_EXECUTORS.get(action["tool"])
    if executor is None:
        return f"❌ {action['label']}: kein Executor für Tool '{action['tool']}'."
    return await executor(action["action"], action["params"])


async def permission_hook(tool_name: str, tool_input: dict, context) -> object:
    """can_use_tool-Gate — Allowlist der Jarvis-MCP-Tools.

    Feuert nur für Tools, die NICHT in allowed_tools stehen (WebSearch/WebFetch
    sind dort gelistet → auto-erlaubt). Lese-/Schreib-Unterscheidung macht ab
    Plan 3 das Tool selbst (Schreib-Aktionen werden vorgemerkt).
    """
    if tool_name in _ALLOWED_TOOL_NAMES:
        return PermissionResultAllow(updated_input=tool_input)
    return PermissionResultDeny(
        message=f"Werkzeug '{tool_name}' ist nicht freigegeben.",
        interrupt=False,
    )
