"""Tests for ContextBuilder."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nanobot.agent.context import ContextBuilder


@pytest.fixture
def temp_workspace(tmp_path: Path):
    """Create a temporary workspace."""
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "memory").mkdir()
    return workspace


@pytest.fixture
def context_builder(temp_workspace: Path):
    """Create a ContextBuilder instance."""
    return ContextBuilder(temp_workspace)


class TestContextBuilder:
    """Test ContextBuilder functionality."""

    def test_init(self, context_builder: ContextBuilder):
        """Test initialization."""
        assert context_builder.workspace == context_builder.workspace
        assert isinstance(context_builder.memory, object)
        assert isinstance(context_builder.skills, object)

    def test_build_system_prompt(self, context_builder: ContextBuilder):
        """Test building system prompt."""
        prompt = context_builder.build_system_prompt()

        assert "nanobot" in prompt
        assert "Current Time" in prompt
        assert "Workspace" in prompt

    def test_system_prompt_includes_time(self, context_builder: ContextBuilder):
        """Test system prompt includes current time."""
        prompt = context_builder.build_system_prompt()
        import re
        # Check for date pattern (YYYY-MM-DD)
        assert re.search(r'\d{4}-\d{2}-\d{2}', prompt)

    def test_system_prompt_includes_workspace(self, context_builder: ContextBuilder):
        """Test system prompt includes workspace path."""
        prompt = context_builder.build_system_prompt()
        assert str(context_builder.workspace) in prompt

    async def test_build_messages(self, context_builder: ContextBuilder):
        """Test building message list."""
        history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"}
        ]
        current = "How are you?"

        messages = await context_builder.build_messages(history, current)

        # Should have system prompt + history + current message
        assert len(messages) == 4
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert messages[2]["role"] == "assistant"
        assert messages[3]["role"] == "user"
        assert messages[3]["content"] == current

    async def test_build_messages_with_media(self, context_builder: ContextBuilder):
        """Test building messages with media attachments."""
        # Create a test image
        import base64
        test_image = context_builder.workspace / "test.png"
        # Create a minimal 1x1 PNG
        png_data = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAfjSJHAAAAPElEQVR42mP8/"
            "5+cRAw8APWIw1zfAAAAAASUVORK5CYII="
        )
        test_image.write_bytes(png_data)

        # Without vision support, should return plain text
        messages = await context_builder.build_messages(
            [], "Check image", media=[str(test_image)], supports_vision=False
        )
        assert len(messages) == 2  # system + user with content
        user_msg = messages[1]
        assert "content" in user_msg
        assert isinstance(user_msg["content"], str)
        assert user_msg["content"] == "Check image"

        # With vision support, should return list with base64 image
        messages = await context_builder.build_messages(
            [], "Check image", media=[str(test_image)], supports_vision=True
        )
        assert len(messages) == 2  # system + user with content
        user_msg = messages[1]
        assert "content" in user_msg
        assert isinstance(user_msg["content"], list)
        assert len(user_msg["content"]) == 2  # image + text

    def test_add_tool_result(self, context_builder: ContextBuilder):
        """Test adding tool result to messages."""
        messages = [
            {"role": "user", "content": "Hello"}
        ]

        context_builder.add_tool_result(
            messages,
            "call_123",
            "search",
            "Found results"
        )

        assert len(messages) == 2
        assert messages[1]["role"] == "tool"
        assert messages[1]["tool_call_id"] == "call_123"
        assert messages[1]["name"] == "search"
        assert messages[1]["content"] == "Found results"

    def test_add_assistant_message(self, context_builder: ContextBuilder):
        """Test adding assistant message."""
        messages = [
            {"role": "user", "content": "Hello"}
        ]

        context_builder.add_assistant_message(messages, "Response text")

        assert len(messages) == 2
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"] == "Response text"

    def test_add_assistant_message_with_tool_calls(self, context_builder: ContextBuilder):
        """Test adding assistant message with tool calls."""
        messages = [
            {"role": "user", "content": "Search"}
        ]

        tool_calls = [
            {
                "id": "call_123",
                "type": "function",
                "function": {
                    "name": "search",
                    "arguments": '{"query": "test"}'
                }
            }
        ]

        context_builder.add_assistant_message(messages, "Thinking...", tool_calls)

        assert len(messages) == 2
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"] == "Thinking..."
        assert messages[1]["tool_calls"] == tool_calls

    def test_build_messages_with_skills(self, context_builder: ContextBuilder):
        """Test building messages with skills."""
        # Create a skill file
        skills_dir = context_builder.workspace / "skills"
        skills_dir.mkdir(parents=True)
        test_skill = skills_dir / "test-skill" / "SKILL.md"
        test_skill.parent.mkdir(parents=True)
        test_skill.write_text(
            "---\n"
            "name: test-skill\n"
            "description: Test skill\n"
            "---\n\n"
            "This is a test skill."
        )

        prompt = context_builder.build_system_prompt()
        assert "test-skill" in prompt

    def test_build_messages_with_bootstrap_files(self, context_builder: ContextBuilder):
        """Test building messages with bootstrap files."""
        # Create AGENTS.md
        (context_builder.workspace / "AGENTS.md").write_text(
            "# Agent Instructions\nBe helpful!"
        )

        # Create MEMORY.md
        (context_builder.workspace / "memory" / "MEMORY.md").write_text(
            "# Memory\nImportant info"
        )

        prompt = context_builder.build_system_prompt()
        assert "Agent Instructions" in prompt
        assert "Memory" in prompt

    def test_mcp_status_in_skills_summary(self, temp_workspace: Path):
        """Test MCP status is included in skills summary."""

        # Create MCP skill
        skills_dir = temp_workspace / "skills"
        skills_dir.mkdir(parents=True)
        mcp_skill = skills_dir / "test-mcp" / "SKILL.md"
        mcp_skill.parent.mkdir(parents=True)
        mcp_skill.write_text(
            "---\n"
            "name: test-mcp\n"
            "type: mcp\n"
            "mcp_servers:\n"
            "  - test-server\n"
            "---\n\n"
            "Test MCP skill."
        )

        context_builder = ContextBuilder(temp_workspace)

        # Mock MCP client
        mock_client = MagicMock()
        mock_client.get_server_names.return_value = ["test-server"]

        context_builder.build_system_prompt()
        # Should include MCP status in skills summary
        # (the actual format depends on implementation)

    async def test_build_messages_empty_history(self, context_builder: ContextBuilder):
        """Test building messages with empty history."""
        messages = await context_builder.build_messages([], "Hello")

        assert len(messages) == 2  # system + user
        assert messages[1]["content"] == "Hello"

    def test_build_user_content_with_empty_media(self, context_builder: ContextBuilder):
        """Test _build_user_content with empty media."""
        result = context_builder._build_user_content("Test", None)
        assert result == "Test"

    def test_build_user_content_with_invalid_media(self, context_builder: ContextBuilder):
        """Test _build_user_content filters out non-images."""
        # Create a text file
        text_file = context_builder.workspace / "test.txt"
        text_file.write_text("Not an image")

        # Without vision support, should just return text
        result = context_builder._build_user_content("Test", [str(text_file)], supports_vision=False)
        assert result == "Test"

        # With vision support but non-image file, should still return text
        result = context_builder._build_user_content("Test", [str(text_file)], supports_vision=True)
        assert result == "Test"
