"""Improved modals for Discord Map Bot with loading states."""

import discord
from datetime import datetime
from typing import TYPE_CHECKING
from io import BytesIO

if TYPE_CHECKING:
    from cogs.map import MapV2Cog


class ProximityModal(discord.ui.Modal, title='Find Nearby Members'):
    def __init__(self, cog: 'MapV2Cog', guild_id: int, original_interaction: discord.Interaction):
        super().__init__()
        self.cog = cog
        self.guild_id = guild_id
        self.original_interaction = original_interaction

    distance = discord.ui.TextInput(
        label='Search Radius (km)',
        placeholder='e.g., 50 for 50 kilometers',
        required=True,
        max_length=4,
        min_length=1
    )

    async def on_submit(self, interaction: discord.Interaction):
        # Show loading message immediately
        loading_embed = discord.Embed(
            title="🔍 Generating Proximity View",
            description="Just a moment, I'm generating the proximity view...",
            color=0x7289da
        )
        await interaction.response.edit_message(embed=loading_embed, view=None)
        
        try:
            # Validate distance input
            try:
                distance_km = int(self.distance.value)
                if distance_km <= 0 or distance_km > 2000:  # Reasonable limits
                    error_embed = discord.Embed(
                        title="⛔ Invalid Distance",
                        description="Please enter a distance between 1 and 2000 kilometers.",
                        color=0xff4444
                    )
                    await self.original_interaction.edit_original_response(embed=error_embed, view=None)
                    return
            except ValueError:
                error_embed = discord.Embed(
                    title="⛔ Invalid Input",
                    description="Please enter a valid number for the distance.",
                    color=0xff4444
                )
                await self.original_interaction.edit_original_response(embed=error_embed, view=None)
                return

            # Use centralized progress handler
            from core.map_progress_handler import create_proximity_progress_callback
            progress_callback = await create_proximity_progress_callback(interaction, self.cog.log)
            
            # Generate proximity map
            user_id = interaction.user.id
            result = await self.cog._generate_proximity_map(user_id, self.guild_id, distance_km, progress_callback)
            
            if not result:
                error_embed = discord.Embed(
                    title="⛔ Generation Error",
                    description="Could not generate proximity view. Please try again.",
                    color=0xff4444
                )
                await self.original_interaction.edit_original_response(embed=error_embed, view=None)
                return
            
            proximity_image, nearby_users = result
            
            # Create result embed
            embed = discord.Embed(
                title=f"🔍 Nearby Members ({distance_km}km radius)",
                color=0x7289da,
                timestamp=datetime.now()
            )
            
            if nearby_users:
                # Add nearby users to embed - USE ORIGINAL INPUT AND USER MENTIONS
                user_list = []
                for user_data in nearby_users:
                    user_id_str = user_data.get('user_id', '')
                    location_input = user_data.get('location', 'Unknown')  # Use original user input
                    distance = user_data.get('distance', 0)
                    
                    # Create user mention instead of username
                    user_mention = f"<@{user_id_str}>" if user_id_str else "Unknown User"
                    user_list.append(f"{user_mention} - {location_input} ({distance:.1f}km)")
                
                # Split into multiple fields if too many users
                max_per_field = 10
                for i in range(0, len(user_list), max_per_field):
                    field_users = user_list[i:i+max_per_field]
                    field_name = f"👥 Found Members" if i == 0 else f"👥 Found Members (cont.)"
                    embed.add_field(
                        name=field_name,
                        value="\n".join(field_users),
                        inline=False
                    )
            else:
                embed.add_field(
                    name="👥 Found Members",
                    value="No members found within the specified radius.",
                    inline=False
                )
            
            embed.add_field(
                name="📊 Summary",
                value=f"**{len(nearby_users)}** members within **{distance_km}km**",
                inline=False
            )
            
            # Replace loading message with results and embed the map within the embed
            filename = f"proximity_{distance_km}km_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            embed.set_image(url=f"attachment://{filename}")
            await self.original_interaction.edit_original_response(
                embed=embed,
                attachments=[discord.File(proximity_image, filename=filename)],
                view=None
            )
            
        except Exception as e:
            self.cog.log.error(f"Error generating proximity view: {e}")
            error_embed = discord.Embed(
                title="⛔ Generation Error",
                description="An error occurred while generating the proximity view.",
                color=0xff4444
            )
            await self.original_interaction.edit_original_response(embed=error_embed, view=None)