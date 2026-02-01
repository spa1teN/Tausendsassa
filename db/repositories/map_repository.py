"""
Repository for map operations.
"""

from typing import List, Optional, Dict, Any
from datetime import datetime
import json

from db.repositories.base import BaseRepository
from db.models import MapSettings, MapPin


class MapRepository(BaseRepository):
    """Repository for map database operations."""

    # ==========================================
    # Map Settings
    # ==========================================

    async def get_settings(self, guild_id: int) -> Optional[MapSettings]:
        """Get map settings for a guild."""
        row = await self.fetchrow(
            "SELECT * FROM map_settings WHERE guild_id = $1",
            guild_id
        )
        return MapSettings.from_record(row) if row else None

    async def get_or_create_settings(self, guild_id: int) -> MapSettings:
        """Get or create map settings for a guild."""
        row = await self.fetchrow(
            """INSERT INTO map_settings (guild_id)
               VALUES ($1)
               ON CONFLICT (guild_id) DO UPDATE SET updated_at = NOW()
               RETURNING *""",
            guild_id
        )
        return MapSettings.from_record(row)

    async def update_settings(self, guild_id: int, **kwargs) -> Optional[MapSettings]:
        """Update map settings."""
        if not kwargs:
            return await self.get_settings(guild_id)

        # Handle settings JSON conversion
        if 'settings' in kwargs and kwargs['settings'] is not None:
            if not isinstance(kwargs['settings'], str):
                kwargs['settings'] = json.dumps(kwargs['settings'])

        set_parts = []
        values = []
        for i, (key, value) in enumerate(kwargs.items(), start=1):
            set_parts.append(f"{key} = ${i}")
            values.append(value)

        values.append(guild_id)
        query = f"""UPDATE map_settings SET {', '.join(set_parts)}, updated_at = NOW()
                    WHERE guild_id = ${len(values)} RETURNING *"""

        row = await self.fetchrow(query, *values)
        return MapSettings.from_record(row) if row else None

    async def set_region(self, guild_id: int, region: str) -> None:
        """Set the map region."""
        await self.execute(
            """INSERT INTO map_settings (guild_id, region)
               VALUES ($1, $2)
               ON CONFLICT (guild_id) DO UPDATE SET region = $2, updated_at = NOW()""",
            guild_id, region
        )

    async def set_visual_settings(self, guild_id: int, settings: Dict[str, Any]) -> None:
        """Set visual settings (colors, borders, pins)."""
        settings_json = json.dumps(settings) if not isinstance(settings, str) else settings
        await self.execute(
            """INSERT INTO map_settings (guild_id, settings)
               VALUES ($1, $2)
               ON CONFLICT (guild_id) DO UPDATE SET settings = $2, updated_at = NOW()""",
            guild_id, settings_json
        )

    async def delete_settings(self, guild_id: int) -> bool:
        """Delete map settings and all pins for a guild."""
        result = await self.execute(
            "DELETE FROM map_settings WHERE guild_id = $1",
            guild_id
        )
        return result == "DELETE 1"

    async def has_map(self, guild_id: int) -> bool:
        """Check if a guild has a map configured."""
        result = await self.fetchval(
            "SELECT EXISTS(SELECT 1 FROM map_settings WHERE guild_id = $1)",
            guild_id
        )
        return result

    # ==========================================
    # Map Pins
    # ==========================================

    async def get_pins(self, guild_id: int) -> List[MapPin]:
        """Get all pins for a guild."""
        rows = await self.fetch(
            "SELECT * FROM map_pins WHERE guild_id = $1 ORDER BY pinned_at",
            guild_id
        )
        return [MapPin.from_record(row) for row in rows]

    async def get_pin(self, guild_id: int, user_id: int) -> Optional[MapPin]:
        """Get a specific pin by user."""
        row = await self.fetchrow(
            "SELECT * FROM map_pins WHERE guild_id = $1 AND user_id = $2",
            guild_id, user_id
        )
        return MapPin.from_record(row) if row else None

    async def get_pins_dict(self, guild_id: int) -> Dict[str, Dict[str, Any]]:
        """Get all pins as a dictionary (user_id -> pin data)."""
        rows = await self.fetch(
            "SELECT * FROM map_pins WHERE guild_id = $1",
            guild_id
        )
        result = {}
        for row in rows:
            user_id = str(row['user_id'])
            result[user_id] = {
                'username': row['username'],
                'display_name': row['display_name'],
                'location': row['location'],
                'lat': row['latitude'],
                'lng': row['longitude'],
                'color': row['color'],
                'avatar_hash': row['avatar_hash'],
                'timestamp': row['pinned_at'].isoformat() if row['pinned_at'] else None,
            }
        return result

    async def set_pin(
        self,
        guild_id: int,
        user_id: int,
        latitude: float,
        longitude: float,
        username: str = None,
        display_name: str = None,
        location: str = None,
        color: str = '#FF0000',
        avatar_hash: str = None
    ) -> MapPin:
        """Set or update a pin for a user."""
        row = await self.fetchrow(
            """INSERT INTO map_pins
               (guild_id, user_id, latitude, longitude, username, display_name, location, color, avatar_hash)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
               ON CONFLICT (guild_id, user_id) DO UPDATE SET
                   latitude = $3,
                   longitude = $4,
                   username = COALESCE($5, map_pins.username),
                   display_name = COALESCE($6, map_pins.display_name),
                   location = COALESCE($7, map_pins.location),
                   color = COALESCE($8, map_pins.color),
                   avatar_hash = COALESCE($9, map_pins.avatar_hash),
                   updated_at = NOW()
               RETURNING *""",
            guild_id, user_id, latitude, longitude, username, display_name, location, color, avatar_hash
        )
        return MapPin.from_record(row)

    async def update_pin_color(self, guild_id: int, user_id: int, color: str) -> bool:
        """Update pin color."""
        result = await self.execute(
            "UPDATE map_pins SET color = $3, updated_at = NOW() WHERE guild_id = $1 AND user_id = $2",
            guild_id, user_id, color
        )
        return result == "UPDATE 1"

    async def delete_pin(self, guild_id: int, user_id: int) -> bool:
        """Delete a pin."""
        result = await self.execute(
            "DELETE FROM map_pins WHERE guild_id = $1 AND user_id = $2",
            guild_id, user_id
        )
        return result == "DELETE 1"

    async def delete_all_pins(self, guild_id: int) -> int:
        """Delete all pins for a guild."""
        result = await self.execute(
            "DELETE FROM map_pins WHERE guild_id = $1",
            guild_id
        )
        try:
            return int(result.split()[-1])
        except (ValueError, IndexError):
            return 0

    async def count_pins(self, guild_id: int) -> int:
        """Count pins for a guild."""
        result = await self.fetchval(
            "SELECT COUNT(*) FROM map_pins WHERE guild_id = $1",
            guild_id
        )
        return result or 0

    # ==========================================
    # Global Map Config
    # ==========================================

    async def get_global_config(self, key: str) -> Optional[Any]:
        """Get a global config value."""
        row = await self.fetchrow(
            "SELECT value FROM map_global_config WHERE key = $1",
            key
        )
        if row:
            value = row['value']
            return json.loads(value) if isinstance(value, str) else value
        return None

    async def set_global_config(self, key: str, value: Any) -> None:
        """Set a global config value."""
        value_json = json.dumps(value) if not isinstance(value, str) else value
        await self.execute(
            """INSERT INTO map_global_config (key, value)
               VALUES ($1, $2)
               ON CONFLICT (key) DO UPDATE SET value = $2, updated_at = NOW()""",
            key, value_json
        )

    async def get_all_global_config(self) -> Dict[str, Any]:
        """Get all global config as a dictionary."""
        rows = await self.fetch("SELECT key, value FROM map_global_config")
        result = {}
        for row in rows:
            value = row['value']
            result[row['key']] = json.loads(value) if isinstance(value, str) else value
        return result

    # ==========================================
    # Bulk Operations for Migration
    # ==========================================

    async def load_all_maps(self) -> Dict[str, Dict[str, Any]]:
        """Load all map data in the format used by MapStorage.load_all_data()."""
        maps = {}

        # Get all settings
        settings_rows = await self.fetch("SELECT * FROM map_settings")

        for settings_row in settings_rows:
            guild_id = str(settings_row['guild_id'])

            # Get pins for this guild
            pins = await self.get_pins_dict(int(guild_id))

            settings = settings_row['settings']
            if isinstance(settings, str):
                settings = json.loads(settings)
            settings = settings or {}

            # Extract meta fields from settings JSON (stored there for flexibility)
            allow_proximity = settings.pop('allow_proximity', True)
            created_by = settings.pop('created_by', None)
            created_at = settings.pop('created_at', None) or (
                settings_row['created_at'].isoformat() if settings_row['created_at'] else None
            )

            maps[guild_id] = {
                'region': settings_row['region'],
                'channel_id': settings_row['channel_id'],
                'message_id': settings_row['message_id'],
                'pins': pins,
                'settings': settings,  # Visual settings (colors, borders, pins)
                'allow_proximity': allow_proximity,
                'created_by': created_by,
                'created_at': created_at,
            }

        return maps

    async def save_map_data(self, guild_id: int, data: Dict[str, Any]) -> None:
        """Save complete map data (used for migration and general saves)."""
        # Prepare settings JSON - includes visual settings and meta fields
        settings = dict(data.get('settings', {}))  # Copy visual settings

        # Add meta fields to settings JSON for storage
        if 'allow_proximity' in data:
            settings['allow_proximity'] = data['allow_proximity']
        if 'created_by' in data:
            settings['created_by'] = data['created_by']
        if 'created_at' in data:
            settings['created_at'] = data['created_at']

        await self.execute(
            """INSERT INTO map_settings (guild_id, region, channel_id, message_id, settings)
               VALUES ($1, $2, $3, $4, $5)
               ON CONFLICT (guild_id) DO UPDATE SET
                   region = $2,
                   channel_id = $3,
                   message_id = $4,
                   settings = $5,
                   updated_at = NOW()""",
            guild_id,
            data.get('region', 'world'),
            data.get('channel_id'),
            data.get('message_id'),
            json.dumps(settings)
        )

        # Save pins (only if there are new pins to save)
        pins = data.get('pins', {})
        for user_id_str, pin_data in pins.items():
            user_id = int(user_id_str)
            await self.set_pin(
                guild_id=guild_id,
                user_id=user_id,
                latitude=pin_data['lat'],
                longitude=pin_data['lng'],
                username=pin_data.get('username'),
                display_name=pin_data.get('display_name'),
                location=pin_data.get('location'),
                color=pin_data.get('color', '#FF0000'),
                avatar_hash=pin_data.get('avatar_hash')
            )
