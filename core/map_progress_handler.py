"""
Centralized progress handler for map rendering operations.

This module provides a unified interface for handling progress updates
during map generation, including embed updates and intermediate image displays.
"""

import discord
from typing import Optional, Callable
from datetime import datetime
import asyncio


class MapProgressHandler:
    """Centralized handler for map rendering progress updates."""
    
    def __init__(self, interaction: discord.Interaction, map_type: str, logger, message=None, region: str = None, hide_final_image: bool = False):
        """
        Initialize the progress handler.
        
        Args:
            interaction: Discord interaction to update (used for edit_original_response)
            map_type: Type of map being rendered (e.g., "Close-up", "Preview", "Proximity")
            logger: Logger instance for error reporting
            message: Optional Discord message to edit (used for followup messages)
            region: Optional region code for emoji selection (e.g., "france", "germany")
            hide_final_image: If True, don't show the final image at 100% (to avoid duplication with public channel posts)
        """
        self.interaction = interaction
        self.map_type = map_type
        self.logger = logger
        self.message = message  # For followup messages like server maps
        self.region = region  # Store region for emoji selection
        self.hide_final_image = hide_final_image  # Prevent final image display
        self._last_update = 0
        self._update_lock = asyncio.Lock()
        self._current_image = None  # Store current image to retain until replaced
        self._current_percentage = 0
    
    async def update_progress(self, message: str, percentage: int, image_buffer: Optional = None) -> None:
        """
        Update the ephemeral response with progress information.
        
        Args:
            message: Progress message to display
            percentage: Progress percentage (0-100)
            image_buffer: Optional image buffer to display as attachment
        """
        async with self._update_lock:
            try:
                # Rate limit updates to avoid Discord API limits
                current_time = asyncio.get_event_loop().time()
                if current_time - self._last_update < 0.5 and percentage < 100:  # 500ms throttle, except for final update
                    return
                self._last_update = current_time
                
                # Update stored image if a new one is provided
                if image_buffer is not None:
                    self._current_image = image_buffer
                    self._current_percentage = percentage
                
                # Determine emoji based on region
                emoji = self._get_region_emoji()
                
                # Create progress embed
                progress_embed = discord.Embed(
                    title=f"{emoji} Generating {self.map_type}",
                    description=f"{message} ({percentage}%)",
                    color=0x7289da
                )
                
                # Add progress bar visual
                progress_bar = self._create_progress_bar(percentage)
                progress_embed.add_field(name="Progress", value=progress_bar, inline=False)
                
                # Add timestamp
                progress_embed.timestamp = datetime.utcnow()
                
                # Use the most recent image if available, including at 100% completion
                # Show the final image at 100% to display the completed map (unless hide_final_image is True)
                if self._current_image and not (self.hide_final_image and percentage == 100):
                    self._current_image.seek(0)
                    file = discord.File(self._current_image, filename=f"progress_{self._current_percentage}.png")
                    progress_embed.set_image(url=f"attachment://progress_{self._current_percentage}.png")
                    
                    # Use message.edit for followup messages, interaction.edit_original_response for ephemeral responses
                    if self.message:
                        await self.message.edit(content=None, embed=progress_embed, attachments=[file])
                    else:
                        await self.interaction.edit_original_response(
                            content=None, 
                            embed=progress_embed, 
                            attachments=[file]
                        )
                else:
                    # No image or completion reached - clear attachments
                    # Use message.edit for followup messages, interaction.edit_original_response for ephemeral responses
                    if self.message:
                        await self.message.edit(content=None, embed=progress_embed, attachments=[])
                    else:
                        await self.interaction.edit_original_response(
                            content=None, 
                            embed=progress_embed, 
                            attachments=[]
                        )
                    
            except Exception as e:
                self.logger.warning(f"Failed to update progress message: {e}")
    
    def _get_region_emoji(self) -> str:
        """Get appropriate emoji for the region being rendered."""
        if not self.region:
            return "🌍"  # Default world emoji
        
        # Import here to avoid circular imports
        try:
            from core.map_config import MapConfig
            config = MapConfig()
            
            # Check if it's a German state first
            if self.region in config.GERMAN_STATES:
                state_data = config.GERMAN_STATES[self.region]
                emoji_id = state_data.get('emoji_id')
                if emoji_id:
                    return f"<:coat_{state_data.get('short', 'state').lower()}:{emoji_id}>"
                return "🏛️"  # Fallback for German states
            
            # Otherwise use country flag emojis
            return config.COUNTRY_FLAG_EMOJIS.get(self.region, "🌍")
        except ImportError:
            return "🌍"  # Fallback
    
    def _create_progress_bar(self, percentage: int) -> str:
        """Create a visual progress bar using Unicode blocks."""
        filled = int(percentage / 5)  # 20 blocks total (100/5)
        empty = 20 - filled
        return f"{'█' * filled}{'░' * empty} {percentage}%"
    
    def create_callback(self) -> Callable:
        """
        Create a callback function compatible with existing map generation functions.
        
        Returns:
            Async callback function that can be passed to map generation methods
        """
        async def progress_callback(message: str, percentage: int, image_buffer: Optional = None) -> None:
            await self.update_progress(message, percentage, image_buffer)
        
        return progress_callback


class MapProgressHandlerFactory:
    """Factory for creating map progress handlers."""
    
    @staticmethod
    def create_server_map_handler(interaction: discord.Interaction, logger, message=None, hide_final_image: bool = False) -> MapProgressHandler:
        """Create progress handler for server map generation."""
        return MapProgressHandler(interaction, "Server Map", logger, message, hide_final_image=hide_final_image)
    
    @staticmethod
    def create_closeup_handler(interaction: discord.Interaction, continent: str, logger) -> MapProgressHandler:
        """Create progress handler for continent closeup generation."""
        return MapProgressHandler(interaction, f"{continent} Close-up", logger, region=continent)
    
    @staticmethod
    def create_proximity_handler(interaction: discord.Interaction, logger) -> MapProgressHandler:
        """Create progress handler for proximity map generation."""
        return MapProgressHandler(interaction, "Proximity Map", logger)
    
    @staticmethod
    def create_preview_handler(interaction: discord.Interaction, logger) -> MapProgressHandler:
        """Create progress handler for map preview generation."""
        return MapProgressHandler(interaction, "Map Preview", logger)


# Convenience functions for backward compatibility and easy usage
async def create_server_map_progress_callback(interaction: discord.Interaction, logger, message=None, hide_final_image: bool = False) -> Callable:
    """Create a progress callback for server map generation."""
    handler = MapProgressHandlerFactory.create_server_map_handler(interaction, logger, message, hide_final_image)
    return handler.create_callback()


async def create_closeup_progress_callback(interaction: discord.Interaction, continent: str, logger) -> Callable:
    """Create a progress callback for continent closeup generation."""
    handler = MapProgressHandlerFactory.create_closeup_handler(interaction, continent, logger)
    return handler.create_callback()


async def create_proximity_progress_callback(interaction: discord.Interaction, logger) -> Callable:
    """Create a progress callback for proximity map generation."""
    handler = MapProgressHandlerFactory.create_proximity_handler(interaction, logger)
    return handler.create_callback()


async def create_preview_progress_callback(interaction: discord.Interaction, logger) -> Callable:
    """Create a progress callback for map preview generation."""
    handler = MapProgressHandlerFactory.create_preview_handler(interaction, logger)
    return handler.create_callback()