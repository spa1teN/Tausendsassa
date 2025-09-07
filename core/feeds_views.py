# core/feeds_views.py

from typing import List
import discord
from discord import app_commands

def _is_bluesky_feed_url(url: str) -> bool:
    """Check if the given URL is a Bluesky profile feed"""
    return "bsky.app/profile/" in url

class FeedRemoveView(discord.ui.View):
    """View for feed removal with dropdown selection"""
    def __init__(self, feeds: List[dict], cog, guild_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        
        # Create dropdown options
        options = []
        for feed in feeds[:25]:  # Discord limit
            options.append(discord.SelectOption(
                label=feed["name"],
                description=f"URL: {feed['feed_url'][:50]}..." if len(feed['feed_url']) > 50 else feed['feed_url'],
                value=feed["name"]
            ))
        
        if options:
            select = FeedRemoveSelect(options, cog, guild_id)
            self.add_item(select)

class FeedRemoveSelect(discord.ui.Select):
    """Select dropdown for feed removal"""
    def __init__(self, options: List[discord.SelectOption], cog, guild_id: int):
        super().__init__(
            placeholder="Choose a feed to remove...",
            options=options,
            min_values=1,
            max_values=1
        )
        self.cog = cog
        self.guild_id = guild_id
    
    async def callback(self, interaction: discord.Interaction):
        feed_name = self.values[0]
        
        # Remove the feed
        config = self.cog._load_guild_config(self.guild_id)
        old_feeds = config.get("feeds", [])
        new_feeds = [f for f in old_feeds if f.get("name") != feed_name]
        
        config["feeds"] = new_feeds
        self.cog._save_guild_config(self.guild_id, config)
        
        # Update runtime config and stats
        self.cog.guild_configs[self.guild_id] = config
        if self.guild_id in self.cog.stats:
            self.cog.stats[self.guild_id].pop(feed_name, None)
        
        self.cog.poll_loop.restart()
        
        await interaction.response.edit_message(
            content=f"✅ Feed **{feed_name}** removed from this server.",
            view=None
        )

class FeedConfigureView(discord.ui.View):
    """View for feed configuration with dropdown selection"""
    def __init__(self, feeds: List[dict], cog, guild_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        
        # Create dropdown options
        options = []
        for feed in feeds[:25]:  # Discord limit
            options.append(discord.SelectOption(
                label=feed["name"],
                description=f"Channel: #{feed.get('channel_name', 'unknown')}",
                value=feed["name"]
            ))
        
        if options:
            select = FeedConfigureSelect(options, cog, guild_id)
            self.add_item(select)

class FeedConfigureSelect(discord.ui.Select):
    """Select dropdown for feed configuration"""
    def __init__(self, options: List[discord.SelectOption], cog, guild_id: int):
        super().__init__(
            placeholder="Choose a feed to configure...",
            options=options,
            min_values=1,
            max_values=1
        )
        self.cog = cog
        self.guild_id = guild_id
    
    async def callback(self, interaction: discord.Interaction):
        feed_name = self.values[0]
        
        # Find the feed config
        config = self.cog._load_guild_config(self.guild_id)
        feeds = config.get("feeds", [])
        feed_config = next((f for f in feeds if f.get("name") == feed_name), None)
        
        if not feed_config:
            await interaction.response.edit_message(
                content="❌ Feed not found.",
                view=None
            )
            return
        
        # Create configuration modal
        modal = FeedConfigModal(feed_config, self.cog, self.guild_id)
        await interaction.response.send_modal(modal)

class FeedConfigModal(discord.ui.Modal):
    """Modal for configuring feed settings"""
    def __init__(self, feed_config: dict, cog, guild_id: int):
        self.feed_config = feed_config
        self.cog = cog
        self.guild_id = guild_id
        
        super().__init__(title=f"Configure Feed: {feed_config['name']}")
        
        # Add input fields
        self.name_input = discord.ui.TextInput(
            label="Feed Name",
            default=feed_config.get("name", ""),
            max_length=100
        )
        
        self.avatar_input = discord.ui.TextInput(
            label="Avatar URL (optional)",
            default=feed_config.get("avatar_url", ""),
            required=False,
            max_length=500
        )
        
        current_color = feed_config.get("embed_template", {}).get("color", 0x3498DB)
        self.color_input = discord.ui.TextInput(
            label="Color (hex without #, e.g. 3498DB)",
            default=f"{current_color:06X}",
            max_length=6
        )
        
        self.add_item(self.name_input)
        self.add_item(self.avatar_input)
        self.add_item(self.color_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        # Validate color
        try:
            color_hex = int(self.color_input.value.lstrip("#"), 16)
        except ValueError:
            await interaction.response.send_message(
                f"❌ Invalid color: {self.color_input.value}", ephemeral=True
            )
            return
        
        # Update feed config
        config = self.cog._load_guild_config(self.guild_id)
        feeds = config.get("feeds", [])
        
        for feed in feeds:
            if feed.get("name") == self.feed_config["name"]:
                old_name = feed["name"]
                feed["name"] = self.name_input.value
                feed["avatar_url"] = self.avatar_input.value or None
                feed["embed_template"]["color"] = color_hex
                feed["embed_template"]["footer"]["text"] = self.name_input.value
                
                # Update title for Bluesky feeds if name changed
                if _is_bluesky_feed_url(feed["feed_url"]):
                    feed["embed_template"]["title"] = f"{self.name_input.value} just posted on Bluesky"
                    if "author" in feed["embed_template"]:
                        feed["embed_template"]["author"]["name"] = self.name_input.value
                
                # Update stats if name changed
                if old_name != self.name_input.value and self.guild_id in self.cog.stats:
                    if old_name in self.cog.stats[self.guild_id]:
                        self.cog.stats[self.guild_id][self.name_input.value] = self.cog.stats[self.guild_id].pop(old_name)
                break
        
        self.cog._save_guild_config(self.guild_id, config)
        self.cog.guild_configs[self.guild_id] = config
        
        await interaction.response.send_message(
            f"✅ Feed **{self.name_input.value}** updated successfully!", ephemeral=True
        )
