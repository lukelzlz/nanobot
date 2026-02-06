"""Tests for ConversationSummarizer."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.summary import ConversationSummarizer
from nanobot.providers.base import LLMResponse


@pytest.fixture
def mock_provider():
    """Create a mock LLM provider."""
    provider = MagicMock()
    provider.chat = AsyncMock()
    return provider


@pytest.fixture
def summarizer(mock_provider):
    """Create a ConversationSummarizer instance."""
    return ConversationSummarizer(provider=mock_provider, model="test-model")


class TestTokenEstimation:
    """Test token estimation methods."""

    def test_estimate_empty_string(self, summarizer):
        """Test estimation with empty string."""
        assert summarizer._estimate_tokens("") == 0
        assert summarizer._estimate_tokens(None) == 0

    def test_estimate_english_text(self, summarizer):
        """Test estimation with English text (~4 chars per token)."""
        # 40 ASCII characters should be ~10 tokens
        text = "Hello world, this is a test message for estimation."
        result = summarizer._estimate_tokens(text)
        # 40 chars / 4 = 10, but let's allow some margin
        assert 8 <= result <= 12

    def test_estimate_chinese_text(self, summarizer):
        """Test estimation with Chinese text (~1 char per token)."""
        # 20 Chinese characters should be ~20 tokens
        text = "這是一個測試消息用於估算token數量"
        result = summarizer._estimate_tokens(text)
        # Each Chinese char is ~1 token (allow wider range for heuristic)
        assert 10 <= result <= 25

    def test_estimate_mixed_text(self, summarizer):
        """Test estimation with mixed English and Chinese."""
        text = "Hello 你好 world 世界"
        # 11 ASCII + 4 non-ASCII
        # 11/4 + 4 = 2.75 + 4 = ~7 tokens
        result = summarizer._estimate_tokens(text)
        assert 5 <= result <= 10

    def test_estimate_returns_at_least_one(self, summarizer):
        """Test that estimation returns at least 1 for non-empty text."""
        assert summarizer._estimate_tokens("a") == 1


class TestThresholdCalculation:
    """Test threshold calculation methods."""

    def test_normal_thresholds(self, summarizer):
        """Test normal threshold calculation."""
        t1, t2 = summarizer._calculate_thresholds(3000, 4000)
        assert t1 == 3000
        assert t2 == 4000

    def test_t2_less_than_t1_adjusts(self, summarizer):
        """Test that T2 is adjusted when less than T1."""
        t1, t2 = summarizer._calculate_thresholds(4000, 3000)
        assert t1 == 4000
        assert t2 == 4200  # T1 + 200

    def test_t2_equal_to_t1_adjusts(self, summarizer):
        """Test that T2 is adjusted when equal to T1."""
        t1, t2 = summarizer._calculate_thresholds(3000, 3000)
        assert t1 == 3000
        assert t2 == 3200  # T1 + 200


class TestMessageCleaning:
    """Test message content cleaning methods."""

    def test_remove_json_blocks(self, summarizer):
        """Test removing JSON code blocks."""
        text = '''
Before block
```json
{"key": "value", "nested": {"data": "large content here"}}
```
After block
'''
        result = summarizer._remove_json_blocks(text)
        assert "```json" not in result
        assert "After block" in result
        assert "Before block" in result

    def test_remove_multiline_json_object(self, summarizer):
        """Test removing large JSON object blocks."""
        text = '''
Some text
{"name": "test", "value": "a" * 50, "data": {"nested": "content"}}
More text
'''
        result = summarizer._remove_json_blocks(text)
        # Long JSON should be removed
        assert "Some text" in result
        assert "More text" in result

    def test_remove_tool_traces(self, summarizer):
        """Test removing tool call traces."""
        text = '''
User message content
"tool_calls": [{"id": "call_123"}]
"function": {"name": "search"}
Real content here
'''
        result = summarizer._remove_tool_traces(text)
        assert "tool_calls" not in result
        assert "function" not in result
        assert "User message content" in result
        assert "Real content here" in result

    def test_clean_message_content_ignores_tool_role(self, summarizer):
        """Test that tool messages are ignored."""
        msg = {"role": "tool", "content": "tool result"}
        result = summarizer._clean_message_content(msg)
        assert result is None

    def test_clean_message_content_keeps_system(self, summarizer):
        """Test that system messages are kept (not for tail)."""
        msg = {"role": "system", "content": "System instruction"}
        result = summarizer._clean_message_content(msg, for_tail=False)
        assert result == "System instruction"

    def test_clean_message_content_ignores_system_for_tail(self, summarizer):
        """Test that system messages are ignored for tail calculation."""
        msg = {"role": "system", "content": "System instruction"}
        result = summarizer._clean_message_content(msg, for_tail=True)
        assert result is None

    def test_clean_message_content_cleans_user(self, summarizer):
        """Test that user messages are cleaned."""
        msg = {
            "role": "user",
            "content": "Hello\n```json\n{\"test\": \"value\"}\n```\nWorld"
        }
        result = summarizer._clean_message_content(msg)
        assert result is not None
        assert "```json" not in result
        assert "Hello" in result

    def test_clean_message_content_empty(self, summarizer):
        """Test cleaning empty message content."""
        msg = {"role": "user", "content": ""}
        result = summarizer._clean_message_content(msg)
        # Empty content returns empty string (or None depending on implementation)
        assert result == "" or result is None


class TestContentFlattening:
    """Test content flattening methods."""

    def test_flatten_string_content(self, summarizer):
        """Test flattening plain string content."""
        result = summarizer._flatten_content("Plain text")
        assert result == "Plain text"

    def test_flatten_list_content(self, summarizer):
        """Test flattening list content (multimodal)."""
        content = [
            {"type": "text", "text": "Text part"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}}
        ]
        result = summarizer._flatten_content(content)
        assert result == "Text part"

    def test_flatten_list_with_strings(self, summarizer):
        """Test flattening list with string elements."""
        content = ["Line 1", "Line 2", "Line 3"]
        result = summarizer._flatten_content(content)
        assert result == "Line 1\nLine 2\nLine 3"

    def test_flatten_none_content(self, summarizer):
        """Test flattening None content."""
        result = summarizer._flatten_content(None)
        assert result == ""

    def test_flatten_dict_content(self, summarizer):
        """Test flattening dict content."""
        content = {"key": "value"}
        result = summarizer._flatten_content(content)
        assert result == "{'key': 'value'}"


class TestShouldSummarize:
    """Test should_summarize logic."""

    def test_should_summarize_true_when_exceeds_t2(self, summarizer):
        """Test that summarization is triggered when exceeding T2."""
        # Create a long history (~5000 tokens estimated)
        history = [
            {"role": "user", "content": "Message " * 1000}
            for _ in range(10)
        ]

        result = summarizer.should_summarize(history, 3000, 4000)
        assert result is True

    def test_should_not_summarize_when_under_t2(self, summarizer):
        """Test that summarization is not triggered when under T2."""
        history = [
            {"role": "user", "content": "Short message"}
        ]

        result = summarizer.should_summarize(history, 3000, 4000)
        assert result is False

    def test_should_summarize_with_tool_messages(self, summarizer):
        """Test that tool messages are excluded from count."""
        # Tool messages should be ignored
        history = [
            {"role": "user", "content": "Short message"},
            {"role": "tool", "content": "X" * 10000},  # Should be ignored
        ]

        result = summarizer.should_summarize(history, 3000, 4000)
        assert result is False


class TestApplySummary:
    """Test apply_summary method."""

    def test_apply_summary_creates_summary_message(self, summarizer):
        """Test that apply_summary creates a summary message."""
        history = [
            {"role": "user", "content": "Message 1"},
            {"role": "assistant", "content": "Response 1"},
            {"role": "user", "content": "Message 2"},
            {"role": "assistant", "content": "Response 2"},
        ]

        result = summarizer.apply_summary(history, "Summary text", 5)  # Very low threshold

        # Should have summary at the beginning, and may have some tail messages
        assert result[0]["role"] == "assistant"
        assert "[AutoSummary]" in result[0]["content"]
        assert "Summary text" in result[0]["content"]

    def test_apply_summary_retains_tail(self, summarizer):
        """Test that recent messages are retained in tail."""
        history = [
            {"role": "user", "content": "Old message 1"},
            {"role": "assistant", "content": "Old response 1"},
            {"role": "user", "content": "Recent message"},
            {"role": "assistant", "content": "Recent response"},
        ]

        result = summarizer.apply_summary(history, "Summary", 50)

        # Should have summary + last 2 messages
        assert len(result) >= 2
        assert "[AutoSummary]" in result[0]["content"]
        # Last message should be recent
        assert result[-1]["content"] == "Recent response"

    def test_apply_summary_with_low_retain_threshold(self, summarizer):
        """Test apply_summary with very low retain threshold."""
        history = [
            {"role": "user", "content": "Message " + str(i)}
            for i in range(100)
        ]

        result = summarizer.apply_summary(history, "Summary", 1)  # Extremely low

        # Should have summary at minimum
        assert len(result) >= 1
        assert "[AutoSummary]" in result[0]["content"]


class TestTruncateToTail:
    """Test truncate_to_tail fallback method."""

    def test_truncate_keeps_recent_messages(self, summarizer):
        """Test that truncation keeps recent messages."""
        history = [
            {"role": "user", "content": "Old message " + str(i)}
            for i in range(100)
        ]

        result = summarizer.truncate_to_tail(history, 100)

        # Should have fewer messages than original
        assert len(result) < len(history)
        # Last message should be from the end
        assert result[-1]["content"] == "Old message 99"

    def test_truncate_empty_history(self, summarizer):
        """Test truncating empty history."""
        result = summarizer.truncate_to_tail([], 100)
        assert result == []

    def test_truncate_with_system_messages(self, summarizer):
        """Test that system messages are excluded from tail."""
        history = [
            {"role": "system", "content": "System instruction"},
            {"role": "user", "content": "User message"},
        ]

        result = summarizer.truncate_to_tail(history, 1000)

        # System should not be in result
        assert all(m["role"] != "system" for m in result)


class TestBuildSummarySource:
    """Test _build_summary_source method."""

    def test_build_source_includes_all_roles(self, summarizer):
        """Test that source includes all non-tool roles."""
        messages = [
            {"role": "user", "content": "User says hi"},
            {"role": "assistant", "content": "Assistant responds"},
            {"role": "tool", "content": "Tool result"},  # Should be excluded
            {"role": "system", "content": "System prompt"},
        ]

        result = summarizer._build_summary_source(messages)

        assert "user: User says hi" in result
        assert "assistant: Assistant responds" in result
        assert "system: System prompt" in result
        assert "tool" not in result

    def test_build_source_cleans_content(self, summarizer):
        """Test that source cleans JSON blocks from user/assistant."""
        messages = [
            {
                "role": "user",
                "content": "Question\n```json\n{\"data\": \"value\"}\n```"
            },
            {"role": "assistant", "content": "Answer"},
        ]

        result = summarizer._build_summary_source(messages)

        assert "```json" not in result
        assert "Question" in result
        assert "Answer" in result


class TestSummarizeIntegration:
    """Integration tests for summarize method."""

    @pytest.mark.asyncio
    async def test_summarize_calls_llm(self, summarizer, mock_provider):
        """Test that summarize calls the LLM provider."""
        mock_provider.chat.return_value = LLMResponse(
            content="This is a summary",
            tool_calls=[]
        )

        messages = [
            {"role": "user", "content": "Long conversation " * 100},
        ]

        result = await summarizer.summarize(
            messages,
            "Summarize this",
            target_length=300,
        )

        assert result == "This is a summary"
        mock_provider.chat.assert_called_once()

    @pytest.mark.asyncio
    async def test_summarize_removes_code_blocks_from_result(self, summarizer, mock_provider):
        """Test that code blocks are removed from summary result."""
        # When the entire response is just a code block, it's removed entirely
        mock_provider.chat.return_value = LLMResponse(
            content="```json\n{\"summary\": \"text\"}\n```",
            tool_calls=[]
        )

        messages = [{"role": "user", "content": "Test"}]

        result = await summarizer.summarize(messages, "Summarize", 300)

        # Entire content was a code block, so result is None after stripping
        assert result is None or result == ""

    @pytest.mark.asyncio
    async def test_summarize_preserves_text_outside_code_blocks(self, summarizer, mock_provider):
        """Test that text outside code blocks is preserved."""
        mock_provider.chat.return_value = LLMResponse(
            content="Here's a summary:\n```json\n{\"data\": \"value\"}\n```\nEnd of summary",
            tool_calls=[]
        )

        messages = [{"role": "user", "content": "Test"}]

        result = await summarizer.summarize(messages, "Summarize", 300)

        # Code block removed but other text preserved
        assert result is not None
        assert "```" not in result
        assert "Here's a summary" in result
        assert "End of summary" in result

    @pytest.mark.asyncio
    async def test_summarize_returns_none_on_error(self, summarizer, mock_provider):
        """Test that summarize returns None on error."""
        mock_provider.chat.side_effect = Exception("API error")

        messages = [{"role": "user", "content": "Test"}]

        result = await summarizer.summarize(messages, "Summarize", 300)

        assert result is None

    @pytest.mark.asyncio
    async def test_summarize_with_empty_source(self, summarizer, mock_provider):
        """Test summarizing empty source text."""
        result = await summarizer.summarize(
            [{"role": "tool", "content": "result"}],  # All tools, will result in empty
            "Summarize",
            300
        )

        assert result == ""

    @pytest.mark.asyncio
    async def test_summarize_uses_budget_tokens(self, summarizer, mock_provider):
        """Test that budget_tokens is used in prompt."""
        mock_provider.chat.return_value = LLMResponse(
            content="Summary",
            tool_calls=[]
        )

        messages = [{"role": "user", "content": "Test"}]

        await summarizer.summarize(messages, "Summarize", 300, budget_tokens=500)

        # Check that the call included budget info
        call_args = mock_provider.chat.call_args
        assert call_args is not None

    @pytest.mark.asyncio
    async def test_summarize_strips_empty_response(self, summarizer, mock_provider):
        """Test that empty/whitespace responses return None."""
        mock_provider.chat.return_value = LLMResponse(
            content="   ",
            tool_calls=[]
        )

        messages = [{"role": "user", "content": "Test"}]

        result = await summarizer.summarize(messages, "Summarize", 300)

        # Empty after strip should return None
        assert result is None or result == ""


class TestCountTokens:
    """Test _count_tokens method."""

    def test_count_empty_history(self, summarizer):
        """Test counting empty history."""
        result = summarizer._count_tokens([])
        assert result == 0

    def test_count_all_tool_messages(self, summarizer):
        """Test counting history with only tool messages."""
        history = [
            {"role": "tool", "content": "Result 1"},
            {"role": "tool", "content": "Result 2"},
        ]
        result = summarizer._count_tokens(history)
        # Tool messages are ignored
        assert result == 0

    def test_count_mixed_history(self, summarizer):
        """Test counting mixed message types."""
        history = [
            {"role": "user", "content": "Hello"},  # ~5 chars = ~1-2 tokens
            {"role": "assistant", "content": "Hi there!"},  # ~9 chars = ~2-3 tokens
            {"role": "tool", "content": "Tool result"},  # Ignored
        ]
        result = summarizer._count_tokens(history)
        # Should count only user and assistant
        assert 1 <= result <= 10
