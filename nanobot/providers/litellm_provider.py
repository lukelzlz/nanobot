"""LiteLLM provider implementation for multi-provider support."""

import os
from typing import Any

import litellm
from litellm import acompletion

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


class LiteLLMProvider(LLMProvider):
    """
    LLM provider using LiteLLM for multi-provider support.

    Supports OpenRouter, Anthropic, OpenAI, Gemini, and many other providers through
    a unified interface.
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        default_model: str = "anthropic/claude-opus-4-5"
    ):
        super().__init__(api_key, api_base)
        self.default_model = default_model

        # Detect Zhipu by model name (NOT by api_base - coding plan uses OpenAI-compatible API)
        # Note: GLM Coding Plan endpoint (/api/coding/paas/v4) is OpenAI-compatible
        self.is_zhipu = (
            "zhipu" in default_model and "coding" not in str(api_base).lower() or
            "zai" in default_model or
            (api_base and "zhipu" in api_base and "coding" not in api_base.lower())
        )

        # Detect OpenRouter by api_key prefix or explicit api_base
        self.is_openrouter = (
            (api_key and api_key.startswith("sk-or-")) or
            (api_base and "openrouter" in api_base)
        )

        # Track if using custom endpoint (vLLM, etc.)
        # Exclude Zhipu from vLLM detection since it uses custom api_base
        self.is_vllm = bool(api_base) and not self.is_openrouter and not self.is_zhipu

        # Configure LiteLLM based on provider
        if api_key:
            if self.is_openrouter:
                # OpenRouter mode - set key
                os.environ["OPENROUTER_API_KEY"] = api_key
            elif self.is_zhipu:
                # Zhipu AI (Z.AI) - use ZAI_API_KEY
                os.environ["ZAI_API_KEY"] = api_key
            elif self.is_vllm:
                # vLLM/custom endpoint - uses OpenAI-compatible API
                os.environ["OPENAI_API_KEY"] = api_key
            elif "anthropic" in default_model:
                os.environ.setdefault("ANTHROPIC_API_KEY", api_key)
            elif "openai" in default_model or "gpt" in default_model:
                os.environ.setdefault("OPENAI_API_KEY", api_key)
            elif "gemini" in default_model.lower():
                os.environ.setdefault("GEMINI_API_KEY", api_key)
            elif "groq" in default_model:
                os.environ.setdefault("GROQ_API_KEY", api_key)

        if api_base:
            litellm.api_base = api_base

        # Disable LiteLLM logging noise
        litellm.suppress_debug_info = True

    def supports_vision(self, model: str | None = None) -> bool:
        """
        Check if the model supports vision (image) input.

        Models that support vision:
        - Claude 3.5+ (claude-sonnet-4, claude-opus-4, claude-3-5-*)
        - GPT-4o, GPT-4o-mini, gpt-4.1
        - Gemini 2.0 Flash, Gemini 1.5 Pro
        - Llama 3.2 Vision (llama-3.2-90b-vision)
        - Grok-2-vision
        - Qwen 2.5 VL (qwen-2.5-72b-instruct)

        Args:
            model: Optional model identifier. If None, uses default model.

        Returns:
            True if the model supports vision input.
        """
        model = model or self.default_model
        model_lower = model.lower()

        # Claude 3.5+ and 4.x support vision
        if "claude" in model_lower:
            vision_models = {
                "claude-sonnet-4", "claude-opus-4",
                "claude-3-5-sonnet", "claude-3-5-haiku",
                "claude-sonnet-4.5", "claude-sonnet-4-20250514",
            }
            return any(pattern in model_lower for pattern in vision_models)

        # GPT-4o and GPT-4.1 support vision
        if "gpt" in model_lower:
            vision_models = {
                "gpt-4o", "gpt-4o-mini",
                "gpt-4.1", "gpt-4-turbo",
                "chatgpt-4o", "chatgpt-4o-latest",
            }
            return any(pattern in model_lower for pattern in vision_models)

        # Gemini 2.0 Flash and 1.5 Pro support vision
        if "gemini" in model_lower:
            return "2.0-flash" in model_lower or "1.5" in model_lower

        # Llama 3.2 Vision
        if "llama" in model_lower and "vision" in model_lower:
            return True

        # Grok-2-vision
        if "grok" in model_lower and "vision" in model_lower:
            return True

        # Qwen 2.5 VL (Vision Language)
        if "qwen" in model_lower and ("vl" in model_lower or "vision" in model_lower):
            return True

        # OpenRouter: check if model name contains vision keywords
        if self.is_openrouter:
            vision_keywords = ["vision", "vl", "visual", "claude-3", "claude-4", "gpt-4o"]
            return any(kw in model_lower for kw in vision_keywords)

        return False

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """
        Send a chat completion request via LiteLLM.

        Args:
            messages: List of message dicts with 'role' and 'content'.
            tools: Optional list of tool definitions in OpenAI format.
            model: Model identifier (e.g., 'anthropic/claude-sonnet-4-5').
            max_tokens: Maximum tokens in response.
            temperature: Sampling temperature.

        Returns:
            LLMResponse with content and/or tool calls.
        """
        model = model or self.default_model

        # For OpenRouter, prefix model name if not already prefixed
        if self.is_openrouter and not model.startswith("openrouter/"):
            model = f"openrouter/{model}"

        # For Zhipu/Z.ai cloud API (NOT Coding Plan), ensure prefix is present
        # Coding Plan endpoint is OpenAI-compatible, don't add prefix
        if self.is_zhipu and not self.is_vllm:
            if ("glm" in model.lower() or "zhipu" in model.lower() or "zai" in model.lower()) and not (
                model.startswith("zai/") or
                model.startswith("openrouter/")
            ):
                model = f"zai/{model}"

        # For hosted vLLM (only when no custom api_base), use hosted_vllm/ prefix
        # For custom vLLM endpoints (api_base is set), use openai/ prefix (OpenAI-compatible API)
        if self.is_vllm:
            if self.api_base:
                # Custom endpoint - use OpenAI-compatible API
                if not model.startswith("openai/"):
                    model = f"openai/{model}"
            else:
                # LiteLLM's hosted vLLM service
                if not model.startswith("hosted_vllm/"):
                    model = f"hosted_vllm/{model}"

        # For Gemini, ensure gemini/ prefix if not already present
        if "gemini" in model.lower() and not model.startswith("gemini/"):
            model = f"gemini/{model}"

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        # Pass api_base directly for custom endpoints (vLLM, etc.)
        if self.api_base:
            kwargs["api_base"] = self.api_base

        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        try:
            response = await acompletion(**kwargs)
            return self._parse_response(response)
        except Exception as e:
            # Return error as content for graceful handling
            return LLMResponse(
                content=f"Error calling LLM: {str(e)}",
                finish_reason="error",
            )

    def _parse_response(self, response: Any) -> LLMResponse:
        """Parse LiteLLM response into our standard format."""
        choice = response.choices[0]
        message = choice.message

        tool_calls = []
        if hasattr(message, "tool_calls") and message.tool_calls:
            for tc in message.tool_calls:
                # Parse arguments from JSON string if needed
                args = tc.function.arguments
                if isinstance(args, str):
                    import json
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {"raw": args}

                tool_calls.append(ToolCallRequest(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=args,
                ))

        usage = {}
        if hasattr(response, "usage") and response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        return LLMResponse(
            content=message.content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "stop",
            usage=usage,
        )

    def get_default_model(self) -> str:
        """Get the default model."""
        return self.default_model
