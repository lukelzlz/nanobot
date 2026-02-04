"""Tests for MCP integration."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.agent.mcp import MCPClient, MCPServerConfig
from nanobot.agent.mcp.transports import MCPTransportError


@pytest.fixture
def mcp_config():
    """Create a test MCP config."""
    from nanobot.config.schema import MCPConfig
    return MCPConfig(
        enabled=True,
        servers=[
            {
                "name": "test-server",
                "transport": "stdio",
                "command": "echo",
                "args": [],
                "enabled": True,
            }
        ],
    )


@pytest.fixture
def server_config():
    """Create a test server config."""
    return MCPServerConfig(
        name="test-server",
        transport="stdio",
        command="echo",
        args=[],
        enabled=True,
    )


class TestMCPServerConfig:
    """Test MCPServerConfig dataclass."""

    def test_server_config_defaults(self):
        """Test default values."""
        config = MCPServerConfig(name="test")
        assert config.name == "test"
        assert config.transport == "stdio"
        assert config.enabled is True
        assert config.command is None
        assert config.args == []
        assert config.env == {}
        assert config.url is None
        assert config.timeout == 30

    def test_server_config_custom(self):
        """Test custom values."""
        config = MCPServerConfig(
            name="custom",
            transport="sse",
            url="http://localhost:8080",
            timeout=60,
        )
        assert config.name == "custom"
        assert config.transport == "sse"
        assert config.url == "http://localhost:8080"
        assert config.timeout == 60


class TestMCPClient:
    """Test MCP client."""

    def test_client_init(self):
        """Test client initialization."""
        from nanobot.config.schema import MCPConfig

        config = MCPConfig()
        client = MCPClient(config)

        assert client.config == config
        assert client._transports == {}
        assert client._tools == {}
        assert client._resources == {}

    def test_client_init_no_config(self):
        """Test client initialization without config."""
        client = MCPClient()
        assert client.config is not None
        assert client.config.enabled is False

    @pytest.mark.asyncio
    async def test_connect_disabled_server(self):
        """Test connecting to a disabled server."""
        config = MCPServerConfig(name="test", enabled=False)
        client = MCPClient()

        # Should not raise, just return
        await client.connect(config)
        assert "test" not in client._transports

    @pytest.mark.asyncio
    async def test_get_cached_tools_empty(self):
        """Test getting cached tools when none exist."""
        client = MCPClient()
        tools = client.get_cached_tools("nonexistent")
        assert tools == []

    @pytest.mark.asyncio
    async def test_call_tool_not_connected(self):
        """Test calling tool when server not connected."""
        client = MCPClient()
        result = await client.call_tool("test", "tool", {})
        assert "Error: MCP server test not connected" in result

    @pytest.mark.asyncio
    async def test_list_resources_not_connected(self):
        """Test listing resources when server not connected."""
        client = MCPClient()
        resources = await client.list_resources("test")
        assert resources == []

    @pytest.mark.asyncio
    async def test_read_resource_not_connected(self):
        """Test reading resource when server not connected."""
        client = MCPClient()
        result = await client.read_resource("test", "file:///test.txt")
        assert "Error: MCP server test not connected" in result

    def test_get_server_names_empty(self):
        """Test getting server names when none connected."""
        client = MCPClient()
        assert client.get_server_names() == []

    def test_is_connected_false(self):
        """Test is_connected when not connected."""
        client = MCPClient()
        assert client.is_connected("test") is False

    def test_get_status_summary_empty(self):
        """Test status summary when no servers."""
        client = MCPClient()
        summary = client.get_status_summary()
        assert summary == ""

    @pytest.mark.asyncio
    async def test_health_check_empty(self):
        """Test health check with no servers."""
        client = MCPClient()
        health = await client.health_check()
        assert health == {}

    @pytest.mark.asyncio
    async def test_disconnect_all_empty(self):
        """Test disconnect all when no servers."""
        client = MCPClient()
        await client.disconnect_all()
        assert client._transports == {}


class TestMCPToolAdapter:
    """Test MCP tool adapter."""

    def test_adapter_properties(self):
        """Test adapter properties."""
        from nanobot.agent.mcp.tool_adapter import MCPToolAdapter

        client = MagicMock()
        tool_def = {
            "name": "test_tool",
            "description": "A test tool",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "arg1": {"type": "string"}
                }
            }
        }

        adapter = MCPToolAdapter("test-server", tool_def, client)

        assert adapter.name == "test-server_test_tool"
        assert adapter.description == "[test-server] A test tool"
        assert adapter.parameters == tool_def["inputSchema"]
        assert adapter.server_name == "test-server"
        assert adapter.original_name == "test_tool"

    def test_to_schema(self):
        """Test to_schema conversion."""
        from nanobot.agent.mcp.tool_adapter import MCPToolAdapter

        client = MagicMock()
        tool_def = {
            "name": "test_tool",
            "description": "A test tool",
            "inputSchema": {"type": "object"}
        }

        adapter = MCPToolAdapter("test-server", tool_def, client)
        schema = adapter.to_schema()

        assert schema["type"] == "function"
        assert schema["function"]["name"] == "test-server_test_tool"
        assert schema["function"]["description"] == "[test-server] A test tool"
        assert schema["function"]["parameters"] == {"type": "object"}

    @pytest.mark.asyncio
    async def test_execute_success(self):
        """Test successful tool execution."""
        from nanobot.agent.mcp.tool_adapter import MCPToolAdapter

        client = MagicMock()
        client.call_tool = AsyncMock(return_value="Success!")

        tool_def = {
            "name": "test_tool",
            "description": "A test tool",
            "inputSchema": {"type": "object"}
        }

        adapter = MCPToolAdapter("test-server", tool_def, client)
        result = await adapter.execute(arg1="value")

        assert result == "Success!"
        client.call_tool.assert_called_once_with("test-server", "test_tool", {"arg1": "value"})

    @pytest.mark.asyncio
    async def test_execute_with_list_result(self):
        """Test tool execution returning a list."""
        from nanobot.agent.mcp.tool_adapter import MCPToolAdapter

        client = MagicMock()
        client.call_tool = AsyncMock(return_value=[
            {"type": "text", "text": "Line 1"},
            {"type": "text", "text": "Line 2"}
        ])

        tool_def = {
            "name": "test_tool",
            "description": "A test tool",
            "inputSchema": {"type": "object"}
        }

        adapter = MCPToolAdapter("test-server", tool_def, client)
        result = await adapter.execute()

        assert result == "Line 1\nLine 2"

    @pytest.mark.asyncio
    async def test_execute_error(self):
        """Test tool execution with error."""
        from nanobot.agent.mcp.tool_adapter import MCPToolAdapter

        client = MagicMock()
        client.call_tool = AsyncMock(side_effect=Exception("Connection error"))

        tool_def = {
            "name": "test_tool",
            "description": "A test tool",
            "inputSchema": {"type": "object"}
        }

        adapter = MCPToolAdapter("test-server", tool_def, client)
        result = await adapter.execute()

        assert "Error calling test-server_test_tool" in result


class TestMCPResourceAdapter:
    """Test MCP resource adapter."""

    def test_resource_adapter_properties(self):
        """Test resource adapter properties."""
        from nanobot.agent.mcp.tool_adapter import MCPResourceAdapter

        client = MagicMock()
        resource = {
            "uri": "file:///test.txt",
            "name": "test.txt",
            "description": "Test file",
            "mimeType": "text/plain"
        }

        adapter = MCPResourceAdapter("test-server", resource, client)

        assert adapter.uri == "file:///test.txt"
        assert adapter.name == "test.txt"
        assert adapter.description == "Test file"
        assert adapter.mime_type == "text/plain"

    @pytest.mark.asyncio
    async def test_resource_read(self):
        """Test reading a resource."""
        from nanobot.agent.mcp.tool_adapter import MCPResourceAdapter

        client = MagicMock()
        client.read_resource = AsyncMock(return_value="Content")

        resource = {
            "uri": "file:///test.txt",
            "name": "test.txt",
        }

        adapter = MCPResourceAdapter("test-server", resource, client)
        result = await adapter.read()

        assert result == "Content"
        client.read_resource.assert_called_once_with("test-server", "file:///test.txt")

    def test_resource_repr(self):
        """Test resource string representation."""
        from nanobot.agent.mcp.tool_adapter import MCPResourceAdapter

        client = MagicMock()
        resource = {
            "uri": "file:///test.txt",
            "name": "test.txt",
        }

        adapter = MCPResourceAdapter("test-server", resource, client)
        assert repr(adapter) == "MCPResourceAdapter(uri=file:///test.txt, name=test.txt)"


class TestMCPConfigSchema:
    """Test MCP configuration schema."""

    def test_mcp_config_defaults(self):
        """Test default MCP config values."""
        from nanobot.config.schema import MCPConfig, MCPServerConfig

        config = MCPConfig()
        assert config.enabled is False
        assert config.servers == []
        assert config.timeout == 30
        assert config.max_retries == 3

    def test_mcp_server_config_defaults(self):
        """Test default MCP server config values."""
        from nanobot.config.schema import MCPServerConfig

        config = MCPServerConfig()
        assert config.name == ""
        assert config.transport == "stdio"
        assert config.enabled is True
        assert config.command is None
        assert config.args == []
        assert config.env == {}
        assert config.url is None
        assert config.timeout == 30

    def test_mcp_config_with_servers(self):
        """Test MCP config with servers."""
        from nanobot.config.schema import MCPConfig

        config = MCPConfig(
            enabled=True,
            servers=[
                {
                    "name": "filesystem",
                    "transport": "stdio",
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                    "enabled": True,
                }
            ],
        )

        assert config.enabled is True
        assert len(config.servers) == 1
        assert config.servers[0].name == "filesystem"
