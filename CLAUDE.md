# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**nanobot** is an ultra-lightweight personal AI assistant framework written in Python (≥3.11). It delivers core agent functionality in ~4,000 lines of code — 99% smaller than similar frameworks. The project uses an event-driven architecture with asyncio, supporting multiple chat platforms (Telegram, WhatsApp, Discord) and LLM providers.

## Development Commands

```bash
# Install in development mode
pip install -e ".[dev]"

# Linting
ruff check .

# Testing (asyncio mode configured)
pytest

# Run specific test
pytest tests/test_specific_file.py

# Build with uv (alternative to pip)
uv build
```

## Code Style

- **Line length**: 100 characters
- **Target Python**: 3.11+
- **Linter**: Ruff (select: E, F, I, N, W; ignore: E501)
- **Async/await**: Used throughout for non-blocking operations

## Architecture Overview

### Core Components

1. **Agent Loop** (`agent/loop.py`): Central processing engine orchestrating LLM calls and tool execution with iteration limits
2. **Message Bus** (`bus/`): Event-driven architecture using InboundMessage/OutboundMessage, decoupling channels from agent processing
3. **Provider System** (`providers/`): Abstraction layer for LLM providers (OpenRouter, Anthropic, OpenAI, Groq, Gemini, vLLM)
4. **Channel System** (`channels/`): Platform-specific implementations with unified message interface
5. **Skills System** (`skills/`): Extensible capabilities using YAML frontmatter + Markdown format
6. **Tool Registry** (`agent/tools/`): Built-in tools for file operations, shell execution, web search, and background tasks

### Key Files

- `cli/commands.py` - Main CLI entry point with all commands
- `agent/loop.py` - Core agent processing engine
- `config/schema.py` - Pydantic configuration models
- `bus/events.py` - Message event definitions
- `providers/base.py` - LLM provider abstraction
- `workspace/AGENTS.md` - Agent behavior guidelines

### Design Patterns

- **Event-Driven**: Message bus decouples components
- **Registry Pattern**: Tool and skill registration
- **Provider Pattern**: Pluggable LLM backends
- **Factory Pattern**: Channel creation

## Configuration

- **Location**: `~/.nanobot/config.json`
- **Schema**: Pydantic-based validation
- **Format**: JSON with provider, channel, and tool-specific configs
- **Workspace**: File operations are workspace-relative

## Skills Format

Skills use YAML frontmatter with Markdown content:

```yaml
---
name: skill-name
description: "Brief description"
metadata: {"nanobot": {"emoji": "🎯", "requires": {"bins": ["cmd"]}}}
---
# Markdown instructions with examples
```

See `nanobot/skills/README.md` for detailed documentation.

## Agent Behavior Guidelines

Key instructions from `workspace/AGENTS.md`:
- Always explain actions before taking them
- Ask for clarification when requests are ambiguous
- Use cron commands for reminders, not just memory writes
- `HEARTBEAT.md` is checked every 30 minutes for periodic tasks
- Keep heartbeat tasks minimal to reduce token usage

## WhatsApp Bridge

The WhatsApp channel uses a Node.js/TypeScript bridge in the `bridge/` directory (not included in wheel, included in sdist). This is a separate process that communicates with the Python bot via WebSocket.
