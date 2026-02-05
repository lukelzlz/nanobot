"""Discord channel implementation using discord.py."""

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands
from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import DiscordConfig


class DiscordChannel(BaseChannel):
    """
    Discord channel using discord.py.

    Features:
    - Slash commands (/start, /help)
    - Text and attachment support
    - Voice message transcription via Groq Whisper
    - DM and guild channel support
    """

    name = "discord"

    def __init__(self, config: DiscordConfig, bus: MessageBus, groq_api_key: str = ""):
        super().__init__(config, bus)
        self.config: DiscordConfig = config
        self.groq_api_key = groq_api_key
        self._bot: commands.Bot | None = None
        self._bot_task: asyncio.Task | None = None
        self._shutdown_callback: Callable[[], None] | None = None
        self._reload_callback: Callable[[], dict[str, Any]] | None = None
        self._commands_registered = False

        # Create the bot instance with setup_hook
        self._create_bot()

    def _create_bot(self) -> None:
        """Create the Discord bot instance and register commands."""
        # Configure intents
        intents = discord.Intents.default()
        intents.message_content = True
        intents.messages = True
        intents.guilds = True
        intents.voice_states = False

        # Create bot
        self._bot = commands.Bot(
            command_prefix="!",
            intents=intents,
            help_command=None,
        )

        # Register slash commands using app_commands
        self._bot.tree.add_command(app_commands.Command(
            name="start",
            description="Start the bot and get a welcome message",
            callback=self._slash_start
        ))

        self._bot.tree.add_command(app_commands.Command(
            name="help",
            description="Get help information",
            callback=self._slash_help
        ))

        self._bot.tree.add_command(app_commands.Command(
            name="reload",
            description="Reload skills and configuration",
            callback=self._slash_reload
        ))

        self._bot.tree.add_command(app_commands.Command(
            name="stop",
            description="Stop the bot (admin only)",
            callback=self._slash_stop
        ))

        self._commands_registered = True
        logger.debug("Registered 4 slash commands in _create_bot")

        # Register event handlers
        self._bot.listen("on_ready")(self._on_ready)
        self._bot.listen("on_message")(self._on_message)
        self._bot.listen("on_command_error")(self._on_command_error)

    async def start(self) -> None:
        """Start the Discord bot."""
        if not self.config.token:
            logger.error("Discord bot token not configured")
            return

        self._running = True
        logger.info("Starting Discord bot...")

        # Start the bot (this runs until stopped)
        try:
            await self._bot.start(self.config.token)
        except Exception as e:
            logger.error(f"Discord bot error: {e}")
            self._running = False

    async def stop(self) -> None:
        """Stop the Discord bot."""
        self._running = False

        if self._bot:
            logger.info("Stopping Discord bot...")
            await self._bot.close()
            self._bot = None

    def set_shutdown_callback(self, callback: Callable[[], None]) -> None:
        """Set callback for shutdown command."""
        self._shutdown_callback = callback

    def set_reload_callback(self, callback: Callable[[], dict[str, Any]]) -> None:
        """Set callback for reload command."""
        self._reload_callback = callback

    def _is_admin(self, user_id: str | int) -> bool:
        """Check if user is admin."""
        user_id_str = str(user_id)
        return user_id_str in self.config.admin_users

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through Discord."""
        if not self._bot or not self._bot.is_ready():
            logger.warning("Discord bot not running")
            return

        try:
            # chat_id can be a DM channel ID or guild channel ID
            # Convert to int for Discord API
            channel_id = int(msg.chat_id)

            # Try to get the channel
            channel = self._bot.get_channel(channel_id)
            if not channel:
                # Try to fetch it (might be a DM or not cached)
                try:
                    channel = await self._bot.fetch_channel(channel_id)
                except discord.NotFound:
                    logger.error(f"Discord channel not found: {channel_id}")
                    return
                except discord.Forbidden:
                    logger.error(f"No permission to access Discord channel: {channel_id}")
                    return

            # Discord supports Markdown natively, so we can send content directly
            # However, we should be careful with message length (Discord limit is 2000 chars)
            content = msg.content
            if len(content) > 2000:
                # Split long messages (simple split at newlines if possible)
                parts = self._split_long_message(content)
                for part in parts:
                    await channel.send(part)
            else:
                await channel.send(content)

        except ValueError:
            logger.error(f"Invalid chat_id for Discord: {msg.chat_id}")
        except discord.Forbidden:
            logger.error(f"No permission to send message to Discord channel: {msg.chat_id}")
        except Exception as e:
            logger.error(f"Error sending Discord message: {e}")

    def _split_long_message(self, text: str, max_length: int = 2000) -> list[str]:
        """Split a long message into chunks that fit Discord's limit."""
        if len(text) <= max_length:
            return [text]

        parts = []
        current = ""
        # Try to split at newlines first
        for line in text.split("\n"):
            if len(current) + len(line) + 1 > max_length:
                if current:
                    parts.append(current)
                # If a single line is too long, split it
                if len(line) > max_length:
                    for i in range(0, len(line), max_length):
                        parts.append(line[i:i + max_length])
                    current = ""
                else:
                    current = line
            else:
                if current:
                    current += "\n" + line
                else:
                    current = line

        if current:
            parts.append(current)

        return parts

    async def _on_ready(self) -> None:
        """Called when the bot is ready."""
        if not self._bot:
            return

        logger.info(f"Discord bot connected as {self._bot.user.name} (ID: {self._bot.user.id})")

        # Log command tree state before sync
        logger.debug(f"Commands registered: {self._commands_registered}")
        commands_before = list(self._bot.tree.get_commands(type=None, guild=None))
        logger.debug(f"Tree has {len(commands_before)} commands before sync")

        # Sync slash commands with Discord
        try:
            # If test_guild_id is configured, sync to that guild instantly (no caching)
            # Otherwise sync globally (may take up to 1 hour to propagate)
            if self.config.test_guild_id:
                guild_id = int(self.config.test_guild_id)
                logger.info(f"Syncing commands to guild {guild_id}...")

                # Check bot permissions in the guild
                try:
                    guild = self._bot.get_guild(guild_id)
                    if guild:
                        bot_member = guild.me
                        permissions = bot_member.guild_permissions
                        logger.info(f"Bot permissions in guild: administer={permissions.administrator}, manage_guild={permissions.manage_guild}")
                except Exception as perm_error:
                    logger.warning(f"Could not check permissions: {perm_error}")

                synced = await self._bot.tree.sync(guild=discord.Object(id=guild_id))
                logger.info(f"Synced {len(synced)} slash command(s) to guild {guild_id}")
                for cmd in synced:
                    logger.debug(f"  - /{cmd.name}")

                if len(synced) == 0:
                    logger.error("No commands were synced! Possible issues:")
                    logger.error("  1. Bot lacks 'applications.commands' scope in OAuth2 URL")
                    logger.error("  2. Bot lacks permission to manage commands in this guild")
                    logger.error("  3. Check Discord Developer Portal -> Bot -> OAuth2 -> Scopes")
            else:
                logger.info("Syncing commands globally...")
                synced = await self._bot.tree.sync()
                logger.info(f"Synced {len(synced)} slash command(s) globally (may take up to 1 hour to propagate)")
                logger.info("Tip: Set 'test_guild_id' in config to sync commands instantly for testing")
                for cmd in synced:
                    logger.debug(f"  - /{cmd.name}")
        except Exception as e:
            logger.error(f"Failed to sync slash commands: {e}")
            import traceback
            traceback.print_exc()

    async def _on_command_error(self, ctx: commands.Context, error: Exception) -> None:
        """Handle command errors."""
        logger.debug(f"Discord command error: {error}")

    async def _on_message(self, message: discord.Message) -> None:
        """Handle incoming messages."""
        # Ignore messages from bots (including ourselves)
        if message.author.bot:
            return

        # Ignore slash command invocations (they're handled separately)
        if message.interaction and message.interaction.type == discord.InteractionType.application_command:
            return

        # Get sender ID (Discord user ID)
        sender_id = str(message.author.id)

        # Store username for allowlist compatibility
        if message.author.global_name:
            sender_id = f"{sender_id}|{message.author.global_name}"
        elif message.author.name:
            sender_id = f"{sender_id}|{message.author.name}"

        # Get channel ID for replies
        channel_id = str(message.channel.id)

        # Build content from text and/or attachments
        content_parts = []
        media_paths = []

        # Text content
        if message.content:
            content_parts.append(message.content)

        # Handle attachments (images, files, voice messages)
        for attachment in message.attachments:
            try:
                # Download the attachment
                media_dir = Path.home() / ".nanobot" / "media"
                media_dir.mkdir(parents=True, exist_ok=True)

                # Determine file extension
                ext = Path(attachment.filename).suffix or ""
                if not ext:
                    ext = self._guess_extension(attachment.content_type)

                file_path = media_dir / f"{attachment.id[:16]}{ext}"

                # Download the file
                await attachment.save(str(file_path))
                media_paths.append(str(file_path))

                # Determine media type
                media_type = self._get_media_type(attachment.content_type)

                # Handle voice/audio transcription
                if media_type in ("voice", "audio"):
                    if self.groq_api_key:
                        from nanobot.providers.transcription import GroqTranscriptionProvider
                        transcriber = GroqTranscriptionProvider(api_key=self.groq_api_key)
                        transcription = await transcriber.transcribe(file_path)
                        if transcription:
                            logger.info(f"Transcribed {media_type}: {transcription[:50]}...")
                            content_parts.append(f"[transcription: {transcription}]")
                        else:
                            content_parts.append(f"[{media_type}: {file_path}]")
                    else:
                        content_parts.append(f"[{media_type}: {file_path}]")
                else:
                    content_parts.append(f"[{media_type}: {file_path}]")

                logger.debug(f"Downloaded attachment to {file_path}")

            except Exception as e:
                logger.error(f"Failed to download attachment {attachment.id}: {e}")
                content_parts.append("[attachment: download failed]")

        content = "\n".join(content_parts) if content_parts else "[empty message]"

        logger.debug(f"Discord message from {sender_id}: {content[:50]}...")

        # Determine if this is a DM or guild message
        is_dm = isinstance(message.channel, discord.DMChannel)

        # Forward to the message bus
        await self._handle_message(
            sender_id=sender_id,
            chat_id=channel_id,
            content=content,
            media=media_paths,
            metadata={
                "message_id": message.id,
                "user_id": message.author.id,
                "username": message.author.name,
                "global_name": message.author.global_name,
                "is_dm": is_dm,
                "guild_id": message.guild.id if not is_dm else None,
                "guild_name": message.guild.name if not is_dm else None,
            }
        )

    async def _slash_start(self, interaction: discord.Interaction) -> None:
        """Handle /start slash command."""
        await interaction.response.send_message(
            "👋 Hi there! I'm **nanobot**.\n\n"
            "Send me a message and I'll respond!\n\n"
            "Use `/help` to see available commands."
        )

    async def _slash_help(self, interaction: discord.Interaction) -> None:
        """Handle /help slash command."""
        help_text = (
            "**nanobot Commands**\n\n"
            "`/start` - Get a welcome message\n"
            "`/help` - Show this help message\n"
            "`/reload` - Reload skills and configuration\n"
            "`/stop` - Stop the bot (admin only)\n\n"
            "Just send me a message to chat!"
        )
        await interaction.response.send_message(help_text)

    async def _slash_reload(self, interaction: discord.Interaction) -> None:
        """Handle /reload slash command."""
        if not self._reload_callback:
            await interaction.response.send_message(
                "Reload callback not configured. This feature may not be available.",
                ephemeral=True
            )
            return

        try:
            # Defer response as reload might take a moment
            await interaction.response.defer()

            # Call reload callback
            result = self._reload_callback()

            # Build response message
            parts = ["**Reload Results**\n"]

            if result.get("added"):
                parts.append(f"✓ **Added:** {', '.join(result['added'])}")
            if result.get("removed"):
                parts.append(f"✗ **Removed:** {', '.join(result['removed'])}")
            if result.get("modified"):
                parts.append(f"~ **Modified:** {', '.join(result['modified'])}")
            if not any(result.get(k) for k in ("added", "removed", "modified")):
                parts.append("No changes detected.")

            await interaction.followup.send("\n".join(parts))
        except Exception as e:
            logger.error(f"Error during reload: {e}")
            await interaction.followup.send(f"Reload failed: {e}")

    async def _slash_stop(self, interaction: discord.Interaction) -> None:
        """Handle /stop slash command (admin only)."""
        user_id = interaction.user.id

        if not self._is_admin(user_id):
            await interaction.response.send_message(
                "You don't have permission to use this command.",
                ephemeral=True
            )
            return

        if not self._shutdown_callback:
            await interaction.response.send_message(
                "Shutdown callback not configured.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            "🛑 Shutting down nanobot... Goodbye!"
        )

        # Trigger shutdown
        if self._shutdown_callback:
            self._shutdown_callback()

    def _get_media_type(self, content_type: str | None) -> str:
        """Determine media type from content type."""
        if not content_type:
            return "file"

        content_type = content_type.lower()

        if content_type.startswith("image/"):
            return "image"
        elif content_type.startswith("audio/"):
            return "audio"
        elif content_type.startswith("video/"):
            return "video"
        else:
            return "file"

    def _guess_extension(self, content_type: str | None) -> str:
        """Guess file extension from content type."""
        if not content_type:
            return ""

        ext_map = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/gif": ".gif",
            "image/webp": ".webp",
            "audio/ogg": ".ogg",
            "audio/mpeg": ".mp3",
            "audio/mp4": ".m4a",
            "audio/wav": ".wav",
            "video/mp4": ".mp4",
            "video/webm": ".webm",
            "application/pdf": ".pdf",
            "text/plain": ".txt",
        }
        return ext_map.get(content_type, "")
