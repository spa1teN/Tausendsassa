"""Improved Proximity Modal with city extraction and message replacement."""

import discord
from datetime import datetime
from typing import TYPE_CHECKING
import re

if TYPE_CHECKING:
    from cogs.map import MapV2Cog


class ProximityModal(discord.ui.Modal, title='Nearby Members Search'):
    def __init__(self, cog: 'MapV2Cog', guild_id: int, original_interaction: discord.Interaction):
        super().__init__()
        self.cog = cog
        self.guild_id = guild_id
        self.original_interaction = original_interaction

    radius_input = discord.ui.TextInput(
        label='Search Radius (km)',
        placeholder='e.g. 5, 10, 25, 50, 100...',
        required=True,
        max_length=10
    )

    def _extract_city_name(self, display_name: str) -> str:
        """Extract city/town name from full display name with better logic."""
        if not display_name:
            return "Unknown"
        
        # Split by comma and clean parts
        parts = [part.strip() for part in display_name.split(',')]
        
        # Common patterns to exclude (not city names)
        exclude_patterns = [
            r'^[\d]',  # Starts with number (street addresses)
            r'straße$|straße\s|str\.$|str\s',  # Street names (German)
            r'street$|street\s|st\.$|st\s',  # Street names (English)
            r'avenue$|ave\.$|ave\s',  # Avenues
            r'road$|rd\.$|rd\s',  # Roads
            r'platz$|platz\s',  # Squares (German)
            r'weg$|weg\s',  # Ways (German)
            r'gasse$|gasse\s',  # Alleys (German)
            r'bundesland|state|province|region|county|kreis|landkreis',  # Administrative regions
            r'deutschland|germany|österreich|austria|schweiz|switzerland',  # Countries
            r'^\d{5}\s',  # Postal codes
        ]
        
        # Administrative level keywords that indicate regions, not cities
        admin_keywords = [
            'schleswig-holstein', 'baden-württemberg', 'nordrhein-westfalen',
            'rheinland-pfalz', 'sachsen-anhalt', 'mecklenburg-vorpommern',
            'bayern', 'bavaria', 'hessen', 'hesse', 'niedersachsen', 'thüringen',
            'brandenburg', 'sachsen', 'saxony', 'saarland', 'bremen', 'hamburg',
            'berlin', 'state', 'province', 'region', 'county', 'district'
        ]
        
        def is_likely_city(text: str) -> bool:
            """Check if text is likely a city name."""
            text_lower = text.lower().strip()
            
            # Skip empty or very short
            if len(text_lower) < 2:
                return False
            
            # Skip administrative regions
            if any(keyword in text_lower for keyword in admin_keywords):
                return False
            
            # Skip if matches exclude patterns
            for pattern in exclude_patterns:
                if re.search(pattern, text_lower, re.IGNORECASE):
                    return False
            
            # Skip if only numbers or postal codes
            if re.match(r'^\d+$', text_lower):
                return False
            
            # Good indicators for cities
            city_indicators = [
                'stadt', 'city', 'town', 'village', 'dorf', 'gemeinde',
                'municipality', 'ort', 'kommune'
            ]
            
            # If it contains city indicators, it's likely a city
            if any(indicator in text_lower for indicator in city_indicators):
                return True
            
            # If it's a reasonable length and doesn't match exclusions, likely a city
            return 3 <= len(text_lower) <= 30
        
        # Try to find the best city name from parts
        for i, part in enumerate(parts):
            clean_part = part.strip()
            
            # Skip the first part if it looks like an address
            if i == 0 and re.match(r'^\d+\s', clean_part):
                continue
            
            if is_likely_city(clean_part):
                # Clean up common prefixes/suffixes
                city = re.sub(r'^(Stadt|City|Municipality of|Gemeinde)\s+', '', clean_part, flags=re.IGNORECASE)
                city = re.sub(r'\s+(Stadt|City|Municipality|Gemeinde)$', '', city, flags=re.IGNORECASE)
                
                return city.strip()
        
        # Fallback: try to clean the first part
        if parts:
            first_clean = re.sub(r'^\d+\s+', '', parts[0])  # Remove house numbers
            first_clean = re.sub(r'\s*,.*$', '', first_clean)  # Remove everything after comma
            first_clean = first_clean.strip()
            
            if is_likely_city(first_clean):
                return first_clean
        
        return "Unknown Location"

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        try:
            distance_km = int(self.radius_input.value.strip())
            
            if distance_km <= 0 or distance_km > 1000:
                await interaction.followup.send(
                    "❌ Please enter a valid radius between 1 and 1000 km",
                    ephemeral=True
                )
                return
            
            proximity_result = await self.cog._generate_proximity_map(
                interaction.user.id, self.guild_id, distance_km
            )
            
            if proximity_result:
                image_buffer, nearby_users = proximity_result
                
                embed = discord.Embed(
                    title=f"Nearby Members ({distance_km}km radius)",
                    description=f"Found {len(nearby_users)} member(s) within {distance_km}km",
                    color=0x7289da
                )
                
                if nearby_users:
                    user_list = []
                    for user_data in nearby_users[:10]:  # Max 10 users
                        distance = user_data['distance']
                        user_id = user_data['user_id']
                        raw_location = user_data['location']
                        
                        # Extract city name from full location
                        city = self._extract_city_name(raw_location)
                        
                        # Format: @username - distance (city)
                        user_list.append(f"<@{user_id}> - {distance:.1f}km ({city})")
                    
                    embed.add_field(
                        name="Nearby Members",
                        value="\n".join(user_list),
                        inline=False
                    )
                
                filename = f"proximity_{distance_km}km_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                
                # Replace the original message instead of creating new one
                await self.original_interaction.edit_original_response(
                    content=None,
                    embed=embed,
                    attachments=[discord.File(image_buffer, filename=filename)],
                    view=None
                )
            else:
                await interaction.followup.send(
                    "You need to pin your location first to use proximity search!",
                    ephemeral=True
                )
                
        except ValueError:
            await interaction.followup.send(
                "❌ Please enter a valid number for the radius (e.g., 25)",
                ephemeral=True
            )
        except Exception as e:
            self.cog.log.error(f"Error in proximity modal: {e}")
            await interaction.followup.send("❌ Error generating proximity map", ephemeral=True)
