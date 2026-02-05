# Long-term Memory

This file stores important information that should persist across sessions.

## User Information

- Developer working on nanobot project
- Uses Python 3.11+, asyncio, event-driven architecture
- Prefers concise, technical explanations

## Preferences

- Code style: Ruff linter, 100 char line length
- Uses Git for version control (main branch)
- Tests with pytest in asyncio mode
- Values code quality and documentation

## Project Context

### nanobot - AI Assistant Framework

- Ultra-lightweight (~4,000 lines) personal AI assistant
- Event-driven architecture with message bus pattern
- Multi-platform: Telegram, WhatsApp, Discord
- Multi-provider LLM support: OpenRouter, Anthropic, OpenAI, Groq, Gemini, vLLM

### Key Components

- `agent/loop.py` - Central agent processing engine
- `bus/events.py` - Message bus (InboundMessage/OutboundMessage)
- `providers/` - LLM provider abstraction layer
- `channels/` - Platform-specific implementations
- `skills/` - YAML+Markdown extensible capabilities
- `agent/tools/` - Built-in tools (9 total)

### Built-in Tools

1. **File Operations**: `read_file`, `write_file`, `edit_file`, `list_dir`
2. **Shell**: `exec` (with safety guards)
3. **Web**: `web_search` (Brave API), `web_fetch` (readability)
4. **Communication**: `message` (send to channels)
5. **Background**: `spawn` (subagent tasks)
6. **Scheduled**: `cron` (direct tool for scheduled tasks)

### Recent Changes (2025-02)

- Enhanced CronTool with direct model access
- Fixed unhashable dict error in `reload_context()`
- Cron tasks now support channel/chat_id context for message delivery
- `process_direct()` accepts channel and chat_id parameters

## Configuration

- Config location: `~/.nanobot/config.json`
- Pydantic-based schema validation
- Workspace-relative file operations

## Important Notes

- Skills use YAML frontmatter + Markdown format
- HEARTBEAT.md checked every 30 minutes for periodic tasks
- Cron tasks can use other tools (read_file, web_search, message)
- WhatsApp bridge uses Node.js/TypeScript in `bridge/` directory

---

*Last updated: 2025-02-05*
