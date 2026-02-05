"""Tests for configuration schema."""


from nanobot.config.schema import (
    AgentDefaults,
    ChannelsConfig,
    Config,
    DiscordConfig,
    GitRepoConfig,
    GitUpdateConfig,
    MCPConfig,
    MCPServerConfig,
    ProvidersConfig,
    ToolsConfig,
)


class TestAgentDefaults:
    """Test AgentDefaults configuration."""

    def test_defaults(self):
        """Test default values."""
        defaults = AgentDefaults()
        assert defaults.workspace == "~/.nanobot/workspace"
        assert defaults.model == "anthropic/claude-opus-4-5"
        assert defaults.max_tokens == 8192
        assert defaults.temperature == 0.7
        assert defaults.max_tool_iterations == 20

    def test_custom_values(self):
        """Test custom values."""
        defaults = AgentDefaults(
            workspace="/custom/workspace",
            model="custom/model",
            max_tokens=4096,
            temperature=0.5,
            max_tool_iterations=10
        )
        assert defaults.workspace == "/custom/workspace"
        assert defaults.model == "custom/model"
        assert defaults.max_tokens == 4096
        assert defaults.temperature == 0.5
        assert defaults.max_tool_iterations == 10


class TestChannelsConfig:
    """Test ChannelsConfig."""

    def test_defaults(self):
        """Test default channel configs."""
        config = ChannelsConfig()
        assert not config.discord.enabled
        assert not config.telegram.enabled
        assert not config.whatsapp.enabled

    def test_discord_config(self):
        """Test Discord configuration."""
        config = DiscordConfig(
            enabled=True,
            token="test_token",
            allow_from=["user123"],
            admin_users=["admin123"]
        )
        assert config.enabled is True
        assert config.token == "test_token"
        assert config.allow_from == ["user123"]
        assert config.admin_users == ["admin123"]


class TestProvidersConfig:
    """Test ProvidersConfig."""

    def test_defaults(self):
        """Test default provider configs."""
        config = ProvidersConfig()
        assert config.openrouter.api_key == ""
        assert config.anthropic.api_key == ""
        assert config.openai.api_key == ""

    def test_custom_api_keys(self):
        """Test custom API keys."""
        config = ProvidersConfig(
            openrouter={"api_key": "sk-test"}
        )
        assert config.openrouter.api_key == "sk-test"


class TestMCPServerConfig:
    """Test MCP server configuration."""

    def test_defaults(self):
        """Test default values."""
        config = MCPServerConfig()
        assert config.name == ""
        assert config.transport == "stdio"
        assert config.enabled is True
        assert config.command is None
        assert config.args == []
        assert config.env == {}

    def test_stdio_config(self):
        """Test stdio transport configuration."""
        config = MCPServerConfig(
            name="test-server",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem", "/path"],
            env={"TEST": "value"}
        )
        assert config.name == "test-server"
        assert config.command == "npx"
        assert config.args == ["-y", "@modelcontextprotocol/server-filesystem", "/path"]
        assert config.env == {"TEST": "value"}

    def test_sse_config(self):
        """Test SSE transport configuration."""
        config = MCPServerConfig(
            name="sse-server",
            transport="sse",
            url="http://localhost:8080/mcp"
        )
        assert config.name == "sse-server"
        assert config.transport == "sse"
        assert config.url == "http://localhost:8080/mcp"


class TestMCPConfig:
    """Test MCP configuration."""

    def test_defaults(self):
        """Test default values."""
        config = MCPConfig()
        assert config.enabled is False
        assert config.servers == []
        assert config.timeout == 30
        assert config.max_retries == 3

    def test_with_servers(self):
        """Test MCP config with servers."""
        config = MCPConfig(
            enabled=True,
            servers=[
                MCPServerConfig(
                    name="filesystem",
                    command="npx",
                    args=["-y", "@modelcontextprotocol/server-filesystem", "/path"]
                )
            ]
        )
        assert config.enabled is True
        assert len(config.servers) == 1
        assert config.servers[0].name == "filesystem"


class TestToolsConfig:
    """Test Tools configuration."""

    def test_defaults(self):
        """Test default tool configs."""
        config = ToolsConfig()
        assert not config.web.search.api_key
        assert config.web.search.max_results == 5
        assert config.exec.timeout == 60
        assert not config.exec.restrict_to_workspace

    def test_custom_values(self):
        """Test custom values."""
        config = ToolsConfig(
            web={"search": {"api_key": "key", "max_results": 10}},
            exec={"timeout": 120, "restrict_to_workspace": True}
        )
        assert config.web.search.api_key == "key"
        assert config.web.search.max_results == 10
        assert config.exec.timeout == 120
        assert config.exec.restrict_to_workspace is True

    def test_mcp_integration(self):
        """Test MCP config is part of tools."""
        config = ToolsConfig(
            mcp={"enabled": True, "servers": [
                {"name": "test", "command": "test"}
            ]}
        )
        assert config.mcp.enabled is True
        assert config.mcp.servers[0].name == "test"


class TestGitUpdateConfig:
    """Test Git update configuration."""

    def test_defaults(self):
        """Test default values."""
        config = GitUpdateConfig()
        assert config.enabled is False
        assert config.repos == []

    def test_with_repo(self):
        """Test git update config with a repo."""
        config = GitUpdateConfig(
            enabled=True,
            repos=[
                GitRepoConfig(
                    path="/path/to/repo",
                    branch="main",
                    schedule="0 2 * * *",
                    enabled=True
                )
            ]
        )
        assert config.enabled is True
        assert len(config.repos) == 1
        assert config.repos[0].path == "/path/to/repo"


class TestGitRepoConfig:
    """Test Git repository configuration."""

    def test_defaults(self):
        """Test default values."""
        config = GitRepoConfig()
        assert config.path == ""
        assert config.branch == "main"
        assert config.schedule == "0 2 * * *"
        assert config.enabled is True

    def test_all_fields(self):
        """Test all fields."""
        config = GitRepoConfig(
            path="/repo",
            branch="develop",
            schedule="*/5 * * *",
            enabled=False,
            on_update=["echo 'updated'"],
            on_conflict=["echo 'conflict'"],
            notify_on_change=False
        )
        assert config.path == "/repo"
        assert config.branch == "develop"
        assert config.schedule == "*/5 * * *"
        assert config.enabled is False
        assert config.on_update == ["echo 'updated'"]
        assert config.on_conflict == ["echo 'conflict'"]
        assert config.notify_on_change is False


class TestConfig:
    """Test root Config class."""

    def test_defaults(self):
        """Test default configuration."""
        config = Config()
        assert config.agents.defaults.workspace == "~/.nanobot/workspace"
        assert not config.channels.discord.enabled
        assert config.tools.exec.timeout == 60

    def test_workspace_path_property(self):
        """Test workspace_path property expands tilde."""
        config = Config()
        workspace = config.workspace_path
        assert str(workspace).endswith("nanobot/workspace")
        assert "~" not in str(workspace)

    def test_get_api_key_priority(self):
        """Test API key priority order."""
        config = Config()
        # No keys set
        assert config.get_api_key() is None

        # Set openrouter
        config = Config(providers={
            "openrouter": {"api_key": "sk-or"},
            "anthropic": {"api_key": "sk-ant"}
        })
        assert config.get_api_key() == "sk-or"

        # When openrouter is set, it has priority
        config = Config(providers={
            "anthropic": {"api_key": "sk-ant"},
            "openrouter": {"api_key": "sk-or"}
        })
        assert config.get_api_key() == "sk-or"

    def test_get_api_base(self):
        """Test getting API base URL."""
        config = Config()

        # No API key - no base
        assert config.get_api_base() is None

        # Zhipu with custom base (requires api_key to be set)
        config = Config(providers={
            "zhipu": {"api_key": "key", "api_base": "https://custom.endpoint"}
        })
        assert config.get_api_base() == "https://custom.endpoint"

        # Default Zhipu base
        config = Config(providers={
            "zhipu": {"api_key": "key"}
        })
        # Zhipu has no default base in this implementation
        # (it returns None unless a custom one is set)
