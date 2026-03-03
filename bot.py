# bot.py
import os
import yaml
import logging
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
import aiohttp
import asyncio
from datetime import datetime
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
from db import get_db, DatabaseManager

from dotenv import load_dotenv
load_dotenv()


# ─── Webhook Log Handler ────────────────────────────────────────────────────
class WebhookLogHandler(logging.Handler):
    """Custom logging handler that sends logs to Discord via webhook as embeds"""
    
    def __init__(self, webhook_url: str, bot_instance=None):
        super().__init__()
        self.webhook_url = webhook_url
        self.bot = bot_instance
        self.session = None
        self.queue = asyncio.Queue()
        self.task = None
        self.colors = {
            'DEBUG': 0x808080,     # Gray
            'INFO': 0x0099ff,      # Blue
            'WARNING': 0xff9900,   # Orange
            'ERROR': 0xff0000,     # Red
            'CRITICAL': 0x8b0000   # Dark Red
        }
    
    async def start_webhook_worker(self):
        """Start the webhook worker task"""
        # Use shared HTTP client instead of creating new session
        self.session = await http_client.get_session()
        
        if not self.task or self.task.done():
            self.task = asyncio.create_task(self._webhook_worker())
    
    async def stop_webhook_worker(self):
        """Stop the webhook worker and clean up"""
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        
        # Don't close shared HTTP session here - it's managed globally
        self.session = None
    
    def emit(self, record):
        """Called when a log record is emitted"""
        try:
            if self.bot and hasattr(self.bot, 'loop') and not self.bot.is_closed():
                # Check if we're in an async context
                try:
                    loop = asyncio.get_running_loop()
                    if loop == self.bot.loop:
                        self.bot.loop.call_soon_threadsafe(self.queue.put_nowait, record)
                    else:
                        # Different loop, skip webhook logging
                        pass
                except RuntimeError:
                    # No running loop, skip webhook logging
                    pass
        except Exception:
            # Completely silent fallback - don't spam console
            pass
    
    async def _webhook_worker(self):
        """Worker that processes the log queue and sends webhooks"""
        while True:
            try:
                record = await asyncio.wait_for(self.queue.get(), timeout=1.0)
                await self._send_webhook(record)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                print(f"Error in webhook worker: {e}")
                await asyncio.sleep(1)
    
    async def _send_webhook(self, record):
        """Send a single log record as a webhook embed"""
        try:
            if not self.session or self.session.closed:
                self.session = await http_client.get_session()
            
            message = self.format(record)
            
            # Determine emoji based on log level
            emoji_map = {
                'DEBUG': '🔍',
                'INFO': 'ℹ️',
                'WARNING': '⚠️',
                'ERROR': '❌',
                'CRITICAL': '🚨'
            }
            
            embed = {
                "title": f"{emoji_map.get(record.levelname, '📝')} {record.levelname} - {record.name}",
                "description": f"{message[:2000]}\n",
                "color": self.colors.get(record.levelname, 0x808080),
                "timestamp": datetime.utcnow().isoformat(),
                "fields": [
                    {
                        "name": "Module",
                        "value": record.name,
                        "inline": True
                    },
                    {
                        "name": "Function",
                        "value": f"{record.funcName}:{record.lineno}",
                        "inline": True
                    }
                ]
            }
            
            # Add exception info if present
            if record.exc_info:
                exc_text = ''.join(traceback.format_exception(*record.exc_info))
                embed["fields"].append({
                    "name": "Exception Details",
                    "value": f"```python\n{exc_text[:1000]}{'...' if len(exc_text) > 1000 else ''}\n```",
                    "inline": False
                })
            
            payload = {
                "embeds": [embed],
                "username": "Tausendsassa Logger",
                "avatar_url": "https://cdn.discordapp.com/attachments/1398436953422037013/1409705616817127556/1473097.png?ex=68ae5a2a&is=68ad08aa&hm=7b30d4675929866f2a09c7acec96785443aede3912a92c8745fc69ae703a132e&"
            }

            if record.levelname != 'INFO':
                async with self.session.post(
                        self.webhook_url,
                        json=payload,
                        headers={"Content-Type": "application/json"}
                ) as resp:
                    if resp.status not in (200, 204):
                        print(f"Webhook failed with status {resp.status}")

        except Exception as e:
            print(f"Error sending webhook: {e}")

# ─── Logging ────────────────────────────────────────────────────────────────
LOG_FORMAT  = "%(asctime)s %(levelname)s %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Base logging setup
logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    datefmt=DATE_FORMAT,
    handlers=[
        logging.StreamHandler(),
        TimedRotatingFileHandler("logs/tausendsassa.log", when="midnight", interval=1, backupCount=30, encoding="utf-8")
    ]
)

# Main bot logger
log = logging.getLogger("tausendsassa")

# ─── Intents & COG-Liste ────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

COGS = ["cogs.feeds", "cogs.map", "cogs.monitor", "cogs.server_monitor", "cogs.moderation", "cogs.whenistrumpgone", "cogs.help", "cogs.calendar"]

# ─── Enhanced Bot-Klasse ────────────────────────────────────────────────────
class Tausendsassa(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

        # Webhook configuration
        self.webhook_url = config.log_webhook_url
        self.webhook_handler = None
        self.cog_loggers: Dict[str, logging.Logger] = {}

        self.owner_id = config.owner_id

        # Database connection (initialized in setup_hook)
        self.db: Optional[DatabaseManager] = None

        # Setup webhook logging if URL is provided
        if self.webhook_url:
            self.setup_webhook_logging()
            
    def setup_webhook_logging(self):
        """Setup webhook logging handler"""
        if self.webhook_url:
            self.webhook_handler = WebhookLogHandler(self.webhook_url, self)
            self.webhook_handler.setLevel(logging.INFO)  # Only send INFO+ to webhook
            
            formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
            self.webhook_handler.setFormatter(formatter)
            
            # Add to main logger
            log.addHandler(self.webhook_handler)
            
            log.info("Webhook logging handler initialized")
    
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
                
                # Webhook handler if available
                if self.webhook_handler:
                    logger.addHandler(self.webhook_handler)
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

        # Start webhook worker if handler exists
        if self.webhook_handler:
            await self.webhook_handler.start_webhook_worker()
            log.info("✅ Webhook logger started")

        # Create logs directory for cog-specific logs
        os.makedirs("logs", exist_ok=True)

        # Load extensions
        for ext in COGS:
            try:
                await self.load_extension(ext)
                log.info(f"✅ Loaded extension {ext}")
            except Exception as e:
                log.exception(f"❌ Failed to load extension {ext}: {e}")
        
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
    
    async def close(self):
        """Cleanup when bot is shutting down"""
        log.info("🔄 Bot is shutting down...")

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

        # Stop webhook handler
        if self.webhook_handler:
            await self.webhook_handler.stop_webhook_worker()
            log.info("✅ Webhook logger stopped")

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
        
        # Check for webhook URL
        webhook_url = config.log_webhook_url
        if webhook_url:
            log.info("✅ Webhook URL found - live logging enabled")
        else:
            log.info("ℹ️ No webhook URL provided - using file/console logging only")
        
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
