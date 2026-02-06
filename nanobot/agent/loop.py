"""Agent loop: the core processing engine."""

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.agent.context import ContextBuilder
from nanobot.agent.skills import SkillsLoader
from nanobot.agent.subagent import SubagentManager
from nanobot.agent.tools.cron import CronTool
from nanobot.agent.tools.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from nanobot.agent.tools.message import MessageTool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.spawn import SpawnTool
from nanobot.agent.tools.web import WebFetchTool, WebSearchTool
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider
from nanobot.session.manager import SessionManager

if TYPE_CHECKING:
    from nanobot.config.schema import ExecToolConfig, MCPConfig

# Optional MCP support
try:
    from nanobot.agent.mcp import MCPClient, MCPServerConfig
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False

# Optional auto-summary support
try:
    from nanobot.agent.summary import ConversationSummarizer
    SUMMARY_AVAILABLE = True
except ImportError:
    ConversationSummarizer = None  # type: ignore
    SUMMARY_AVAILABLE = False


class AgentLoop:
    """
    The agent loop is the core processing engine.

    It:
    1. Receives messages from the bus
    2. Builds context with history, memory, skills
    3. Calls the LLM
    4. Executes tool calls
    5. Sends responses back
    """

    def __init__(
        self,
        bus: MessageBus,
        provider: LLMProvider,
        workspace: Path,
        model: str | None = None,
        max_iterations: int = 20,
        brave_api_key: str | None = None,
        exec_config: "ExecToolConfig | None" = None,
        mcp_config: "MCPConfig | None" = None,
        auto_summary_config: dict[str, Any] | None = None,
    ):
        from nanobot.config.schema import ExecToolConfig, MCPConfig
        self.bus = bus
        self.provider = provider
        self.workspace = workspace
        self.model = model or provider.get_default_model()
        self.max_iterations = max_iterations
        self.brave_api_key = brave_api_key
        self.exec_config = exec_config or ExecToolConfig()
        self.mcp_config: MCPConfig | None = None
        self.mcp_client: MCPClient | None = None
        self.auto_summary_config = auto_summary_config or {}

        # Initialize MCP client if available and enabled
        if MCP_AVAILABLE and mcp_config and mcp_config.enabled:
            self.mcp_client = MCPClient(mcp_config)
            self.mcp_config = mcp_config

        self.context = ContextBuilder(
            workspace,
            mcp_client=self.mcp_client,
            auto_summary_config=self.auto_summary_config,
        )
        self.sessions = SessionManager(workspace)
        self.tools = ToolRegistry()
        self.skills_loader = SkillsLoader(workspace)

        self.subagents = SubagentManager(
            provider=provider,
            workspace=workspace,
            bus=bus,
            model=self.model,
            brave_api_key=brave_api_key,
            exec_config=self.exec_config,
        )

        self._running = False
        self._register_default_tools()
        self._init_summarizer()

    def _init_summarizer(self) -> None:
        """Initialize the conversation summarizer if enabled."""
        if not SUMMARY_AVAILABLE:
            return

        if not self.auto_summary_config.get("enabled", False):
            logger.debug("[agent] Auto-summary disabled")
            return

        try:
            self._summarizer = ConversationSummarizer(
                provider=self.provider,
                model=self.model,
            )
            self.context.set_summarizer(self._summarizer)
            logger.info(
                f"[agent] Auto-summary enabled: "
                f"T1={self.auto_summary_config.get('threshold_low', 3000)}, "
                f"T2={self.auto_summary_config.get('threshold_high', 4000)}"
            )
        except Exception as e:
            logger.warning(f"[agent] Failed to initialize summarizer: {e}")
        self._init_summarizer()

    def _register_default_tools(self) -> None:
        """Register the default set of tools."""
        # File tools (with workspace restriction if configured)
        restrict = self.exec_config.restrict_to_workspace
        self.tools.register(ReadFileTool(
            workspace=self.workspace if restrict else None,
            restrict_to_workspace=restrict,
        ))
        self.tools.register(WriteFileTool(
            workspace=self.workspace if restrict else None,
            restrict_to_workspace=restrict,
        ))
        self.tools.register(EditFileTool(
            workspace=self.workspace if restrict else None,
            restrict_to_workspace=restrict,
        ))
        self.tools.register(ListDirTool(
            workspace=self.workspace if restrict else None,
            restrict_to_workspace=restrict,
        ))

        # Shell tool
        self.tools.register(ExecTool(
            working_dir=str(self.workspace),
            timeout=self.exec_config.timeout,
            restrict_to_workspace=self.exec_config.restrict_to_workspace,
        ))

        # Web tools
        self.tools.register(WebSearchTool(api_key=self.brave_api_key))
        self.tools.register(WebFetchTool())

        # Message tool
        message_tool = MessageTool(send_callback=self.bus.publish_outbound)
        self.tools.register(message_tool)

        # Spawn tool (for subagents)
        spawn_tool = SpawnTool(manager=self.subagents)
        self.tools.register(spawn_tool)

        # Cron tool
        from nanobot.config.loader import get_data_dir
        cron_store_path = get_data_dir() / "cron" / "jobs.json"
        self.tools.register(CronTool(cron_store_path))

    async def _register_mcp_tools(self) -> None:
        """Register tools from MCP servers."""
        if not self.mcp_client or not self.mcp_config:
            return

        for server_config in self.mcp_config.servers:
            if not server_config.enabled:
                continue

            try:
                # Convert config schema to MCP client config
                mcp_server_config = MCPServerConfig(
                    name=server_config.name,
                    transport=server_config.transport,
                    enabled=server_config.enabled,
                    command=server_config.command,
                    args=server_config.args,
                    env=server_config.env,
                    url=server_config.url,
                    timeout=server_config.timeout,
                )

                await self.mcp_client.connect(mcp_server_config)

                # Register tools from this server
                tools = self.mcp_client.get_cached_tools(server_config.name)
                for tool_def in tools:
                    adapter = self.mcp_client.create_tool_adapter(
                        server_config.name, tool_def
                    )
                    self.tools.register(adapter)
                    logger.debug(
                        f"Registered MCP tool: {adapter.name} from {server_config.name}"
                    )

                logger.info(
                    f"Registered {len(tools)} tools from MCP server: {server_config.name}"
                )
            except Exception as e:
                logger.error(f"Failed to connect to MCP server {server_config.name}: {e}")

    async def start_mcp(self) -> None:
        """Start MCP connections and register tools."""
        if self.mcp_client:
            await self._register_mcp_tools()

    async def stop_mcp(self) -> None:
        """Stop all MCP connections."""
        if self.mcp_client:
            await self.mcp_client.disconnect_all()


    async def run(self) -> None:
        """Run the agent loop, processing messages from the bus."""
        self._running = True
        logger.info("Agent loop started")

        while self._running:
            try:
                # Wait for next message
                msg = await asyncio.wait_for(
                    self.bus.consume_inbound(),
                    timeout=1.0
                )

                # Process it
                try:
                    response = await self._process_message(msg)
                    if response:
                        await self.bus.publish_outbound(response)
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
                    # Send error response
                    await self.bus.publish_outbound(OutboundMessage(
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        content=f"Sorry, I encountered an error: {str(e)}"
                    ))
            except asyncio.TimeoutError:
                continue

    def stop(self) -> None:
        """Stop the agent loop."""
        self._running = False
        logger.info("Agent loop stopping")

    def reload_context(self) -> dict[str, Any]:
        """
        Reload agent context (skills, configuration).

        Returns:
            Dict with 'added', 'removed', 'modified' lists of changed skills.
        """
        # Get skill lists (dictionaries with 'name' key)
        old_skills_list = self.skills_loader.list_skills(filter_unavailable=False)
        # Reload to pick up any changes
        new_skills_list = self.skills_loader.list_skills(filter_unavailable=False)

        # Extract skill names as sets (dicts aren't hashable, so use names)
        old_names = {s["name"] for s in old_skills_list}
        new_names = {s["name"] for s in new_skills_list}

        # Find changes using set operations
        added = list(new_names - old_names)
        removed = list(old_names - new_names)
        # For simplicity, we don't detect modifications in this implementation
        modified = []

        # Rebuild context (will pick up new skills)
        self.context = ContextBuilder(
            self.workspace,
            mcp_client=self.mcp_client,
            auto_summary_config=self.auto_summary_config,
        )

        # Re-initialize summarizer
        self._init_summarizer()

        logger.info(f"Reloaded context: added={added}, removed={removed}, modified={modified}")

        return {
            "added": added,
            "removed": removed,
            "modified": modified,
        }

    async def _process_message(self, msg: InboundMessage) -> OutboundMessage | None:
        """
        Process a single inbound message.

        Args:
            msg: The inbound message to process.

        Returns:
            The response message, or None if no response needed.
        """
        # Handle system messages (subagent announces)
        # The chat_id contains the original "channel:chat_id" to route back to
        if msg.channel == "system":
            return await self._process_system_message(msg)

        logger.info(f"Processing message from {msg.channel}:{msg.sender_id}")

        # Get or create session
        session = self.sessions.get_or_create(msg.session_key)

        # Update tool contexts
        message_tool = self.tools.get("message")
        if isinstance(message_tool, MessageTool):
            message_tool.set_context(msg.channel, msg.chat_id)

        spawn_tool = self.tools.get("spawn")
        if isinstance(spawn_tool, SpawnTool):
            spawn_tool.set_context(msg.channel, msg.chat_id)

        # Build initial messages (use get_history for LLM-formatted messages)
        messages = await self.context.build_messages(
            history=session.get_history(),
            current_message=msg.content,
            media=msg.media if msg.media else None,
            supports_vision=self.provider.supports_vision(self.model),
            session_key=msg.session_key,
        )

        # Agent loop
        iteration = 0
        final_content = None

        while iteration < self.max_iterations:
            iteration += 1

            # Call LLM
            response = await self.provider.chat(
                messages=messages,
                tools=self.tools.get_definitions(),
                model=self.model
            )

            # Handle tool calls
            if response.has_tool_calls:
                # Add assistant message with tool calls
                tool_call_dicts = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments)  # Must be JSON string
                        }
                    }
                    for tc in response.tool_calls
                ]
                messages = self.context.add_assistant_message(
                    messages, response.content, tool_call_dicts
                )

                # Execute tools
                for tool_call in response.tool_calls:
                    args_str = json.dumps(tool_call.arguments)
                    logger.debug(f"Executing tool: {tool_call.name} with arguments: {args_str}")
                    result = await self.tools.execute(tool_call.name, tool_call.arguments)
                    messages = self.context.add_tool_result(
                        messages, tool_call.id, tool_call.name, result
                    )
            else:
                # No tool calls, we're done
                final_content = response.content
                break

        if final_content is None:
            final_content = "I've completed processing but have no response to give."

        # Save to session
        session.add_message("user", msg.content)
        session.add_message("assistant", final_content)
        self.sessions.save(session)

        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=final_content
        )

    async def _process_system_message(self, msg: InboundMessage) -> OutboundMessage | None:
        """
        Process a system message (e.g., subagent announce).

        The chat_id field contains "original_channel:original_chat_id" to route
        the response back to the correct destination.
        """
        logger.info(f"Processing system message from {msg.sender_id}")

        # Parse origin from chat_id (format: "channel:chat_id")
        if ":" in msg.chat_id:
            parts = msg.chat_id.split(":", 1)
            origin_channel = parts[0]
            origin_chat_id = parts[1]
        else:
            # Fallback
            origin_channel = "cli"
            origin_chat_id = msg.chat_id

        # Use the origin session for context
        session_key = f"{origin_channel}:{origin_chat_id}"
        session = self.sessions.get_or_create(session_key)

        # Update tool contexts
        message_tool = self.tools.get("message")
        if isinstance(message_tool, MessageTool):
            message_tool.set_context(origin_channel, origin_chat_id)

        spawn_tool = self.tools.get("spawn")
        if isinstance(spawn_tool, SpawnTool):
            spawn_tool.set_context(origin_channel, origin_chat_id)

        # Build messages with the announce content
        messages = await self.context.build_messages(
            history=session.get_history(),
            current_message=msg.content,
            supports_vision=self.provider.supports_vision(self.model),
            session_key=session_key,
        )

        # Agent loop (limited for announce handling)
        iteration = 0
        final_content = None

        while iteration < self.max_iterations:
            iteration += 1

            response = await self.provider.chat(
                messages=messages,
                tools=self.tools.get_definitions(),
                model=self.model
            )

            if response.has_tool_calls:
                tool_call_dicts = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments)
                        }
                    }
                    for tc in response.tool_calls
                ]
                messages = self.context.add_assistant_message(
                    messages, response.content, tool_call_dicts
                )

                for tool_call in response.tool_calls:
                    args_str = json.dumps(tool_call.arguments)
                    logger.debug(f"Executing tool: {tool_call.name} with arguments: {args_str}")
                    result = await self.tools.execute(tool_call.name, tool_call.arguments)
                    messages = self.context.add_tool_result(
                        messages, tool_call.id, tool_call.name, result
                    )
            else:
                final_content = response.content
                break

        if final_content is None:
            final_content = "Background task completed."

        # Save to session (mark as system message in history)
        session.add_message("user", f"[System: {msg.sender_id}] {msg.content}")
        session.add_message("assistant", final_content)
        self.sessions.save(session)

        return OutboundMessage(
            channel=origin_channel,
            chat_id=origin_chat_id,
            content=final_content
        )

    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
    ) -> str:
        """
        Process a message directly (for CLI usage or cron jobs).

        Args:
            content: The message content.
            session_key: Session identifier.
            channel: Target channel for tool context (e.g., "telegram", "whatsapp").
            chat_id: Target chat ID for tool context.

        Returns:
            The agent's response.
        """
        msg = InboundMessage(
            channel=channel,
            sender_id="system",
            chat_id=chat_id,
            content=content
        )

        response = await self._process_message(msg)
        return response.content if response else ""
