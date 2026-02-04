"""CLI commands for nanobot."""

import asyncio
import os
import signal
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from nanobot import __version__, __logo__

app = typer.Typer(
    name="nanobot",
    help=f"{__logo__} nanobot - Personal AI Assistant",
    no_args_is_help=True,
)

console = Console()


def version_callback(value: bool):
    if value:
        console.print(f"{__logo__} nanobot v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        None, "--version", "-v", callback=version_callback, is_eager=True
    ),
):
    """nanobot - Personal AI Assistant."""
    pass


# ============================================================================
# Onboard / Setup
# ============================================================================


@app.command()
def onboard():
    """Initialize nanobot configuration and workspace."""
    from nanobot.config.loader import get_config_path, save_config
    from nanobot.config.schema import Config
    from nanobot.utils.helpers import get_workspace_path
    
    config_path = get_config_path()
    
    if config_path.exists():
        console.print(f"[yellow]Config already exists at {config_path}[/yellow]")
        if not typer.confirm("Overwrite?"):
            raise typer.Exit()
    
    # Create default config
    config = Config()
    save_config(config)
    console.print(f"[green]✓[/green] Created config at {config_path}")
    
    # Create workspace
    workspace = get_workspace_path()
    console.print(f"[green]✓[/green] Created workspace at {workspace}")
    
    # Create default bootstrap files
    _create_workspace_templates(workspace)
    
    console.print(f"\n{__logo__} nanobot is ready!")
    console.print("\nNext steps:")
    console.print("  1. Add your API key to [cyan]~/.nanobot/config.json[/cyan]")
    console.print("     Get one at: https://openrouter.ai/keys")
    console.print("  2. Chat: [cyan]nanobot agent -m \"Hello!\"[/cyan]")
    console.print("\n[dim]Want Telegram/WhatsApp? See: https://github.com/HKUDS/nanobot#-chat-apps[/dim]")




def _create_workspace_templates(workspace: Path):
    """Create default workspace template files."""
    templates = {
        "AGENTS.md": """# Agent Instructions

You are a helpful AI assistant. Be concise, accurate, and friendly.

## Guidelines

- Always explain what you're doing before taking actions
- Ask for clarification when the request is ambiguous
- Use tools to help accomplish tasks
- Remember important information in your memory files
""",
        "SOUL.md": """# Soul

I am nanobot, a lightweight AI assistant.

## Personality

- Helpful and friendly
- Concise and to the point
- Curious and eager to learn

## Values

- Accuracy over speed
- User privacy and safety
- Transparency in actions
""",
        "USER.md": """# User

Information about the user goes here.

## Preferences

- Communication style: (casual/formal)
- Timezone: (your timezone)
- Language: (your preferred language)
""",
    }
    
    for filename, content in templates.items():
        file_path = workspace / filename
        if not file_path.exists():
            file_path.write_text(content)
            console.print(f"  [dim]Created {filename}[/dim]")
    
    # Create memory directory and MEMORY.md
    memory_dir = workspace / "memory"
    memory_dir.mkdir(exist_ok=True)
    memory_file = memory_dir / "MEMORY.md"
    if not memory_file.exists():
        memory_file.write_text("""# Long-term Memory

This file stores important information that should persist across sessions.

## User Information

(Important facts about the user)

## Preferences

(User preferences learned over time)

## Important Notes

(Things to remember)
""")
        console.print("  [dim]Created memory/MEMORY.md[/dim]")


# ============================================================================
# Gateway / Server
# ============================================================================


@app.command()
def gateway(
    port: int = typer.Option(18790, "--port", "-p", help="Gateway port"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """Start the nanobot gateway."""
    from nanobot.config.loader import load_config, get_data_dir
    from nanobot.bus.queue import MessageBus
    from nanobot.providers.litellm_provider import LiteLLMProvider
    from nanobot.agent.loop import AgentLoop
    from nanobot.channels.manager import ChannelManager
    from nanobot.cron.service import CronService
    from nanobot.cron.types import CronJob
    from nanobot.heartbeat.service import HeartbeatService
    from nanobot.git_update.service import GitUpdater
    from nanobot.git_update.types import GitUpdateResult
    
    if verbose:
        import logging
        logging.basicConfig(level=logging.DEBUG)
    
    console.print(f"{__logo__} Starting nanobot gateway on port {port}...")
    
    config = load_config()
    
    # Create components
    bus = MessageBus()
    
    # Create provider (supports OpenRouter, Anthropic, OpenAI, Bedrock)
    api_key = config.get_api_key()
    api_base = config.get_api_base()
    model = config.agents.defaults.model
    is_bedrock = model.startswith("bedrock/")

    if not api_key and not is_bedrock:
        console.print("[red]Error: No API key configured.[/red]")
        console.print("Set one in ~/.nanobot/config.json under providers.openrouter.apiKey")
        raise typer.Exit(1)
    
    provider = LiteLLMProvider(
        api_key=api_key,
        api_base=api_base,
        default_model=config.agents.defaults.model
    )
    
    # Create agent
    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        model=config.agents.defaults.model,
        max_iterations=config.agents.defaults.max_tool_iterations,
        brave_api_key=config.tools.web.search.api_key or None,
        exec_config=config.tools.exec,
    )
    
    # Create cron service
    async def on_cron_job(job: CronJob) -> str | None:
        """Execute a cron job through the agent."""
        response = await agent.process_direct(
            job.payload.message,
            session_key=f"cron:{job.id}"
        )
        # Optionally deliver to channel
        if job.payload.deliver and job.payload.to:
            from nanobot.bus.events import OutboundMessage
            await bus.publish_outbound(OutboundMessage(
                channel=job.payload.channel or "whatsapp",
                chat_id=job.payload.to,
                content=response or ""
            ))
        return response
    
    cron_store_path = get_data_dir() / "cron" / "jobs.json"
    cron = CronService(cron_store_path, on_job=on_cron_job)

    # Create git update service
    async def on_git_update(result: GitUpdateResult) -> None:
        """Handle git update result - optionally notify."""
        if result.status == "updated":
            logger.info(f"Git updated: {result.repo_id}, {result.old_commit[:8]}... → {result.new_commit[:8]}...")
            # You could send notifications here via channels
        elif result.status == "conflict":
            logger.warning(f"Git conflict: {result.repo_id} - {result.error}")

    git_store_path = get_data_dir() / "git_update" / "state.json"
    git_updater = GitUpdater(config, git_store_path, on_update=on_git_update)
    
    # Create heartbeat service
    async def on_heartbeat(prompt: str) -> str:
        """Execute heartbeat through the agent."""
        return await agent.process_direct(prompt, session_key="heartbeat")
    
    heartbeat = HeartbeatService(
        workspace=config.workspace_path,
        on_heartbeat=on_heartbeat,
        interval_s=30 * 60,  # 30 minutes
        enabled=True
    )
    
    # Create channel manager
    channels = ChannelManager(config, bus)
    
    if channels.enabled_channels:
        console.print(f"[green]✓[/green] Channels enabled: {', '.join(channels.enabled_channels)}")
    else:
        console.print("[yellow]Warning: No channels enabled[/yellow]")
    
    cron_status = cron.status()
    if cron_status["jobs"] > 0:
        console.print(f"[green]✓[/green] Cron: {cron_status['jobs']} scheduled jobs")

    console.print(f"[green]✓[/green] Heartbeat: every 30m")

    git_status = git_updater.status()
    if git_status["enabled"] and git_status["repos"] > 0:
        console.print(f"[green]✓[/green] Git update: {git_status['repos']} repos")

    # Create shutdown event for graceful shutdown
    shutdown_event = asyncio.Event()

    def signal_handler():
        """Handle signals for graceful shutdown."""
        shutdown_event.set()

    # Register signal handlers
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)

    # Set up Discord callbacks if Discord is enabled
    discord_channel = channels.get_channel("discord")
    if discord_channel:
        # Set reload callback
        def reload_callback() -> dict[str, Any]:
            return agent.reload_context()

        # Set shutdown callback (triggers graceful shutdown)
        def shutdown_callback():
            shutdown_event.set()

        discord_channel.set_reload_callback(reload_callback)
        discord_channel.set_shutdown_callback(shutdown_callback)
        console.print("[green]✓[/green] Discord admin commands enabled")

    async def run():
        try:
            await cron.start()
            await heartbeat.start()
            await git_updater.start()
            # Run agent and channels concurrently with shutdown check
            agent_task = asyncio.create_task(agent.run())
            channels_task = asyncio.create_task(channels.start_all())

            # Wait for either shutdown signal or task completion
            done, pending = await asyncio.wait(
                [agent_task, channels_task, asyncio.create_task(shutdown_event.wait())],
                return_when=asyncio.FIRST_COMPLETED
            )

            # Cancel pending tasks
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        except KeyboardInterrupt:
            console.print("\nShutting down...")
        finally:
            console.print("Shutting down...")
            heartbeat.stop()
            cron.stop()
            git_updater.stop()
            agent.stop()
            await channels.stop_all()

    asyncio.run(run())




# ============================================================================
# Agent Commands
# ============================================================================


@app.command()
def agent(
    message: str = typer.Option(None, "--message", "-m", help="Message to send to the agent"),
    session_id: str = typer.Option("cli:default", "--session", "-s", help="Session ID"),
):
    """Interact with the agent directly."""
    from nanobot.config.loader import load_config
    from nanobot.bus.queue import MessageBus
    from nanobot.providers.litellm_provider import LiteLLMProvider
    from nanobot.agent.loop import AgentLoop
    
    config = load_config()
    
    api_key = config.get_api_key()
    api_base = config.get_api_base()
    model = config.agents.defaults.model
    is_bedrock = model.startswith("bedrock/")

    if not api_key and not is_bedrock:
        console.print("[red]Error: No API key configured.[/red]")
        raise typer.Exit(1)

    bus = MessageBus()
    provider = LiteLLMProvider(
        api_key=api_key,
        api_base=api_base,
        default_model=config.agents.defaults.model
    )
    
    agent_loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        brave_api_key=config.tools.web.search.api_key or None,
        exec_config=config.tools.exec,
    )
    
    if message:
        # Single message mode
        async def run_once():
            response = await agent_loop.process_direct(message, session_id)
            console.print(f"\n{__logo__} {response}")
        
        asyncio.run(run_once())
    else:
        # Interactive mode
        console.print(f"{__logo__} Interactive mode (Ctrl+C to exit)\n")
        
        async def run_interactive():
            while True:
                try:
                    user_input = console.input("[bold blue]You:[/bold blue] ")
                    if not user_input.strip():
                        continue
                    
                    response = await agent_loop.process_direct(user_input, session_id)
                    console.print(f"\n{__logo__} {response}\n")
                except KeyboardInterrupt:
                    console.print("\nGoodbye!")
                    break
        
        asyncio.run(run_interactive())


# ============================================================================
# Channel Commands
# ============================================================================


channels_app = typer.Typer(help="Manage channels")
app.add_typer(channels_app, name="channels")


@channels_app.command("status")
def channels_status():
    """Show channel status."""
    from nanobot.config.loader import load_config

    config = load_config()

    table = Table(title="Channel Status")
    table.add_column("Channel", style="cyan")
    table.add_column("Enabled", style="green")
    table.add_column("Configuration", style="yellow")

    # WhatsApp
    wa = config.channels.whatsapp
    table.add_row(
        "WhatsApp",
        "✓" if wa.enabled else "✗",
        wa.bridge_url
    )

    # Telegram
    tg = config.channels.telegram
    tg_config = f"token: {tg.token[:10]}..." if tg.token else "[dim]not configured[/dim]"
    table.add_row(
        "Telegram",
        "✓" if tg.enabled else "✗",
        tg_config
    )

    console.print(table)


def _get_bridge_dir() -> Path:
    """Get the bridge directory, setting it up if needed."""
    import shutil
    import subprocess
    
    # User's bridge location
    user_bridge = Path.home() / ".nanobot" / "bridge"
    
    # Check if already built
    if (user_bridge / "dist" / "index.js").exists():
        return user_bridge
    
    # Check for npm
    if not shutil.which("npm"):
        console.print("[red]npm not found. Please install Node.js >= 18.[/red]")
        raise typer.Exit(1)
    
    # Find source bridge: first check package data, then source dir
    pkg_bridge = Path(__file__).parent.parent / "bridge"  # nanobot/bridge (installed)
    src_bridge = Path(__file__).parent.parent.parent / "bridge"  # repo root/bridge (dev)
    
    source = None
    if (pkg_bridge / "package.json").exists():
        source = pkg_bridge
    elif (src_bridge / "package.json").exists():
        source = src_bridge
    
    if not source:
        console.print("[red]Bridge source not found.[/red]")
        console.print("Try reinstalling: pip install --force-reinstall nanobot")
        raise typer.Exit(1)
    
    console.print(f"{__logo__} Setting up bridge...")
    
    # Copy to user directory
    user_bridge.parent.mkdir(parents=True, exist_ok=True)
    if user_bridge.exists():
        shutil.rmtree(user_bridge)
    shutil.copytree(source, user_bridge, ignore=shutil.ignore_patterns("node_modules", "dist"))
    
    # Install and build
    try:
        console.print("  Installing dependencies...")
        subprocess.run(["npm", "install"], cwd=user_bridge, check=True, capture_output=True)
        
        console.print("  Building...")
        subprocess.run(["npm", "run", "build"], cwd=user_bridge, check=True, capture_output=True)
        
        console.print("[green]✓[/green] Bridge ready\n")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Build failed: {e}[/red]")
        if e.stderr:
            console.print(f"[dim]{e.stderr.decode()[:500]}[/dim]")
        raise typer.Exit(1)
    
    return user_bridge


@channels_app.command("login")
def channels_login():
    """Link device via QR code."""
    import subprocess
    
    bridge_dir = _get_bridge_dir()
    
    console.print(f"{__logo__} Starting bridge...")
    console.print("Scan the QR code to connect.\n")
    
    try:
        subprocess.run(["npm", "start"], cwd=bridge_dir, check=True)
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Bridge failed: {e}[/red]")
    except FileNotFoundError:
        console.print("[red]npm not found. Please install Node.js.[/red]")


# ============================================================================
# Cron Commands
# ============================================================================

cron_app = typer.Typer(help="Manage scheduled tasks")
app.add_typer(cron_app, name="cron")


@cron_app.command("list")
def cron_list(
    all: bool = typer.Option(False, "--all", "-a", help="Include disabled jobs"),
):
    """List scheduled jobs."""
    from nanobot.config.loader import get_data_dir
    from nanobot.cron.service import CronService
    
    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)
    
    jobs = service.list_jobs(include_disabled=all)
    
    if not jobs:
        console.print("No scheduled jobs.")
        return
    
    table = Table(title="Scheduled Jobs")
    table.add_column("ID", style="cyan")
    table.add_column("Name")
    table.add_column("Schedule")
    table.add_column("Status")
    table.add_column("Next Run")
    
    import time
    for job in jobs:
        # Format schedule
        if job.schedule.kind == "every":
            sched = f"every {(job.schedule.every_ms or 0) // 1000}s"
        elif job.schedule.kind == "cron":
            sched = job.schedule.expr or ""
        else:
            sched = "one-time"
        
        # Format next run
        next_run = ""
        if job.state.next_run_at_ms:
            next_time = time.strftime("%Y-%m-%d %H:%M", time.localtime(job.state.next_run_at_ms / 1000))
            next_run = next_time
        
        status = "[green]enabled[/green]" if job.enabled else "[dim]disabled[/dim]"
        
        table.add_row(job.id, job.name, sched, status, next_run)
    
    console.print(table)


@cron_app.command("add")
def cron_add(
    name: str = typer.Option(..., "--name", "-n", help="Job name"),
    message: str = typer.Option(..., "--message", "-m", help="Message for agent"),
    every: int = typer.Option(None, "--every", "-e", help="Run every N seconds"),
    cron_expr: str = typer.Option(None, "--cron", "-c", help="Cron expression (e.g. '0 9 * * *')"),
    at: str = typer.Option(None, "--at", help="Run once at time (ISO format)"),
    deliver: bool = typer.Option(False, "--deliver", "-d", help="Deliver response to channel"),
    to: str = typer.Option(None, "--to", help="Recipient for delivery"),
    channel: str = typer.Option(None, "--channel", help="Channel for delivery (e.g. 'telegram', 'whatsapp')"),
):
    """Add a scheduled job."""
    from nanobot.config.loader import get_data_dir
    from nanobot.cron.service import CronService
    from nanobot.cron.types import CronSchedule
    
    # Determine schedule type
    if every:
        schedule = CronSchedule(kind="every", every_ms=every * 1000)
    elif cron_expr:
        schedule = CronSchedule(kind="cron", expr=cron_expr)
    elif at:
        import datetime
        dt = datetime.datetime.fromisoformat(at)
        schedule = CronSchedule(kind="at", at_ms=int(dt.timestamp() * 1000))
    else:
        console.print("[red]Error: Must specify --every, --cron, or --at[/red]")
        raise typer.Exit(1)
    
    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)
    
    job = service.add_job(
        name=name,
        schedule=schedule,
        message=message,
        deliver=deliver,
        to=to,
        channel=channel,
    )
    
    console.print(f"[green]✓[/green] Added job '{job.name}' ({job.id})")


@cron_app.command("remove")
def cron_remove(
    job_id: str = typer.Argument(..., help="Job ID to remove"),
):
    """Remove a scheduled job."""
    from nanobot.config.loader import get_data_dir
    from nanobot.cron.service import CronService
    
    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)
    
    if service.remove_job(job_id):
        console.print(f"[green]✓[/green] Removed job {job_id}")
    else:
        console.print(f"[red]Job {job_id} not found[/red]")


@cron_app.command("enable")
def cron_enable(
    job_id: str = typer.Argument(..., help="Job ID"),
    disable: bool = typer.Option(False, "--disable", help="Disable instead of enable"),
):
    """Enable or disable a job."""
    from nanobot.config.loader import get_data_dir
    from nanobot.cron.service import CronService
    
    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)
    
    job = service.enable_job(job_id, enabled=not disable)
    if job:
        status = "disabled" if disable else "enabled"
        console.print(f"[green]✓[/green] Job '{job.name}' {status}")
    else:
        console.print(f"[red]Job {job_id} not found[/red]")


@cron_app.command("run")
def cron_run(
    job_id: str = typer.Argument(..., help="Job ID to run"),
    force: bool = typer.Option(False, "--force", "-f", help="Run even if disabled"),
):
    """Manually run a job."""
    from nanobot.config.loader import get_data_dir
    from nanobot.cron.service import CronService
    
    store_path = get_data_dir() / "cron" / "jobs.json"
    service = CronService(store_path)
    
    async def run():
        return await service.run_job(job_id, force=force)
    
    if asyncio.run(run()):
        console.print(f"[green]✓[/green] Job executed")
    else:
        console.print(f"[red]Failed to run job {job_id}[/red]")


# ============================================================================
# Git Update Commands
# ============================================================================


git_app = typer.Typer(help="Manage git auto-update")
app.add_typer(git_app, name="git")


@git_app.command("list")
def git_list():
    """List configured git repositories."""
    import time
    from nanobot.config.loader import load_config, get_data_dir
    from nanobot.git_update.service import GitUpdater

    config = load_config()

    if not config.git_update.enabled:
        console.print("[yellow]Git auto-update is disabled in config.[/yellow]")
        console.print("Set git_update.enabled = true in ~/.nanobot/config.json")
        return

    store_path = get_data_dir() / "git_update" / "state.json"
    updater = GitUpdater(config, store_path)

    repos = updater.list_repos()

    if not repos:
        console.print("No git repositories configured.")
        console.print("\n[dim]Add repos in config.json under git_update.repos:[/dim]")
        console.print('  {"path": "/path/to/repo", "branch": "main", "schedule": "0 2 * * *"}')
        return

    table = Table(title="Git Auto-Update Repositories")
    table.add_column("ID", style="cyan")
    table.add_column("Path")
    table.add_column("Branch")
    table.add_column("Schedule")
    table.add_column("Status")
    table.add_column("Last Status")
    table.add_column("Next Run")

    for repo in repos:
        # Format last status
        last_status = ""
        if repo.state.last_status:
            status_colors = {
                "ok": "[green]ok[/green]",
                "error": "[red]error[/red]",
                "conflict": "[yellow]conflict[/yellow]",
                "no_change": "[dim]no_change[/dim]",
            }
            last_status = status_colors.get(repo.state.last_status, repo.state.last_status)

        # Format next run
        next_run = ""
        if repo.state.next_run_at_ms:
            next_time = time.strftime("%Y-%m-%d %H:%M", time.localtime(repo.state.next_run_at_ms / 1000))
            next_run = next_time
        else:
            next_run = "[dim]--[/dim]"

        enabled = "[green]enabled[/green]" if repo.enabled else "[dim]disabled[/dim]"

        table.add_row(
            repo.id,
            repo.path[:40] + "..." if len(repo.path) > 40 else repo.path,
            repo.branch,
            repo.schedule,
            enabled,
            last_status or "--",
            next_run,
        )

    console.print(table)


@git_app.command("run")
def git_run(
    repo_id: str = typer.Argument(..., help="Repository ID or path to update"),
):
    """Manually trigger an update for a repository."""
    from nanobot.config.loader import load_config, get_data_dir
    from nanobot.git_update.service import GitUpdater

    config = load_config()
    store_path = get_data_dir() / "git_update" / "state.json"
    updater = GitUpdater(config, store_path)

    # Load repos to find the matching one
    repos = updater.list_repos()
    target_repo = None

    for repo in repos:
        if repo.id == repo_id or repo.path == repo_id or repo.path.endswith(repo_id):
            target_repo = repo
            break

    if not target_repo:
        console.print(f"[red]Repository {repo_id} not found[/red]")
        console.print("[dim]Use 'nanobot git list' to see configured repos.[/dim]")
        return

    async def run():
        result = await updater.run_update(target_repo.id)
        if result is None:
            console.print(f"[red]Repository {repo_id} not found[/red]")
            return

        if result.status == "updated":
            console.print(f"[green]✓[/green] Repository updated")
            if result.old_commit and result.new_commit:
                console.print(f"  {result.old_commit[:8]} → {result.new_commit[:8]}")
            if result.changes:
                console.print(f"  [dim]{len(result.changes)} new commits[/dim]")
                for change in result.changes[:5]:
                    console.print(f"    {change}")
                if len(result.changes) > 5:
                    console.print(f"    ... and {len(result.changes) - 5} more")
        elif result.status == "no_change":
            console.print("[dim]No changes to pull[/dim]")
        elif result.status == "conflict":
            console.print(f"[yellow]Conflict detected[/yellow]")
            console.print(f"  {result.error}")
        else:
            console.print(f"[red]Error: {result.error}[/red]")

    asyncio.run(run())


@git_app.command("enable")
def git_enable(
    repo_id: str = typer.Argument(..., help="Repository ID or path"),
    disable: bool = typer.Option(False, "--disable", help="Disable instead of enable"),
):
    """Enable or disable auto-update for a repository."""
    import json
    from nanobot.config.loader import load_config, save_config, get_config_path

    config = load_config()

    # Find the repo by ID or path
    for repo_config in config.git_update.repos:
        if repo_config.path == repo_id or repo_config.path.endswith(repo_id):
            repo_config.enabled = not disable
            save_config(config)
            status = "disabled" if disable else "enabled"
            console.print(f"[green]✓[/green] Repository {repo_config.path} {status}")
            return

    console.print(f"[red]Repository {repo_id} not found[/red]")
    console.print("[dim]Use 'nanobot git list' to see configured repos.[/dim]")


# ============================================================================
# systemd Service Commands
# ============================================================================


@app.command("install-service")
def install_service(
    user: bool = typer.Option(True, "--user", help="Install user service (default)"),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing service file"),
):
    """Install nanobot as a systemd service."""
    import shutil
    import subprocess

    from nanobot.config.loader import get_config_path

    # Get service file location
    pkg_dir = Path(__file__).parent
    service_file_source = pkg_dir / "systemd" / "nanobot.service"

    if not service_file_source.exists():
        console.print(f"[red]Service file not found at {service_file_source}[/red]")
        console.print("This may indicate nanobot was not installed correctly.")
        raise typer.Exit(1)

    # Determine target directory
    if user:
        service_dir = Path.home() / ".config" / "systemd" / "user"
        service_name = "nanobot.service"
    else:
        service_dir = Path("/etc/systemd/system")
        service_name = "nanobot.service"
        if not (Path.cwd() == "/" or os.geteuid() == 0):
            console.print("[yellow]Note: Installing system service requires root privileges.[/yellow]")
            console.print("Use: sudo nanobot install-service --no-user")

    service_file_target = service_dir / service_name

    # Check if exists
    if service_file_target.exists() and not force:
        console.print(f"[yellow]Service file already exists at {service_file_target}[/yellow]")
        if not typer.confirm("Overwrite?"):
            console.print("Use --force to overwrite without prompting.")
            raise typer.Exit()

    # Create directory if needed
    service_dir.mkdir(parents=True, exist_ok=True)

    # Copy service file
    shutil.copy(service_file_source, service_file_target)
    console.print(f"[green]✓[/green] Installed service file to {service_file_target}")

    # Reload systemd
    try:
        if user:
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
            console.print("[green]✓[/green] Reloaded systemd user daemon")
        else:
            subprocess.run(["systemctl", "daemon-reload"], check=True)
            console.print("[green]✓[/green] Reloaded systemd daemon")

        # Enable service
        if user:
            subprocess.run(["systemctl", "--user", "enable", service_name], check=True)
            console.print(f"[green]✓[/green] Enabled {service_name}")
        else:
            subprocess.run(["systemctl", "enable", service_name], check=True)
            console.print(f"[green]✓[/green] Enabled {service_name}")

        console.print("\n[dim]To start the service:[/dim]")
        if user:
            console.print("  systemctl --user start nanobot")
            console.print("\n[dim]To view logs:[/dim]")
            console.print("  journalctl --user -u nanobot -f")
        else:
            console.print("  systemctl start nanobot")
            console.print("\n[dim]To view logs:[/dim]")
            console.print("  journalctl -u nanobot -f")

    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error with systemd: {e}[/red]")
        raise typer.Exit(1)
    except FileNotFoundError:
        console.print("[red]systemctl not found. Is systemd installed?[/red]")
        raise typer.Exit(1)


@app.command("uninstall-service")
def uninstall_service(
    user: bool = typer.Option(True, "--user", help="Uninstall user service (default)"),
):
    """Uninstall nanobot systemd service."""
    import subprocess

    if user:
        service_dir = Path.home() / ".config" / "systemd" / "user"
        service_name = "nanobot.service"
    else:
        service_dir = Path("/etc/systemd/system")
        service_name = "nanobot.service"

    service_file = service_dir / service_name

    if not service_file.exists():
        console.print(f"[yellow]Service file not found at {service_file}[/yellow]")
        raise typer.Exit()

    # Stop and disable
    try:
        if user:
            subprocess.run(["systemctl", "--user", "stop", service_name], check=False)
            subprocess.run(["systemctl", "--user", "disable", service_name], check=True)
        else:
            subprocess.run(["systemctl", "stop", service_name], check=False)
            subprocess.run(["systemctl", "disable", service_name], check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    # Remove file
    service_file.unlink()
    console.print(f"[green]✓[/green] Removed {service_file}")

    # Reload systemd
    try:
        if user:
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        else:
            subprocess.run(["systemctl", "daemon-reload"], check=True)
        console.print("[green]✓[/green] Reloaded systemd daemon")
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        console.print(f"[yellow]Warning: Could not reload systemd: {e}[/yellow]")


# ============================================================================
# Status Commands
# ============================================================================


@app.command()
def status():
    """Show nanobot status."""
    from nanobot.config.loader import load_config, get_config_path

    config_path = get_config_path()
    config = load_config()
    workspace = config.workspace_path

    console.print(f"{__logo__} nanobot Status\n")

    console.print(f"Config: {config_path} {'[green]✓[/green]' if config_path.exists() else '[red]✗[/red]'}")
    console.print(f"Workspace: {workspace} {'[green]✓[/green]' if workspace.exists() else '[red]✗[/red]'}")

    if config_path.exists():
        console.print(f"Model: {config.agents.defaults.model}")
        
        # Check API keys
        has_openrouter = bool(config.providers.openrouter.api_key)
        has_anthropic = bool(config.providers.anthropic.api_key)
        has_openai = bool(config.providers.openai.api_key)
        has_gemini = bool(config.providers.gemini.api_key)
        has_vllm = bool(config.providers.vllm.api_base)
        
        console.print(f"OpenRouter API: {'[green]✓[/green]' if has_openrouter else '[dim]not set[/dim]'}")
        console.print(f"Anthropic API: {'[green]✓[/green]' if has_anthropic else '[dim]not set[/dim]'}")
        console.print(f"OpenAI API: {'[green]✓[/green]' if has_openai else '[dim]not set[/dim]'}")
        console.print(f"Gemini API: {'[green]✓[/green]' if has_gemini else '[dim]not set[/dim]'}")
        vllm_status = f"[green]✓ {config.providers.vllm.api_base}[/green]" if has_vllm else "[dim]not set[/dim]"
        console.print(f"vLLM/Local: {vllm_status}")


if __name__ == "__main__":
    app()
