"""
Data models for the Tausendsassa database.
Uses dataclasses for type safety and easy serialization.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any
import json


@dataclass
class Guild:
    """Discord guild (server) base information."""
    id: int
    name: Optional[str] = None
    joined_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def from_record(cls, record) -> 'Guild':
        return cls(
            id=record['id'],
            name=record.get('name'),
            joined_at=record.get('joined_at'),
            created_at=record.get('created_at'),
            updated_at=record.get('updated_at'),
        )


@dataclass
class GuildTimezone:
    """Per-guild timezone setting."""
    guild_id: int
    timezone: str = 'Europe/Berlin'

    @classmethod
    def from_record(cls, record) -> 'GuildTimezone':
        return cls(
            guild_id=record['guild_id'],
            timezone=record['timezone'],
        )


@dataclass
class ModerationConfig:
    """Moderation settings per guild."""
    guild_id: int
    member_log_webhook: Optional[str] = None
    join_role_id: Optional[int] = None

    @classmethod
    def from_record(cls, record) -> 'ModerationConfig':
        return cls(
            guild_id=record['guild_id'],
            member_log_webhook=record.get('member_log_webhook'),
            join_role_id=record.get('join_role_id'),
        )


@dataclass
class Feed:
    """RSS/Atom feed configuration."""
    id: Optional[int] = None
    guild_id: int = 0
    name: str = ''
    feed_url: str = ''
    channel_id: int = 0
    webhook_url: Optional[str] = None
    username: Optional[str] = None
    avatar_url: Optional[str] = None
    color: Optional[int] = None
    max_items: int = 3
    crosspost: bool = False
    embed_template: Optional[Dict[str, Any]] = None
    enabled: bool = True
    failure_count: int = 0
    last_success: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def from_record(cls, record) -> 'Feed':
        embed_template = record.get('embed_template')
        if isinstance(embed_template, str):
            embed_template = json.loads(embed_template)

        return cls(
            id=record['id'],
            guild_id=record['guild_id'],
            name=record['name'],
            feed_url=record['feed_url'],
            channel_id=record['channel_id'],
            webhook_url=record.get('webhook_url'),
            username=record.get('username'),
            avatar_url=record.get('avatar_url'),
            color=record.get('color'),
            max_items=record.get('max_items', 3),
            crosspost=record.get('crosspost', False),
            embed_template=embed_template,
            enabled=record.get('enabled', True),
            failure_count=record.get('failure_count', 0),
            last_success=record.get('last_success'),
            created_at=record.get('created_at'),
            updated_at=record.get('updated_at'),
        )

    def to_feed_cfg(self) -> Dict[str, Any]:
        """Convert to the format expected by feeds_rss.poll()."""
        return {
            'name': self.name,
            'feed_url': self.feed_url,
            'channel_id': self.channel_id,
            'max_items': self.max_items,
            'embed_template': self.embed_template or {},
            'color': self.color,
        }


@dataclass
class PostedEntry:
    """Tracks posted feed entries."""
    id: Optional[int] = None
    guild_id: int = 0
    guid: str = ''
    message_id: Optional[int] = None
    channel_id: Optional[int] = None
    content_hash: Optional[str] = None
    posted_at: Optional[datetime] = None

    @classmethod
    def from_record(cls, record) -> 'PostedEntry':
        return cls(
            id=record.get('id'),
            guild_id=record['guild_id'],
            guid=record['guid'],
            message_id=record.get('message_id'),
            channel_id=record.get('channel_id'),
            content_hash=record.get('content_hash'),
            posted_at=record.get('posted_at'),
        )


@dataclass
class Calendar:
    """iCal calendar configuration."""
    id: Optional[int] = None
    guild_id: int = 0
    calendar_id: str = ''
    text_channel_id: int = 0
    voice_channel_id: int = 0
    ical_url: str = ''
    blacklist: List[str] = field(default_factory=list)
    whitelist: List[str] = field(default_factory=list)
    reminder_role_id: Optional[int] = None
    last_message_id: Optional[int] = None
    current_week_start: Optional[datetime] = None
    last_sync: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def from_record(cls, record) -> 'Calendar':
        return cls(
            id=record['id'],
            guild_id=record['guild_id'],
            calendar_id=record['calendar_id'],
            text_channel_id=record['text_channel_id'],
            voice_channel_id=record['voice_channel_id'],
            ical_url=record['ical_url'],
            blacklist=list(record.get('blacklist') or []),
            whitelist=list(record.get('whitelist') or []),
            reminder_role_id=record.get('reminder_role_id'),
            last_message_id=record.get('last_message_id'),
            current_week_start=record.get('current_week_start'),
            last_sync=record.get('last_sync'),
            created_at=record.get('created_at'),
            updated_at=record.get('updated_at'),
        )


@dataclass
class CalendarEvent:
    """Discord event created from calendar."""
    id: Optional[int] = None
    calendar_pk: int = 0
    event_title: str = ''
    discord_event_id: int = 0
    created_at: Optional[datetime] = None

    @classmethod
    def from_record(cls, record) -> 'CalendarEvent':
        return cls(
            id=record.get('id'),
            calendar_pk=record['calendar_pk'],
            event_title=record['event_title'],
            discord_event_id=record['discord_event_id'],
            created_at=record.get('created_at'),
        )


@dataclass
class CalendarReminder:
    """Sent calendar reminder tracking."""
    id: Optional[int] = None
    calendar_pk: int = 0
    reminder_key: str = ''
    sent_at: Optional[datetime] = None

    @classmethod
    def from_record(cls, record) -> 'CalendarReminder':
        return cls(
            id=record.get('id'),
            calendar_pk=record['calendar_pk'],
            reminder_key=record['reminder_key'],
            sent_at=record.get('sent_at'),
        )


@dataclass
class MapSettings:
    """Map visual settings per guild."""
    guild_id: int
    region: str = 'world'
    channel_id: Optional[int] = None
    message_id: Optional[int] = None
    settings: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def from_record(cls, record) -> 'MapSettings':
        settings = record.get('settings')
        if isinstance(settings, str):
            settings = json.loads(settings)
        return cls(
            guild_id=record['guild_id'],
            region=record.get('region', 'world'),
            channel_id=record.get('channel_id'),
            message_id=record.get('message_id'),
            settings=settings or {},
            created_at=record.get('created_at'),
            updated_at=record.get('updated_at'),
        )


@dataclass
class MapPin:
    """User location pin on guild map."""
    id: Optional[int] = None
    guild_id: int = 0
    user_id: int = 0
    username: Optional[str] = None
    display_name: Optional[str] = None
    location: Optional[str] = None
    latitude: float = 0.0
    longitude: float = 0.0
    color: str = '#FF0000'
    pinned_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def from_record(cls, record) -> 'MapPin':
        return cls(
            id=record.get('id'),
            guild_id=record['guild_id'],
            user_id=record['user_id'],
            username=record.get('username'),
            display_name=record.get('display_name'),
            location=record.get('location'),
            latitude=record['latitude'],
            longitude=record['longitude'],
            color=record.get('color', '#FF0000'),
            pinned_at=record.get('pinned_at'),
            updated_at=record.get('updated_at'),
        )


@dataclass
class WebhookCache:
    """Cached Discord webhook information."""
    channel_id: int
    webhook_id: int
    webhook_token: str
    webhook_name: Optional[str] = None
    created_at: Optional[datetime] = None

    @classmethod
    def from_record(cls, record) -> 'WebhookCache':
        return cls(
            channel_id=record['channel_id'],
            webhook_id=record['webhook_id'],
            webhook_token=record['webhook_token'],
            webhook_name=record.get('webhook_name'),
            created_at=record.get('created_at'),
        )


@dataclass
class FeedCache:
    """HTTP cache for feed requests."""
    url: str
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    content_hash: Optional[str] = None
    last_check: Optional[datetime] = None

    @classmethod
    def from_record(cls, record) -> 'FeedCache':
        return cls(
            url=record['url'],
            etag=record.get('etag'),
            last_modified=record.get('last_modified'),
            content_hash=record.get('content_hash'),
            last_check=record.get('last_check'),
        )


@dataclass
class MonitorMessage:
    """Monitor message tracking."""
    id: Optional[int] = None
    channel_id: int = 0
    message_id: int = 0
    monitor_type: str = ''
    auto_update_interval: int = 300
    last_update: Optional[datetime] = None
    created_at: Optional[datetime] = None

    @classmethod
    def from_record(cls, record) -> 'MonitorMessage':
        return cls(
            id=record.get('id'),
            channel_id=record['channel_id'],
            message_id=record['message_id'],
            monitor_type=record['monitor_type'],
            auto_update_interval=record.get('auto_update_interval', 300),
            last_update=record.get('last_update'),
            created_at=record.get('created_at'),
        )
