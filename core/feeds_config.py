# core/feeds_config.py

from discord import app_commands
from core.config import config

# Configuration constants (now using centralized config)
POLL_INTERVAL_MINUTES = config.poll_interval_minutes
MAX_POST_AGE_SECONDS = config.max_post_age_seconds
RATE_LIMIT_SECONDS = config.rate_limit_seconds
FAILURE_THRESHOLD = config.failure_threshold
AUTHORIZED_USERS = config.authorized_users

# Predefined color choices for easier selection
COLOR_CHOICES = [
    app_commands.Choice(name="Blue", value="3498DB"),
    app_commands.Choice(name="Green", value="2ECC71"),
    app_commands.Choice(name="Red", value="E74C3C"),
    app_commands.Choice(name="Orange", value="F39C12"),
    app_commands.Choice(name="Purple", value="9B59B6"),
    app_commands.Choice(name="Cyan", value="1ABC9C"),
    app_commands.Choice(name="Yellow", value="F1C40F"),
    app_commands.Choice(name="Pink", value="E91E63"),
    app_commands.Choice(name="Dark Blue", value="2C3E50"),
    app_commands.Choice(name="Gray", value="95A5A6")
]

def is_bluesky_feed_url(url: str) -> bool:
    """Check if the given URL is a Bluesky profile feed"""
    return "bsky.app/profile/" in url

def create_bluesky_embed_template(name: str, default_color: int) -> dict:
    """Create a specialized embed template for Bluesky feeds"""
    return {
        "title": f"{name} just posted on Bluesky",  # Static title for all Bluesky posts
        "description": "{summary}",  # Show post content in description
        "url": "{link}",
        "color": default_color,
        "timestamp": "{published_custom}",
        "footer": {"text": name},
        "image": {"url": "{thumbnail}"}
    }

def create_standard_embed_template(name: str, default_color: int) -> dict:
    """Create a standard embed template for RSS feeds"""
    return {
        "title": "{title}",
        "description": "{description}",
        "url": "{link}",
        "color": default_color,
        "timestamp": "{published_custom}",
        "footer": {"text": name},
        "image": {"url": "{thumbnail}"}
    }
