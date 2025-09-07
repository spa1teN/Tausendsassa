# bot.py
import os
import yaml
import logging
from logging.handlers import RotatingFileHandler
import aiohttp
import asyncio
from datetime import datetime
import traceback
from typing import Dict, Optional

import discord
from discord.ext import commands

GUILD_ID = 1398409754967015647
OWNER_ID = 485051896655249419
GUILD    = discord.Object(id=GUILD_ID) if GUILD_ID else None
LOG_WEBHOOK_URL = "https://discord.com/api/webhooks/1402497318208409680/xBavteSxxo1xzwkwqvHrja9bl3gh4zwKMKsm48dH9mGG6aBuDh7v0EDDajQOtnCwX1vt"

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
        if not self.session:
            self.session = aiohttp.ClientSession()
        
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
        
        if self.session and not self.session.closed:
            await self.session.close()
    
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
                self.session = aiohttp.ClientSession()
            
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
        RotatingFileHandler("logs/tausendsassa.log", maxBytes=5*1024*1024, backupCount=3, encoding="utf-8")
    ]
)

# Main bot logger
log = logging.getLogger("tausendsassa")

# ─── Intents & COG-Liste ────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

COGS = ["cogs.feeds", "cogs.map", "cogs.monitor", "cogs.moderation", "cogs.whenistrumpgone", "cogs.help", "cogs.backup"]

# ─── Enhanced Bot-Klasse ────────────────────────────────────────────────────
class Tausendsassa(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)
        
        # Webhook configuration
        self.webhook_url = LOG_WEBHOOK_URL
        self.webhook_handler = None
        self.cog_loggers: Dict[str, logging.Logger] = {}

        self.owner_id = OWNER_ID
        
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
                
                # File handler
                file_handler = RotatingFileHandler(
                    f"logs/{cog_name}.log", 
                    maxBytes=5*1024*1024, 
                    backupCount=2, 
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
        
        await self.tree.sync()
        log.info("✅ All slash commands synced")

    async def on_ready(self):
        status = discord.Status.online
        activity = discord.Activity(
            type=discord.ActivityType.listening,
            name="/help"
        )
        await self.change_presence(status=status, activity=activity)
        log.info(f"🤖 Logged in as {self.user} (ID: {self.user.id})")
        log.info(f"📊 Connected to {len(self.guilds)} guild(s)")
        print("------")
    
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
        
        # Stop webhook handler
        if self.webhook_handler:
            await self.webhook_handler.stop_webhook_worker()
            log.info("✅ Webhook logger stopped")
        
        await super().close()

# ─── Main ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        log.error("DISCORD_TOKEN environment variable not set")
        exit(1)
    
    # Check for webhook URL
    webhook_url = LOG_WEBHOOK_URL
    if webhook_url:
        log.info("✅ Webhook URL found - live logging enabled")
    else:
        log.info("ℹ️ No webhook URL provided - using file/console logging only")
    
    bot = Tausendsassa()
    
    try:
        bot.run(token)
    except KeyboardInterrupt:
        log.info("Bot stopped by user")
    except Exception as e:
        log.error(f"Bot crashed: {e}", exc_info=True)
