"""MCP transport implementations for stdio and SSE connections."""

import asyncio
import json
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    pass


class MCPTransportError(Exception):
    """Base exception for MCP transport errors."""
    pass


class StdioTransport:
    """
    Transport layer for communicating with MCP servers via stdio.

    This transport spawns a subprocess and communicates with it using
    JSON-RPC messages over stdin/stdout.
    """

    def __init__(
        self,
        command: str,
        args: list[str],
        env: dict[str, str] | None = None,
    ):
        """
        Initialize the stdio transport.

        Args:
            command: Command to run (e.g., "npx", "uvx", "python")
            args: Arguments to pass to the command
            env: Optional environment variables for the subprocess
        """
        self.command = command
        self.args = args
        self.env = env or {}
        self.process: asyncio.subprocess.Process | None = None
        self._request_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._read_task: asyncio.Task | None = None
        self._initialized = False

    async def start(self) -> None:
        """Start the MCP server process."""
        cmd_list = [self.command] + self.args
        logger.debug(f"Starting MCP server: {' '.join(cmd_list)}")

        # Prepare environment
        import os
        env = os.environ.copy()
        env.update(self.env)

        try:
            self.process = await asyncio.create_subprocess_exec(
                *cmd_list,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        except FileNotFoundError as e:
            raise MCPTransportError(f"Command not found: {self.command}") from e
        except OSError as e:
            raise MCPTransportError(f"Failed to start process: {e}") from e

        # Start reading responses
        self._read_task = asyncio.create_task(self._read_loop())

        # Initialize the connection
        await self._initialize()

    async def _initialize(self) -> None:
        """Send initialization request to the MCP server."""
        await self._send_request({
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "nanobot",
                    "version": "0.1.0"
                }
            }
        })
        self._initialized = True

        # Send initialized notification
        await self._send_notification({
            "jsonrpc": "2.0",
            "method": "notifications/initialized"
        })

    async def stop(self) -> None:
        """Stop the MCP server process."""
        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass
            self._read_task = None

        # Cancel all pending requests
        for future in self._pending.values():
            future.cancel()
        self._pending.clear()

        if self.process:
            try:
                self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()
            except Exception as e:
                logger.warning(f"Error stopping MCP server: {e}")
            self.process = None

        self._initialized = False

    async def _read_loop(self) -> None:
        """Read messages from stdout and dispatch to waiting futures."""
        if not self.process or not self.process.stdout:
            return

        buffer = b""

        while self.process and self.process.stdout:
            try:
                chunk = await self.process.stdout.read(4096)
                if not chunk:
                    break

                buffer += chunk
                # Process complete JSON-RPC messages (one per line)
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if not line.strip():
                        continue

                    try:
                        message = json.loads(line.decode("utf-8"))
                        await self._handle_message(message)
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse JSON-RPC message: {e}")
            except Exception as e:
                if self.process:
                    logger.error(f"Error reading from MCP server: {e}")
                break

        # Signal EOF to all pending requests
        for future in self._pending.values():
            if not future.done():
                future.set_exception(MCPTransportError("Connection closed"))
        self._pending.clear()

    async def _handle_message(self, message: dict[str, Any]) -> None:
        """Handle a JSON-RPC message from the server."""
        if "id" in message:
            # Response to a request
            request_id = message["id"]
            future = self._pending.pop(request_id, None)
            if future:
                if "error" in message:
                    future.set_exception(
                        MCPTransportError(message["error"].get("message", "Unknown error"))
                    )
                else:
                    future.set_result(message.get("result"))
        else:
            # Notification - ignore for now
            pass

    def _next_id(self) -> int:
        """Get the next request ID."""
        self._request_id += 1
        return self._request_id

    async def _send_request(self, request: dict[str, Any]) -> Any:
        """Send a JSON-RPC request and wait for the response."""
        if not self.process or not self.process.stdin:
            raise MCPTransportError("Not connected")

        request_id = request["id"]
        future: asyncio.Future = asyncio.Future()
        self._pending[request_id] = future

        try:
            message = json.dumps(request) + "\n"
            self.process.stdin.write(message.encode("utf-8"))
            await self.process.stdin.drain()
        except Exception as e:
            self._pending.pop(request_id, None)
            raise MCPTransportError(f"Failed to send request: {e}") from e

        try:
            return await asyncio.wait_for(future, timeout=30.0)
        except asyncio.TimeoutError:
            self._pending.pop(request_id, None)
            raise MCPTransportError("Request timeout")

    async def _send_notification(self, notification: dict[str, Any]) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        if not self.process or not self.process.stdin:
            raise MCPTransportError("Not connected")

        try:
            message = json.dumps(notification) + "\n"
            self.process.stdin.write(message.encode("utf-8"))
            await self.process.stdin.drain()
        except Exception as e:
            raise MCPTransportError(f"Failed to send notification: {e}") from e

    async def list_tools(self) -> list[dict[str, Any]]:
        """List available tools from the MCP server."""
        response = await self._send_request({
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/list",
            "params": {}
        })
        return response.get("tools", [])

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any]
    ) -> str | list[dict[str, Any]]:
        """Call a tool on the MCP server."""
        response = await self._send_request({
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {
                "name": name,
                "arguments": arguments
            }
        })

        # Handle different response formats
        content = response.get("content", [])
        if isinstance(content, list):
            # Return formatted text content
            text_parts = []
            for item in content:
                if item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
                elif item.get("type") == "resource":
                    # Handle resource references
                    uri = item.get("uri", "")
                    text_parts.append(f"[Resource: {uri}]")
                elif item.get("type") == "image":
                    # Handle image content
                    data = item.get("data", "")
                    mime = item.get("mimeType", "image/png")
                    text_parts.append(f"[Image: {mime}, {len(data)} chars]")
            return "\n".join(text_parts) if text_parts else "Tool executed successfully"
        return str(content)

    async def list_resources(self) -> list[dict[str, Any]]:
        """List available resources from the MCP server."""
        response = await self._send_request({
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "resources/list",
            "params": {}
        })
        return response.get("resources", [])

    async def read_resource(self, uri: str) -> str:
        """Read a resource from the MCP server."""
        response = await self._send_request({
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "resources/read",
            "params": {"uri": uri}
        })

        contents = response.get("contents", [])
        if not contents:
            return ""

        # Handle different content types
        result = []
        for content in contents:
            if content.get("type") == "text":
                result.append(content.get("text", ""))
            elif content.get("type") == "resource":
                # Embedded resource
                contents_inner = content.get("contents", [])
                for c in contents_inner if isinstance(contents_inner, list) else [contents_inner]:
                    if c.get("type") == "text":
                        result.append(c.get("text", ""))
        return "\n".join(result)

    @property
    def is_running(self) -> bool:
        """Check if the transport is running."""
        return self.process is not None and self._initialized


class SSETransport:
    """
    Transport layer for communicating with MCP servers via Server-Sent Events.

    This transport connects to an HTTP server that provides MCP endpoints
    using SSE for server-to-client messages.
    """

    def __init__(
        self,
        url: str,
        timeout: int = 30,
    ):
        """
        Initialize the SSE transport.

        Args:
            url: Base URL of the MCP server
            timeout: Request timeout in seconds
        """
        self.url = url.rstrip("/")
        self.timeout = timeout
        self._request_id = 0
        self._session: Any = None  # httpx.AsyncSession
        self._endpoint: str | None = None

    async def start(self) -> None:
        """Start the SSE transport connection."""
        try:
            import httpx
        except ImportError:
            raise MCPTransportError(
                "httpx is required for SSE transport. "
                "Install it with: pip install httpx"
            )

        self._session = httpx.AsyncSession(timeout=self.timeout)

        # Discover the endpoint
        await self._discover_endpoint()

        # Initialize the connection
        await self._initialize()

    async def _discover_endpoint(self) -> None:
        """Discover the MCP endpoint from the server."""
        # Try common endpoints
        for path in ["/mcp", "/sse", "/"]:
            try:
                response = await self._session.get(f"{self.url}{path}")
                if response.status_code == 200:
                    # Check for SSE endpoint in response
                    self._endpoint = f"{self.url}{path}"
                    return
            except Exception:
                continue

        # Default to /mcp
        self._endpoint = f"{self.url}/mcp"

    async def _initialize(self) -> None:
        """Initialize the SSE connection."""
        # For SSE, initialization is typically handled on first request
        pass

    async def stop(self) -> None:
        """Stop the SSE transport connection."""
        if self._session:
            await self._session.aclose()
            self._session = None
        self._endpoint = None

    def _next_id(self) -> int:
        """Get the next request ID."""
        self._request_id += 1
        return self._request_id

    async def _send_request(self, method: str, params: dict[str, Any]) -> Any:
        """Send a JSON-RPC request via HTTP POST."""
        if not self._session:
            raise MCPTransportError("Not connected")

        url = f"{self._endpoint}/{method}" if self._endpoint else f"{self.url}/{method}"

        try:
            response = await self._session.post(
                url,
                json={
                    "jsonrpc": "2.0",
                    "id": self._next_id(),
                    "method": method,
                    "params": params
                }
            )
            response.raise_for_status()
            data = response.json()

            if "error" in data:
                raise MCPTransportError(data["error"].get("message", "Unknown error"))
            return data.get("result")
        except Exception as e:
            if "HTTPStatusError" in type(e).__name__:
                raise MCPTransportError(f"HTTP error: {e.response.status_code}") from e
            if "RequestError" in type(e).__name__:
                raise MCPTransportError(f"Request error: {e}") from e
            raise MCPTransportError(f"Request error: {e}") from e
            raise MCPTransportError(f"Request error: {e}") from e

    async def list_tools(self) -> list[dict[str, Any]]:
        """List available tools from the MCP server."""
        response = await self._send_request("tools/list", {})
        return response.get("tools", []) if response else []

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any]
    ) -> str | list[dict[str, Any]]:
        """Call a tool on the MCP server."""
        response = await self._send_request("tools/call", {
            "name": name,
            "arguments": arguments
        })

        # Handle different response formats
        content = response.get("content", []) if response else []
        if isinstance(content, list):
            text_parts = []
            for item in content:
                if item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
            return "\n".join(text_parts) if text_parts else "Tool executed successfully"
        return str(content) if content else "Tool executed successfully"

    async def list_resources(self) -> list[dict[str, Any]]:
        """List available resources from the MCP server."""
        response = await self._send_request("resources/list", {})
        return response.get("resources", []) if response else []

    async def read_resource(self, uri: str) -> str:
        """Read a resource from the MCP server."""
        response = await self._send_request("resources/read", {"uri": uri})

        contents = response.get("contents", []) if response else []
        if not contents:
            return ""

        result = []
        for content in contents:
            if content.get("type") == "text":
                result.append(content.get("text", ""))
        return "\n".join(result)

    @property
    def is_running(self) -> bool:
        """Check if the transport is running."""
        return self._session is not None
