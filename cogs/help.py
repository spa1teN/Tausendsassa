import discord
from discord.ext import commands
from discord import app_commands
import os

class HelpCog(commands.Cog):
    """Cog for displaying help information from commands.md file"""
    
    def __init__(self, bot):
        self.bot = bot
        self.commands_file_path = "commands.md"
        
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
            
            # Discord has a 2000 character limit for message content
            if len(help_content) > 2000:
                # Split content if too long
                chunks = [help_content[i:i+2000] for i in range(0, len(help_content), 2000)]
                
                await interaction.response.send_message(f"**Bot Commands** (Part 1/{len(chunks)}):\n\n{chunks[0]}", ephemeral=True)
                
                # Send remaining chunks as follow-up messages
                for i, chunk in enumerate(chunks[1:], 2):
                    await ctx.followup.send(f"**Bot Commands** (Part {i}/{len(chunks)}):\n\n{chunk}", ephemeral=True)
            else:
                await interaction.response.send_message(f"## **Bot Commands**:\n{help_content}", ephemeral=True)
            
            
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
            await interaction.reponse.send_message(
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
