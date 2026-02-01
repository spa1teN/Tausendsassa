import discord
from discord.ext import commands
from discord import app_commands
import os

# Constants for external links
GITHUB_EMOJI_ID = 1415543938135359550
GITHUB_URL = "https://github.com/spa1teN/Tausendsassa"
DEV_SERVER_EMOJI_ID = 1415544743961694258
DEV_SERVER_URL = "https://discord.gg/yVNkpH6vDS"

class HelpButtonsView(discord.ui.View):
    """View with GitHub and Development Server buttons"""
    
    def __init__(self):
        super().__init__(timeout=None)
        
        # Add GitHub button
        github_button = discord.ui.Button(
            emoji=f"<:github:{GITHUB_EMOJI_ID}>",
            label="GitHub",
            style=discord.ButtonStyle.link,
            url=GITHUB_URL
        )
        self.add_item(github_button)
        
        # Add Development Server button
        dev_button = discord.ui.Button(
            emoji=f"<:devserver:{DEV_SERVER_EMOJI_ID}>",
            label="Development Server",
            style=discord.ButtonStyle.link,
            url=DEV_SERVER_URL
        )
        self.add_item(dev_button)

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
            
            # Create view with buttons
            view = HelpButtonsView()
            
            # Discord has a 2000 character limit for message content
            if len(help_content) > 2000:
                # Split content if too long
                chunks = [help_content[i:i+2000] for i in range(0, len(help_content), 2000)]
                
                await interaction.response.send_message(f"**Bot Commands** (Part 1/{len(chunks)}):\n\n{chunks[0]}", view=view, ephemeral=True)
                
                # Send remaining chunks as follow-up messages
                for i, chunk in enumerate(chunks[1:], 2):
                    await interaction.followup.send(f"**Bot Commands** (Part {i}/{len(chunks)}):\n\n{chunk}", ephemeral=True)
            else:
                await interaction.response.send_message(f"## **Bot Commands**:\n{help_content}", view=view, ephemeral=True)
            
            
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
