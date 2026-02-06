"""Context builder for assembling agent prompts."""

import base64
import mimetypes
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.agent.memory import MemoryStore
from nanobot.agent.skills import SkillsLoader

# Optional MCP support
try:
    from nanobot.agent.mcp import MCP_AVAILABLE, MCPClient
except ImportError:
    MCP_AVAILABLE = False
    MCPClient = None  # type: ignore

# Optional auto-summary support
try:
    from nanobot.agent.summary import ConversationSummarizer
except ImportError:
    ConversationSummarizer = None  # type: ignore


class ContextBuilder:
    """
    Builds the context (system prompt + messages) for the agent.

    Assembles bootstrap files, memory, skills, and conversation history
    into a coherent prompt for the LLM.
    """

    BOOTSTRAP_FILES = ["AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md", "IDENTITY.md"]

    def __init__(
        self,
        workspace: Path,
        mcp_client: "MCPClient | None" = None,  # type: ignore
        auto_summary_config: dict[str, Any] | None = None,
    ):  # type: ignore
        self.workspace = workspace
        self.memory = MemoryStore(workspace)
        self.skills = SkillsLoader(workspace)
        self.mcp_client = mcp_client
        self.auto_summary_config = auto_summary_config or {}
        self._summarizer: ConversationSummarizer | None = None
        self._summarizing_sessions: set[str] = set()  # Concurrency protection

    def build_system_prompt(self, skill_names: list[str] | None = None) -> str:
        """
        Build the system prompt from bootstrap files, memory, and skills.

        Args:
            skill_names: Optional list of skills to include.

        Returns:
            Complete system prompt.
        """
        parts = []

        # Core identity
        parts.append(self._get_identity())

        # Bootstrap files
        bootstrap = self._load_bootstrap_files()
        if bootstrap:
            parts.append(bootstrap)

        # Memory context
        memory = self.memory.get_memory_context()
        if memory:
            parts.append(f"# Memory\n\n{memory}")

        # Skills - progressive loading
        # 1. Always-loaded skills: include full content
        always_skills = self.skills.get_always_skills()
        if always_skills:
            always_content = self.skills.load_skills_for_context(always_skills)
            if always_content:
                parts.append(f"# Active Skills\n\n{always_content}")

        # 2. Available skills: only show summary (agent uses read_file to load)
        # Get MCP server status if available
        mcp_status = None
        if self.mcp_client:
            mcp_status = {name: True for name in self.mcp_client.get_server_names()}

        skills_summary = self.skills.build_skills_summary(mcp_status=mcp_status)
        if skills_summary:
            parts.append(f"""# Skills

The following skills extend your capabilities. To use a skill, read its SKILL.md file using the read_file tool.
Skills with available="false" need dependencies installed first - you can try installing them with apt/brew.

{skills_summary}""")

        return "\n\n---\n\n".join(parts)

    def _get_identity(self) -> str:
        """Get the core identity section."""
        from datetime import datetime
        now = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")
        workspace_path = str(self.workspace.expanduser().resolve())

        return f"""# nanobot 🐈

You are nanobot, a helpful AI assistant. You have access to tools that allow you to:
- Read, write, and edit files
- Execute shell commands
- Search the web and fetch web pages
- Send messages to users on chat channels
- Spawn subagents for complex background tasks

## Current Time
{now}

## Workspace
Your workspace is at: {workspace_path}
- Memory files: {workspace_path}/memory/MEMORY.md
- Daily notes: {workspace_path}/memory/YYYY-MM-DD.md
- Custom skills: {workspace_path}/skills/{{skill-name}}/SKILL.md

IMPORTANT: When responding to direct questions or conversations, reply directly with your text response.
Only use the 'message' tool when you need to send a message to a specific chat channel (like WhatsApp).
For normal conversation, just respond with text - do not call the message tool.

Always be helpful, accurate, and concise. When using tools, explain what you're doing.
When remembering something, write to {workspace_path}/memory/MEMORY.md"""

    def _load_bootstrap_files(self) -> str:
        """Load all bootstrap files from workspace."""
        parts = []

        for filename in self.BOOTSTRAP_FILES:
            file_path = self.workspace / filename
            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                parts.append(f"## {filename}\n\n{content}")

        return "\n\n".join(parts) if parts else ""

    def set_summarizer(self, summarizer: "ConversationSummarizer | None") -> None:  # type: ignore
        """Set the conversation summarizer instance."""
        self._summarizer = summarizer

    def set_auto_summary_config(self, config: dict[str, Any] | None) -> None:  # type: ignore
        """Update auto-summary configuration."""
        self.auto_summary_config = config or {}

    async def _maybe_summarize(
        self,
        history: list[dict[str, Any]],
        session_key: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Check if history needs summarization and apply if needed.

        Args:
            history: Conversation history messages.
            session_key: Optional session key for concurrency protection.

        Returns:
            Processed history (summarized if needed).
        """
        if not self.auto_summary_config.get("enabled", False):
            return history

        if self._summarizer is None:
            logger.warning("[summary] Config enabled but no summarizer available")
            return history

        # Concurrency protection
        if session_key and session_key in self._summarizing_sessions:
            logger.debug(f"[summary] Session {session_key} already being summarized")
            return history

        threshold_low = self.auto_summary_config.get("threshold_low", 3000)
        threshold_high = self.auto_summary_config.get("threshold_high", 4000)

        if not self._summarizer.should_summarize(history, threshold_low, threshold_high):
            return history

        # Lock session
        if session_key:
            self._summarizing_sessions.add(session_key)

        try:
            # Calculate tail retention
            t1, t2 = self._summarizer._calculate_thresholds(
                threshold_low, threshold_high
            )

            # Find messages to compress (those beyond T1 tail)
            tail_tokens = 0
            preserved_indices = []
            for i in range(len(history) - 1, -1, -1):
                content = self._summarizer._clean_message_content(history[i], for_tail=True)
                if not content:
                    continue
                msg_len = self._summarizer._estimate_tokens(content)
                if tail_tokens + msg_len > t1:
                    break
                tail_tokens += msg_len
                preserved_indices.append(i)

            preserved_indices.reverse()
            preserved_set = set(preserved_indices)

            # Messages to compress
            compress_indices = [
                i for i, m in enumerate(history)
                if m.get("role") != "tool" and i not in preserved_set
            ]

            if not compress_indices:
                return history

            # Generate summary
            target_length = self.auto_summary_config.get("target_length", 300)
            budget_tokens = max(50, t2 - tail_tokens)
            prompt = self.auto_summary_config.get(
                "prompt",
                "請根據對話歷史生成結構化摘要，提取要點、當前狀態與未完成事項。"
            )

            summary = await self._summarizer.summarize(
                [history[i] for i in compress_indices],
                prompt,
                target_length,
                budget_tokens,
            )

            if summary:
                new_history = self._summarizer.apply_summary(history, summary, t1)
                logger.info(
                    f"[summary] Compressed {len(history)} -> {len(new_history)} messages"
                )
                return new_history
            else:
                # Fallback: truncate to tail
                logger.warning("[summary] Generation failed, using truncation fallback")
                return self._summarizer.truncate_to_tail(history, t1)

        finally:
            if session_key:
                self._summarizing_sessions.discard(session_key)

    async def build_messages(
        self,
        history: list[dict[str, Any]],
        current_message: str,
        skill_names: list[str] | None = None,
        media: list[str] | None = None,
        supports_vision: bool = False,
        session_key: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Build the complete message list for an LLM call.

        Args:
            history: Previous conversation messages.
            current_message: The new user message.
            skill_names: Optional skills to include.
            media: Optional list of local file paths for images/media.
            supports_vision: Whether the LLM supports vision input (base64 images).
            session_key: Optional session key for summary concurrency protection.

        Returns:
            List of messages including system prompt.
        """
        messages = []

        # System prompt
        system_prompt = self.build_system_prompt(skill_names)
        messages.append({"role": "system", "content": system_prompt})

        # Apply summarization if needed
        processed_history = await self._maybe_summarize(history, session_key)

        # History
        messages.extend(processed_history)

        # Current message (with optional image attachments)
        user_content = self._build_user_content(current_message, media, supports_vision)
        messages.append({"role": "user", "content": user_content})

        return messages

    def _build_user_content(
        self, text: str, media: list[str] | None, supports_vision: bool = False
    ) -> str | list[dict[str, Any]]:
        """
        Build user message content with optional base64-encoded images.

        Args:
            text: The user's text message.
            media: Optional list of local file paths for images/media.
            supports_vision: Whether to encode images as base64 for vision models.

        Returns:
            Either a plain string (text only) or a list with image_url blocks.
        """
        if not media:
            return text

        # Only encode images if the model supports vision
        if not supports_vision:
            return text

        images = []
        for path in media:
            p = Path(path)
            mime, _ = mimetypes.guess_type(path)
            if not p.is_file() or not mime or not mime.startswith("image/"):
                continue
            b64 = base64.b64encode(p.read_bytes()).decode()
            images.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})

        if not images:
            return text
        return images + [{"type": "text", "text": text}]

    def add_tool_result(
        self,
        messages: list[dict[str, Any]],
        tool_call_id: str,
        tool_name: str,
        result: str
    ) -> list[dict[str, Any]]:
        """
        Add a tool result to the message list.

        Args:
            messages: Current message list.
            tool_call_id: ID of the tool call.
            tool_name: Name of the tool.
            result: Tool execution result.

        Returns:
            Updated message list.
        """
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": result
        })
        return messages

    def add_assistant_message(
        self,
        messages: list[dict[str, Any]],
        content: str | None,
        tool_calls: list[dict[str, Any]] | None = None
    ) -> list[dict[str, Any]]:
        """
        Add an assistant message to the message list.

        Args:
            messages: Current message list.
            content: Message content.
            tool_calls: Optional tool calls.

        Returns:
            Updated message list.
        """
        msg: dict[str, Any] = {"role": "assistant", "content": content or ""}

        if tool_calls:
            msg["tool_calls"] = tool_calls

        messages.append(msg)
        return messages
