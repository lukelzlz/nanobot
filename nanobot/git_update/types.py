"""Git update types."""

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class GitRepoState:
    """Runtime state of a git repo."""
    next_run_at_ms: int | None = None
    last_run_at_ms: int | None = None
    last_status: Literal["ok", "error", "conflict", "no_change"] | None = None
    last_error: str | None = None
    last_commit: str | None = None  # Last commit hash after update
    updates_applied: int = 0  # Total number of updates applied


@dataclass
class GitRepo:
    """A git repository to auto-update."""
    id: str
    path: str
    branch: str = "main"
    schedule: str = "0 2 * * *"  # Cron expression
    enabled: bool = True
    on_update: list[str] = field(default_factory=list)
    on_conflict: list[str] = field(default_factory=list)
    notify_on_change: bool = True
    state: GitRepoState = field(default_factory=GitRepoState)


@dataclass
class GitUpdateResult:
    """Result of a git update operation."""
    repo_id: str
    status: Literal["updated", "no_change", "conflict", "error"]
    old_commit: str | None = None
    new_commit: str | None = None
    error: str | None = None
    changes: list[str] = field(default_factory=list)  # List of updated commits
