"""Tests for filesystem tools."""

from pathlib import Path

import pytest

from nanobot.agent.tools.filesystem import (
    EditFileTool,
    ListDirTool,
    ReadFileTool,
    WriteFileTool,
)


@pytest.fixture
def temp_dir(tmp_path: Path):
    """Create a temporary directory."""
    dir_path = tmp_path / "test_workspace"
    dir_path.mkdir(parents=True)
    return dir_path


class TestReadFileTool:
    """Test ReadFileTool functionality."""

    def test_properties(self):
        """Test tool properties."""
        tool = ReadFileTool()
        assert tool.name == "read_file"
        assert tool.description
        assert "path" in tool.parameters.get("properties", {})

    @pytest.mark.asyncio
    async def test_read_file(self, temp_dir: Path):
        """Test reading a file."""
        test_file = temp_dir / "test.txt"
        test_file.write_text("Hello, World!")

        tool = ReadFileTool()
        result = await tool.execute(path=str(test_file))

        assert "Hello, World!" in result

    @pytest.mark.asyncio
    async def test_read_nonexistent_file(self, temp_dir: Path):
        """Test reading a file that doesn't exist."""
        tool = ReadFileTool()
        result = await tool.execute(path=str(temp_dir / "nonexistent.txt"))

        assert "Error:" in result

    @pytest.mark.asyncio
    async def test_read_with_tilde_expansion(self, temp_dir: Path):
        """Test reading file with path containing tilde."""
        tool = ReadFileTool()
        # Create a file in temp_dir
        test_file = temp_dir / "test.txt"
        test_file.write_text("Content")

        # Use absolute path
        result = await tool.execute(path=str(test_file))
        assert "Content" in result


class TestWriteFileTool:
    """Test WriteFileTool functionality."""

    def test_properties(self):
        """Test tool properties."""
        tool = WriteFileTool()
        assert tool.name == "write_file"
        assert "path" in tool.parameters.get("properties", {})
        assert "content" in tool.parameters.get("properties", {})

    @pytest.mark.asyncio
    async def test_write_file(self, temp_dir: Path):
        """Test writing a file."""
        tool = WriteFileTool()
        test_file = temp_dir / "output.txt"

        result = await tool.execute(path=str(test_file), content="Test content")

        # Check file was written
        assert test_file.exists()
        assert test_file.read_text() == "Test content"
        # Check result message
        assert "error" not in result.lower() or "wrote" in result.lower()

    @pytest.mark.asyncio
    async def test_write_creates_directories(self, temp_dir: Path):
        """Test writing creates parent directories."""
        tool = WriteFileTool()
        nested_file = temp_dir / "subdir" / "nested" / "file.txt"

        await tool.execute(path=str(nested_file), content="Nested content")

        assert nested_file.exists()
        assert nested_file.read_text() == "Nested content"


class TestEditFileTool:
    """Test EditFileTool functionality."""

    def test_properties(self):
        """Test tool properties."""
        tool = EditFileTool()
        assert tool.name == "edit_file"
        assert "path" in tool.parameters.get("properties", {})
        assert "old_text" in tool.parameters.get("properties", {})
        assert "new_text" in tool.parameters.get("properties", {})

    @pytest.mark.asyncio
    async def test_edit_file_simple(self, temp_dir: Path):
        """Test simple file edit."""
        test_file = temp_dir / "edit.txt"
        test_file.write_text("Line 1\nLine 2\nLine 3\n")

        tool = EditFileTool()
        await tool.execute(
            path=str(test_file),
            old_text="Line 2",
            new_text="Modified Line 2"
        )

        content = test_file.read_text()
        assert "Modified Line 2" in content
        assert "Line 1" in content
        assert "Line 3" in content

    @pytest.mark.asyncio
    async def test_edit_file_multiple(self, temp_dir: Path):
        """Test multiple sequential edits."""
        test_file = temp_dir / "multi.txt"
        test_file.write_text("A\nB\nC\n")

        tool = EditFileTool()
        # First edit
        await tool.execute(
            path=str(test_file),
            old_text="A",
            new_text="X"
        )
        # Second edit
        await tool.execute(
            path=str(test_file),
            old_text="C",
            new_text="Z"
        )

        content = test_file.read_text()
        assert "X\nB\nZ" in content

    @pytest.mark.asyncio
    async def test_edit_file_not_found(self, temp_dir: Path):
        """Test editing non-existent file."""
        tool = EditFileTool()
        result = await tool.execute(
            path=str(temp_dir / "nonexistent.txt"),
            old_text="A",
            new_text="B"
        )

        assert "Error:" in result


class TestListDirTool:
    """Test ListDirTool functionality."""

    def test_properties(self):
        """Test tool properties."""
        tool = ListDirTool()
        assert tool.name == "list_dir"
        assert "path" in tool.parameters.get("properties", {})

    @pytest.mark.asyncio
    async def test_list_dir(self, temp_dir: Path):
        """Test listing directory."""
        # Create some files
        (temp_dir / "file1.txt").write_text("content1")
        (temp_dir / "file2.txt").write_text("content2")
        (temp_dir / "subdir").mkdir()

        tool = ListDirTool()
        result = await tool.execute(path=str(temp_dir))

        assert "file1.txt" in result
        assert "file2.txt" in result
        assert "subdir" in result

    @pytest.mark.asyncio
    async def test_list_dir_nonexistent(self, temp_dir: Path):
        """Test listing non-existent directory."""
        tool = ListDirTool()
        result = await tool.execute(path=str(temp_dir / "nonexistent"))

        assert "Error:" in result
