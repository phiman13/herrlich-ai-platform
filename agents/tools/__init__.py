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

_MCP_SERVER_NAME = "jarvis"
# Alle in diesem Server registrierten Tools.
_TOOLS = [_workspace_capability, _weather_capability, _news_capability]
# Voller MCP-Tool-Name: mcp__<server-name>__<tool-name>
_ALLOWED_TOOL_NAMES = {f"mcp__{_MCP_SERVER_NAME}__{t.name}" for t in _TOOLS}


def build_mcp_server() -> McpSdkServerConfig:
    """In-Process-MCP-Server mit allen Jarvis-Tools."""
    return create_sdk_mcp_server(name=_MCP_SERVER_NAME, version="1.0.0", tools=_TOOLS)


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
