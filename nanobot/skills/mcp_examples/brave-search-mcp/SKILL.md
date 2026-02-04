---
name: brave-search-mcp
description: "Brave Search integration through MCP server"
type: mcp
mcp_servers:
  - brave-search
always: false
requires:
  env:
    - BRAVE_API_KEY
metadata:
  {"nanobot": {"emoji": "search", "requires": {"env": ["BRAVE_API_KEY"]}}}
---

# Brave Search MCP Skill

This skill provides web search capabilities through the Brave Search MCP server.

## Setup

1. Get a Brave Search API key from https://api.search.brave.com/app/keys

2. Configure the Brave Search MCP server in `~/.nanobot/config.json`:
   ```json
   {
     "tools": {
       "mcp": {
         "enabled": true,
         "servers": [
           {
             "name": "brave-search",
             "transport": "stdio",
             "command": "npx",
             "args": ["-y", "@modelcontextprotocol/server-brave-search"],
             "env": {"BRAVE_API_KEY": "your-brave-api-key"},
             "enabled": true
           }
         ]
       }
     }
   }
   ```

3. Set your `BRAVE_API_KEY` environment variable.

## Available Tools

- `brave_web_search` - Search the web using Brave Search

## Usage

Ask the agent to search the web, and it will use the Brave Search MCP tool.

Examples:
- "Search for recent news about artificial intelligence"
- "Find information about the latest Python release"
- "Search for tutorials on Rust programming"
