# Available Tools

This document describes the tools available to nanobot.

## File Operations

### read_file

Read the contents of a file.

```py
read_file(path: str) -> str
```

### write_file

Write content to a file (creates parent directories if needed).

```py
write_file(path: str, content: str) -> str
```

### edit_file

Edit a file by replacing specific text.

```py
edit_file(path: str, old_text: str, new_text: str) -> str
```

### list_dir

List contents of a directory.

```py
list_dir(path: str) -> str
```

## Shell Execution

### exec

Execute a shell command and return output.

```py
exec(command: str, working_dir: str = None) -> str
```

**Safety Notes:**

- Commands have a configurable timeout (default 60s)
- Dangerous commands are blocked (rm -rf, format, dd, shutdown, etc.)
- Output is truncated at 10,000 characters
- Optional `restrictToWorkspace` config to limit paths

## Web Access

### web_search

Search the web using Brave Search API.

```py
web_search(query: str, count: int = 5) -> str
```

Returns search results with titles, URLs, and snippets. Requires `tools.web.search.apiKey` in config.

### web_fetch

Fetch and extract main content from a URL.

```py
web_fetch(url: str, extractMode: str = "markdown", maxChars: int = 50000) -> str
```

**Notes:**

- Content is extracted using readability
- Supports markdown or plain text extraction
- Output is truncated at 50,000 characters by default

## Communication

### message

Send a message to a specific chat channel.

```py
message(content: str, channel: str = None, chat_id: str = None) -> str
```

**Parameters:**
- `content` - The message text to send
- `channel` - Target channel (telegram, discord, whatsapp)
- `chat_id` - Target recipient's chat ID or phone number

**Usage Notes:**

- **Normal conversation**: Do NOT use this tool — just respond with text
- **Cron/Heartbeat tasks**: You MUST use this tool to send messages
  - Cron tasks have no direct session context
  - Returning text alone will NOT reach the user
  - Always call `message(content="...")` to ensure delivery

**Examples:**

```python
# In a cron task - REQUIRED
message(content="Daily report: All systems operational")

# When channel/chat_id are set in cron job, defaults are used:
message(content="Your reminder message")
```

## Background Tasks

### spawn

Spawn a subagent to handle a task in the background.

```py
spawn(task: str, label: str = None) -> str
```

Use for complex or time-consuming tasks that can run independently. The subagent will complete the task and report back when done.

## Scheduled Reminders (Cron)

### cron tool

Direct tool for managing scheduled tasks without shell commands:

```py
cron(operation: str, name: str = None, schedule_type: str = None, at: str = None,
     every_seconds: int = None, cron_expr: str = None, message: str = "",
     deliver: bool = False, channel: str = None, to: str = None, job_id: str = None) -> str
```

**Operations:**

- `add` - Create a new scheduled task
- `list` - List all scheduled tasks
- `remove` - Remove a task by ID

**Schedule types:**

- `at` - One-time at specific datetime (ISO format: "2024-03-15T14:30:00")
- `every` - Recurring every N seconds
- `cron` - Cron expression (e.g., `"0 9 * * *"` for daily at 9am)

**Parameters:**

- `deliver` - If true, sends the agent's response to the channel
- `channel` - Target channel (telegram, whatsapp, discord)
- `to` - Target recipient (chat_id or phone number)

**Examples:**

```py
# One-time reminder with delivery
cron(operation="add", name="meeting", schedule_type="at",
     at="2024-03-15T14:30:00", message="Meeting starting!",
     deliver=True, channel="telegram", to="123456789")

# Daily task that uses tools
cron(operation="add", name="daily-report", schedule_type="cron",
     cron_expr="0 9 * * *", message="Read logs/report.txt and summarize",
     channel="telegram", to="123456789")

# List all tasks
cron(operation="list")

# Remove a task
cron(operation="remove", job_id="abc12345")
```

**Note:** Cron tasks run with full agent capabilities. When `channel` and `to` are set, the `message` tool automatically uses them as the default target.

---

### CLI commands (alternative)

You can also use shell commands with `nanobot cron add`:

```bash
# Every day at 9am
nanobot cron add --name "morning" --message "Good morning! ☀️" --cron "0 9 * * *"

# Every 2 hours
nanobot cron add --name "water" --message "Drink water! 💧" --every 7200

# At a specific time (ISO format)
nanobot cron add --name "meeting" --message "Meeting starts now!" --at "2025-01-31T15:00:00"

# Manage reminders
nanobot cron list              # List all jobs
nanobot cron remove <job_id>   # Remove a job
```

## Heartbeat Task Management

The `HEARTBEAT.md` file in the workspace is checked every 30 minutes.
Use file operations to manage periodic tasks:

### Add a heartbeat task

```py
# Append a new task
edit_file(
    path="HEARTBEAT.md",
    old_text="## Example Tasks",
    new_text="- [ ] New periodic task here\n\n## Example Tasks"
)
```

### Remove a heartbeat task

```py
# Remove a specific task
edit_file(
    path="HEARTBEAT.md",
    old_text="- [ ] Task to remove\n",
    new_text=""
)
```

### Rewrite all tasks

```py
# Replace the entire file
write_file(
    path="HEARTBEAT.md",
    content="# Heartbeat Tasks\n\n- [ ] Task 1\n- [ ] Task 2\n"
)
```

---

## Adding Custom Tools

To add custom tools:

1. Create a class that extends `Tool` in `nanobot/agent/tools/`
2. Implement `name`, `description`, `parameters`, and `execute`
3. Register it in `AgentLoop._register_default_tools()`
