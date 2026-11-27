"""JARVIS Orb: a voice-first chat with the local LM Studio model and its MCP tools."""

from .advisor import Advisor, ToolCatalog
from .brain import OrbBrain, OrbReply
from .mcp_stdio import McpError, McpServerSpec, McpStdioClient
from .studio import OrbStudio
from .toolbox import McpToolbox, select_tools

__all__ = [
    "Advisor",
    "McpError",
    "McpServerSpec",
    "McpStdioClient",
    "McpToolbox",
    "OrbBrain",
    "OrbReply",
    "OrbStudio",
    "ToolCatalog",
    "select_tools",
]
