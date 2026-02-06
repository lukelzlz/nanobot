"""Conversation history summarization using dual-threshold strategy.

This module implements automatic conversation compression:
- T1 (retain threshold): Keep recent T1 tokens of raw conversation
- T2 (trigger threshold): When total length exceeds T2, compress
- Compression: Summarize [T1, ∞) messages into a single assistant [AutoSummary]

Original: [system] [msg1] [msg2] ... [msgN-10] ... [msgN-1] [msgN]
                      ↓ Compress segment    ↓ Retain tail
Result:   [system] [AutoSummary] [msgN-10] ... [msgN-1] [msgN]
"""

import re
from typing import Any

from loguru import logger

from nanobot.providers.base import LLMProvider


class ConversationSummarizer:
    """
    Handles conversation history summarization using dual-threshold strategy.

    The summarization process:
    1. Estimate token count of conversation history
    2. If total > T2, compress messages beyond T1
    3. Clean messages (remove JSON blocks, tool traces)
    4. Call LLM to generate summary
    5. Replace old messages with [AutoSummary] + retained tail
    """

    # Patterns to remove from user/assistant messages
    JSON_BLOCK_PATTERNS = [
        r"(?mis)```(?:json|JSON)?\s*[\r\n]+[\s\S]*?```",
        r"(?mis)```[\s\S]{40,}?```",
    ]

    TOOL_TRACE_PATTERNS = [
        r'^\s*"?tool_calls"?\s*:',
        r'^\s*"?tool_call_id"?\s*:',
        r'^\s*"?function"?\s*:',
        r'^\s*"?type"?\s*:\s*"?function"?',
        r'^\s*"id"\s*:\s*"?call_[^"]+"?',
    ]

    def __init__(self, provider: LLMProvider, model: str):
        """
        Initialize the summarizer.

        Args:
            provider: LLM provider for generating summaries.
            model: Model identifier to use for summarization.
        """
        self.provider = provider
        self.model = model

    def _estimate_tokens(self, text: str) -> int:
        """
        Estimate token count using heuristics.

        Approximation:
        - ASCII characters (English): ~4 chars per token
        - Non-ASCII characters (Chinese): ~1 char per token

        Args:
            text: Text to estimate.

        Returns:
            Estimated token count.
        """
        if not text:
            return 0

        ascii_chars = sum(1 for c in text if ord(c) < 128)
        non_ascii = len(text) - ascii_chars

        # English ~4 chars/token, Chinese ~1 char/token
        return max(1, int(ascii_chars / 4) + non_ascii)

    def _calculate_thresholds(
        self,
        threshold_low: int,
        threshold_high: int,
    ) -> tuple[int, int]:
        """
        Calculate T1 and T2 thresholds.

        Ensures T2 > T1 to avoid logical conflicts.

        Args:
            threshold_low: T1 (retain threshold).
            threshold_high: T2 (trigger threshold).

        Returns:
            Tuple of (T1, T2).
        """
        t1 = threshold_low
        t2 = threshold_high

        if t2 <= t1:
            t2 = t1 + 200

        return t1, t2

    def _remove_json_blocks(self, text: str) -> str:
        """
        Remove JSON code blocks from text.

        Args:
            text: Text to clean.

        Returns:
            Cleaned text.
        """
        if not text:
            return text

        for pattern in self.JSON_BLOCK_PATTERNS:
            text = re.sub(pattern, "", text)

        # Remove large JSON object/array blocks
        def _strip_if_json_block(match):
            block = match.group(0)
            if len(block) >= 80 and (block.count(':') >= 2 or block.count('"') >= 4):
                return ""
            return block

        text = re.sub(r"(?ms)^\s*{[\s\S]{30,}?}\s*$", _strip_if_json_block, text)
        text = re.sub(r"(?ms)^\s*\[[\s\S]{30,}?\]\s*$", _strip_if_json_block, text)

        return text

    def _remove_tool_traces(self, text: str) -> str:
        """
        Remove tool call traces from text.

        Args:
            text: Text to clean.

        Returns:
            Cleaned text.
        """
        if not text:
            return text

        lines = text.splitlines()
        filtered = []

        for line in lines:
            if any(re.search(p, line, flags=re.IGNORECASE) for p in self.TOOL_TRACE_PATTERNS):
                continue
            filtered.append(line)

        cleaned = "\n".join(filtered)
        cleaned = re.sub(r'(?ms)^\s*{[\s\S]{80,}?}\s*$', '', cleaned)

        return cleaned

    def _flatten_content(self, content: Any) -> str:
        """
        Flatten content to string.

        Handles both plain strings and multimodal content structures.

        Args:
            content: Content to flatten (str, list, or dict).

        Returns:
            Flattened string content.
        """
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text" and isinstance(item.get("text"), str):
                        parts.append(item["text"])
                elif isinstance(item, str):
                    parts.append(item)
            return "\n".join(parts)
        return str(content) if content is not None else ""

    def _clean_message_content(
        self,
        msg: dict[str, Any],
        for_tail: bool = False,
    ) -> str | None:
        """
        Clean message content for counting or summarization.

        Args:
            msg: Message dict with 'role' and 'content'.
            for_tail: If True, system messages are ignored (not counted for tail).

        Returns:
            Cleaned content string, or None if message should be ignored.
        """
        role = msg.get("role")
        if role == "tool":
            return None

        content = self._flatten_content(msg.get("content", ""))
        if not content:
            return None

        # System messages: ignore for tail, keep for summary
        if role == "system":
            return None if for_tail else content

        # User/assistant: clean JSON and tool traces
        content = self._remove_json_blocks(content)
        content = self._remove_tool_traces(content)

        return content

    def _build_summary_source(self, messages: list[dict[str, Any]]) -> str:
        """
        Build source text for summarization.

        Args:
            messages: Messages to summarize.

        Returns:
            Formatted source text.
        """
        parts = []

        for msg in messages:
            role = msg.get("role")
            if role == "tool":
                continue

            content = self._flatten_content(msg.get("content", ""))
            if not content:
                continue

            if role in ("user", "assistant"):
                content = self._remove_json_blocks(content)
                content = self._remove_tool_traces(content)

            if content:
                parts.append(f"{role}: {content}")

        return "\n".join(parts).strip()

    def _count_tokens(self, messages: list[dict[str, Any]]) -> int:
        """
        Count total tokens in messages.

        Args:
            messages: Messages to count.

        Returns:
            Estimated token count.
        """
        total = 0
        for msg in messages:
            content = self._clean_message_content(msg, for_tail=False)
            if content:
                total += self._estimate_tokens(content)
        return total

    def should_summarize(
        self,
        history: list[dict[str, Any]],
        threshold_low: int,
        threshold_high: int,
    ) -> bool:
        """
        Check if conversation history should be summarized.

        Args:
            history: Conversation history messages.
            threshold_low: T1 (retain threshold).
            threshold_high: T2 (trigger threshold).

        Returns:
            True if summarization is needed.
        """
        t1, t2 = self._calculate_thresholds(threshold_low, threshold_high)
        total_tokens = self._count_tokens(history)

        logger.debug(
            f"[summary] Token check: {total_tokens} (T1={t1}, T2={t2})"
        )

        return total_tokens > t2

    async def summarize(
        self,
        messages: list[dict[str, Any]],
        prompt: str,
        target_length: int,
        budget_tokens: int | None = None,
    ) -> str | None:
        """
        Generate a summary of the given messages.

        Args:
            messages: Messages to summarize.
            prompt: Summary instruction prompt.
            target_length: Target summary length in tokens.
            budget_tokens: Optional budget constraint for summary.

        Returns:
            Generated summary text, or None on failure.
        """
        source_text = self._build_summary_source(messages)

        if not source_text.strip():
            return ""

        budget = budget_tokens or target_length
        user_prompt = (
            f"{prompt}\n\n"
            f"目標長度（約token數）≤ {budget}。\n\n"
            f"請總結以下對話：\n\n{source_text}"
        )

        logger.debug(
            f"[summary] Input: chars={len(source_text)}, "
            f"tokens≈{self._estimate_tokens(source_text)}, budget≈{budget}"
        )

        try:
            response = await self.provider.chat(
                messages=[
                    {"role": "system", "content": "你是對話摘要助手。請保留事實、人物/實體、約束與未完成事項。"},
                    {"role": "user", "content": user_prompt},
                ],
                model=self.model,
                max_tokens=target_length,
                temperature=0.3,
            )

            summary = (response.content or "").strip()

            # Remove any code blocks
            summary = re.sub(r"(?mis)```[\s\S]*?```", "", summary).strip()

            logger.debug(
                f"[summary] Output: chars={len(summary)}, "
                f"tokens≈{self._estimate_tokens(summary)}"
            )

            return summary if summary else None

        except Exception as e:
            logger.error(f"[summary] Generation failed: {e}")
            return None

    def apply_summary(
        self,
        history: list[dict[str, Any]],
        summary: str,
        retain_tokens: int,
    ) -> list[dict[str, Any]]:
        """
        Apply summary to conversation history.

        Replaces messages beyond retain threshold with a summary message.

        Args:
            history: Original conversation history.
            summary: Generated summary text.
            retain_tokens: T1 threshold for tail retention.

        Returns:
            Updated history with summary applied.
        """
        # Calculate tail retention (from newest backward)
        tail_tokens = 0
        preserved_indices = []

        for i in range(len(history) - 1, -1, -1):
            content = self._clean_message_content(history[i], for_tail=True)
            if not content:
                continue

            msg_len = self._estimate_tokens(content)
            if tail_tokens + msg_len > retain_tokens:
                break

            tail_tokens += msg_len
            preserved_indices.append(i)

        preserved_indices.reverse()  # Ascending order

        # Build new history: summary + preserved tail
        new_history: list[dict[str, Any]] = [
            {"role": "assistant", "content": f"[AutoSummary]\n{summary}"}
        ]

        for idx in preserved_indices:
            new_history.append(history[idx])

        logger.debug(
            f"[summary] Applied: retained={len(preserved_indices)} messages, "
            f"tail≈{tail_tokens} tokens"
        )

        return new_history

    def truncate_to_tail(
        self,
        history: list[dict[str, Any]],
        retain_tokens: int,
    ) -> list[dict[str, Any]]:
        """
        Fallback: truncate history to retain tail only.

        Used when summarization fails.

        Args:
            history: Original conversation history.
            retain_tokens: T1 threshold for tail retention.

        Returns:
            Truncated history with only tail messages.
        """
        tail_tokens = 0
        preserved_indices = []

        for i in range(len(history) - 1, -1, -1):
            content = self._clean_message_content(history[i], for_tail=True)
            if not content:
                continue

            msg_len = self._estimate_tokens(content)
            if tail_tokens + msg_len > retain_tokens:
                break

            tail_tokens += msg_len
            preserved_indices.append(i)

        preserved_indices.reverse()

        result = [history[i] for i in preserved_indices]

        logger.debug(
            f"[summary] Truncated: retained={len(result)} messages, "
            f"≈{tail_tokens} tokens"
        )

        return result
