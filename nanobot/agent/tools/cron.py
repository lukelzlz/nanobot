"""Cron/scheduling tool for managing scheduled tasks."""

import time
from datetime import datetime
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool
from nanobot.cron.types import CronSchedule


def _now_ms() -> int:
    return int(time.time() * 1000)


class CronTool(Tool):
    """
    Tool for managing scheduled cron jobs.

    This tool allows the agent to create, list, and remove scheduled tasks
    directly without using shell commands.

    Delegates to CronService for all operations to avoid code duplication.
    """

    def __init__(self, store_path: Path):
        """
        Initialize the cron tool.

        Args:
            store_path: Path to the cron jobs JSON file.
        """
        from nanobot.cron.service import CronService
        # Create a CronService instance (no callback needed for tool usage)
        self._service = CronService(store_path=store_path, on_job=None)

    @property
    def name(self) -> str:
        return "cron"

    @property
    def description(self) -> str:
        return """Manage scheduled tasks and reminders.

Supported operations:
- add: Create a new scheduled task
- list: List all scheduled tasks
- remove: Remove a scheduled task by ID

For reminders, use 'at' schedule type. For recurring tasks, use 'every' or 'cron'."""

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["add", "list", "remove"],
                    "description": "The operation to perform"
                },
                "name": {
                    "type": "string",
                    "description": "Name/label for the task (required for add)"
                },
                "schedule_type": {
                    "type": "string",
                    "enum": ["at", "every", "cron"],
                    "description": "Schedule type: 'at' (one-time), 'every' (interval), or 'cron' (cron expression)"
                },
                "at": {
                    "type": "string",
                    "description": "ISO datetime for one-time task (e.g., '2024-03-15T14:30:00')"
                },
                "every_seconds": {
                    "type": "integer",
                    "description": "Interval in seconds for 'every' schedule"
                },
                "cron_expr": {
                    "type": "string",
                    "description": "Cron expression (e.g., '0 9 * * *' for 9 AM daily)"
                },
                "message": {
                    "type": "string",
                    "description": "Message to send when task runs"
                },
                "deliver": {
                    "type": "boolean",
                    "description": "Whether to deliver response to a channel"
                },
                "channel": {
                    "type": "string",
                    "description": "Channel to deliver to (e.g., 'telegram', 'whatsapp')"
                },
                "to": {
                    "type": "string",
                    "description": "Recipient ID (chat_id or phone number)"
                },
                "job_id": {
                    "type": "string",
                    "description": "Job ID to remove (required for remove operation)"
                }
            }
        }

    def _format_datetime(self, ms: int | None) -> str:
        """Format milliseconds as readable datetime."""
        if not ms:
            return "N/A"
        return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M:%S")

    def _format_schedule(self, schedule: CronSchedule) -> str:
        """Format schedule for display."""
        if schedule.kind == "at":
            return f"at {self._format_datetime(schedule.at_ms)}"
        elif schedule.kind == "every":
            ms = schedule.every_ms if schedule.every_ms else 0
            secs = ms / 1000
            if secs < 60:
                return f"every {int(secs)}s"
            elif secs < 3600:
                return f"every {int(secs // 60)}m"
            else:
                hours = int(secs // 3600)
                mins = int((secs % 3600) // 60)
                if mins > 0:
                    return f"every {hours}h {mins}m"
                return f"every {hours}h"
        elif schedule.kind == "cron":
            return schedule.expr or "cron"
        return schedule.kind

    async def execute(self, operation: str, **kwargs: Any) -> str:
        """Execute a cron operation."""
        if operation == "add":
            return await self._add_job(**kwargs)
        elif operation == "list":
            return await self._list_jobs()
        elif operation == "remove":
            return await self._remove_job(**kwargs)
        else:
            return f"Error: Unknown operation '{operation}'. Use 'add', 'list', or 'remove'."

    async def _add_job(
        self,
        name: str,
        schedule_type: str = "at",
        at: str | None = None,
        every_seconds: int | None = None,
        cron_expr: str | None = None,
        message: str = "",
        deliver: bool = False,
        channel: str | None = None,
        to: str | None = None,
        **kwargs: Any,
    ) -> str:
        """Add a new scheduled job by delegating to CronService."""
        # Build schedule
        schedule = CronSchedule(kind=schedule_type)

        if schedule_type == "at":
            if not at:
                return "Error: 'at' parameter required for 'at' schedule type"
            try:
                dt = datetime.fromisoformat(at)
                schedule.at_ms = int(dt.timestamp() * 1000)
            except ValueError:
                return f"Error: Invalid datetime format '{at}'. Use ISO format like '2024-03-15T14:30:00'"

        elif schedule_type == "every":
            if not every_seconds or every_seconds <= 0:
                return "Error: 'every_seconds' must be a positive integer"
            schedule.every_ms = every_seconds * 1000

        elif schedule_type == "cron":
            if not cron_expr:
                return "Error: 'cron_expr' required for 'cron' schedule type"
            schedule.expr = cron_expr

        # Delegate to CronService
        delete_after_run = (schedule_type == "at")
        job = await self._service.add_job(
            name=name,
            schedule=schedule,
            message=message,
            deliver=deliver,
            channel=channel,
            to=to,
            delete_after_run=delete_after_run,
        )

        next_run_str = self._format_datetime(job.state.next_run_at_ms) if job.state.next_run_at_ms else "N/A"

        result = f"Created scheduled task '{name}' (ID: {job.id})\n"
        result += f"  Schedule: {self._format_schedule(schedule)}\n"
        result += f"  Next run: {next_run_str}\n"
        if deliver and channel and to:
            result += f"  Will deliver to: {channel}:{to}"

        return result

    async def _list_jobs(self) -> str:
        """List all scheduled jobs by delegating to CronService."""
        jobs = await self._service.list_jobs(include_disabled=True)

        if not jobs:
            return "No scheduled tasks."

        lines = ["Scheduled Tasks:\n"]

        for job in jobs:
            status = "enabled" if job.enabled else "disabled"
            next_run = self._format_datetime(job.state.next_run_at_ms)
            last_run = self._format_datetime(job.state.last_run_at_ms)

            lines.append(f"  [{status}] {job.name} (ID: {job.id})")
            lines.append(f"    Schedule: {self._format_schedule(job.schedule)}")
            lines.append(f"    Next run: {next_run}")
            if job.state.last_run_at_ms:
                lines.append(f"    Last run: {last_run}")
            if job.payload.message:
                msg = job.payload.message[:50] + "..." if len(job.payload.message) > 50 else job.payload.message
                lines.append(f"    Message: {msg}")
            if job.payload.deliver:
                lines.append(f"    Delivers to: {job.payload.channel}:{job.payload.to}")
            lines.append("")

        return "\n".join(lines)

    async def _remove_job(self, job_id: str = "", **kwargs: Any) -> str:
        """Remove a scheduled job by delegating to CronService."""
        if not job_id:
            return "Error: 'job_id' parameter required for remove operation"

        removed = await self._service.remove_job(job_id)

        if removed:
            return f"Removed scheduled task {job_id}"
        else:
            return f"Error: Job '{job_id}' not found"

    @property
    def store_path(self) -> Path:
        """Expose the store path for testing purposes."""
        return self._service.store_path

    async def _load_store(self):
        """Load store for testing purposes."""
        return await self._service._load_store()
