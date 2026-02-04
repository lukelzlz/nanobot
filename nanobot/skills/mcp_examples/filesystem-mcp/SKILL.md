---
name: filesystem-mcp
description: "Filesystem access through MCP server with configurable path restrictions"
type: mcp
mcp_servers:
  - filesystem
always: false
metadata:
  {"nanobot": {"emoji": "folder"}}
---

# Filesystem MCP Skill

This skill provides controlled filesystem access through the MCP filesystem server.

## Setup

Configure the filesystem MCP server in `~/.nanobot/config.json`:

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
        }
      ]
    }
  }
}
```

**Important**: Replace `/allowed/path` with the actual directory path you want to allow access to. Only this directory and its subdirectories will be accessible.

## Available Tools

- `filesystem_read_file` - Read file contents
- `filesystem_write_file` - Write to files
- `filesystem_create_directory` - Create directories
- `filesystem_list_directory` - List directory contents
- `filesystem_search_files` - Search for files

## Usage

The agent can access files in the configured allowed path.

Examples:
- "List all Python files in the project"
- "Read the configuration file"
- "Create a new directory structure for my project"
