"""Git auto-update service."""

import asyncio
import json
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from loguru import logger

from nanobot.config.schema import Config, GitRepoConfig
from nanobot.git_update.types import GitRepo, GitRepoState, GitUpdateResult


def _now_ms() -> int:
    return int(time.time() * 1000)


def _compute_next_run(schedule: str, now_ms: int) -> int | None:
    """Compute next run time in ms using croniter."""
    try:
        from croniter import croniter
        cron = croniter(schedule, time.time())
        next_time = cron.get_next()
        return int(next_time * 1000)
    except Exception as e:
        logger.error(f"Invalid cron expression '{schedule}': {e}")
        return None


class GitUpdater:
    """Service for auto-updating git repositories on schedule."""

    def __init__(
        self,
        config: Config,
        store_path: Path,
        on_update: Callable[[GitUpdateResult], None] | None = None,
    ):
        self.config = config
        self.store_path = store_path
        self.on_update = on_update  # Callback for update notifications
        self._repos: list[GitRepo] = []
        self._timer_task: asyncio.Task | None = None
        self._running = False
        self._exec_available: bool | None = None  # Cached exec tool availability

    def _load_store(self) -> None:
        """Load repo states from disk."""
        if self._repos:
            return  # Already loaded from config

        # Load from config
        for repo_config in self.config.git_update.repos:
            now = _now_ms()
            repo = GitRepo(
                id=str(uuid.uuid4())[:8],
                path=repo_config.path,
                branch=repo_config.branch,
                schedule=repo_config.schedule,
                enabled=repo_config.enabled,
                on_update=repo_config.on_update,
                on_conflict=repo_config.on_conflict,
                notify_on_change=repo_config.notify_on_change,
                state=GitRepoState(
                    next_run_at_ms=_compute_next_run(repo_config.schedule, now)
                ),
            )
            self._repos.append(repo)

        # Try to load persisted states
        if self.store_path.exists():
            try:
                data = json.loads(self.store_path.read_text())
                for state_data in data.get("repo_states", []):
                    repo_id = state_data.get("id")
                    for repo in self._repos:
                        if repo.id == repo_id:
                            repo.state = GitRepoState(
                                next_run_at_ms=state_data.get("nextRunAtMs"),
                                last_run_at_ms=state_data.get("lastRunAtMs"),
                                last_status=state_data.get("lastStatus"),
                                last_error=state_data.get("lastError"),
                                last_commit=state_data.get("lastCommit"),
                                updates_applied=state_data.get("updatesApplied", 0),
                            )
                            break
            except Exception as e:
                logger.warning(f"Failed to load git update store: {e}")

    def _save_store(self) -> None:
        """Save repo states to disk."""
        self.store_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "version": 1,
            "repo_states": [
                {
                    "id": r.id,
                    "path": r.path,
                    "nextRunAtMs": r.state.next_run_at_ms,
                    "lastRunAtMs": r.state.last_run_at_ms,
                    "lastStatus": r.state.last_status,
                    "lastError": r.state.last_error,
                    "lastCommit": r.state.last_commit,
                    "updatesApplied": r.state.updates_applied,
                }
                for r in self._repos
            ],
        }

        self.store_path.write_text(json.dumps(data, indent=2))

    def _run_git(self, repo: GitRepo, *args: str) -> tuple[int, str, str]:
        """Run a git command in the repo directory."""
        cwd = Path(repo.path).expanduser()
        if not cwd.exists():
            return 1, "", f"Repository path does not exist: {cwd}"

        try:
            result = subprocess.run(
                ["git"] + list(args),
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=60,
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return 1, "", "Git command timed out"
        except Exception as e:
            return 1, "", str(e)

    async def _execute_commands(self, commands: list[str], cwd: Path) -> list[str]:
        """Execute shell commands after update."""
        results = []
        for cmd in commands:
            try:
                proc = await asyncio.create_subprocess_shell(
                    cmd,
                    cwd=cwd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
                if proc.returncode != 0:
                    results.append(f"Command '{cmd}' failed: {stderr.decode()}")
                else:
                    output = stdout.decode().strip()
                    if output:
                        results.append(f"Command '{cmd}': {output}")
            except Exception as e:
                results.append(f"Command '{cmd}' error: {e}")
        return results

    async def _update_repo(self, repo: GitRepo) -> GitUpdateResult:
        """Update a single git repository."""
        logger.info(f"Git update: checking {repo.path} (branch: {repo.branch})")

        path = Path(repo.path).expanduser()
        result = GitUpdateResult(repo_id=repo.id, status="error")

        # Check if repo exists
        if not path.exists():
            result.error = f"Repository path does not exist: {path}"
            return result

        # Get current commit
        code, stdout, stderr = self._run_git(repo, "rev-parse", "HEAD")
        if code != 0:
            result.error = f"Failed to get current commit: {stderr}"
            return result
        result.old_commit = stdout.strip()

        # Fetch from remote
        code, stdout, stderr = self._run_git(repo, "fetch", "origin", repo.branch)
        if code != 0:
            result.error = f"Failed to fetch: {stderr}"
            return result

        # Get remote commit
        code, stdout, stderr = self._run_git(repo, "rev-parse", f"origin/{repo.branch}")
        if code != 0:
            result.error = f"Failed to get remote commit: {stderr}"
            return result
        remote_commit = stdout.strip()

        # Check if update needed
        if result.old_commit == remote_commit:
            repo.state.last_status = "no_change"
            result.status = "no_change"
            return result

        # Get list of new commits
        code, stdout, stderr = self._run_git(
            repo, "log", "--oneline", f"{result.old_commit}..{remote_commit}"
        )
        if code == 0:
            result.changes = stdout.strip().split("\n") if stdout.strip() else []

        # Check for local changes
        code, stdout, stderr = self._run_git(repo, "status", "--porcelain")
        has_local_changes = code == 0 and stdout.strip()

        try:
            if has_local_changes:
                # Stash local changes, then rebase
                logger.info(f"Git update: stashing local changes in {repo.path}")
                self._run_git(repo, "stash", "push", "-m", "nanobot-auto-update-stash")
                self._run_git(repo, "rebase", f"origin/{repo.branch}")

                # Check if rebase had conflicts
                code, stdout, stderr = self._run_git(repo, "status", "--porcelain")
                if "UU" in stdout or code != 0:
                    # Abort rebase, pop stash
                    logger.warning(f"Git update: conflict in {repo.path}, aborting rebase")
                    self._run_git(repo, "rebase", "--abort")
                    self._run_git(repo, "stash", "pop")
                    repo.state.last_status = "conflict"
                    result.status = "conflict"
                    result.error = "Rebase conflict - local changes preserved"

                    # Run on_conflict commands
                    if repo.on_conflict:
                        await self._execute_commands(repo.on_conflict, path)

                    return result

                # Rebase successful, try to pop stash
                self._run_git(repo, "stash", "pop")
                result.status = "updated"
                result.new_commit = remote_commit
                repo.state.updates_applied += 1
                repo.state.last_status = "ok"

            else:
                # No local changes, simple pull --rebase
                self._run_git(repo, "pull", "--rebase", "origin", repo.branch)
                result.status = "updated"
                result.new_commit = remote_commit
                repo.state.updates_applied += 1
                repo.state.last_status = "ok"

            # Get new commit
            code, stdout, stderr = self._run_git(repo, "rev-parse", "HEAD")
            if code == 0:
                result.new_commit = stdout.strip()
                repo.state.last_commit = result.new_commit

            # Run on_update commands
            if repo.on_update:
                cmd_results = await self._execute_commands(repo.on_update, path)
                if cmd_results:
                    logger.info(f"Git update: post-update commands for {repo.path}: {cmd_results}")

        except Exception as e:
            repo.state.last_status = "error"
            repo.state.last_error = str(e)
            result.status = "error"
            result.error = str(e)

        return result

    async def _on_timer(self) -> None:
        """Handle timer tick - run due updates."""
        now = _now_ms()
        due_repos = [
            r for r in self._repos
            if r.enabled and r.state.next_run_at_ms and now >= r.state.next_run_at_ms
        ]

        for repo in due_repos:
            start_ms = _now_ms()
            repo.state.last_run_at_ms = start_ms

            result = await self._update_repo(repo)

            if result.status == "error":
                repo.state.last_error = result.error
            else:
                repo.state.last_error = None

            # Compute next run
            repo.state.next_run_at_ms = _compute_next_run(repo.schedule, _now_ms())

            # Notify callback
            if repo.notify_on_change and self.on_update:
                try:
                    self.on_update(result)
                except Exception as e:
                    logger.error(f"Git update callback error: {e}")

        self._save_store()
        self._arm_timer()

    def _get_next_wake_ms(self) -> int | None:
        """Get the earliest next run time across all repos."""
        times = [
            r.state.next_run_at_ms
            for r in self._repos
            if r.enabled and r.state.next_run_at_ms
        ]
        return min(times) if times else None

    def _arm_timer(self) -> None:
        """Schedule the next timer tick."""
        if self._timer_task:
            self._timer_task.cancel()

        next_wake = self._get_next_wake_ms()
        if not next_wake or not self._running:
            return

        delay_ms = max(0, next_wake - _now_ms())
        delay_s = delay_ms / 1000

        async def tick():
            await asyncio.sleep(delay_s)
            if self._running:
                await self._on_timer()

        self._timer_task = asyncio.create_task(tick())

    async def start(self) -> None:
        """Start the git update service."""
        if not self.config.git_update.enabled:
            logger.info("Git update service disabled in config")
            return

        self._running = True
        self._load_store()
        self._save_store()
        self._arm_timer()

        enabled_count = len([r for r in self._repos if r.enabled])
        logger.info(f"Git update service started with {enabled_count} repos")

    def stop(self) -> None:
        """Stop the git update service."""
        self._running = False
        if self._timer_task:
            self._timer_task.cancel()
            self._timer_task = None

    # ========== Public API ==========

    def list_repos(self) -> list[GitRepo]:
        """List all configured repos."""
        self._load_store()
        return self._repos.copy()

    async def run_update(self, repo_id: str) -> GitUpdateResult | None:
        """Manually trigger an update for a specific repo."""
        self._load_store()
        for repo in self._repos:
            if repo.id == repo_id:
                result = await self._update_repo(repo)
                repo.state.next_run_at_ms = _compute_next_run(repo.schedule, _now_ms())
                self._save_store()
                self._arm_timer()
                return result
        return None

    def status(self) -> dict:
        """Get service status."""
        self._load_store()
        return {
            "enabled": self._running,
            "repos": len(self._repos),
            "next_wake_at_ms": self._get_next_wake_ms(),
        }
