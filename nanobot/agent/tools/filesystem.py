"""File system tools: read, write, edit."""

from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool


def _validate_path_safety(
    file_path: Path,
    workspace: Path | None = None,
    allow_absolute: bool = False,
) -> tuple[bool, str]:
    """
    Validate that a path is safe for file operations.

    Args:
        file_path: The path to validate (should be resolved)
        workspace: Optional workspace path to restrict access to
        allow_absolute: Whether to allow absolute paths outside workspace

    Returns:
        Tuple of (is_safe, error_message)
    """
    # Check for path traversal patterns in the original path string
    path_str = str(file_path)
    if "../" in path_str or "..\\" in path_str:
        return False, "Error: Path traversal detected (../ or ..\\ not allowed)"

    # If workspace is specified, ensure path is within workspace
    if workspace is not None:
        workspace_resolved = workspace.resolve()

        # For relative paths, resolve them relative to workspace
        if not file_path.is_absolute():
            resolved_path = (workspace_resolved / file_path).resolve()
        else:
            resolved_path = file_path.resolve()

        try:
            # Check if resolved path is within workspace
            resolved_path.relative_to(workspace_resolved)
        except ValueError:
            return False, f"Error: Path outside workspace not allowed: {resolved_path}"

    return True, ""


class ReadFileTool(Tool):
    """Tool to read file contents."""

    def __init__(self, workspace: Path | None = None, restrict_to_workspace: bool = False):
        """
        Initialize ReadFileTool.

        Args:
            workspace: Workspace path to restrict file operations to
            restrict_to_workspace: Whether to enforce workspace boundary
        """
        self.workspace = workspace
        self.restrict_to_workspace = restrict_to_workspace

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return "Read the contents of a file at the given path."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The file path to read"
                }
            },
            "required": ["path"]
        }

    async def execute(self, path: str, **kwargs: Any) -> str:
        try:
            file_path = Path(path).expanduser()

            # For relative paths with workspace restriction, resolve relative to workspace
            if self.restrict_to_workspace and self.workspace and not file_path.is_absolute():
                file_path = self.workspace / file_path

            # Validate path safety
            if self.restrict_to_workspace and self.workspace:
                is_safe, error = _validate_path_safety(file_path, self.workspace)
                if not is_safe:
                    return error

            if not file_path.exists():
                return f"Error: File not found: {path}"
            if not file_path.is_file():
                return f"Error: Not a file: {path}"

            content = file_path.read_text(encoding="utf-8")
            return content
        except PermissionError:
            return f"Error: Permission denied: {path}"
        except Exception as e:
            return f"Error reading file: {str(e)}"


class WriteFileTool(Tool):
    """Tool to write content to a file."""

    def __init__(self, workspace: Path | None = None, restrict_to_workspace: bool = False, max_size: int = 10_000_000):
        """
        Initialize WriteFileTool.

        Args:
            workspace: Workspace path to restrict file operations to
            restrict_to_workspace: Whether to enforce workspace boundary
            max_size: Maximum file size in bytes (default 10MB)
        """
        self.workspace = workspace
        self.restrict_to_workspace = restrict_to_workspace
        self.max_size = max_size

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return "Write content to a file at the given path. Creates parent directories if needed."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The file path to write to"
                },
                "content": {
                    "type": "string",
                    "description": "The content to write"
                }
            },
            "required": ["path", "content"]
        }

    async def execute(self, path: str, content: str, **kwargs: Any) -> str:
        try:
            # Check content size
            content_size = len(content.encode('utf-8'))
            if content_size > self.max_size:
                return f"Error: Content too large ({content_size} bytes, max {self.max_size})"

            file_path = Path(path).expanduser()

            # For relative paths with workspace restriction, resolve relative to workspace
            if self.restrict_to_workspace and self.workspace and not file_path.is_absolute():
                file_path = self.workspace / file_path

            # Validate path safety (check parent directory)
            if self.restrict_to_workspace and self.workspace:
                is_safe, error = _validate_path_safety(file_path.parent, self.workspace)
                if not is_safe:
                    return error

            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            return f"Successfully wrote {content_size} bytes to {path}"
        except PermissionError:
            return f"Error: Permission denied: {path}"
        except Exception as e:
            return f"Error writing file: {str(e)}"


class EditFileTool(Tool):
    """Tool to edit a file by replacing text."""

    def __init__(self, workspace: Path | None = None, restrict_to_workspace: bool = False):
        """
        Initialize EditFileTool.

        Args:
            workspace: Workspace path to restrict file operations to
            restrict_to_workspace: Whether to enforce workspace boundary
        """
        self.workspace = workspace
        self.restrict_to_workspace = restrict_to_workspace

    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def description(self) -> str:
        return "Edit a file by replacing old_text with new_text. The old_text must exist exactly in the file."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The file path to edit"
                },
                "old_text": {
                    "type": "string",
                    "description": "The exact text to find and replace"
                },
                "new_text": {
                    "type": "string",
                    "description": "The text to replace with"
                }
            },
            "required": ["path", "old_text", "new_text"]
        }

    async def execute(self, path: str, old_text: str, new_text: str, **kwargs: Any) -> str:
        try:
            file_path = Path(path).expanduser()

            # For relative paths with workspace restriction, resolve relative to workspace
            if self.restrict_to_workspace and self.workspace and not file_path.is_absolute():
                file_path = self.workspace / file_path

            # Validate path safety
            if self.restrict_to_workspace and self.workspace:
                is_safe, error = _validate_path_safety(file_path, self.workspace)
                if not is_safe:
                    return error

            if not file_path.exists():
                return f"Error: File not found: {path}"

            content = file_path.read_text(encoding="utf-8")

            if old_text not in content:
                return "Error: old_text not found in file. Make sure it matches exactly."

            # Count occurrences
            count = content.count(old_text)
            if count > 1:
                return f"Warning: old_text appears {count} times. Please provide more context to make it unique."

            new_content = content.replace(old_text, new_text, 1)
            file_path.write_text(new_content, encoding="utf-8")

            return f"Successfully edited {path}"
        except PermissionError:
            return f"Error: Permission denied: {path}"
        except Exception as e:
            return f"Error editing file: {str(e)}"


class ListDirTool(Tool):
    """Tool to list directory contents."""

    def __init__(self, workspace: Path | None = None, restrict_to_workspace: bool = False):
        """
        Initialize ListDirTool.

        Args:
            workspace: Workspace path to restrict file operations to
            restrict_to_workspace: Whether to enforce workspace boundary
        """
        self.workspace = workspace
        self.restrict_to_workspace = restrict_to_workspace

    @property
    def name(self) -> str:
        return "list_dir"

    @property
    def description(self) -> str:
        return "List the contents of a directory."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The directory path to list"
                }
            },
            "required": ["path"]
        }

    async def execute(self, path: str, **kwargs: Any) -> str:
        try:
            dir_path = Path(path).expanduser()

            # For relative paths with workspace restriction, resolve relative to workspace
            if self.restrict_to_workspace and self.workspace and not dir_path.is_absolute():
                dir_path = self.workspace / dir_path

            # Validate path safety
            if self.restrict_to_workspace and self.workspace:
                is_safe, error = _validate_path_safety(dir_path, self.workspace)
                if not is_safe:
                    return error

            if not dir_path.exists():
                return f"Error: Directory not found: {path}"
            if not dir_path.is_dir():
                return f"Error: Not a directory: {path}"

            items = []
            for item in sorted(dir_path.iterdir()):
                prefix = "📁 " if item.is_dir() else "📄 "
                items.append(f"{prefix}{item.name}")

            if not items:
                return f"Directory {path} is empty"

            return "\n".join(items)
        except PermissionError:
            return f"Error: Permission denied: {path}"
        except Exception as e:
            return f"Error listing directory: {str(e)}"
