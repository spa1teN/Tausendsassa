# core/config.py
import os
from typing import List, Optional
import logging

log = logging.getLogger("tausendsassa.config")

class BotConfig:
    """Centralized configuration management for the bot"""
    
    def __init__(self):
        self._validate_required_env_vars()
    
    # Discord Configuration
    @property
    def discord_token(self) -> str:
        return os.getenv("DISCORD_TOKEN", "")
    
    @property
    def guild_id(self) -> Optional[int]:
        guild_id = os.getenv("GUILD_ID")
        return int(guild_id) if guild_id else None
    
    @property
    def owner_id(self) -> int:
        return int(os.getenv("BOT_OWNER_ID", "485051896655249419"))
    
    # Logging Configuration
    @property
    def log_webhook_url(self) -> Optional[str]:
        return os.getenv("LOG_WEBHOOK_URL")
    
    @property
    def log_level(self) -> str:
        return os.getenv("LOG_LEVEL", "INFO").upper()
    
    # RSS Feed Configuration
    @property
    def poll_interval_minutes(self) -> float:
        return float(os.getenv("RSS_POLL_INTERVAL_MINUTES", "1.0"))
    
    @property
    def max_post_age_seconds(self) -> int:
        return int(os.getenv("RSS_MAX_POST_AGE_SECONDS", "86400"))
    
    @property
    def rate_limit_seconds(self) -> int:
        return int(os.getenv("RSS_RATE_LIMIT_SECONDS", "30"))
    
    @property
    def failure_threshold(self) -> int:
        return int(os.getenv("RSS_FAILURE_THRESHOLD", "3"))
    
    @property
    def max_retries(self) -> int:
        return int(os.getenv("RSS_MAX_RETRIES", "3"))
    
    @property
    def base_retry_delay(self) -> float:
        return float(os.getenv("RSS_BASE_RETRY_DELAY", "2.0"))
    
    @property
    def authorized_users(self) -> List[int]:
        users_str = os.getenv("AUTHORIZED_USERS", "485051896655249419,506551160354766848,703896034820096000")
        return [int(user_id.strip()) for user_id in users_str.split(",") if user_id.strip()]
    
    @property
    def global_monitor_channel_id(self) -> Optional[int]:
        channel_id = os.getenv("GLOBAL_MONITOR_CHANNEL_ID")
        return int(channel_id) if channel_id else None
    
    # Map Configuration
    @property
    def pin_cooldown_minutes(self) -> int:
        return int(os.getenv("MAP_PIN_COOLDOWN_MINUTES", "30"))
    
    # Cache Configuration
    @property
    def max_cache_size_mb(self) -> int:
        return int(os.getenv("MAX_CACHE_SIZE_MB", "100"))
    
    @property
    def max_memory_cache_items(self) -> int:
        return int(os.getenv("MAX_MEMORY_CACHE_ITEMS", "50"))
    
    # HTTP Configuration
    @property
    def http_timeout(self) -> int:
        return int(os.getenv("HTTP_TIMEOUT", "30"))
    
    @property
    def max_connections(self) -> int:
        return int(os.getenv("MAX_HTTP_CONNECTIONS", "100"))
    
    @property
    def max_connections_per_host(self) -> int:
        return int(os.getenv("MAX_HTTP_CONNECTIONS_PER_HOST", "10"))
    
    # Monitor Configuration
    @property
    def monitor_authorized_roles(self) -> List[int]:
        roles_str = os.getenv("MONITOR_AUTHORIZED_ROLES", "1402526603057303653,1398500235541610639")
        return [int(role_id.strip()) for role_id in roles_str.split(",") if role_id.strip()]
    
    @property
    def system_metrics_interval(self) -> int:
        return int(os.getenv("SYSTEM_METRICS_INTERVAL", "60"))
    
    @property
    def monitor_update_interval(self) -> int:
        return int(os.getenv("MONITOR_UPDATE_INTERVAL", "300"))
    
    def _validate_required_env_vars(self):
        """Validate that required environment variables are set"""
        required_vars = ["DISCORD_TOKEN"]
        missing_vars = []
        
        for var in required_vars:
            if not os.getenv(var):
                missing_vars.append(var)
        
        if missing_vars:
            error_msg = f"Missing required environment variables: {', '.join(missing_vars)}"
            log.error(error_msg)
            raise ValueError(error_msg)
    
    def log_configuration(self):
        """Log current configuration (excluding sensitive data)"""
        log.info("Bot Configuration:")
        log.info(f"  Guild ID: {self.guild_id}")
        log.info(f"  Owner ID: {self.owner_id}")
        log.info(f"  Log Level: {self.log_level}")
        log.info(f"  RSS Poll Interval: {self.poll_interval_minutes} minutes")
        log.info(f"  RSS Rate Limit: {self.rate_limit_seconds} seconds")
        log.info(f"  RSS Failure Threshold: {self.failure_threshold}")
        log.info(f"  Pin Cooldown: {self.pin_cooldown_minutes} minutes")
        log.info(f"  Max Cache Size: {self.max_cache_size_mb} MB")
        log.info(f"  HTTP Timeout: {self.http_timeout} seconds")
        log.info(f"  Authorized Users: {len(self.authorized_users)} users")
        log.info(f"  Webhook Logging: {'Enabled' if self.log_webhook_url else 'Disabled'}")

# Global configuration instance
config = BotConfig()