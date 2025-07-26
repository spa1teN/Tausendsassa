# bot.py
import os
import yaml
import logging
from logging.handlers import RotatingFileHandler

import discord
from discord.ext import commands

# ─── Logging ────────────────────────────────────────────────────────────────
LOG_FORMAT  = "%(asctime)s %(levelname)s %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    datefmt=DATE_FORMAT,
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler("rssbot.log", maxBytes=5*1024*1024, backupCount=3, encoding="utf-8")
    ]
)
log = logging.getLogger("rssbot")

# ─── Config ─────────────────────────────────────────────────────────────────
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")
with open(CONFIG_PATH, encoding="utf-8") as f:
    CONFIG = yaml.safe_load(f)

# ─── Intents & COG-Liste ────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True

COGS = ["cogs.feeds"]

# ─── Bot-Klasse ─────────────────────────────────────────────────────────────
class RSSBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        # Hier awaiten wir korrekt das Laden der Cogs
        for ext in COGS:
            try:
                await self.load_extension(ext)
                log.info(f"✅ Loaded extension {ext}")
            except Exception:
                log.exception(f"❌ Failed to load extension {ext}")

    async def on_ready(self):
        log.info(f"Logged in as {self.user} (ID: {self.user.id})")
        print("------")

# ─── Main ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        log.error("DISCORD_TOKEN environment variable not set")
        exit(1)
    bot = RSSBot()
    bot.run(token)
