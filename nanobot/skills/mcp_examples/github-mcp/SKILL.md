---
name: github-mcp
description: "GitHub operations through MCP server integration"
type: mcp
mcp_servers:
  - github
always: false
requires:
  env:
    - GITHUB_TOKEN
metadata:
  {"nanobot": {"emoji": "octocat", "requires": {"env": ["GITHUB_TOKEN"]}}}
---

# GitHub MCP Skill

This skill provides GitHub integration through the official Model Context Protocol (MCP) GitHub server.

## Setup

1. Install the MCP GitHub server:
   ```bash
   npx -y @modelcontextprotocol/server-github
   ```

2. Configure the GitHub MCP server in `~/.nanobot/config.json`:
   ```json
   {
     "tools": {
       "mcp": {
         "enabled": true,
         "servers": [
           {
             "name": "github",
             "transport": "stdio",
             "command": "npx",
             "args": ["-y", "@modelcontextprotocol/server-github"],
             "env": {"GITHUB_TOKEN": "your-github-token"},
             "enabled": true
           }
         ]
       }
     }
   }
   ```

3. Set your `GITHUB_TOKEN` environment variable with a GitHub personal access token.

## Available Tools

When connected, the following GitHub tools will be available:

- `github_create_issue` - Create issues in repositories
- `github_create_pull_request` - Create pull requests
- `github_push_files` - Push files to repositories
- `github_create_or_update_file` - Create or update files
- `github_find_file_references` - Find file references
- `github_get_file_contents` - Get file contents
- `github_list_branches` - List repository branches
- `github_list_commits` - List commits
- `github_list_issues` - List issues
- `github_list_pull_requests` - List pull requests
- `github_search_code` - Search for code
- `github_search_issues` - Search issues
- `github_search_repositories` - Search repositories

## Usage

Simply ask the agent to perform GitHub operations, and it will use the MCP tools automatically.

Examples:
- "Create an issue in myrepo about the bug in login"
- "List the open pull requests for microsoft/typescript"
- "Search for Python repositories about machine learning"
