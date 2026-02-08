"""MCP client for managing connections to MCP servers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from loguru import logger

from nanobot.agent.mcp.tool_adapter import MCPResourceAdapter, MCPToolAdapter
from nanobot.agent.mcp.transports import (
    MCPTransportError,
    SSETransport,
    StdioTransport,
)

# Optional config import
try:
    from nanobot.config.schema import MCPConfig
except ImportError:
    MCPConfig = None  # type: ignore


@dataclass
class MCPServerConfig:
    """Configuration for a single MCP server."""

    name: str
    transport: str = "stdio"  # "stdio" or "sse"
    enabled: bool = True
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    url: str | None = None
    timeout: int = 30

    def __post_init__(self):
        if self.args is None:
            self.args = []
        if self.env is None:
            self.env = {}


class MCPClient:
    """
    Client for managing connections to multiple MCP servers.

    This client handles:
    - Starting and stopping MCP servers
    - Listing and calling tools
    - Reading resources
    - Error handling and reconnection
    """

    def __init__(self, config: MCPConfig | None = None):
        """
        Initialize the MCP client.

        Args:
            config: MCP configuration with server list
        """
        from nanobot.config.schema import MCPConfig

        self.config = config or MCPConfig()
        self._transports: dict[str, StdioTransport | SSETransport] = {}
        self._tools: dict[str, list[dict[str, Any]]] = {}
        self._resources: dict[str, list[dict[str, Any]]] = {}
        self._lock = asyncio.Lock()
        # Server configs for reconnection
        self._server_configs: dict[str, MCPServerConfig] = {}
        # Health check tracking
        self._health_check_task: asyncio.Task | None = None
        self._reconnect_attempts: dict[str, int] = {}
        self._reconnect_callbacks: list[callable] = []

    async def connect(self, server_config: MCPServerConfig) -> None:
        """
        Connect to an MCP server.

        Args:
            server_config: Configuration for the server to connect to.

        Raises:
            MCPTransportError: If connection fails.
        """
        if not server_config.enabled:
            logger.info(f"MCP server {server_config.name} is disabled, skipping")
            return

        logger.info(f"Connecting to MCP server: {server_config.name}")

        # Store config for reconnection
        self._server_configs[server_config.name] = server_config

        async with self._lock:
            if server_config.name in self._transports:
                logger.warning(f"MCP server {server_config.name} already connected")
                return

            # Reset reconnect attempts on successful manual connection
            self._reconnect_attempts.pop(server_config.name, None)

            try:
                transport = await self._create_transport(server_config)
                await transport.start()
                self._transports[server_config.name] = transport

                # Cache tools and resources
                try:
                    tools = await transport.list_tools()
                    self._tools[server_config.name] = tools
                    logger.info(
                        f"MCP server {server_config.name} provides {len(tools)} tools"
                    )
                except Exception as e:
                    logger.warning(f"Failed to list tools from {server_config.name}: {e}")
                    self._tools[server_config.name] = []

                try:
                    resources = await transport.list_resources()
                    self._resources[server_config.name] = resources
                    logger.info(
                        f"MCP server {server_config.name} provides {len(resources)} resources"
                    )
                except Exception as e:
                    logger.warning(f"Failed to list resources from {server_config.name}: {e}")
                    self._resources[server_config.name] = []

            except Exception as e:
                logger.error(f"Failed to connect to MCP server {server_config.name}: {e}")
                raise MCPTransportError(f"Connection failed: {e}") from e

    async def _create_transport(
        self, config: MCPServerConfig
    ) -> StdioTransport | SSETransport | None:
        """Create a transport instance based on config."""
        if config.transport == "sse":
            if not config.url:
                raise MCPTransportError("SSE transport requires a URL")
            return SSETransport(url=config.url, timeout=config.timeout)
        elif config.transport == "stdio":
            if not config.command:
                raise MCPTransportError("stdio transport requires a command")
            return StdioTransport(
                command=config.command,
                args=config.args or [],
                env=config.env or {},
            )
        else:
            raise MCPTransportError(f"Unknown transport type: {config.transport}")

    async def disconnect(self, name: str) -> None:
        """
        Disconnect from an MCP server.

        Args:
            name: Server name to disconnect.
        """
        async with self._lock:
            transport = self._transports.pop(name, None)
            if transport:
                logger.info(f"Disconnecting from MCP server: {name}")
                await transport.stop()
                self._tools.pop(name, None)
                self._resources.pop(name, None)

    async def disconnect_all(self) -> None:
        """Disconnect from all MCP servers."""
        async with self._lock:
            for name in list(self._transports.keys()):
                transport = self._transports.pop(name)
                await transport.stop()
            self._tools.clear()
            self._resources.clear()

    async def list_tools(self, server: str) -> list[dict[str, Any]]:
        """
        List tools from a specific server.

        Args:
            server: Server name.

        Returns:
            List of tool definitions.
        """
        transport = self._transports.get(server)
        if not transport:
            logger.warning(f"MCP server {server} not connected")
            return []

        try:
            return await transport.list_tools()
        except Exception as e:
            logger.error(f"Error listing tools from {server}: {e}")
            return []

    def get_cached_tools(self, server: str) -> list[dict[str, Any]]:
        """Get cached tools for a server."""
        return self._tools.get(server, [])

    async def call_tool(
        self, server: str, name: str, args: dict[str, Any]
    ) -> str | list[Any]:
        """
        Call a tool on an MCP server.

        Args:
            server: Server name.
            name: Tool name.
            args: Tool arguments.

        Returns:
            Tool result.
        """
        transport = self._transports.get(server)
        if not transport:
            return f"Error: MCP server {server} not connected"

        try:
            return await transport.call_tool(name, args)
        except MCPTransportError as e:
            logger.error(f"Error calling tool {server}.{name}: {e}")
            return f"Error: {str(e)}"
        except Exception as e:
            logger.error(f"Unexpected error calling tool {server}.{name}: {e}")
            return f"Error: {str(e)}"

    async def list_resources(self, server: str) -> list[dict[str, Any]]:
        """
        List resources from a specific server.

        Args:
            server: Server name.

        Returns:
            List of resource definitions.
        """
        transport = self._transports.get(server)
        if not transport:
            return []

        try:
            return await transport.list_resources()
        except Exception as e:
            logger.error(f"Error listing resources from {server}: {e}")
            return []

    def get_cached_resources(self, server: str) -> list[dict[str, Any]]:
        """Get cached resources for a server."""
        return self._resources.get(server, [])

    async def read_resource(self, server: str, uri: str) -> str:
        """
        Read a resource from an MCP server.

        Args:
            server: Server name.
            uri: Resource URI.

        Returns:
            Resource content.
        """
        transport = self._transports.get(server)
        if not transport:
            return f"Error: MCP server {server} not connected"

        try:
            return await transport.read_resource(uri)
        except Exception as e:
            logger.error(f"Error reading resource {uri} from {server}: {e}")
            return f"Error: {str(e)}"

    def create_tool_adapter(
        self, server: str, tool_def: dict[str, Any]
    ) -> MCPToolAdapter:
        """
        Create a nanobot Tool adapter for an MCP tool.

        Args:
            server: Server name.
            tool_def: Tool definition from MCP server.

        Returns:
            MCPToolAdapter instance.
        """
        return MCPToolAdapter(server, tool_def, self)

    def create_resource_adapter(
        self, server: str, resource_def: dict[str, Any]
    ) -> MCPResourceAdapter:
        """
        Create an adapter for an MCP resource.

        Args:
            server: Server name.
            resource_def: Resource definition from MCP server.

        Returns:
            MCPResourceAdapter instance.
        """
        return MCPResourceAdapter(server, resource_def, self)

    def get_server_names(self) -> list[str]:
        """Get list of connected server names."""
        return list(self._transports.keys())

    def is_connected(self, name: str) -> bool:
        """Check if a server is connected."""
        transport = self._transports.get(name)
        return transport is not None and transport.is_running

    async def health_check(self) -> dict[str, bool]:
        """
        Check health of all connected servers.

        Returns:
            Dict mapping server names to health status.
        """
        results = {}
        for name, transport in self._transports.items():
            results[name] = transport.is_running
        return results

    def get_status_summary(self) -> str:
        """
        Get a summary of MCP server status for display in agent context.

        Returns:
            Formatted summary string.
        """
        if not self._transports:
            return ""

        lines = ["## MCP Servers"]

        for name in sorted(self._transports.keys()):
            tools = self._tools.get(name, [])
            resources = self._resources.get(name, [])
            status = "✓" if self.is_connected(name) else "✗"

            lines.append(f"- {name}: {status}")
            if tools:
                lines.append(f"  Tools: {', '.join(t.get('name', '?') for t in tools[:5])}")
                if len(tools) > 5:
                    lines.append(f"    ... and {len(tools) - 5} more")
            if resources:
                lines.append(f"  Resources: {len(resources)} available")

        return "\n".join(lines)

    # Health check and auto-reconnect methods

    def set_reconnect_callback(self, callback: callable) -> None:
        """
        Set a callback to be invoked when a server is reconnected.

        The callback receives (server_name: str, tools: list) as arguments.
        """
        self._reconnect_callbacks.append(callback)

    async def start_health_check(self) -> None:
        """Start the background health check task."""
        if not self.config.health_check_enabled:
            logger.info("MCP health check disabled")
            return

        if self._health_check_task is not None and not self._health_check_task.done():
            logger.warning("MCP health check already running")
            return

        logger.info(
            f"Starting MCP health check (interval: {self.config.health_check_interval}s)"
        )
        self._health_check_task = asyncio.create_task(self._health_check_loop())

    async def stop_health_check(self) -> None:
        """Stop the background health check task."""
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
            self._health_check_task = None
            logger.info("MCP health check stopped")

    async def _health_check_loop(self) -> None:
        """Background loop that checks server health and reconnects if needed."""
        interval = self.config.health_check_interval

        while True:
            try:
                await asyncio.sleep(interval)
                await self._check_and_reconnect()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in MCP health check loop: {e}")

    async def _check_and_reconnect(self) -> None:
        """Check all servers and reconnect disconnected ones."""
        disconnected = []

        # Find disconnected servers
        for name in list(self._server_configs.keys()):
            if not self.is_connected(name):
                disconnected.append(name)

        if not disconnected:
            return

        # Attempt reconnection
        for name in disconnected:
            server_config = self._server_configs.get(name)
            if not server_config or not server_config.enabled:
                continue

            await self._reconnect_server(name, server_config)

    async def _reconnect_server(self, name: str, server_config: MCPServerConfig) -> None:
        """
        Attempt to reconnect a disconnected server with exponential backoff.

        Args:
            name: Server name to reconnect.
            server_config: Server configuration.
        """
        attempts = self._reconnect_attempts.get(name, 0)
        max_attempts = self.config.reconnect_max_attempts

        # Check if we've exceeded max attempts
        if max_attempts > 0 and attempts >= max_attempts:
            logger.warning(
                f"MCP server {name} reconnection failed after {max_attempts} attempts, giving up"
            )
            return

        # Calculate delay with exponential backoff
        delay = min(
            self.config.reconnect_base_delay * (2 ** attempts),
            self.config.reconnect_max_delay,
        )

        self._reconnect_attempts[name] = attempts + 1

        logger.info(
            f"Attempting to reconnect MCP server {name} "
            f"(attempt {attempts + 1}/{max_attempts or '∞'}) after {delay:.1f}s delay"
        )

        await asyncio.sleep(delay)

        try:
            # Clean up old transport if exists
            if name in self._transports:
                old_transport = self._transports.pop(name)
                try:
                    await old_transport.stop()
                except Exception:
                    pass

            # Create new transport and connect
            transport = await self._create_transport(server_config)
            await transport.start()
            self._transports[name] = transport

            # Fetch tools and resources
            try:
                tools = await transport.list_tools()
                self._tools[name] = tools
            except Exception as e:
                logger.warning(f"Failed to list tools from {name}: {e}")
                self._tools[name] = []

            try:
                resources = await transport.list_resources()
                self._resources[name] = resources
            except Exception:
                self._resources[name] = []

            # Success - reset attempts
            self._reconnect_attempts.pop(name, None)
            logger.info(f"Successfully reconnected MCP server: {name}")

            # Notify callbacks (for re-registering tools)
            for callback in self._reconnect_callbacks:
                try:
                    await callback(name, self._tools.get(name, []))
                except Exception as e:
                    logger.error(f"Error in reconnect callback: {e}")

        except Exception as e:
            logger.error(f"Failed to reconnect MCP server {name}: {e}")
