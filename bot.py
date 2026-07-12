# bot.py
import os
import yaml
import logging
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
import aiohttp
import asyncio
from datetime import datetime, timezone
import traceback
import socket
import time
from typing import Dict, Optional

import discord
from discord.ext import commands
from core.config import config
from core.cache_manager import cache_manager
from core.http_client import http_client
from core.validation import run_full_validation, log_validation_results
from core.status_reporter import status_reporter
from db import get_db, DatabaseManager

from dotenv import load_dotenv
load_dotenv()


# ─── Error Tracker Handler ──────────────────────────────────────────────────
class ErrorTrackerHandler(logging.Handler):
    """Feeds log records into the dashboard status instead of posting them to
    a Discord webhook. Every INFO+ record bumps bot.counters.log_messages (the
    "activity" line so the dashboard log graph is never empty), ERROR+
    records additionally bump bot.counters.log_errors, and WARNING+ records
    are appended to the rolling bot.error_log so the click-to-inspect popup
    only shows things worth looking at. Mirrors RoaringBot's bot.py."""

    def emit(self, record):
        try:
            status_reporter.bump_counter("bot", "log_messages")
            if record.levelno >= logging.ERROR:
                status_reporter.bump_counter("bot", "log_errors")
            if record.levelno >= logging.WARNING:
                status_reporter.record_event(
                    "bot", "error_log",
                    {
                        "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "level": record.levelname,
                        "logger": record.name,
                        "message": record.getMessage(),
                    },
                    max_len=200,
                )
        except Exception:
            pass  # logging must never itself raise

# ─── Logging ────────────────────────────────────────────────────────────────
LOG_FORMAT  = "%(asctime)s %(levelname)s %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

error_tracker_handler = ErrorTrackerHandler()
error_tracker_handler.setLevel(logging.INFO)

# Base logging setup
logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    datefmt=DATE_FORMAT,
    handlers=[
        logging.StreamHandler(),
        TimedRotatingFileHandler("logs/tausendsassa.log", when="midnight", interval=1, backupCount=30, encoding="utf-8"),
        error_tracker_handler,
    ]
)

# Main bot logger
log = logging.getLogger("tausendsassa")

# ─── Intents & COG-Liste ────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

COGS = ["cogs.feeds", "cogs.map", "cogs.moderation", "cogs.help", "cogs.calendar", "cogs.feedback"]

# ─── Enhanced Bot-Klasse ────────────────────────────────────────────────────
class Tausendsassa(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

        self.cog_loggers: Dict[str, logging.Logger] = {}

        self.owner_id = config.owner_id

        # Database connection (initialized in setup_hook)
        self.db: Optional[DatabaseManager] = None

    def get_cog_logger(self, cog_name: str) -> logging.Logger:
        """Get or create a logger for a specific cog"""
        logger_name = f"tausendsassa.{cog_name}"
        
        if logger_name not in self.cog_loggers:
            logger = logging.getLogger(logger_name)
            logger.setLevel(logging.INFO)
            
            # Don't add handlers if they're already inherited from parent logger
            if not logger.handlers:
                # Console handler
                console_handler = logging.StreamHandler()
                console_handler.setLevel(logging.INFO)
                formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
                console_handler.setFormatter(formatter)
                logger.addHandler(console_handler)
                
                # File handler with daily rotation (30 days retention)
                file_handler = TimedRotatingFileHandler(
                    f"logs/{cog_name}.log",
                    when="midnight",
                    interval=1,
                    backupCount=30,
                    encoding="utf-8"
                )
                file_handler.setLevel(logging.INFO)
                file_handler.setFormatter(formatter)
                logger.addHandler(file_handler)

                logger.addHandler(error_tracker_handler)
                logger.propagate = False
            
            self.cog_loggers[logger_name] = logger
        
        return self.cog_loggers[logger_name]

    async def setup_hook(self):
        # Initialize database connection
        try:
            self.db = await get_db()
            log.info("✅ Database connection established")
        except Exception as e:
            log.error(f"❌ Failed to connect to database: {e}")
            log.warning("⚠️ Bot will continue without database - some features may not work")
            self.db = None

        # Start cache management
        await cache_manager.start_cleanup_task()
        log.info("✅ Cache manager started")

        # Create logs directory for cog-specific logs
        os.makedirs("logs", exist_ok=True)

        status_reporter.load()

        # Load extensions
        for ext in COGS:
            try:
                await self.load_extension(ext)
                log.info(f"✅ Loaded extension {ext}")
            except Exception as e:
                log.exception(f"❌ Failed to load extension {ext}: {e}")

        status_reporter.record("bot", loaded_cogs=[e.split(".")[-1] for e in self.extensions.keys()])
        await status_reporter.start(asyncio)
        log.info("✅ Status reporter started")

        # Start internal API server for dashboard (discord-dependent lookups)
        from core.api_server import start_api_server
        await start_api_server(self)
        log.info("✅ API server started")

        @self.tree.error
        async def on_app_command_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
            if isinstance(error, discord.app_commands.errors.TransformerError):
                msg = "Couldn't find that channel. Please select it from the dropdown menu."
                try:
                    if interaction.response.is_done():
                        await interaction.followup.send(msg, ephemeral=True)
                    else:
                        await interaction.response.send_message(msg, ephemeral=True)
                except discord.NotFound:
                    pass
            else:
                log.error(f"App command error in '{interaction.command and interaction.command.name}'", exc_info=error)

        try:
            await self.tree.sync()
            log.info("✅ All slash commands synced globally")
        except discord.HTTPException as e:
            if e.code != 50240:
                raise
            # Discord Activity Entry Point command exists and cannot be removed via bulk sync.
            # Fall back to guild-specific sync so commands are current in the test guild.
            log.warning(
                "⚠️ Global sync blocked by Activity Entry Point command (code 50240). "
                "Global commands remain as-is; syncing to test guild as fallback."
            )
            test_guild_id = config.test_guild_id
            if test_guild_id:
                test_guild = discord.Object(id=test_guild_id)
                self.tree.copy_global_to(guild=test_guild)
                await self.tree.sync(guild=test_guild)
                log.info(f"✅ Slash commands synced to test guild {test_guild_id}")

    async def on_ready(self):
        status = discord.Status.online
        activity = discord.Activity(
            type=discord.ActivityType.listening,
            name="/help"
        )
        await self.change_presence(status=status, activity=activity)
        log.info(f"🤖 Logged in as {self.user} (ID: {self.user.id})")
        log.info(f"📊 Connected to {len(self.guilds)} guild(s)")

        status_reporter.record(
            "bot",
            user=str(self.user),
            user_id=self.user.id,
            guild_count=len(self.guilds),
            latency_ms=round(self.latency * 1000) if self.latency else None,
            gateway_status="connected",
        )

        # Update guild info in database
        if self.db and self.db.is_connected:
            for guild in self.guilds:
                try:
                    # guild.icon is an Asset with a .key attribute containing the hash
                    icon_hash = guild.icon.key if guild.icon else None
                    await self.db.guilds.ensure_exists(guild.id, guild.name, icon_hash, guild.member_count)
                except Exception as e:
                    log.warning(f"Failed to update guild {guild.id}: {e}")
            log.info("✅ Guild info synced to database")

        print("------")

    async def on_guild_join(self, guild: discord.Guild):
        """Called when the bot joins a new guild."""
        log.info(f"📥 Joined guild: {guild.name} (ID: {guild.id})")
        if self.db and self.db.is_connected:
            try:
                icon_hash = guild.icon.key if guild.icon else None
                await self.db.guilds.ensure_exists(guild.id, guild.name, icon_hash, guild.member_count)
            except Exception as e:
                log.warning(f"Failed to save guild {guild.id}: {e}")

    async def on_guild_update(self, before: discord.Guild, after: discord.Guild):
        """Called when a guild is updated (e.g., name change)."""
        if before.name != after.name:
            log.info(f"📝 Guild renamed: {before.name} -> {after.name}")
            if self.db and self.db.is_connected:
                try:
                    await self.db.guilds.update_name(after.id, after.name)
                except Exception as e:
                    log.warning(f"Failed to update guild name {after.id}: {e}")
    
    async def on_command_error(self, ctx, error):
        """Handle command errors and log them"""
        if isinstance(error, commands.CommandNotFound):
            return  # Ignore unknown commands

        log.error(
            f"Command error in '{ctx.command}' used by {ctx.author} (ID: {ctx.author.id}) "
            f"in guild {ctx.guild.id if ctx.guild else 'DM'}: {error}",
            exc_info=True
        )

    async def on_error(self, event, *args, **kwargs):
        """Handle general bot errors"""
        log.error(f"Bot error in event '{event}'", exc_info=True)

    async def on_disconnect(self):
        status_reporter.record("bot", gateway_status="disconnected")

    async def on_resumed(self):
        status_reporter.record(
            "bot",
            gateway_status="connected",
            latency_ms=round(self.latency * 1000) if self.latency else None,
        )
    

    async def on_interaction(self, interaction: discord.Interaction):
        """Track all component interactions for dashboard analytics."""
        try:
            status_reporter.bump_counter("bot", "interactions")
            if interaction.type == discord.InteractionType.component:
                status_reporter.bump_counter("bot", "component_interactions")
                # Persist to analytics table for all-time cumulative data
                if self.db and self.db.pool:
                    from core.analytics import track_event
                    await track_event(
                        self.db.pool, "component_interaction",
                        guild_id=interaction.guild_id if interaction.guild else None)
        except Exception:
            pass

    async def on_app_command_completion(self, interaction: discord.Interaction, command: discord.app_commands.Command | discord.app_commands.ContextMenu):
        """Track slash command usage for dashboard analytics."""
        try:
            status_reporter.bump_counter("bot", "slash_commands")
            status_reporter.bump_counter("bot", f"slash_{command.qualified_name.replace(' ', '_')}")
            # Persist to analytics table for all-time cumulative data
            if self.db and self.db.pool:
                from core.analytics import track_event
                await track_event(
                    self.db.pool, "slash_command",
                    guild_id=interaction.guild_id if interaction.guild else None)
        except Exception:
            pass

    async def close(self):
        """Cleanup when bot is shutting down"""
        log.info("🔄 Bot is shutting down...")

        await status_reporter.stop()

        # IMPORTANT: First unload all cogs to cancel their background tasks
        # This must happen BEFORE closing the database, otherwise tasks
        # will try to use a closed database connection
        for ext in list(self.extensions.keys()):
            try:
                await self.unload_extension(ext)
                log.info(f"✅ Unloaded extension {ext}")
            except Exception as e:
                log.warning(f"⚠️ Error unloading {ext}: {e}")

        # Now close database connection (after all tasks are cancelled)
        if self.db:
            await self.db.close()
            log.info("✅ Database connection closed")

        # Stop cache manager
        await cache_manager.stop_cleanup_task()
        log.info("✅ Cache manager stopped")

        # Stop HTTP client
        await http_client.close()
        log.info("✅ HTTP client closed")

        await super().close()


# ─── DNS Wait Function ──────────────────────────────────────────────────────
def wait_for_dns(host: str = "discord.com", max_wait: int = 120, interval: int = 5) -> bool:
    """Wait for DNS to be available by trying to resolve a host.
    
    This is useful when running as a systemd service at boot time,
    as DNS may not be immediately available (especially with local DNS like PiHole).
    """
    start_time = time.time()
    attempt = 0
    
    while time.time() - start_time < max_wait:
        attempt += 1
        try:
            socket.gethostbyname(host)
            if attempt > 1:
                log.info(f"✅ DNS ready after {attempt} attempts ({int(time.time() - start_time)}s)")
            return True
        except socket.gaierror:
            log.warning(f"⏳ Waiting for DNS... (attempt {attempt}, {host} not resolvable)")
            time.sleep(interval)
    
    log.error(f"❌ DNS not available after {max_wait}s")
    return False

# ─── Main ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        # Wait for DNS to be ready (important for boot-time startup)
        if not wait_for_dns():
            log.error("❌ Cannot start bot without DNS. Exiting.")
            exit(1)
        
        # Run comprehensive validation before starting
        log.info("🔍 Running configuration validation...")
        validation_results = run_full_validation()
        log_validation_results(validation_results)
        
        if not validation_results["valid"]:
            log.error("❌ Validation failed. Please fix the issues above and restart.")
            exit(1)
        
        # Log configuration for debugging
        config.log_configuration()

        log.info("🚀 Starting Tausendsassa Bot...")
        bot = Tausendsassa()
        
        bot.run(config.discord_token)
    except ValueError as e:
        log.error(f"Configuration error: {e}")
        exit(1)
    except KeyboardInterrupt:
        log.info("Bot stopped by user")
    except Exception as e:
        log.error(f"Bot crashed: {e}", exc_info=True)
