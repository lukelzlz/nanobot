"""Cron/scheduling tool for managing scheduled tasks."""

import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool
from nanobot.cron.types import CronJob, CronJobState, CronPayload, CronSchedule, CronStore


def _now_ms() -> int:
    return int(time.time() * 1000)


def _compute_next_run(schedule: CronSchedule, now_ms: int) -> int | None:
    """Compute next run time in ms."""
    if schedule.kind == "at":
        return schedule.at_ms if schedule.at_ms and schedule.at_ms > now_ms else None

    if schedule.kind == "every":
        if not schedule.every_ms or schedule.every_ms <= 0:
            return None
        return now_ms + schedule.every_ms

    if schedule.kind == "cron" and schedule.expr:
        try:
            from croniter import croniter
            cron = croniter(schedule.expr, time.time())
            next_time = cron.get_next()
            return int(next_time * 1000)
        except Exception:
            return None

    return None


class CronTool(Tool):
    """
    Tool for managing scheduled cron jobs.

    This tool allows the agent to create, list, and remove scheduled tasks
    directly without using shell commands.
    """

    def __init__(self, store_path: Path):
        """
        Initialize the cron tool.

        Args:
            store_path: Path to the cron jobs JSON file.
        """
        self.store_path = store_path
        self._store: CronStore | None = None

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

    def _load_store(self) -> CronStore:
        """Load jobs from disk."""
        if self._store:
            return self._store

        if self.store_path.exists():
            try:
                import json

                data = json.loads(self.store_path.read_text())
                jobs = []
                for j in data.get("jobs", []):
                    jobs.append(CronJob(
                        id=j["id"],
                        name=j["name"],
                        enabled=j.get("enabled", True),
                        schedule=CronSchedule(
                            kind=j["schedule"]["kind"],
                            at_ms=j["schedule"].get("atMs"),
                            every_ms=j["schedule"].get("everyMs"),
                            expr=j["schedule"].get("expr"),
                            tz=j["schedule"].get("tz"),
                        ),
                        payload=CronPayload(
                            kind=j["payload"].get("kind", "agent_turn"),
                            message=j["payload"].get("message", ""),
                            deliver=j["payload"].get("deliver", False),
                            channel=j["payload"].get("channel"),
                            to=j["payload"].get("to"),
                        ),
                        state=CronJobState(
                            next_run_at_ms=j.get("state", {}).get("nextRunAtMs"),
                            last_run_at_ms=j.get("state", {}).get("lastRunAtMs"),
                            last_status=j.get("state", {}).get("lastStatus"),
                            last_error=j.get("state", {}).get("lastError"),
                        ),
                        created_at_ms=j.get("createdAtMs", 0),
                        updated_at_ms=j.get("updatedAtMs", 0),
                        delete_after_run=j.get("deleteAfterRun", False),
                    ))
                self._store = CronStore(jobs=jobs)
            except Exception as e:
                logger.warning(f"Failed to load cron store: {e}")
                self._store = CronStore()
        else:
            self._store = CronStore()

        return self._store

    def _save_store(self) -> None:
        """Save jobs to disk."""
        if not self._store:
            return

        self.store_path.parent.mkdir(parents=True, exist_ok=True)

        import json

        data = {
            "version": self._store.version,
            "jobs": [
                {
                    "id": j.id,
                    "name": j.name,
                    "enabled": j.enabled,
                    "schedule": {
                        "kind": j.schedule.kind,
                        "atMs": j.schedule.at_ms,
                        "everyMs": j.schedule.every_ms,
                        "expr": j.schedule.expr,
                        "tz": j.schedule.tz,
                    },
                    "payload": {
                        "kind": j.payload.kind,
                        "message": j.payload.message,
                        "deliver": j.payload.deliver,
                        "channel": j.payload.channel,
                        "to": j.payload.to,
                    },
                    "state": {
                        "nextRunAtMs": j.state.next_run_at_ms,
                        "lastRunAtMs": j.state.last_run_at_ms,
                        "lastStatus": j.state.last_status,
                        "lastError": j.state.last_error,
                    },
                    "createdAtMs": j.created_at_ms,
                    "updatedAtMs": j.updated_at_ms,
                    "deleteAfterRun": j.delete_after_run,
                }
                for j in self._store.jobs
            ]
        }

        self.store_path.write_text(json.dumps(data, indent=2))

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
            secs = schedule.every_ms or 0
            if secs < 60:
                return f"every {secs}s"
            elif secs < 3600:
                return f"every {secs // 60}m"
            else:
                return f"every {secs // 3600}h {secs % 3600 // 60}m"
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
        """Add a new scheduled job."""
        store = self._load_store()
        now = _now_ms()

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

        # Compute next run
        next_run = _compute_next_run(schedule, now)
        if not next_run and schedule_type != "at":
            return "Error: Could not compute next run time for the given schedule"

        # Create job
        job = CronJob(
            id=str(uuid.uuid4())[:8],
            name=name,
            enabled=True,
            schedule=schedule,
            payload=CronPayload(
                kind="agent_turn",
                message=message,
                deliver=deliver,
                channel=channel,
                to=to,
            ),
            state=CronJobState(next_run_at_ms=next_run),
            created_at_ms=now,
            updated_at_ms=now,
            delete_after_run=(schedule_type == "at"),  # Auto-cleanup one-time jobs
        )

        store.jobs.append(job)
        self._save_store()

        next_run_str = self._format_datetime(next_run) if next_run else "N/A"

        result = f"Created scheduled task '{name}' (ID: {job.id})\n"
        result += f"  Schedule: {self._format_schedule(schedule)}\n"
        result += f"  Next run: {next_run_str}\n"
        if deliver and channel and to:
            result += f"  Will deliver to: {channel}:{to}"

        return result

    async def _list_jobs(self) -> str:
        """List all scheduled jobs."""
        store = self._load_store()

        if not store.jobs:
            return "No scheduled tasks."

        lines = ["Scheduled Tasks:\n"]

        for job in sorted(store.jobs, key=lambda j: j.state.next_run_at_ms or float('inf')):
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
        """Remove a scheduled job."""
        if not job_id:
            return "Error: 'job_id' parameter required for remove operation"

        store = self._load_store()
        before = len(store.jobs)
        store.jobs = [j for j in store.jobs if j.id != job_id]
        removed = len(store.jobs) < before

        if removed:
            self._save_store()
            return f"Removed scheduled task {job_id}"
        else:
            return f"Error: Job '{job_id}' not found"
