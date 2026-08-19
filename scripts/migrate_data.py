#!/usr/bin/env python3
"""
Migration script to transfer data from file-based storage to PostgreSQL.

Usage:
    python scripts/migrate_data.py --dry-run     # Validate without writing
    python scripts/migrate_data.py --migrate     # Perform actual migration
    python scripts/migrate_data.py --validate    # Validate database after migration

Environment variables:
    DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
"""

import asyncio
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

import yaml

try:
    import asyncpg
except ImportError:
    print("Error: asyncpg not installed. Run: pip install asyncpg")
    sys.exit(1)

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_BASE = PROJECT_ROOT / "config"
DATA_BASE = PROJECT_ROOT / "cogs/map_data"


class MigrationStats:
    """Track migration statistics."""

    def __init__(self):
        self.guilds = 0
        self.feeds = 0
        self.posted_entries = 0
        self.calendars = 0
        self.calendar_events = 0
        self.calendar_reminders = 0
        self.map_settings = 0
        self.map_pins = 0
        self.moderation_configs = 0
        self.timezones = 0
        self.webhooks = 0
        self.feed_cache = 0
        self.entry_hashes = 0
        self.monitor_messages = 0
        self.errors: List[str] = []

    def print_summary(self, dry_run: bool = False):
        """Print migration summary."""
        print("\n" + "=" * 60)
        print(f"MIGRATION SUMMARY {'(DRY RUN)' if dry_run else ''}")
        print("=" * 60)
        print(f"Guilds:              {self.guilds}")
        print(f"Timezones:           {self.timezones}")
        print(f"Feeds:               {self.feeds}")
        print(f"Posted Entries:      {self.posted_entries}")
        print(f"Calendars:           {self.calendars}")
        print(f"Calendar Events:     {self.calendar_events}")
        print(f"Calendar Reminders:  {self.calendar_reminders}")
        print(f"Map Settings:        {self.map_settings}")
        print(f"Map Pins:            {self.map_pins}")
        print(f"Moderation Configs:  {self.moderation_configs}")
        print(f"Webhook Cache:       {self.webhooks}")
        print(f"Feed Cache:          {self.feed_cache}")
        print(f"Entry Hashes:        {self.entry_hashes}")
        print(f"Monitor Messages:    {self.monitor_messages}")

        if self.errors:
            print(f"\nErrors ({len(self.errors)}):")
            for error in self.errors[:20]:  # Show first 20 errors
                print(f"  - {error}")
            if len(self.errors) > 20:
                print(f"  ... and {len(self.errors) - 20} more errors")
        else:
            print("\nNo errors encountered!")


class MigrationRunner:
    """Runs the migration from files to database."""

    def __init__(self, pool: asyncpg.Pool, dry_run: bool = True):
        self.pool = pool
        self.dry_run = dry_run
        self.stats = MigrationStats()

    async def migrate_all(self):
        """Run complete migration."""
        print(f"\n{'=' * 60}")
        print(f"Starting migration {'(DRY RUN)' if self.dry_run else '(ACTUAL)'}")
        print(f"{'=' * 60}\n")

        # Migrate global configs first
        print("Migrating global configurations...")
        await self.migrate_moderation_config()
        await self.migrate_webhook_cache()
        await self.migrate_feed_cache()
        await self.migrate_entry_hashes()
        await self.migrate_monitor_config()
        await self.migrate_server_monitor_config()
        await self.migrate_map_global_config()

        # Migrate per-guild data
        print("\nMigrating per-guild data...")
        guild_dirs = [d for d in CONFIG_BASE.iterdir() if d.is_dir() and d.name.isdigit()]
        print(f"Found {len(guild_dirs)} guild(s) to migrate")

        for guild_dir in sorted(guild_dirs, key=lambda d: int(d.name)):
            guild_id = int(guild_dir.name)
            await self.migrate_guild(guild_id, guild_dir)

        self.stats.print_summary(self.dry_run)

    async def migrate_guild(self, guild_id: int, guild_dir: Path):
        """Migrate all data for a single guild."""
        print(f"\n  Guild {guild_id}:")

        # Ensure guild exists in database
        if not self.dry_run:
            await self.pool.execute(
                "INSERT INTO guilds (id) VALUES ($1) ON CONFLICT DO NOTHING",
                guild_id
            )
        self.stats.guilds += 1

        # Migrate each config type
        await self.migrate_timezone(guild_id, guild_dir)
        await self.migrate_feeds(guild_id, guild_dir)
        await self.migrate_posted_entries(guild_id, guild_dir)
        await self.migrate_calendars(guild_id, guild_dir)
        await self.migrate_map(guild_id, guild_dir)

    # ==========================================
    # Per-Guild Migrations
    # ==========================================

    async def migrate_timezone(self, guild_id: int, guild_dir: Path):
        """Migrate timezone_config.yaml."""
        config_file = guild_dir / "timezone_config.yaml"
        if not config_file.exists():
            return

        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f) or {}

            tz = config.get('timezone', 'Europe/Berlin')

            if not self.dry_run:
                await self.pool.execute(
                    """INSERT INTO guild_timezones (guild_id, timezone)
                       VALUES ($1, $2)
                       ON CONFLICT (guild_id) DO UPDATE SET timezone = $2""",
                    guild_id, tz
                )

            self.stats.timezones += 1
            print(f"    - Timezone: {tz}")

        except Exception as e:
            self.stats.errors.append(f"Guild {guild_id} timezone: {e}")

    async def migrate_feeds(self, guild_id: int, guild_dir: Path):
        """Migrate feed_config.yaml."""
        config_file = guild_dir / "feed_config.yaml"
        if not config_file.exists():
            return

        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f) or {}

            feeds = config.get('feeds', [])
            monitor_channel = config.get('monitor_channel_id')

            for feed in feeds:
                if not self.dry_run:
                    embed_template = feed.get('embed_template')
                    if embed_template:
                        embed_template = json.dumps(embed_template)

                    await self.pool.execute(
                        """INSERT INTO feeds
                           (guild_id, name, feed_url, channel_id, webhook_url, username,
                            avatar_url, color, max_items, crosspost, embed_template)
                           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                           ON CONFLICT (guild_id, name) DO UPDATE SET
                           feed_url = $3, channel_id = $4, webhook_url = $5""",
                        guild_id,
                        feed.get('name', 'Unknown'),
                        feed.get('feed_url', ''),
                        feed.get('channel_id', 0),
                        feed.get('webhook_url'),
                        feed.get('username'),
                        feed.get('avatar_url'),
                        feed.get('color'),
                        feed.get('max_items', 3),
                        feed.get('crosspost', False),
                        embed_template
                    )

                self.stats.feeds += 1

            # Migrate monitor channel
            if monitor_channel and not self.dry_run:
                await self.pool.execute(
                    """INSERT INTO feed_monitor_channels (guild_id, channel_id)
                       VALUES ($1, $2)
                       ON CONFLICT (guild_id) DO UPDATE SET channel_id = $2""",
                    guild_id, monitor_channel
                )

            print(f"    - Feeds: {len(feeds)}")

        except Exception as e:
            self.stats.errors.append(f"Guild {guild_id} feeds: {e}")

    async def migrate_posted_entries(self, guild_id: int, guild_dir: Path):
        """Migrate posted_entries.json."""
        config_file = guild_dir / "posted_entries.json"
        if not config_file.exists():
            return

        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                entries = json.load(f)

            # Handle different formats (old list vs new dict)
            if isinstance(entries, list):
                # Old format: just a list of GUIDs
                for guid in entries:
                    if not self.dry_run:
                        await self.pool.execute(
                            """INSERT INTO posted_entries (guild_id, guid)
                               VALUES ($1, $2)
                               ON CONFLICT (guild_id, guid) DO NOTHING""",
                            guild_id, guid
                        )
                    self.stats.posted_entries += 1

            elif isinstance(entries, dict):
                # New format: dict with entry data
                for guid, data in entries.items():
                    if isinstance(data, str):
                        # Intermediate format: just timestamp
                        timestamp = data
                        message_id = None
                        channel_id = None
                    else:
                        # Full format
                        timestamp = data.get('timestamp')
                        message_id = data.get('message_id')
                        channel_id = data.get('channel_id')

                    if not self.dry_run:
                        # Parse timestamp
                        posted_at = None
                        if timestamp:
                            try:
                                posted_at = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                            except (ValueError, AttributeError):
                                posted_at = datetime.now(timezone.utc)

                        await self.pool.execute(
                            """INSERT INTO posted_entries
                               (guild_id, guid, message_id, channel_id, posted_at)
                               VALUES ($1, $2, $3, $4, COALESCE($5, NOW()))
                               ON CONFLICT (guild_id, guid) DO UPDATE SET
                               message_id = COALESCE($3, posted_entries.message_id),
                               channel_id = COALESCE($4, posted_entries.channel_id)""",
                            guild_id, guid, message_id, channel_id, posted_at
                        )

                    self.stats.posted_entries += 1

            print(f"    - Posted entries: {self.stats.posted_entries}")

        except Exception as e:
            self.stats.errors.append(f"Guild {guild_id} posted_entries: {e}")

    async def migrate_calendars(self, guild_id: int, guild_dir: Path):
        """Migrate calendars.yaml."""
        config_file = guild_dir / "calendars.yaml"
        if not config_file.exists():
            return

        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                calendars = yaml.safe_load(f) or {}

            for calendar_id, cal_data in calendars.items():
                if not self.dry_run:
                    # Parse timestamps
                    last_sync = None
                    current_week_start = None

                    if cal_data.get('last_sync'):
                        try:
                            last_sync = datetime.fromisoformat(cal_data['last_sync'])
                        except (ValueError, TypeError):
                            pass

                    if cal_data.get('current_week_start'):
                        try:
                            current_week_start = datetime.fromisoformat(cal_data['current_week_start'])
                        except (ValueError, TypeError):
                            pass

                    # Insert calendar
                    result = await self.pool.fetchrow(
                        """INSERT INTO calendars
                           (guild_id, calendar_id, text_channel_id, voice_channel_id, ical_url,
                            blacklist, whitelist, reminder_role_id, last_message_id,
                            current_week_start, last_sync)
                           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                           ON CONFLICT (guild_id, calendar_id) DO UPDATE SET
                           ical_url = $5, blacklist = $6, whitelist = $7
                           RETURNING id""",
                        guild_id,
                        calendar_id,
                        cal_data.get('text_channel_id', 0),
                        cal_data.get('voice_channel_id', 0),
                        cal_data.get('ical_url', ''),
                        cal_data.get('blacklist', []),
                        cal_data.get('whitelist', []),
                        cal_data.get('reminder_role_id'),
                        cal_data.get('last_message_id'),
                        current_week_start,
                        last_sync
                    )

                    calendar_pk = result['id']

                    # Migrate event_title_to_id mapping
                    event_map = cal_data.get('event_title_to_id', {})
                    for title, discord_event_id in event_map.items():
                        await self.pool.execute(
                            """INSERT INTO calendar_events (calendar_pk, event_title, discord_event_id)
                               VALUES ($1, $2, $3)
                               ON CONFLICT DO NOTHING""",
                            calendar_pk, title, discord_event_id
                        )
                        self.stats.calendar_events += 1

                    # Migrate sent_reminders
                    reminders = cal_data.get('sent_reminders', {})
                    for reminder_key, sent_at in reminders.items():
                        try:
                            sent_datetime = datetime.fromisoformat(sent_at)
                        except (ValueError, TypeError):
                            sent_datetime = datetime.now(timezone.utc)

                        await self.pool.execute(
                            """INSERT INTO calendar_reminders (calendar_pk, reminder_key, sent_at)
                               VALUES ($1, $2, $3)
                               ON CONFLICT DO NOTHING""",
                            calendar_pk, reminder_key, sent_datetime
                        )
                        self.stats.calendar_reminders += 1

                self.stats.calendars += 1

            print(f"    - Calendars: {len(calendars)}")

        except Exception as e:
            self.stats.errors.append(f"Guild {guild_id} calendars: {e}")

    async def migrate_map(self, guild_id: int, guild_dir: Path):
        """Migrate map.json."""
        config_file = guild_dir / "map.json"
        if not config_file.exists():
            return

        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                map_data = json.load(f)

            if not self.dry_run:
                # Insert map settings - include meta fields in settings JSONB
                settings = dict(map_data.get('settings', {}))
                # Store meta fields in settings JSON
                if 'allow_proximity' in map_data:
                    settings['allow_proximity'] = map_data['allow_proximity']
                if 'created_by' in map_data:
                    settings['created_by'] = map_data['created_by']
                if 'created_at' in map_data:
                    settings['created_at'] = map_data['created_at']

                await self.pool.execute(
                    """INSERT INTO map_settings
                       (guild_id, region, channel_id, message_id, settings)
                       VALUES ($1, $2, $3, $4, $5)
                       ON CONFLICT (guild_id) DO UPDATE SET
                       region = $2, channel_id = $3, message_id = $4, settings = $5""",
                    guild_id,
                    map_data.get('region', 'world'),
                    map_data.get('channel_id'),
                    map_data.get('message_id'),
                    json.dumps(settings)
                )

                self.stats.map_settings += 1

                # Insert pins
                pins = map_data.get('pins', {})
                for user_id_str, pin_data in pins.items():
                    user_id = int(user_id_str)

                    # Parse timestamp
                    pinned_at = None
                    if pin_data.get('timestamp'):
                        try:
                            pinned_at = datetime.fromisoformat(pin_data['timestamp'])
                        except (ValueError, TypeError):
                            try:
                                pinned_at = datetime.strptime(pin_data['timestamp'], "%Y-%m-%d %H:%M:%S")
                            except (ValueError, TypeError):
                                pass

                    await self.pool.execute(
                        """INSERT INTO map_pins
                           (guild_id, user_id, latitude, longitude, username,
                            display_name, location, color, pinned_at)
                           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, COALESCE($9, NOW()))
                           ON CONFLICT (guild_id, user_id) DO UPDATE SET
                           latitude = $3, longitude = $4, username = $5,
                           display_name = $6, location = $7, color = $8""",
                        guild_id,
                        user_id,
                        pin_data.get('lat', 0),
                        pin_data.get('lng', 0),
                        pin_data.get('username'),
                        pin_data.get('display_name'),
                        pin_data.get('location'),
                        pin_data.get('color', '#FF0000'),
                        pinned_at
                    )

                    self.stats.map_pins += 1

            print(f"    - Map pins: {len(map_data.get('pins', {}))}")

        except Exception as e:
            self.stats.errors.append(f"Guild {guild_id} map: {e}")

    # ==========================================
    # Global Migrations
    # ==========================================

    async def migrate_moderation_config(self):
        """Migrate moderation_config.json."""
        config_file = CONFIG_BASE / "moderation_config.json"
        if not config_file.exists():
            print("  - moderation_config.json: not found")
            return

        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)

            for guild_id_str, guild_config in config.items():
                guild_id = int(guild_id_str)

                if not self.dry_run:
                    # Ensure guild exists
                    await self.pool.execute(
                        "INSERT INTO guilds (id) VALUES ($1) ON CONFLICT DO NOTHING",
                        guild_id
                    )

                    await self.pool.execute(
                        """INSERT INTO moderation_config
                           (guild_id, member_log_webhook, join_role_id)
                           VALUES ($1, $2, $3)
                           ON CONFLICT (guild_id) DO UPDATE SET
                           member_log_webhook = $2, join_role_id = $3""",
                        guild_id,
                        guild_config.get('member_log_webhook'),
                        guild_config.get('join_role')
                    )

                self.stats.moderation_configs += 1

            print(f"  - moderation_config.json: {len(config)} guild(s)")

        except Exception as e:
            self.stats.errors.append(f"moderation_config: {e}")

    async def migrate_webhook_cache(self):
        """Migrate webhook_cache.json."""
        config_file = CONFIG_BASE / "webhook_cache.json"
        if not config_file.exists():
            print("  - webhook_cache.json: not found")
            return

        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                cache = json.load(f)

            for channel_id_str, webhook_data in cache.items():
                channel_id = int(channel_id_str)

                if not self.dry_run:
                    await self.pool.execute(
                        """INSERT INTO webhook_cache
                           (channel_id, webhook_id, webhook_token, webhook_name)
                           VALUES ($1, $2, $3, $4)
                           ON CONFLICT (channel_id) DO UPDATE SET
                           webhook_id = $2, webhook_token = $3, webhook_name = $4""",
                        channel_id,
                        webhook_data.get('id'),
                        webhook_data.get('token'),
                        webhook_data.get('name')
                    )

                self.stats.webhooks += 1

            print(f"  - webhook_cache.json: {len(cache)} webhook(s)")

        except Exception as e:
            self.stats.errors.append(f"webhook_cache: {e}")

    async def migrate_feed_cache(self):
        """Migrate feed_cache.json."""
        config_file = CONFIG_BASE / "feed_cache.json"
        if not config_file.exists():
            print("  - feed_cache.json: not found")
            return

        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                cache = json.load(f)

            for url, cache_data in cache.items():
                if not self.dry_run:
                    last_check = None
                    if cache_data.get('last_check'):
                        try:
                            last_check = datetime.fromisoformat(cache_data['last_check'])
                        except (ValueError, TypeError):
                            pass

                    await self.pool.execute(
                        """INSERT INTO feed_cache
                           (url, etag, last_modified, content_hash, last_check)
                           VALUES ($1, $2, $3, $4, COALESCE($5, NOW()))
                           ON CONFLICT (url) DO UPDATE SET
                           etag = $2, last_modified = $3, content_hash = $4""",
                        url,
                        cache_data.get('etag'),
                        cache_data.get('last_modified'),
                        cache_data.get('content_hash'),
                        last_check
                    )

                self.stats.feed_cache += 1

            print(f"  - feed_cache.json: {len(cache)} feed(s)")

        except Exception as e:
            self.stats.errors.append(f"feed_cache: {e}")

    async def migrate_entry_hashes(self):
        """Migrate entry_hashes.json."""
        config_file = CONFIG_BASE / "entry_hashes.json"
        if not config_file.exists():
            print("  - entry_hashes.json: not found")
            return

        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                hashes = json.load(f)

            if not self.dry_run and hashes:
                # Batch insert for efficiency
                await self.pool.executemany(
                    """INSERT INTO entry_hashes (guid, content_hash)
                       VALUES ($1, $2)
                       ON CONFLICT (guid) DO UPDATE SET content_hash = $2""",
                    [(guid, hash_) for guid, hash_ in hashes.items()]
                )

            self.stats.entry_hashes = len(hashes)
            print(f"  - entry_hashes.json: {len(hashes)} hash(es)")

        except Exception as e:
            self.stats.errors.append(f"entry_hashes: {e}")

    async def migrate_monitor_config(self):
        """Migrate monitor_config.json."""
        config_file = CONFIG_BASE / "monitor_config.json"
        if not config_file.exists():
            print("  - monitor_config.json: not found")
            return

        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)

            messages = config.get('monitor_messages', {})
            interval = config.get('auto_update_interval', 300)

            for channel_id_str, message_id_str in messages.items():
                if not self.dry_run:
                    await self.pool.execute(
                        """INSERT INTO monitor_messages
                           (channel_id, message_id, monitor_type, auto_update_interval)
                           VALUES ($1, $2, $3, $4)
                           ON CONFLICT (channel_id, monitor_type) DO UPDATE SET
                           message_id = $2, auto_update_interval = $4""",
                        int(channel_id_str),
                        int(message_id_str),
                        'system',
                        interval
                    )

                self.stats.monitor_messages += 1

            print(f"  - monitor_config.json: {len(messages)} message(s)")

        except Exception as e:
            self.stats.errors.append(f"monitor_config: {e}")

    async def migrate_server_monitor_config(self):
        """Migrate server_monitor.json."""
        config_file = CONFIG_BASE / "server_monitor.json"
        if not config_file.exists():
            print("  - server_monitor.json: not found")
            return

        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)

            messages = config.get('monitor_messages', {})

            for channel_id_str, message_id_str in messages.items():
                if not self.dry_run:
                    await self.pool.execute(
                        """INSERT INTO monitor_messages
                           (channel_id, message_id, monitor_type, auto_update_interval)
                           VALUES ($1, $2, $3, $4)
                           ON CONFLICT (channel_id, monitor_type) DO UPDATE SET
                           message_id = $2""",
                        int(channel_id_str),
                        int(message_id_str),
                        'server',
                        300
                    )

                self.stats.monitor_messages += 1

            print(f"  - server_monitor.json: {len(messages)} message(s)")

        except Exception as e:
            self.stats.errors.append(f"server_monitor: {e}")

    async def migrate_map_global_config(self):
        """Migrate map_global_config.json."""
        config_file = DATA_BASE / "map_global_config.json"
        if not config_file.exists():
            print("  - map_global_config.json: not found")
            return

        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)

            for key, value in config.items():
                if not self.dry_run:
                    await self.pool.execute(
                        """INSERT INTO map_global_config (key, value)
                           VALUES ($1, $2)
                           ON CONFLICT (key) DO UPDATE SET value = $2""",
                        key,
                        json.dumps(value)
                    )

            print(f"  - map_global_config.json: {len(config)} key(s)")

        except Exception as e:
            self.stats.errors.append(f"map_global_config: {e}")


async def validate_database(pool: asyncpg.Pool):
    """Validate database contents after migration."""
    print("\n" + "=" * 60)
    print("DATABASE VALIDATION")
    print("=" * 60)

    tables = [
        'guilds', 'guild_timezones', 'moderation_config',
        'feeds', 'posted_entries', 'feed_cache', 'entry_hashes', 'webhook_cache',
        'calendars', 'calendar_events', 'calendar_reminders',
        'map_settings', 'map_pins', 'map_global_config',
        'monitor_messages'
    ]

    for table in tables:
        count = await pool.fetchval(f"SELECT COUNT(*) FROM {table}")
        print(f"  {table}: {count} row(s)")


async def main():
    parser = argparse.ArgumentParser(description='Migrate Tausendsassa data to PostgreSQL')
    parser.add_argument('--dry-run', action='store_true', help='Validate without writing')
    parser.add_argument('--migrate', action='store_true', help='Perform actual migration')
    parser.add_argument('--validate', action='store_true', help='Validate database contents')
    args = parser.parse_args()

    if not any([args.dry_run, args.migrate, args.validate]):
        parser.print_help()
        print("\nPlease specify --dry-run, --migrate, or --validate")
        sys.exit(1)

    # Get database connection info
    db_host = os.getenv('DB_HOST', 'localhost')
    db_port = int(os.getenv('DB_PORT', 5432))
    db_name = os.getenv('DB_NAME', 'tausendsassa')
    db_user = os.getenv('DB_USER', 'tausendsassa')
    db_password = os.getenv('DB_PASSWORD', '')

    print(f"Connecting to database: {db_host}:{db_port}/{db_name}")

    try:
        pool = await asyncpg.create_pool(
            host=db_host,
            port=db_port,
            database=db_name,
            user=db_user,
            password=db_password,
            min_size=1,
            max_size=5
        )
    except Exception as e:
        print(f"Failed to connect to database: {e}")
        sys.exit(1)

    try:
        if args.dry_run:
            runner = MigrationRunner(pool, dry_run=True)
            await runner.migrate_all()

        elif args.migrate:
            runner = MigrationRunner(pool, dry_run=False)
            await runner.migrate_all()

        if args.validate or args.migrate:
            await validate_database(pool)

    finally:
        await pool.close()


if __name__ == '__main__':
    asyncio.run(main())
