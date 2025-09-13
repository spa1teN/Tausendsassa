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
            
            # Create result embed (just the map, no user list)
            embed = discord.Embed(
                title=f"🔍 Proximity Map ({distance_km}km radius)",
                color=0x7289da,
                timestamp=datetime.now()
            )
            
            # Add summary to embed
            embed.add_field(
                name="📊 Summary",
                value=f"**{len(nearby_users)}** members found within **{distance_km}km**",
                inline=False
            )
            
            # Prepare nearby users message content (separate from embed)
            nearby_message = None
            if nearby_users:
                # Build nearby users as regular message content
                user_list = []
                for user_data in nearby_users:
                    user_id_str = user_data.get('user_id', '')
                    location_input = user_data.get('location', 'Unknown')  # Use original user input
                    distance = user_data.get('distance', 0)
                    username = user_data.get('username', 'Unknown User')
                    
                    # Use clickable Discord mentions instead of plain text
                    try:
                        if user_id_str:
                            # Check if user is still in the guild
                            guild = self.original_interaction.guild
                            member = guild.get_member(int(user_id_str))
                            if member:
                                user_display = f"<@{user_id_str}>"  # Clickable mention
                            else:
                                user_display = f"@{username}"  # Fallback for users who left
                        else:
                            user_display = f"@{username}"
                    except (ValueError, AttributeError):
                        user_display = f"@{username}"
                    
                    user_list.append(f"• {user_display} - {location_input} ({distance:.1f}km)")
                
                nearby_message = f"**👥 Nearby Members:**\n" + "\n".join(user_list)
            else:
                nearby_message = "**👥 Nearby Members:**\nNo members found within the specified radius."
            
            # Replace loading message with results - embed the map within the embed and send nearby members as regular content
            filename = f"proximity_{distance_km}km_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            embed.set_image(url=f"attachment://{filename}")
            await self.original_interaction.edit_original_response(
                content=nearby_message,
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