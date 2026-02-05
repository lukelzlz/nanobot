"""Tests for MemoryStore."""

from pathlib import Path
from unittest.mock import patch

import pytest

from nanobot.agent.memory import MemoryStore


@pytest.fixture
def temp_workspace(tmp_path: Path):
    """Create a temporary workspace."""
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    return workspace


@pytest.fixture
def memory_store(temp_workspace: Path):
    """Create a MemoryStore instance."""
    return MemoryStore(temp_workspace)


class TestMemoryStore:
    """Test MemoryStore functionality."""

    def test_init(self, memory_store: MemoryStore):
        """Test initialization."""
        assert memory_store.workspace == memory_store.workspace
        assert memory_store.memory_dir == memory_store.workspace / "memory"
        assert memory_store.memory_file == memory_store.memory_dir / "MEMORY.md"

    def test_get_today_file(self, memory_store: MemoryStore):
        """Test getting today's file path."""
        today_file = memory_store.get_today_file()
        assert today_file.name.endswith(".md")
        assert "memory" in str(today_file)

    def test_read_today_empty(self, memory_store: MemoryStore):
        """Test reading today's memory when file doesn't exist."""
        result = memory_store.read_today()
        assert result == ""

    def test_append_and_read_today(self, memory_store: MemoryStore):
        """Test appending and reading today's memory."""
        content = "Test memory entry"
        memory_store.append_today(content)

        result = memory_store.read_today()
        assert "Test memory entry" in result

    def test_append_multiple_times(self, memory_store: MemoryStore):
        """Test appending multiple times."""
        memory_store.append_today("First entry")
        memory_store.append_today("Second entry")

        result = memory_store.read_today()
        assert "First entry" in result
        assert "Second entry" in result

    def test_append_creates_header_for_new_day(self, memory_store: MemoryStore):
        """Test that appending to a new day creates a header."""
        with patch("nanobot.agent.memory.today_date") as mock_date:
            mock_date.return_value = "2025-01-15"
            memory_store.append_today("First entry")

            result = memory_store.read_today()
            assert "# 2025-01-15" in result
            assert "First entry" in result

    def test_read_long_term_empty(self, memory_store: MemoryStore):
        """Test reading long-term memory when file doesn't exist."""
        result = memory_store.read_long_term()
        assert result == ""

    def test_write_and_read_long_term(self, memory_store: MemoryStore):
        """Test writing and reading long-term memory."""
        content = "# Important Information\nThis should persist."
        memory_store.write_long_term(content)

        result = memory_store.read_long_term()
        assert result == content

    def test_get_recent_memories(self, memory_store: MemoryStore):
        """Test getting recent memories from multiple days."""
        # Create memory files for multiple days
        memory_dir = memory_store.memory_dir

        # Day 1
        day1 = memory_dir / "2025-01-14.md"
        day1.write_text("# Day 1\nContent from day 1")

        # Day 2
        day2 = memory_dir / "2025-01-15.md"
        day2.write_text("# Day 2\nContent from day 2")

        # Day 3 (today)
        day3 = memory_dir / "2025-01-16.md"
        day3.write_text("# Day 3\nContent from day 3")

        with patch("nanobot.agent.memory.datetime") as mock_dt:
            from datetime import datetime as dt

            # Mock datetime.now().date() to return 2025-01-16
            mock_dt.now.return_value = dt(2025, 1, 16, 12, 0, 0)

            result = memory_store.get_recent_memories(days=3)

        assert "Day 1" in result
        assert "Day 2" in result
        assert "Day 3" in result
        # Should be separated by "---"
        assert "---" in result

    def test_get_recent_memories_empty(self, memory_store: MemoryStore):
        """Test getting recent memories when no files exist."""
        with patch("nanobot.agent.memory.datetime") as mock_dt:
            from datetime import datetime as dt

            mock_dt.now.return_value = dt(2025, 1, 16, 12, 0, 0)

            result = memory_store.get_recent_memories(days=3)
            assert result == ""

    def test_list_memory_files(self, memory_store: MemoryStore):
        """Test listing memory files."""
        memory_dir = memory_store.memory_dir

        # Create some memory files
        (memory_dir / "2025-01-14.md").write_text("Day 1")
        (memory_dir / "2025-01-15.md").write_text("Day 2")
        (memory_dir / "2025-01-16.md").write_text("Day 3")

        files = memory_store.list_memory_files()
        assert len(files) == 3
        # Should be sorted newest first
        assert "2025-01-16" in files[0].name
        assert "2025-01-14" in files[2].name

    def test_list_memory_files_empty(self, memory_store: MemoryStore):
        """Test listing when memory directory doesn't exist."""
        files = memory_store.list_memory_files()
        assert files == []

    def test_get_memory_context_empty(self, memory_store: MemoryStore):
        """Test getting memory context when no memories exist."""
        with patch("nanobot.agent.memory.datetime") as mock_dt:
            from datetime import datetime as dt

            mock_dt.now.return_value = dt(2025, 1, 16, 12, 0, 0)

            result = memory_store.get_memory_context()
            assert result == ""

    def test_get_memory_context_with_long_term(self, memory_store: MemoryStore):
        """Test memory context includes long-term memory."""
        memory_store.write_long_term("# Long-term\nImportant info")

        result = memory_store.get_memory_context()
        assert "Long-term" in result
        assert "Important info" in result

    def test_get_memory_context_with_today(self, memory_store: MemoryStore):
        """Test memory context includes today's notes."""
        memory_store.append_today("Today's task")

        with patch("nanobot.agent.memory.datetime") as mock_dt:
            from datetime import datetime as dt

            mock_dt.now.return_value = dt(2025, 1, 16, 12, 0, 0)

            result = memory_store.get_memory_context()
            assert "Today's task" in result

    def test_get_memory_context_with_both(self, memory_store: MemoryStore):
        """Test memory context combines both sources."""
        memory_store.write_long_term("# Long-term\nImportant info")
        memory_store.append_today("Today's task")

        with patch("nanobot.agent.memory.datetime") as mock_dt:
            from datetime import datetime as dt

            mock_dt.now.return_value = dt(2025, 1, 16, 12, 0, 0)

            result = memory_store.get_memory_context()
            assert "Long-term" in result
            assert "Today's task" in result
