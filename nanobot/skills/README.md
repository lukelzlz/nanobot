# nanobot Skills

This directory contains built-in skills that extend nanobot's capabilities.

## Skill Format

Each skill is a directory containing a `SKILL.md` file with:
- YAML frontmatter (name, description, metadata)
- Markdown instructions for the agent

## Skill Types

Skills can have different types:

1. **`instruction`** (default) - Standard instruction-based skills
2. **`mcp`** - MCP-driven skills that require MCP servers
3. **`hybrid`** - Combination of instruction and MCP tools

### MCP Skills

MCP (Model Context Protocol) skills allow nanobot to use external tools through
MCP servers. These skills require:

1. `type: mcp` in the frontmatter
2. `mcp_servers` list specifying required MCP servers
3. MCP server configuration in `~/.nanobot/config.json`

#### MCP Skill Example

```yaml
---
name: github-mcp
description: "GitHub operations through MCP"
type: mcp
mcp_servers:
  - github
always: false
requires:
  env:
    - GITHUB_TOKEN
---
```

#### MCP Configuration

Enable MCP in `~/.nanobot/config.json`:

```json
{
  "tools": {
    "mcp": {
      "enabled": true,
      "servers": [
        {
          "name": "filesystem",
          "transport": "stdio",
          "command": "npx",
          "args": ["-y", "@modelcontextprotocol/server-filesystem", "/allowed/path"],
          "enabled": true
        },
        {
          "name": "github",
          "transport": "stdio",
          "command": "npx",
          "args": ["-y", "@modelcontextprotocol/server-github"],
          "env": {"GITHUB_TOKEN": "your-token"},
          "enabled": true
        }
      ]
    }
  }
}
```

Install MCP support: `pip install nanobot-ai[mcp]`

## Attribution

These skills are adapted from [OpenClaw](https://github.com/openclaw/openclaw)'s skill system.
The skill format and metadata structure follow OpenClaw's conventions to maintain compatibility.

## Available Skills

| Skill | Description | Type |
|-------|-------------|------|
| `github` | Interact with GitHub using the `gh` CLI | instruction |
| `weather` | Get weather info using wttr.in and Open-Meteo | instruction |
| `summarize` | Summarize URLs, files, and YouTube videos | instruction |
| `tmux` | Remote-control tmux sessions | instruction |
| `skill-creator` | Create new skills | instruction |
| `github-mcp` | GitHub operations via MCP server | mcp |
| `filesystem-mcp` | Filesystem access via MCP server | mcp |
| `brave-search-mcp` | Web search via Brave MCP server | mcp |