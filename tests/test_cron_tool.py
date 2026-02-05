"""Tests for CronTool."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.agent.tools.cron import CronTool


@pytest.fixture
def temp_store(tmp_path: Path):
    """Create a temporary store file."""
    return tmp_path / "cron" / "jobs.json"


@pytest.fixture
def cron_tool(temp_store: Path):
    """Create a CronTool with temporary store."""
    return CronTool(temp_store)


class TestCronTool:
    """Test CronTool functionality."""

    def test_tool_properties(self, cron_tool: CronTool):
        """Test tool name and description."""
        assert cron_tool.name == "cron"
        assert cron_tool.description
        assert "scheduled" in cron_tool.description.lower()

    def test_parameters_schema(self, cron_tool: CronTool):
        """Test parameters schema is valid."""
        schema = cron_tool.parameters
        assert schema["type"] == "object"
        assert "operation" in schema["properties"]
        assert "name" in schema["properties"]
        assert "schedule_type" in schema["properties"]

    @pytest.mark.asyncio
    async def test_add_at_schedule(self, cron_tool: CronTool):
        """Test adding a one-time scheduled task."""
        result = await cron_tool.execute(
            operation="add",
            name="test-reminder",
            schedule_type="at",
            at="2025-12-25T09:00:00",
            message="Christmas reminder"
        )

        assert "Created scheduled task" in result
        assert "test-reminder" in result
        assert "ID:" in result

    @pytest.mark.asyncio
    async def test_add_every_schedule(self, cron_tool: CronTool):
        """Test adding a recurring task with interval."""
        result = await cron_tool.execute(
            operation="add",
            name="daily-check",
            schedule_type="every",
            every_seconds=3600,
            message="Hourly check"
        )

        assert "Created scheduled task" in result
        assert "daily-check" in result

    @pytest.mark.asyncio
    async def test_add_cron_schedule(self, cron_tool: CronTool):
        """Test adding a task with cron expression."""
        result = await cron_tool.execute(
            operation="add",
            name="morning",
            schedule_type="cron",
            cron_expr="0 9 * * *",
            message="Good morning"
        )

        assert "Created scheduled task" in result

    @pytest.mark.asyncio
    async def test_add_invalid_datetime(self, cron_tool: CronTool):
        """Test error handling for invalid datetime."""
        result = await cron_tool.execute(
            operation="add",
            name="test",
            schedule_type="at",
            at="invalid-datetime",
            message="test"
        )

        assert "Error:" in result
        assert "Invalid datetime format" in result

    @pytest.mark.asyncio
    async def test_add_missing_at_parameter(self, cron_tool: CronTool):
        """Test error when 'at' parameter is missing."""
        result = await cron_tool.execute(
            operation="add",
            name="test",
            schedule_type="at",
            message="test"
        )

        assert "Error:" in result
        assert "at" in result

    @pytest.mark.asyncio
    async def test_add_missing_every_seconds(self, cron_tool: CronTool):
        """Test error when every_seconds is missing."""
        result = await cron_tool.execute(
            operation="add",
            name="test",
            schedule_type="every",
            message="test"
        )

        assert "Error:" in result

    @pytest.mark.asyncio
    async def test_add_zero_every_seconds(self, cron_tool: CronTool):
        """Test error when every_seconds is zero."""
        result = await cron_tool.execute(
            operation="add",
            name="test",
            schedule_type="every",
            every_seconds=0,
            message="test"
        )

        assert "Error:" in result

    @pytest.mark.asyncio
    async def test_add_with_delivery(self, cron_tool: CronTool):
        """Test adding a task with delivery to channel."""
        result = await cron_tool.execute(
            operation="add",
            name="delivery-test",
            schedule_type="at",
            at="2025-12-25T09:00:00",
            message="Test message",
            deliver=True,
            channel="telegram",
            to="123456"
        )

        assert "Created scheduled task" in result
        assert "telegram:123456" in result

    @pytest.mark.asyncio
    async def test_list_empty(self, cron_tool: CronTool):
        """Test listing when no jobs exist."""
        result = await cron_tool.execute(operation="list")
        assert "No scheduled tasks" in result

    @pytest.mark.asyncio
    async def test_list_with_jobs(self, cron_tool: CronTool):
        """Test listing jobs after adding them."""
        await cron_tool.execute(
            operation="add",
            name="task1",
            schedule_type="every",
            every_seconds=60,
            message="Test 1"
        )
        await cron_tool.execute(
            operation="add",
            name="task2",
            schedule_type="every",
            every_seconds=120,
            message="Test 2"
        )

        result = await cron_tool.execute(operation="list")
        assert "task1" in result
        assert "task2" in result
        assert "enabled" in result

    @pytest.mark.asyncio
    async def test_remove_job(self, cron_tool: CronTool):
        """Test removing a job."""
        # First add a job
        add_result = await cron_tool.execute(
            operation="add",
            name="to-remove",
            schedule_type="every",
            every_seconds=60,
            message="Will be removed"
        )
        # Extract job ID
        import re
        match = re.search(r'ID: ([a-f0-9]+)', add_result)
        assert match
        job_id = match.group(1)

        # Remove it
        result = await cron_tool.execute(
            operation="remove",
            job_id=job_id
        )
        assert "Removed" in result
        assert job_id in result

    @pytest.mark.asyncio
    async def test_remove_nonexistent_job(self, cron_tool: CronTool):
        """Test removing a job that doesn't exist."""
        result = await cron_tool.execute(
            operation="remove",
            job_id="nonexistent"
        )
        assert "Error:" in result
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_remove_without_job_id(self, cron_tool: CronTool):
        """Test remove without providing job_id."""
        result = await cron_tool.execute(operation="remove")
        assert "Error:" in result
        assert "job_id" in result

    @pytest.mark.asyncio
    async def test_unknown_operation(self, cron_tool: CronTool):
        """Test invalid operation."""
        result = await cron_tool.execute(operation="invalid")
        assert "Error:" in result
        assert "Unknown operation" in result

    @pytest.mark.asyncio
    async def test_persistence(self, cron_tool: CronTool):
        """Test that jobs persist across tool instances."""
        # Add a job with first instance
        await cron_tool.execute(
            operation="add",
            name="persistent",
            schedule_type="every",
            every_seconds=60,
            message="Should persist"
        )

        # Create new tool instance with same store
        new_tool = CronTool(cron_tool.store_path)
        result = await new_tool.execute(operation="list")
        assert "persistent" in result

    def test_load_existing_store(self, temp_store: Path):
        """Test loading existing jobs from file."""
        # Create a store file
        temp_store.parent.mkdir(parents=True, exist_ok=True)
        temp_store.write_text(json.dumps({
            "version": 1,
            "jobs": [
                {
                    "id": "test123",
                    "name": "existing-job",
                    "enabled": True,
                    "schedule": {"kind": "every", "everyMs": 60000, "atMs": None, "expr": None, "tz": None},
                    "payload": {"kind": "agent_turn", "message": "Test", "deliver": False, "channel": None, "to": None},
                    "state": {"nextRunAtMs": 1234567890, "lastRunAtMs": None, "lastStatus": None, "lastError": None},
                    "createdAtMs": 1234567890,
                    "updatedAtMs": 1234567890,
                    "deleteAfterRun": False
                }
            ]
        }))

        # Create tool and verify loading
        tool = CronTool(temp_store)
        store = tool._load_store()
        assert len(store.jobs) == 1
        assert store.jobs[0].name == "existing-job"

    def test_format_schedule(self, cron_tool: CronTool):
        """Test schedule formatting."""
        from nanobot.agent.tools.cron import CronSchedule

        # Test 'at' schedule
        schedule_at = CronSchedule(kind="at", at_ms=1234567890000)
        assert "at" in cron_tool._format_schedule(schedule_at)
        assert "2009" in cron_tool._format_schedule(schedule_at)

        # Test 'every' schedule - seconds (30,000 ms = 30 seconds)
        schedule_every_sec = CronSchedule(kind="every", every_ms=30000)
        assert cron_tool._format_schedule(schedule_every_sec) == "every 30s"

        # Test 'every' schedule - minutes (120,000 ms = 2 minutes)
        schedule_every_min = CronSchedule(kind="every", every_ms=120000)
        assert cron_tool._format_schedule(schedule_every_min) == "every 2m"

        # Test 'every' schedule - hours (3,600,000 ms = 1 hour)
        schedule_every_hour = CronSchedule(kind="every", every_ms=3600000)
        assert cron_tool._format_schedule(schedule_every_hour) == "every 1h"

        # Test 'every' schedule with hours and minutes (7,200,000 ms = 2 hours)
        schedule_every_2h = CronSchedule(kind="every", every_ms=7200000)
        assert cron_tool._format_schedule(schedule_every_2h) == "every 2h"

        # Test 'every' schedule with hours and minutes (9,000,000 ms = 2h 30m)
        schedule_every_2h30m = CronSchedule(kind="every", every_ms=9000000)
        assert "every 2h 30m" == cron_tool._format_schedule(schedule_every_2h30m)

        # Test 'cron' schedule
        schedule_cron = CronSchedule(kind="cron", expr="0 9 * * *")
        assert cron_tool._format_schedule(schedule_cron) == "0 9 * * *"

    def test_format_datetime(self, cron_tool: CronTool):
        """Test datetime formatting."""
        assert cron_tool._format_datetime(None) == "N/A"
        # Check that it returns a formatted datetime string
        result = cron_tool._format_datetime(1735107700000)
        assert "12-25" in result  # December 25
        assert ":" in result  # Time separator
