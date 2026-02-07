"""Shell execution tool."""

import asyncio
import os
import re
import shlex
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool


class ExecTool(Tool):
    """Tool to execute shell commands."""

    # Safe commands that can be executed without shell
    _SAFE_COMMANDS = frozenset({
        "ls", "pwd", "cd", "cat", "head", "tail", "grep", "find",
        "echo", "date", "whoami", "id", "uname", "df", "du", "free",
        "ps", "top", "htop", "netstat", "ss", "ping", "traceroute",
        "curl", "wget", "git", "python", "python3", "pip", "pip3",
        "npm", "node", "cargo", "rustc", "go", "java", "javac",
        "mvn", "gradle", "docker", "docker-compose", "kubectl",
        "terraform", "ansible", "make", "cmake", "gcc", "g++", "clang",
        "cargo", "rustup", "gem", "bundle", "composer", "yarn",
        "pytest", "coverage", "black", "ruff", "mypy", "pylint",
        "flake8", "pylint", "sed", "awk", "sort", "uniq", "wc",
        "cut", "tr", "xargs", "timeout", "watch", "tree", "file",
        "stat", "readlink", "realpath", "basename", "dirname",
        "md5sum", "sha1sum", "sha256sum", "base64", "hexdump",
        "jq", "yq", "rsync", "scp", "ssh", "tar", "zip", "unzip",
        "gzip", "gunzip", "xz", "7z", "chmod", "chown", "chgrp",
        "ln", "cp", "mv", "mkdir", "touch", "rm", "rmdir",
    })

    # Characters/patterns that indicate shell features
    _SHELL_PATTERNS = frozenset({
        "|", "&", ";", "$", "`", "\\", ">", "<", "\n", "\r", "\t",
        "&&", "||", ";;", "<<", ">>", "<>", "&>", "&>>", "$(",
        "${", "`\\", "\\$", "\\|", "\\&", "\\;", "\\>", "\\<",
    })

    def __init__(
        self,
        timeout: int = 60,
        working_dir: str | None = None,
        deny_patterns: list[str] | None = None,
        allow_patterns: list[str] | None = None,
        restrict_to_workspace: bool = False,
    ):
        self.timeout = timeout
        self.working_dir = working_dir
        # Extended deny patterns with pipe and command substitution blocks
        self.deny_patterns = deny_patterns or [
            r"\brm\s+-[rf]{1,2}\b",          # rm -r, rm -rf, rm -fr
            r"\bdel\s+/[fq]\b",              # del /f, del /q
            r"\brmdir\s+/s\b",               # rmdir /s
            r"\b(format|mkfs|diskpart)\b",   # disk operations
            r"\bdd\s+if=",                   # dd
            r">\s*/dev/sd",                  # write to disk
            r"\b(shutdown|reboot|poweroff)\b",  # system power
            r":\(\)\s*\{.*\};\s*:",          # fork bomb
            r"\|",                           # pipe command chaining
            r"\$\(",                         # command substitution $()
            r"`",                            # backtick command substitution
            r";\s*\w",                       # command chaining with semicolon
            r"&&",                           # AND command chaining
            r"\|\|",                         # OR command chaining
            r">\s*(?!/dev/null)",            # output redirection (except /dev/null)
            r"<\s*",                         # input redirection
        ]
        self.allow_patterns = allow_patterns or []
        self.restrict_to_workspace = restrict_to_workspace

    @property
    def name(self) -> str:
        return "exec"

    @property
    def description(self) -> str:
        return "Execute a shell command and return its output. Use with caution."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute"
                },
                "working_dir": {
                    "type": "string",
                    "description": "Optional working directory for the command"
                }
            },
            "required": ["command"]
        }

    def _has_shell_features(self, command: str) -> bool:
        """Check if command contains shell features (pipes, redirections, etc.)."""
        for pattern in self._SHELL_PATTERNS:
            if pattern in command:
                return True
        return False

    def _parse_command_safely(self, command: str) -> list[str] | None:
        """
        Parse command into argument list safely.

        Returns None if command has dangerous shell features.
        """
        # Check for shell features first
        if self._has_shell_features(command):
            return None

        try:
            # Use shlex to parse the command into arguments
            args = shlex.split(command)
            if not args:
                return None

            # Verify the command itself is in safe list
            cmd_name = args[0]
            # Extract base command name (remove path if present)
            base_cmd = Path(cmd_name).name

            if base_cmd not in self._SAFE_COMMANDS:
                # Check if it's a path to a command
                if "/" in cmd_name or "\\" in cmd_name:
                    return None  # Don't allow arbitrary paths

            return args
        except ValueError:
            # shlex parsing failed (e.g., unbalanced quotes)
            return None

    async def execute(self, command: str, working_dir: str | None = None, **kwargs: Any) -> str:
        cwd = working_dir or self.working_dir or os.getcwd()
        guard_error = self._guard_command(command, cwd)
        if guard_error:
            return guard_error

        # Parse command safely
        args = self._parse_command_safely(command)
        if args is None:
            return ("Error: Command contains shell features (pipes, redirections, command "
                    "substitution) or uses an unsafe command. For complex operations, "
                    "use multiple exec calls instead.")

        # Resolve working directory path
        try:
            cwd_path = Path(cwd).resolve()
        except Exception:
            cwd_path = Path(os.getcwd()).resolve()

        # Validate working directory exists
        if not cwd_path.exists() or not cwd_path.is_dir():
            return f"Error: Working directory does not exist or is not a directory: {cwd}"

        try:
            # Use create_subprocess_exec instead of shell for safety
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd_path),
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return f"Error: Command timed out after {self.timeout} seconds"

            output_parts = []

            if stdout:
                output_parts.append(stdout.decode("utf-8", errors="replace"))

            if stderr:
                stderr_text = stderr.decode("utf-8", errors="replace")
                if stderr_text.strip():
                    output_parts.append(f"STDERR:\n{stderr_text}")

            if process.returncode != 0:
                output_parts.append(f"\nExit code: {process.returncode}")

            result = "\n".join(output_parts) if output_parts else "(no output)"

            # Truncate very long output
            max_len = 10000
            if len(result) > max_len:
                result = result[:max_len] + f"\n... (truncated, {len(result) - max_len} more chars)"

            return result

        except FileNotFoundError:
            return f"Error: Command not found: {args[0]}"
        except PermissionError:
            return f"Error: Permission denied executing: {args[0]}"
        except Exception as e:
            return f"Error executing command: {str(e)}"

    def _guard_command(self, command: str, cwd: str) -> str | None:
        """Best-effort safety guard for potentially destructive commands."""
        cmd = command.strip()
        lower = cmd.lower()

        # Check deny patterns first
        for pattern in self.deny_patterns:
            if re.search(pattern, lower):
                return "Error: Command blocked by safety guard (dangerous pattern detected)"

        # Check allowlist if configured
        if self.allow_patterns:
            if not any(re.search(p, lower) for p in self.allow_patterns):
                return "Error: Command blocked by safety guard (not in allowlist)"

        # Workspace restriction with improved path traversal detection
        if self.restrict_to_workspace:
            # Check for various path traversal patterns
            traversal_patterns = [
                r"\.\.",           # parent directory
                r"~[^/]",          # home directory expansion
                r"\$HOME",         # $HOME variable
                r"\$USER",         # $USER variable
                r"^/",             # absolute paths at start
                r"^[A-Za-z]:\\",   # Windows absolute paths
            ]

            for pattern in traversal_patterns:
                if re.search(pattern, cmd):
                    return "Error: Command blocked by safety guard (path traversal detected)"

            # Validate all paths in command
            cwd_path = Path(cwd).resolve()

            # Extract paths from command arguments
            try:
                args = shlex.split(cmd)
                for arg in args:
                    # Skip flags and options
                    if arg.startswith("-"):
                        continue

                    arg_path = Path(arg)
                    # Only validate if it looks like a path
                    if arg_path.exists():
                        resolved = arg_path.resolve()
                        # Check if resolved path is within workspace
                        try:
                            if not resolved.is_relative_to(cwd_path):
                                return "Error: Command blocked by safety guard (path outside working dir)"
                        except ValueError:
                            # is_relative_to raises ValueError on Windows for different drives
                            return "Error: Command blocked by safety guard (different drive from working dir)"
            except (ValueError, OSError):
                # If we can't parse safely, block it
                return "Error: Command blocked by safety guard (unable to validate paths)"

        return None
