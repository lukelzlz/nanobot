"""Security tests for filesystem tools."""

import tempfile
from pathlib import Path

import pytest

from nanobot.agent.tools.filesystem import (
    EditFileTool,
    ListDirTool,
    ReadFileTool,
    WriteFileTool,
    _validate_path_safety,
)


class TestPathSafetyValidation:
    """Test path safety validation function."""

    def test_path_traversal_detected(self):
        """Path traversal patterns are rejected."""
        workspace = Path("/tmp/workspace")
        file_path = Path("/tmp/workspace/../../../etc/passwd")

        is_safe, error = _validate_path_safety(file_path, workspace)
        assert not is_safe
        assert "Path traversal detected" in error

    def test_path_traversal_backslash(self):
        """Windows-style path traversal is rejected."""
        workspace = Path("C:/workspace")
        file_path = Path("C:/workspace/..\\..\\Windows")

        is_safe, error = _validate_path_safety(file_path, workspace)
        assert not is_safe
        assert "Path traversal detected" in error

    def test_path_outside_workspace_rejected(self):
        """Paths outside workspace are rejected."""
        workspace = Path("/tmp/workspace")
        file_path = Path("/tmp/other/file.txt")

        is_safe, error = _validate_path_safety(file_path, workspace)
        assert not is_safe
        assert "outside workspace" in error

    def test_path_inside_workspace_allowed(self):
        """Paths inside workspace are allowed."""
        workspace = Path("/tmp/workspace")
        file_path = Path("/tmp/workspace/subdir/file.txt")

        is_safe, error = _validate_path_safety(file_path, workspace)
        assert is_safe
        assert error == ""

    def test_no_workspace_allows_any_path(self):
        """Without workspace restriction, paths are allowed."""
        file_path = Path("/any/path/file.txt")

        is_safe, error = _validate_path_safety(file_path, None)
        assert is_safe
        assert error == ""


class TestReadFileToolSecurity:
    """Security tests for ReadFileTool."""

    @pytest.mark.asyncio
    async def test_rejects_path_traversal(self):
        """Path traversal attempts are rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            tool = ReadFileTool(workspace=workspace, restrict_to_workspace=True)

            result = await tool.execute("../../../etc/passwd")
            assert "Path traversal detected" in result

    @pytest.mark.asyncio
    async def test_rejects_path_outside_workspace(self):
        """Paths outside workspace are rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            tool = ReadFileTool(workspace=workspace, restrict_to_workspace=True)

            result = await tool.execute("/tmp/other_file.txt")
            assert "outside workspace" in result

    @pytest.mark.asyncio
    async def test_allows_path_within_workspace(self):
        """Paths within workspace are allowed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            test_file = workspace / "test.txt"
            test_file.write_text("Hello, world!")

            tool = ReadFileTool(workspace=workspace, restrict_to_workspace=True)
            result = await tool.execute("test.txt")

            assert result == "Hello, world!"

    @pytest.mark.asyncio
    async def test_no_restriction_allows_any_path(self):
        """Without restriction, any path can be read."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            other_file = Path(tmpdir) / "other.txt"
            other_file.write_text("Outside workspace")

            tool = ReadFileTool(workspace=workspace, restrict_to_workspace=False)
            result = await tool.execute(str(other_file))

            assert result == "Outside workspace"


class TestWriteFileToolSecurity:
    """Security tests for WriteFileTool."""

    @pytest.mark.asyncio
    async def test_rejects_path_traversal(self):
        """Path traversal attempts are rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            tool = WriteFileTool(workspace=workspace, restrict_to_workspace=True)

            result = await tool.execute("../../../etc/passwd", "malicious")
            assert "Path traversal detected" in result

    @pytest.mark.asyncio
    async def test_rejects_write_outside_workspace(self):
        """Writes outside workspace are rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            tool = WriteFileTool(workspace=workspace, restrict_to_workspace=True)

            result = await tool.execute("/tmp/other/file.txt", "content")
            assert "outside workspace" in result

    @pytest.mark.asyncio
    async def test_enforces_max_size(self):
        """File size limit is enforced."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            tool = WriteFileTool(max_size=100)

            large_content = "x" * 200
            result = await tool.execute(str(workspace / "large.txt"), large_content)

            assert "too large" in result

    @pytest.mark.asyncio
    async def test_allows_write_within_workspace(self):
        """Writes within workspace are allowed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            tool = WriteFileTool(workspace=workspace, restrict_to_workspace=True)

            result = await tool.execute("test.txt", "Hello!")
            assert "Successfully wrote" in result

            # Verify file was written
            assert (workspace / "test.txt").read_text() == "Hello!"


class TestEditFileToolSecurity:
    """Security tests for EditFileTool."""

    @pytest.mark.asyncio
    async def test_rejects_path_traversal(self):
        """Path traversal attempts are rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            tool = EditFileTool(workspace=workspace, restrict_to_workspace=True)

            result = await tool.execute("../../../etc/passwd", "old", "new")
            assert "Path traversal detected" in result


class TestListDirToolSecurity:
    """Security tests for ListDirTool."""

    @pytest.mark.asyncio
    async def test_rejects_path_traversal(self):
        """Path traversal attempts are rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            tool = ListDirTool(workspace=workspace, restrict_to_workspace=True)

            result = await tool.execute("../../../")
            assert "Path traversal detected" in result

    @pytest.mark.asyncio
    async def test_rejects_listing_outside_workspace(self):
        """Listing outside workspace is rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            tool = ListDirTool(workspace=workspace, restrict_to_workspace=True)

            result = await tool.execute("/tmp")
            assert "outside workspace" in result
