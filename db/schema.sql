-- Tausendsassa Discord Bot - PostgreSQL Schema
-- Version: 1.0.0
-- Created: 2026-01-31

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================
-- CORE TABLES
-- ============================================

-- Guilds (Discord Servers)
CREATE TABLE IF NOT EXISTS guilds (
    id              BIGINT PRIMARY KEY,     -- Discord Guild ID
    name            VARCHAR(255),
    icon_hash       VARCHAR(64),            -- Discord icon hash for CDN URL
    member_count    INTEGER DEFAULT 0,      -- Total member count
    joined_at       TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Guild timezone configuration
CREATE TABLE IF NOT EXISTS guild_timezones (
    guild_id        BIGINT PRIMARY KEY REFERENCES guilds(id) ON DELETE CASCADE,
    timezone        VARCHAR(64) NOT NULL DEFAULT 'Europe/Berlin',
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================
-- MODERATION
-- ============================================

-- Moderation configuration per guild
CREATE TABLE IF NOT EXISTS moderation_config (
    guild_id            BIGINT PRIMARY KEY REFERENCES guilds(id) ON DELETE CASCADE,
    member_log_webhook  TEXT,
    join_role_id        BIGINT,
    created_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================
-- RSS FEEDS
-- ============================================

-- RSS Feed configurations
CREATE TABLE IF NOT EXISTS feeds (
    id                  SERIAL PRIMARY KEY,
    guild_id            BIGINT NOT NULL REFERENCES guilds(id) ON DELETE CASCADE,
    name                VARCHAR(255) NOT NULL,
    feed_url            TEXT NOT NULL,
    channel_id          BIGINT NOT NULL,
    webhook_url         TEXT,
    username            VARCHAR(255),
    avatar_url          TEXT,
    color               INTEGER,
    max_items           INTEGER DEFAULT 3,
    crosspost           BOOLEAN DEFAULT FALSE,
    embed_template      JSONB,
    enabled             BOOLEAN DEFAULT TRUE,
    failure_count       INTEGER DEFAULT 0,
    last_success        TIMESTAMP WITH TIME ZONE,
    created_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(guild_id, name)
);

-- Monitor channel per guild (from feed_config.yaml)
CREATE TABLE IF NOT EXISTS feed_monitor_channels (
    guild_id            BIGINT PRIMARY KEY REFERENCES guilds(id) ON DELETE CASCADE,
    channel_id          BIGINT NOT NULL,
    created_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Posted feed entries (deduplication)
CREATE TABLE IF NOT EXISTS posted_entries (
    id                  SERIAL PRIMARY KEY,
    guild_id            BIGINT NOT NULL REFERENCES guilds(id) ON DELETE CASCADE,
    feed_id             INTEGER REFERENCES feeds(id) ON DELETE SET NULL,
    guid                TEXT NOT NULL,
    message_id          BIGINT,
    channel_id          BIGINT,
    content_hash        VARCHAR(32),
    posted_at           TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(guild_id, guid)
);

-- Global: Feed HTTP cache
CREATE TABLE IF NOT EXISTS feed_cache (
    url                 TEXT PRIMARY KEY,
    etag                TEXT,
    last_modified       TEXT,
    content_hash        VARCHAR(32),
    last_check          TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Global: Entry content hashes for change detection
CREATE TABLE IF NOT EXISTS entry_hashes (
    guid                TEXT PRIMARY KEY,
    content_hash        VARCHAR(32) NOT NULL,
    created_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Global: Webhook cache
CREATE TABLE IF NOT EXISTS webhook_cache (
    channel_id          BIGINT PRIMARY KEY,
    webhook_id          BIGINT NOT NULL,
    webhook_token       TEXT NOT NULL,
    webhook_name        VARCHAR(255),
    created_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================
-- CALENDARS
-- ============================================

-- Calendar configurations
CREATE TABLE IF NOT EXISTS calendars (
    id                  SERIAL PRIMARY KEY,
    guild_id            BIGINT NOT NULL REFERENCES guilds(id) ON DELETE CASCADE,
    calendar_id         VARCHAR(255) NOT NULL,  -- User-defined identifier
    text_channel_id     BIGINT NOT NULL,
    voice_channel_id    BIGINT NOT NULL,
    ical_url            TEXT NOT NULL,
    blacklist           TEXT[] DEFAULT '{}',
    whitelist           TEXT[] DEFAULT '{}',
    reminder_role_id    BIGINT,
    last_message_id     BIGINT,
    current_week_start  TIMESTAMP WITH TIME ZONE,
    last_sync           TIMESTAMP WITH TIME ZONE,
    created_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(guild_id, calendar_id)
);

-- Calendar Discord events tracking
CREATE TABLE IF NOT EXISTS calendar_events (
    id                  SERIAL PRIMARY KEY,
    calendar_pk         INTEGER NOT NULL REFERENCES calendars(id) ON DELETE CASCADE,
    event_title         VARCHAR(255) NOT NULL,
    discord_event_id    BIGINT NOT NULL,
    created_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Calendar reminders tracking
CREATE TABLE IF NOT EXISTS calendar_reminders (
    id                  SERIAL PRIMARY KEY,
    calendar_pk         INTEGER NOT NULL REFERENCES calendars(id) ON DELETE CASCADE,
    reminder_key        VARCHAR(512) NOT NULL,
    sent_at             TIMESTAMP WITH TIME ZONE NOT NULL,
    UNIQUE(calendar_pk, reminder_key)
);

-- ============================================
-- MAPS
-- ============================================

-- Map settings per guild
CREATE TABLE IF NOT EXISTS map_settings (
    guild_id            BIGINT PRIMARY KEY REFERENCES guilds(id) ON DELETE CASCADE,
    region              VARCHAR(64) DEFAULT 'world',
    channel_id          BIGINT,
    message_id          BIGINT,
    settings            JSONB DEFAULT '{}',  -- colors, borders, pins visual settings
    created_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Map pins per guild
CREATE TABLE IF NOT EXISTS map_pins (
    id                  SERIAL PRIMARY KEY,
    guild_id            BIGINT NOT NULL REFERENCES guilds(id) ON DELETE CASCADE,
    user_id             BIGINT NOT NULL,
    username            VARCHAR(255),
    display_name        VARCHAR(255),
    avatar_hash         VARCHAR(64),            -- Discord avatar hash for CDN URL
    location            VARCHAR(255),
    latitude            DOUBLE PRECISION NOT NULL,
    longitude           DOUBLE PRECISION NOT NULL,
    color               VARCHAR(7) DEFAULT '#FF0000',
    pinned_at           TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(guild_id, user_id)
);

-- Global: Map global configuration
CREATE TABLE IF NOT EXISTS map_global_config (
    key                 VARCHAR(64) PRIMARY KEY,
    value               JSONB NOT NULL,
    created_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================
-- MONITORING
-- ============================================

-- Monitor message tracking
CREATE TABLE IF NOT EXISTS monitor_messages (
    id                  SERIAL PRIMARY KEY,
    channel_id          BIGINT NOT NULL,
    message_id          BIGINT NOT NULL,
    monitor_type        VARCHAR(50) NOT NULL,  -- 'system' or 'server'
    auto_update_interval INTEGER DEFAULT 300,
    last_update         TIMESTAMP WITH TIME ZONE,
    created_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(channel_id, monitor_type)
);

-- ============================================
-- INDEXES FOR PERFORMANCE
-- ============================================

-- Feeds indexes
CREATE INDEX IF NOT EXISTS idx_feeds_guild ON feeds(guild_id);
CREATE INDEX IF NOT EXISTS idx_feeds_guild_enabled ON feeds(guild_id, enabled);

-- Posted entries indexes
CREATE INDEX IF NOT EXISTS idx_posted_entries_guild ON posted_entries(guild_id);
CREATE INDEX IF NOT EXISTS idx_posted_entries_guild_guid ON posted_entries(guild_id, guid);
CREATE INDEX IF NOT EXISTS idx_posted_entries_posted_at ON posted_entries(posted_at);
CREATE INDEX IF NOT EXISTS idx_posted_entries_feed ON posted_entries(feed_id);

-- Calendar indexes
CREATE INDEX IF NOT EXISTS idx_calendars_guild ON calendars(guild_id);
CREATE INDEX IF NOT EXISTS idx_calendar_events_calendar ON calendar_events(calendar_pk);
CREATE INDEX IF NOT EXISTS idx_calendar_reminders_calendar ON calendar_reminders(calendar_pk);

-- Map indexes
CREATE INDEX IF NOT EXISTS idx_map_pins_guild ON map_pins(guild_id);
CREATE INDEX IF NOT EXISTS idx_map_pins_user ON map_pins(user_id);

-- ============================================
-- TRIGGER FOR updated_at
-- ============================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Apply trigger to tables with updated_at
DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['guilds', 'guild_timezones', 'moderation_config',
                              'feeds', 'calendars', 'map_settings', 'map_pins',
                              'map_global_config']
    LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS update_%s_updated_at ON %s', t, t);
        EXECUTE format('CREATE TRIGGER update_%s_updated_at
                        BEFORE UPDATE ON %s
                        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column()', t, t);
    END LOOP;
END $$;

-- ============================================
-- COMMENTS FOR DOCUMENTATION
-- ============================================

COMMENT ON TABLE guilds IS 'Discord server (guild) base information';
COMMENT ON TABLE guild_timezones IS 'Per-guild timezone settings';
COMMENT ON TABLE moderation_config IS 'Moderation settings per guild (webhook, join role)';
COMMENT ON TABLE feeds IS 'RSS/Atom feed configurations';
COMMENT ON TABLE posted_entries IS 'Tracks posted feed entries to prevent duplicates';
COMMENT ON TABLE feed_cache IS 'HTTP caching for feed requests (ETag, Last-Modified)';
COMMENT ON TABLE entry_hashes IS 'Content hashes for feed entry change detection';
COMMENT ON TABLE webhook_cache IS 'Cached Discord webhook information per channel';
COMMENT ON TABLE calendars IS 'iCal calendar configurations';
COMMENT ON TABLE calendar_events IS 'Tracks Discord events created from calendar entries';
COMMENT ON TABLE calendar_reminders IS 'Tracks sent calendar reminders';
COMMENT ON TABLE map_settings IS 'Map visual settings and configuration per guild';
COMMENT ON TABLE map_pins IS 'User location pins on guild maps';
COMMENT ON TABLE map_global_config IS 'Global map configuration (key-value store)';
COMMENT ON TABLE monitor_messages IS 'Tracks monitor embed messages for auto-updates';
