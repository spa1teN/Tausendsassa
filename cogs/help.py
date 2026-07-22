import discord
from discord.ext import commands
from discord import app_commands
import os

from core.config import config as bot_config

# Constants for external links
GITHUB_EMOJI_ID = 1415543938135359550
GITHUB_URL = "https://github.com/spa1teN/Tausendsassa"
DEV_SERVER_EMOJI_ID = 1415544743961694258
DEV_SERVER_URL = "https://discord.gg/yVNkpH6vDS"

def build_help_view(help_content: str) -> discord.ui.LayoutView:
    """Components-V2 help card: title, the commands.md body, and link buttons.

    TextDisplay allows 4000 chars; commands.md is well under that. If it ever
    grows past the limit, the extra is split into a second TextDisplay.
    """
    view = discord.ui.LayoutView(timeout=None)
    container = discord.ui.Container(accent_colour=discord.Colour(0x5865F2))
    container.add_item(discord.ui.TextDisplay("# Tausendsassa — Commands"))
    container.add_item(discord.ui.Separator())
    for i in range(0, len(help_content), 3900):
        container.add_item(discord.ui.TextDisplay(help_content[i:i + 3900]))
    container.add_item(discord.ui.Separator())
    row = discord.ui.ActionRow()
    row.add_item(discord.ui.Button(emoji=f"<:github:{GITHUB_EMOJI_ID}>", label="GitHub",
                                   style=discord.ButtonStyle.link, url=GITHUB_URL))
    row.add_item(discord.ui.Button(emoji=f"<:devserver:{DEV_SERVER_EMOJI_ID}>", label="Dev Server",
                                   style=discord.ButtonStyle.link, url=DEV_SERVER_URL))
    if bot_config.webapp_url:
        row.add_item(discord.ui.Button(label="Webapp", emoji="🌐",
                                       style=discord.ButtonStyle.link, url=bot_config.webapp_url))
    fb_btn = discord.ui.Button(label="Feedback", emoji="💬",
                               style=discord.ButtonStyle.secondary,
                               custom_id="help_feedback_btn")

    async def _feedback_callback(interaction: discord.Interaction):
        from core.feedback_menu import build_feedback_menu
        fb_cog = interaction.client.get_cog("FeedbackCog")
        if not fb_cog:
            await interaction.response.send_message("Feedback system unavailable.", ephemeral=True)
            return
        view = build_feedback_menu(fb_cog, interaction.guild_id, interaction.user.id)
        await interaction.response.send_message(view=view, ephemeral=True)

    fb_btn.callback = _feedback_callback
    row.add_item(fb_btn)
    container.add_item(row)
    view.add_item(container)
    return view

class HelpCog(commands.Cog):
    """Cog for displaying help information from commands.md file"""
    
    def __init__(self, bot):
        self.bot = bot
        self.commands_file_path = "resources/commands.md"
        
    @app_commands.command(name="help", description="Display available bot commands")
    async def help_command(self, interaction: discord.Interaction):
        """Display help information from commands.md file"""
        try:
            # Check if commands.md exists
            if not os.path.exists(self.commands_file_path):
                await interaction.response.send_message(
                    "❌ Help file not found. Please contact an administrator.",
                    ephemeral=True
                )
                return
            
            # Read the commands.md file
            with open(self.commands_file_path, 'r', encoding='utf-8') as file:
                help_content = file.read().strip()
            
            # Check if file is empty
            if not help_content:
                await interaction.response.send_message(
                    "❌ Help file is empty. Please contact an administrator.",
                    ephemeral=True
                )
                return
            
            await interaction.response.send_message(view=build_help_view(help_content), ephemeral=True)


        except FileNotFoundError:
            await interaction.response.send_message(
                "❌ Help file not found. Please contact an administrator.",
                ephemeral=True
            )
            
        except PermissionError:
            await interaction.response.send_message(
                "❌ Permission denied reading help file. Please contact an administrator.",
                ephemeral=True
            )
            
        except UnicodeDecodeError:
            await interaction.response.send_message(
                "❌ Help file encoding error. Please contact an administrator.",
                ephemeral=True
            )
            
        except Exception as e:
            await interaction.response.send_message(
                "❌ An unexpected error occurred. Please contact an administrator.",
                ephemeral=True
            )

async def setup(bot: commands.Bot):
    """Setup function to add the cog to the bot"""
    await bot.add_cog(HelpCog(bot))
