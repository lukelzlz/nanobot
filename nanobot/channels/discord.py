"""Discord channel implementation using discord.py."""

import asyncio
from pathlib import Path

import discord
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

    async def start(self) -> None:
        """Start the Discord bot."""
        if not self.config.token:
            logger.error("Discord bot token not configured")
            return

        self._running = True

        # Configure intents - required for Discord to receive events
        intents = discord.Intents.default()
        intents.message_content = True  # Required to read message content
        intents.messages = True
        intents.guilds = True
        intents.voice_states = False  # Not needed for voice messages (attachments)

        # Create bot with command prefix (though we use slash commands mainly)
        self._bot = commands.Bot(
            command_prefix="!",
            intents=intents,
            help_command=None,  # We'll provide custom help
        )

        # Register event handlers using listen() for instance methods
        self._bot.listen("on_ready")(self._on_ready)
        self._bot.listen("on_message")(self._on_message)
        self._bot.listen("on_command_error")(self._on_command_error)

        # Register slash commands
        self._bot.tree.command(name="start", description="Start the bot and get a welcome message")(self._slash_start)
        self._bot.tree.command(name="help", description="Get help information")(self._slash_help)

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

        # Sync slash commands with Discord
        try:
            synced = await self._bot.tree.sync()
            logger.info(f"Synced {len(synced)} slash command(s)")
        except Exception as e:
            logger.warning(f"Failed to sync slash commands: {e}")

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
                content_parts.append(f"[attachment: download failed]")

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
            "`/help` - Show this help message\n\n"
            "Just send me a message to chat!"
        )
        await interaction.response.send_message(help_text)

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
