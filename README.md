# Tausendsassa Discord Bot

A powerful, modular Discord bot featuring RSS feed integration, interactive maps, moderation tools, and comprehensive monitoring. Built with discord.py 2.x using a modern cog-based architecture.

## Features

- 🗞️ **RSS Feed Integration**: Monitor and post RSS/Atom feeds with customizable formatting and colors
- 🗺️ **Interactive Maps**: World, regional, and local maps with user location pins and customization
  - Real-time progress updates during map rendering
  - Proximity maps showing nearby users within embeds
  - Color preview with live rendering feedback
- 🛡️ **Moderation Tools**: Server management and user moderation capabilities
- 📊 **System Monitoring**: Health checks, performance metrics, and status tracking
- 💾 **Automated Backups**: Regular configuration backups with Discord webhook delivery
- 🌍 **Timezone Support**: Guild-specific timezone configuration for consistent timestamps
- 🎨 **Unified Color System**: Support for color names, RGB values, and HEX codes across all features
- 🔧 **Extensible Architecture**: Modular cog system for easy feature additions

## Quick Start

### Prerequisites

- Python 3.9 or higher
- Discord Bot Token
- Git

### Installation

```bash
# Clone the repository
git clone https://github.com/spa1teN/TausendsassaBot.git
cd TausendsassaBot

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# or
venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt
```

### Required Data Files

Download and extract Natural Earth vector data for map functionality:
```bash
# The bot needs these shapefiles in the data/ directory
# Download links are provided in data/sources.txt
mkdir -p data
# Extract shapefiles to data/ directory
```

### Environment Configuration

Create a `.env` file or set environment variables:

```bash
# Required
export DISCORD_TOKEN="your_discord_bot_token_here"

# Optional (with defaults)
export LOG_WEBHOOK_URL="discord_webhook_url_for_logging"
export BOT_OWNER_ID="your_discord_user_id"
export RSS_POLL_INTERVAL_MINUTES="1.0"
export RSS_RATE_LIMIT_SECONDS="30"
export RSS_FAILURE_THRESHOLD="3"
export RSS_MAX_RETRIES="3"
export RSS_BASE_RETRY_DELAY="2.0"
export AUTHORIZED_USERS="user_id1,user_id2,user_id3"
export MAX_CACHE_SIZE_MB="100"
export MAX_MEMORY_CACHE_ITEMS="50"
export HTTP_TIMEOUT="30"
export MAX_HTTP_CONNECTIONS="100"
export MAX_HTTP_CONNECTIONS_PER_HOST="10"
export PIN_COOLDOWN_MINUTES="5"
```

### Running the Bot

```bash
# Activate virtual environment
source venv/bin/activate

# Run the bot
python3 bot.py

# Or use the virtual environment directly
.venv/bin/python3 bot.py
```

## Architecture Overview

### Core Structure

```
├── bot.py                 # Main entry point with logging and cog loading
├── cogs/                  # Feature modules (Discord cogs)
│   ├── feeds.py          # RSS feed monitoring and posting
│   ├── map.py            # Interactive map system
│   ├── moderation.py     # Server moderation tools
│   ├── monitor.py        # System health monitoring
│   ├── backup.py         # Automated backup system
│   └── help.py           # Help and documentation
├── core/                  # Shared utilities and business logic
│   ├── config.py         # Centralized configuration management
│   ├── cache_manager.py  # LRU cache with size limits
│   ├── http_client.py    # Shared HTTP connection pool
│   ├── retry_handler.py  # Exponential backoff retry logic
│   ├── validation.py     # Configuration validation
│   ├── feeds_*.py        # RSS-specific components
│   ├── map_*.py          # Map-specific components
│   └── moderation_*.py   # Moderation-specific components
├── config/               # Per-guild configuration storage
├── data/                 # Static data and shared cache
├── logs/                 # Application logs with rotation
└── backups/              # Automated configuration backups
```

### Key Architectural Patterns

**Modular Cog System**: Each major feature is implemented as a separate Discord cog for easy maintenance and extensibility.

**Centralized Configuration**: All settings managed through `core/config.py` with environment variable support and validation.

**Shared Infrastructure**: Common services like HTTP client, cache manager, and retry handler are shared across cogs.

**Per-Guild Data Isolation**: Each Discord server gets its own configuration directory under `config/{guild_id}/`.

**Intelligent Caching**: Multi-layered caching system with automatic cleanup and size management.

## Development Guide

### Adding New Features

1. **Create a new cog** in `cogs/` directory
2. **Add supporting modules** in `core/` if needed
3. **Update configuration** in `core/config.py` for new settings
4. **Add to bot loading** in `bot.py` COGS list
5. **Use shared infrastructure** (HTTP client, cache, retry handler)

### Cog Template

```python
import discord
from discord.ext import commands
from discord import app_commands

class NewFeatureCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.log = bot.get_cog_logger("new_feature")
        
        # Import config to avoid circular imports
        from core.config import config
        self.config = config

    async def cog_load(self):
        """Called when cog is loaded"""
        self.log.info("New feature cog loaded")

    def cog_unload(self):
        """Called when cog is unloaded"""
        self.log.info("New feature cog unloaded")

    @app_commands.command(name="new_command")
    async def new_command(self, interaction: discord.Interaction):
        """New command description"""
        await interaction.response.send_message("Hello!")

async def setup(bot):
    await bot.add_cog(NewFeatureCog(bot))
```

### Configuration Management

Add new settings to `core/config.py`:

```python
# In config.py
NEW_FEATURE_SETTING = get_env_var('NEW_FEATURE_SETTING', 'default_value', str)

# Validation in validate_config()
if not NEW_FEATURE_SETTING:
    errors.append("NEW_FEATURE_SETTING is required")
```

### Using Shared Services

```python
# HTTP requests
from core.http_client import http_client
response = await http_client.get("https://api.example.com")

# Caching
from core.cache_manager import cache_manager
await cache_manager.set("key", data)
cached_data = await cache_manager.get("key")

# Retry logic
from core.retry_handler import retry_handler
result = await retry_handler.execute_with_retry(
    some_function, arg1, arg2, max_retries=3
)
```

## Testing

### Manual Testing
1. **Create a test Discord server**
2. **Invite the bot with appropriate permissions**
3. **Test each command and feature**
4. **Verify error handling and edge cases**

### Configuration Validation
```bash
# Test configuration validation
python3 -c "from core.validation import ConfigValidator; ConfigValidator().validate_all()"
```

## Deployment

### Production Setup

1. **Environment Variables**: Set all required environment variables
2. **Data Files**: Ensure Natural Earth shapefiles are in `data/` directory
3. **Permissions**: Bot needs appropriate Discord permissions for each feature
4. **Monitoring**: Configure webhook logging for production monitoring
5. **Backups**: Verify automated backup system is working

### Required Bot Permissions

- Send Messages
- Embed Links
- Attach Files
- Use External Emojis
- Read Message History
- Manage Messages (for moderation)
- Create Public Threads (for feeds)
- Use Slash Commands

### Docker Deployment (Optional)

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Create necessary directories
RUN mkdir -p data config logs backups

CMD ["python3", "bot.py"]
```

## Monitoring and Maintenance

### Log Files
- `logs/tausendsassa.log` - Main application log
- `logs/{cog_name}.log` - Per-cog specific logs
- Automatic rotation at midnight with 1 day retention

### New Admin Commands
- `/timezone <timezone>` - Set guild-specific timezone for all embed timestamps (admin only)

### Recent Improvements
- **Centralized Progress Handler** - Unified progress display system for all map rendering with persistent image display
- **Map rendering with live previews** - Real-time progress with intermediate map images during generation
- **Enhanced color support** - Feed customization now accepts color names ('orange'), RGB values ('255,165,0'), and HEX codes  
- **Guild-aware timezones** - Feed timestamps now respect server timezone settings
- **Improved feed UI** - Consistent ephemeral message editing instead of creating new messages
- **Comprehensive cache cleanup** - Map color changes now properly remove all old cached files
- **Interactive help buttons** - Direct links to GitHub repository and Discord development server

### Health Monitoring
- Use `/monitor` command for system status
- Check webhook logs for automated notifications
- Monitor cache usage and cleanup

### Backup System
- Daily automated backups at midnight UTC
- Manual backups via `/owner_backup_now`
- Backups exclude cache images to save space

## Contributing

### Code Style
- Follow PEP 8 Python style guide
- Use type hints where appropriate
- Add docstrings to public methods
- Use meaningful variable names

### Pull Request Process
1. Fork the repository
2. Create a feature branch
3. Make changes with proper testing
4. Update documentation if needed
5. Submit pull request with clear description

### Bug Reports
Include:
- Bot version and environment
- Steps to reproduce
- Expected vs actual behavior
- Relevant log entries

## Troubleshooting

### Common Issues

**Bot not responding**: Check Discord token and bot permissions
**Map rendering fails**: Verify Natural Earth shapefiles are in `data/` directory
**RSS feeds not updating**: Check feed URLs and network connectivity
**Permission errors**: Ensure bot has required Discord permissions

### Debug Mode
```bash
# Enable debug logging
export LOG_LEVEL="DEBUG"
python3 bot.py
```

### Validation
```bash
# Run configuration validation
python3 -c "from core.validation import ConfigValidator; ConfigValidator().validate_all()"
```

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Support

- Check the `/help` command in Discord
- Review this documentation
- Check log files for error details
- Contact developers through official channels

## Version History

See CHANGELOG.md for detailed version history and changes.