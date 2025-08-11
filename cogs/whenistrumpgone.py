import discord
from discord.ext import commands
from discord import app_commands
import datetime

class WhenIsTrumpGone(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="when_is_trump_gone", description="The amount of time we have to endure the orange child")
    async def give_role_command(
            self, 
            interaction: discord.Interaction
    ):
        today = datetime.datetime.now()
        liberation_day = datetime.datetime(year=2029, month=1, day=20)
        rd = liberation_day - today
        await interaction.response.send_message(f"We still have {rd} to go")
                
async def setup(bot):
    await bot.add_cog(WhenIsTrumpGone(bot))
