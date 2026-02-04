"""Adapter for converting MCP tools to nanobot Tools."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nanobot.agent.tools.base import Tool

if TYPE_CHECKING:
    from nanobot.agent.mcp.client import MCPClient


class MCPToolAdapter(Tool):
    """
    Adapter that wraps an MCP tool as a nanobot Tool.

    This allows MCP tools to be registered in the nanobot tool registry
    and executed alongside native tools.
    """

    def __init__(
        self,
        server_name: str,
        mcp_tool: dict[str, Any],
        client: MCPClient,
    ):
        """
        Initialize the MCP tool adapter.

        Args:
            server_name: Name of the MCP server providing this tool
            mcp_tool: Tool definition from the MCP server
            client: MCPClient instance for calling the tool
        """
        self._server_name = server_name
        self._mcp_tool = mcp_tool
        self._client = client

        # Extract tool info
        self._tool_name = mcp_tool.get("name", "unknown")
        self._description = mcp_tool.get("description", "")
        self._input_schema = mcp_tool.get("inputSchema", {})

    @property
    def name(self) -> str:
        """Tool name in format: server_tool."""
        return f"{self._server_name}_{self._tool_name}"

    @property
    def description(self) -> str:
        """Tool description with server prefix."""
        prefix = f"[{self._server_name}] "
        return prefix + self._description

    @property
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for tool parameters."""
        return self._input_schema

    @property
    def server_name(self) -> str:
        """Get the MCP server name."""
        return self._server_name

    @property
    def original_name(self) -> str:
        """Get the original tool name from the MCP server."""
        return self._tool_name

    async def execute(self, **kwargs: Any) -> str:
        """
        Execute the tool via the MCP client.

        Args:
            **kwargs: Tool parameters.

        Returns:
            Tool execution result as string.
        """
        try:
            result = await self._client.call_tool(
                self._server_name,
                self._tool_name,
                kwargs
            )

            if isinstance(result, list):
                # Handle structured responses
                return self._format_result(result)
            return str(result)
        except Exception as e:
            return f"Error calling {self.name}: {str(e)}"

    def _format_result(self, result: list[dict[str, Any]]) -> str:
        """Format a structured result into a string."""
        parts = []
        for item in result:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(item.get("text", ""))
                elif item.get("type") == "resource":
                    uri = item.get("uri", "")
                    parts.append(f"Resource: {uri}")
                else:
                    parts.append(str(item))
            else:
                parts.append(str(item))
        return "\n".join(parts)

    def to_schema(self) -> dict[str, Any]:
        """Convert tool to OpenAI function schema format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            }
        }


class MCPResourceAdapter:
    """
    Adapter for MCP resources.

    Resources are read-only data sources exposed by MCP servers,
    such as files, database contents, or API responses.
    """

    def __init__(
        self,
        server_name: str,
        resource: dict[str, Any],
        client: "MCPClient",  # type: ignore
    ):
        """
        Initialize the MCP resource adapter.

        Args:
            server_name: Name of the MCP server providing this resource
            resource: Resource definition from the MCP server
            client: MCPClient instance for reading the resource
        """
        self._server_name = server_name
        self._resource = resource
        self._client = client

    @property
    def uri(self) -> str:
        """Resource URI."""
        return self._resource.get("uri", "")

    @property
    def name(self) -> str:
        """Resource name."""
        return self._resource.get("name", "")

    @property
    def description(self) -> str:
        """Resource description."""
        return self._resource.get("description", "")

    @property
    def mime_type(self) -> str | None:
        """Resource MIME type."""
        return self._resource.get("mimeType")

    async def read(self) -> str:
        """
        Read the resource content.

        Returns:
            Resource content as string.
        """
        try:
            return await self._client.read_resource(self._server_name, self.uri)
        except Exception as e:
            return f"Error reading resource {self.uri}: {str(e)}"

    def __repr__(self) -> str:
        return f"MCPResourceAdapter(uri={self.uri}, name={self.name})"
