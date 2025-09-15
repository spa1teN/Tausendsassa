# core/feeds_views.py

from typing import List
import discord
from discord import app_commands

def _is_bluesky_feed_url(url: str) -> bool:
    """Check if the given URL is a Bluesky profile feed"""
    return "bsky.app/profile/" in url

class FeedListView(discord.ui.View):
    """View for feed list with remove and configure buttons"""
    def __init__(self, cog, guild_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id

    @discord.ui.button(label="Remove Feed", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def remove_feed(self, interaction: discord.Interaction, button: discord.ui.Button):
        config = self.cog._load_guild_config(self.guild_id)
        feeds = config.get("feeds", [])
        
        if not feeds:
            await interaction.response.edit_message(
                content="No feeds configured for this server.", view=None
            )
            return
        
        view = FeedRemoveView(feeds, self.cog, self.guild_id)
        await interaction.response.edit_message(
            content="Select a feed to remove:", view=view
        )

    @discord.ui.button(label="Configure Feed", style=discord.ButtonStyle.secondary, emoji="⚙️")
    async def configure_feed(self, interaction: discord.Interaction, button: discord.ui.Button):
        config = self.cog._load_guild_config(self.guild_id)
        feeds = config.get("feeds", [])
        
        if not feeds:
            await interaction.response.edit_message(
                content="No feeds configured for this server.", view=None
            )
            return
        
        # Add channel names to feeds for better display
        for feed in feeds:
            channel = self.cog.bot.get_channel(feed.get("channel_id"))
            feed["channel_name"] = channel.name if channel else "unknown"
        
        view = FeedConfigureView(feeds, self.cog, self.guild_id)
        await interaction.response.edit_message(
            content="Select a feed to configure:", view=view
        )

class FeedRemoveView(discord.ui.View):
    """View for feed removal with dropdown selection"""
    def __init__(self, feeds: List[dict], cog, guild_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        
        # Create dropdown options
        options = []
        for i, feed in enumerate(feeds[:25]):  # Discord limit
            options.append(discord.SelectOption(
                label=feed["name"],
                description=f"URL: {feed['feed_url'][:50]}..." if len(feed['feed_url']) > 50 else feed['feed_url'],
                value=f"{i}_{feed['name']}"
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
        feed_identifier = self.values[0]
        # Extract the name from the identifier (format: "index_name")
        feed_name = feed_identifier.split("_", 1)[1] if "_" in feed_identifier else feed_identifier
        
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
        
        # Restart poll loop in background to avoid blocking interaction
        try:
            self.cog.poll_loop.restart()
        except Exception as e:
            # Log error but don't let it break the interaction
            self.cog.log.warning(f"Failed to restart poll loop: {e}")
        
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
        for i, feed in enumerate(feeds[:25]):  # Discord limit
            options.append(discord.SelectOption(
                label=feed["name"],
                description=f"Channel: #{feed.get('channel_name', 'unknown')}",
                value=f"{i}_{feed['name']}"
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
        feed_identifier = self.values[0]
        # Extract the name from the identifier (format: "index_name")
        feed_name = feed_identifier.split("_", 1)[1] if "_" in feed_identifier else feed_identifier
        
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
        modal = FeedConfigModal(feed_config, self.cog, self.guild_id, is_edit=True)
        await interaction.response.send_modal(modal)

class FeedConfigModal(discord.ui.Modal):
    """Modal for configuring feed settings"""
    def __init__(self, feed_config: dict, cog, guild_id: int, is_edit: bool = True):
        self.feed_config = feed_config
        self.cog = cog
        self.guild_id = guild_id
        self.is_edit = is_edit
        
        title = f"Configure Feed: {feed_config.get('name', 'New Feed')}" if is_edit else "Add New Feed"
        super().__init__(title=title)
        
        # Add input fields
        self.name_input = discord.ui.TextInput(
            label="Feed Name",
            default=feed_config.get("name", ""),
            max_length=100,
            required=True
        )
        
        self.url_input = discord.ui.TextInput(
            label="Feed URL",
            default=feed_config.get("feed_url", ""),
            max_length=500,
            required=True,
            style=discord.TextStyle.paragraph
        )
        
        self.avatar_input = discord.ui.TextInput(
            label="Avatar URL (optional)",
            default=feed_config.get("avatar_url", ""),
            required=False,
            max_length=500
        )
        
        current_color = feed_config.get("embed_template", {}).get("color", 0x3498DB)
        self.color_input = discord.ui.TextInput(
            label="Color (name/RGB/hex, e.g. 'orange')",
            default=f"{current_color:06X}",
            max_length=50,
            required=True
        )
        
        # Add crosspost field for editing only (we need channel info for new feeds)
        if is_edit:
            self.crosspost_input = discord.ui.TextInput(
                label="Crosspost (true/false)",
                default=str(feed_config.get("crosspost", False)).lower(),
                max_length=5,
                required=True
            )
            self.add_item(self.crosspost_input)
        
        self.add_item(self.name_input)
        self.add_item(self.url_input)
        self.add_item(self.avatar_input)
        self.add_item(self.color_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        # Import color utility
        from core.colors import get_discord_embed_color
        
        # Validate color using color utility
        color_hex = get_discord_embed_color(self.color_input.value)
        if color_hex is None:
            # List some available colors for help
            from core.colors import get_available_colors
            available = ', '.join(get_available_colors()[:10])  # Show first 10
            await interaction.response.defer(ephemeral=True)
            await interaction.followup.send(
                f"❌ Invalid color: `{self.color_input.value}`\n\n"
                f"**Examples:**\n"
                f"• Color names: `{available}`, etc.\n"
                f"• RGB values: `255,165,0` (orange)\n"
                f"• HEX values: `#FF6600` or `FF6600`", ephemeral=True
            )
            return
        
        # Validate crosspost for edit mode
        crosspost = False
        if self.is_edit:
            crosspost_str = self.crosspost_input.value.lower().strip()
            if crosspost_str in ["true", "1", "yes"]:
                crosspost = True
            elif crosspost_str in ["false", "0", "no"]:
                crosspost = False
            else:
                await interaction.response.defer(ephemeral=True)
                await interaction.followup.send(
                    f"❌ Invalid crosspost value: {self.crosspost_input.value}. Use true or false.", ephemeral=True
                )
                return
        
        # For new feeds, we need to ask for channel via followup
        if not self.is_edit:
            await self._handle_new_feed(interaction, color_hex)
        else:
            await self._handle_edit_feed(interaction, color_hex, crosspost)
    
    async def _handle_new_feed(self, interaction: discord.Interaction, color_hex: int):
        """Handle creating a new feed - need to get channel selection"""
        # Store feed data in a view for channel selection
        view = ChannelSelectView(
            name=self.name_input.value,
            feed_url=self.url_input.value,
            avatar_url=self.avatar_input.value or None,
            color=color_hex,
            cog=self.cog,
            guild_id=self.guild_id
        )
        
        await interaction.response.send_message(
            f"Feed settings configured! Now select a channel for **{self.name_input.value}**:",
            view=view,
            ephemeral=True
        )
    
    async def _handle_edit_feed(self, interaction: discord.Interaction, color_hex: int, crosspost: bool):
        """Handle editing an existing feed"""
        from core.feeds_config import is_bluesky_feed_url, create_bluesky_embed_template, create_standard_embed_template
        
        # Update feed config
        config = self.cog._load_guild_config(self.guild_id)
        feeds = config.get("feeds", [])
        
        for feed in feeds:
            if feed.get("name") == self.feed_config["name"]:
                old_name = feed["name"]
                feed["name"] = self.name_input.value
                feed["feed_url"] = self.url_input.value
                feed["avatar_url"] = self.avatar_input.value or None
                feed["crosspost"] = crosspost
                
                # Recreate embed template based on feed type
                if is_bluesky_feed_url(self.url_input.value):
                    feed["embed_template"] = create_bluesky_embed_template(self.name_input.value, color_hex)
                else:
                    feed["embed_template"] = create_standard_embed_template(self.name_input.value, color_hex)
                
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

class ChannelSelectView(discord.ui.View):
    """View for selecting channel for new feeds"""
    def __init__(self, name: str, feed_url: str, avatar_url: str, color: int, cog, guild_id: int):
        super().__init__(timeout=300)
        self.name = name
        self.feed_url = feed_url
        self.avatar_url = avatar_url
        self.color = color
        self.cog = cog
        self.guild_id = guild_id
        
        # Get text channels in guild
        guild = cog.bot.get_guild(guild_id)
        if guild:
            channels = [ch for ch in guild.text_channels if ch.permissions_for(guild.me).send_messages][:25]
            if channels:
                options = []
                for channel in channels:
                    options.append(discord.SelectOption(
                        label=f"#{channel.name}",
                        description=channel.topic[:50] if channel.topic else "No description",
                        value=str(channel.id)
                    ))
                
                select = ChannelSelect(options, self)
                self.add_item(select)

class ChannelSelect(discord.ui.Select):
    """Select dropdown for channel selection"""
    def __init__(self, options: List[discord.SelectOption], parent_view):
        super().__init__(
            placeholder="Choose a channel for this feed...",
            options=options,
            min_values=1,
            max_values=1
        )
        self.parent_view = parent_view
    
    async def callback(self, interaction: discord.Interaction):
        from core.feeds_config import is_bluesky_feed_url, create_bluesky_embed_template, create_standard_embed_template
        
        channel_id = int(self.values[0])
        
        # Create embed template based on feed type
        if is_bluesky_feed_url(self.parent_view.feed_url):
            embed_template = create_bluesky_embed_template(self.parent_view.name, self.parent_view.color)
        else:
            embed_template = create_standard_embed_template(self.parent_view.name, self.parent_view.color)
        
        new_feed = {
            "name": self.parent_view.name,
            "feed_url": self.parent_view.feed_url,
            "channel_id": channel_id,
            "max_items": 3,
            "crosspost": False,  # Default to false for new feeds
            "avatar_url": self.parent_view.avatar_url,
            "embed_template": embed_template
        }
        
        # Load and update guild config
        config = self.parent_view.cog._load_guild_config(self.parent_view.guild_id)
        config.setdefault("feeds", []).append(new_feed)
        self.parent_view.cog._save_guild_config(self.parent_view.guild_id, config)
        
        # Update runtime config and stats
        self.parent_view.cog.guild_configs[self.parent_view.guild_id] = config
        if self.parent_view.guild_id not in self.parent_view.cog.stats:
            self.parent_view.cog.stats[self.parent_view.guild_id] = {}
        self.parent_view.cog.stats[self.parent_view.guild_id][self.parent_view.name] = {
            "last_run": None, "last_success": None, "failures": 0
        }
        
        # Restart poll loop in background to avoid blocking interaction
        try:
            self.parent_view.cog.poll_loop.restart()
        except Exception as e:
            # Log error but don't let it break the interaction
            self.parent_view.cog.log.warning(f"Failed to restart poll loop: {e}")
        
        # Get channel name for confirmation
        channel = self.parent_view.cog.bot.get_channel(channel_id)
        channel_name = f"#{channel.name}" if channel else f"Channel ID {channel_id}"
        
        feed_type = "Bluesky feed" if is_bluesky_feed_url(self.parent_view.feed_url) else "RSS feed"
        await interaction.response.edit_message(
            content=f"✅ {feed_type} **{self.parent_view.name}** added to {channel_name}!",
            view=None
        )
