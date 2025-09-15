# Dependency Graph - RSStoDiscord Bot

This document provides a comprehensive overview of all Python files in the codebase and their purposes.

## Entry Point

### `bot.py`
**Main bot entry point and orchestrator**
- Initializes the Discord bot with custom logging system
- Manages cog loading and HTTP session management
- Implements WebhookLogHandler for Discord webhook logging
- Sets up configuration validation on startup
- Handles bot lifecycle (startup, shutdown, error handling)
- Creates shared resources (cache manager, HTTP client, retry handler)

## Core Infrastructure Modules

### Configuration & Validation
- **`core/config.py`** - Centralized configuration management using environment variables
- **`core/validation.py`** - Comprehensive validation system for configuration, dependencies, and data files

### Cache & Performance
- **`core/cache_manager.py`** - LRU cache with size limits and automatic cleanup for memory and file caching
- **`core/http_client.py`** - Shared HTTP client with connection pooling and optimized settings
- **`core/retry_handler.py`** - Exponential backoff retry logic for external service calls

### Data Management
- **`core/feeds_state.py`** - State management for RSS feed processing, tracks posted entries and message IDs
- **`core/timezone_util.py`** - Guild-specific timezone management with German timezone fallback

### Utility Modules
- **`core/colors.py`** - Unified color handling supporting names, RGB, and HEX formats
- **`core/__init__.py`** - Core package initializer (empty)

## Feature Modules (Cogs)

### RSS Feed Management
- **`cogs/feeds.py`** - Main RSS feed cog with async polling, webhook management, and per-guild configuration
- **`core/feeds_rss.py`** - RSS feed processing engine with caching, HTML cleaning, and change detection
- **`core/feeds_config.py`** - RSS feed configuration management and template handling
- **`core/feeds_views.py`** - Discord UI components for feed management (modals, buttons, dropdowns) with optimized ephemeral response handling
- **`core/feeds_thumbnails.py`** - Thumbnail extraction and processing for RSS entries

### Interactive Map System
- **`cogs/map.py`** - Main map cog with user pin management and map generation
- **`core/map_gen.py`** - Map generation engine using GeoPandas and PIL for rendering geographic maps
- **`core/map_storage.py`** - Map caching and storage management with intelligent cache invalidation
- **`core/map_config.py`** - Map configuration and region definitions
- **`core/map_proximity.py`** - Proximity calculations and nearby user detection
- **`core/map_progress_handler.py`** - Unified progress display for map generation operations
- **`core/map_views.py`** - User-facing Discord UI components for map interactions
- **`core/map_views_admin.py`** - Administrative Discord UI components for map management
- **`core/map_improved_modals.py`** - Enhanced modal dialogs for map configuration

### Calendar Integration
- **`cogs/calendar.py`** - iCal calendar integration with Discord events and weekly summaries
  - Supports automatic Discord event lifecycle management
  - Provides hourly synchronization with enhanced timeout handling and retry logic
  - Includes smart filtering (blacklist/whitelist) and event reminders
  - Enhanced error handling for network timeouts and calendar fetching
  - Optimized ephemeral response handling with proper interaction flow management

### Monitoring & Administration
- **`cogs/monitor.py`** - System and bot health monitoring with auto-updating embeds
- **`cogs/server_monitor.py`** - Centralized multi-server statistics and overview
- **`cogs/moderation.py`** - Server moderation tools and utilities
- **`core/mod_views.py`** - Discord UI components for moderation features

### User Interface & Help
- **`cogs/help.py`** - Help system that reads from commands.md file
- **`cogs/backup.py`** - Configuration backup and restore functionality
- **`cogs/whenistrumpgone.py`** - Special purpose cog (likely for countdown or status tracking)

### Package Initializers
- **`cogs/__init__.py`** - Cogs package initializer (empty)

## Dependency Relationships

### Core Dependencies
```
bot.py
├── core/config.py (configuration)
├── core/validation.py (startup validation)
├── core/cache_manager.py (caching)
├── core/http_client.py (HTTP connections)
└── all cogs/ (feature modules)
```

### RSS Feed System
```
cogs/feeds.py
├── core/feeds_rss.py (processing engine)
├── core/feeds_config.py (configuration)
├── core/feeds_views.py (UI components)
├── core/feeds_thumbnails.py (media processing)
├── core/feeds_state.py (state tracking)
├── core/retry_handler.py (reliability)
└── core/timezone_util.py (time handling)
```

### Map System
```
cogs/map.py
├── core/map_gen.py (rendering engine)
├── core/map_storage.py (caching)
├── core/map_config.py (configuration)
├── core/map_proximity.py (calculations)
├── core/map_progress_handler.py (UI feedback)
├── core/map_views.py (user UI)
├── core/map_views_admin.py (admin UI)
├── core/map_improved_modals.py (configuration UI)
├── core/colors.py (theming)
└── core/timezone_util.py (time handling)
```

### Calendar System
```
cogs/calendar.py
├── core/http_client.py (iCal fetching)
├── core/retry_handler.py (reliability)
├── core/cache_manager.py (caching)
├── core/config.py (configuration)
└── core/timezone_util.py (time handling)
```

### Monitoring System
```
cogs/monitor.py
├── core/config.py (settings)
└── core/timezone_util.py (time display)

cogs/server_monitor.py
├── core/config.py (settings)
└── core/timezone_util.py (time display)
```

## External Dependencies

### Required Python Packages
- **discord.py** - Discord API interaction
- **aiohttp** - Async HTTP client for external requests
- **feedparser** - RSS/Atom feed parsing
- **geopandas** - Geographic data processing for maps
- **psutil** - System monitoring and resource usage
- **requests** - HTTP requests (fallback/specific use cases)
- **PyYAML** - YAML configuration file handling
- **Pillow (PIL)** - Image processing for map generation
- **icalendar** - iCal calendar file parsing
- **recurring-ical-events** - Recurring event handling

### Required Data Files
- **Natural Earth Shapefiles** (in `data/` directory):
  - `ne_10m_admin_0_countries.shp` - Country boundaries
  - `ne_10m_admin_1_states_provinces.shp` - State/province boundaries
  - `ne_10m_land.shp` - Land masses
  - `ne_10m_lakes.shp` - Lake features

### External APIs
- **Discord API** - Bot interactions and webhook posting
- **Nominatim (OpenStreetMap)** - Geocoding service for map pins
- **RSS/Atom feeds** - External content sources
- **iCal calendar feeds** - Calendar integration sources

## File Organization

### Modular Architecture
The codebase follows a clean separation of concerns:

1. **`bot.py`** - Entry point and orchestration
2. **`core/`** - Shared infrastructure and business logic
3. **`cogs/`** - Feature-specific Discord command handlers
4. **`config/`** - Per-guild configuration storage (created at runtime)
5. **`data/`** - Static data files (shapefiles, cache)
6. **`logs/`** - Log file storage (created at runtime)

### Configuration Management
- Environment variables define global settings
- Per-guild YAML files store feature-specific configuration
- Automatic directory creation and validation on startup
- Smart fallbacks and error handling

### Caching Strategy
- Multi-layer caching: memory (LRU) + file-based
- Intelligent cache invalidation based on content changes
- Size-limited caches with automatic cleanup
- Separate caching for different data types (maps, feeds, etc.)

### Error Handling & Reliability
- Enhanced exponential backoff retry logic for external services with proper timeout handling
- Improved TimeoutError catching for calendar and RSS feed HTTP requests
- Comprehensive validation on startup
- Graceful degradation for non-critical failures
- Detailed logging with Discord webhook integration and timeout context

This architecture enables a highly modular, scalable, and maintainable Discord bot with robust RSS feed processing, interactive map functionality, calendar integration, and comprehensive monitoring capabilities.