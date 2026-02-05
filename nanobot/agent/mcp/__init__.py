"""MCP (Model Context Protocol) client integration for nanobot.

This module provides integration with MCP servers, allowing nanobot to use
external tools and resources through the Model Context Protocol.
"""

# Check if mcp package is available
try:
    import mcp  # noqa: F401
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False

from nanobot.agent.mcp.client import MCPClient, MCPServerConfig
from nanobot.agent.mcp.tool_adapter import MCPToolAdapter

__all__ = ["MCPClient", "MCPServerConfig", "MCPToolAdapter", "MCP_AVAILABLE"]
