"""
Unified color utility for consistent color handling across the bot.
Supports string names, RGB tuples, and HEX values for both map and feed customization.
"""

import re
from typing import Union, Tuple, Optional

class ColorUtil:
    """Utility class for color conversion and validation."""
    
    # Extended color dictionary combining map and feed colors
    COLOR_DICTIONARY = {
        # Basic colors
        'red': ('#FF0000', (255, 0, 0)),
        'green': ('#00FF00', (0, 255, 0)),
        'blue': ('#0000FF', (0, 0, 255)),
        'yellow': ('#FFFF00', (255, 255, 0)),
        'cyan': ('#00FFFF', (0, 255, 255)),
        'magenta': ('#FF00FF', (255, 0, 255)),
        'white': ('#FFFFFF', (255, 255, 255)),
        'black': ('#000000', (0, 0, 0)),
        'gray': ('#808080', (128, 128, 128)),
        'grey': ('#808080', (128, 128, 128)),
        'orange': ('#FFA500', (255, 165, 0)),
        'purple': ('#800080', (128, 0, 128)),
        'brown': ('#A52A2A', (165, 42, 42)),
        'pink': ('#FFC0CB', (255, 192, 203)),
        
        # Additional colors
        'lime': ('#00FF00', (0, 255, 0)),
        'navy': ('#000080', (0, 0, 128)),
        'teal': ('#008080', (0, 128, 128)),
        'olive': ('#808000', (128, 128, 0)),
        'maroon': ('#800000', (128, 0, 0)),
        'aqua': ('#00FFFF', (0, 255, 255)),
        
        # Light variants
        'lightblue': ('#ADD8E6', (173, 216, 230)),
        'lightgreen': ('#90EE90', (144, 238, 144)),
        'lightgray': ('#D3D3D3', (211, 211, 211)),
        'lightgrey': ('#D3D3D3', (211, 211, 211)),
        'lightyellow': ('#FFFFE0', (255, 255, 224)),
        'lightpink': ('#FFB6C1', (255, 182, 193)),
        
        # Dark variants
        'darkblue': ('#00008B', (0, 0, 139)),
        'darkgreen': ('#006400', (0, 100, 0)),
        'darkgray': ('#A9A9A9', (169, 169, 169)),
        'darkgrey': ('#A9A9A9', (169, 169, 169)),
        'darkred': ('#8B0000', (139, 0, 0)),
        
        # Nature colors
        'skyblue': ('#87CEEB', (135, 206, 235)),
        'forestgreen': ('#228B22', (34, 139, 34)),
        'seagreen': ('#2E8B57', (46, 139, 87)),
        'sandybrown': ('#F4A460', (244, 164, 96)),
        'coral': ('#FF7F50', (255, 127, 80)),
        'gold': ('#FFD700', (255, 215, 0)),
        'silver': ('#C0C0C0', (192, 192, 192)),
        'beige': ('#F5F5DC', (245, 245, 220)),
        'tan': ('#D2B48C', (210, 180, 140)),
        'khaki': ('#F0E68C', (240, 230, 140)),
        
        # Discord/Feed specific colors (from feeds_config.py)
        'discordblue': ('#3498DB', (52, 152, 219)),
        'discordgreen': ('#2ECC71', (46, 204, 113)),
        'discordred': ('#E74C3C', (231, 76, 60)),
        'discordorange': ('#F39C12', (243, 156, 18)),
        'discordpurple': ('#9B59B6', (155, 89, 182)),
        'discordcyan': ('#1ABC9C', (26, 188, 156)),
        'discordyellow': ('#F1C40F', (241, 196, 15)),
        'discordpink': ('#E91E63', (233, 30, 99)),
        'discorddarkblue': ('#2C3E50', (44, 62, 80)),
        'discordgray': ('#95A5A6', (149, 165, 166)),
    }
    
    @classmethod
    def parse_color_input(cls, color_input: Union[str, tuple, list]) -> Optional[str]:
        """
        Parse various color input formats and return a HEX string.
        
        Args:
            color_input: Color as string name, HEX string, RGB tuple/list, or comma-separated RGB
            
        Returns:
            HEX color string (e.g., '#FF0000') or None if invalid
        """
        if not color_input:
            return None
        
        # Handle tuple/list RGB input
        if isinstance(color_input, (tuple, list)):
            if len(color_input) == 3:
                try:
                    r, g, b = [int(x) for x in color_input]
                    if all(0 <= x <= 255 for x in [r, g, b]):
                        return f"#{r:02X}{g:02X}{b:02X}"
                except (ValueError, TypeError):
                    pass
            return None
        
        # Handle string input
        if isinstance(color_input, str):
            color_str = color_input.strip()
            
            # Check if it's a color name
            color_lower = color_str.lower()
            if color_lower in cls.COLOR_DICTIONARY:
                return cls.COLOR_DICTIONARY[color_lower][0]
            
            # Check if it's a HEX color (with or without #)
            if color_str.startswith('#') and len(color_str) == 7:
                if re.match(r'^#[0-9A-Fa-f]{6}$', color_str):
                    return color_str.upper()
            elif len(color_str) == 6:
                if re.match(r'^[0-9A-Fa-f]{6}$', color_str):
                    return f"#{color_str.upper()}"
            
            # Check if it's comma-separated RGB
            if ',' in color_str:
                try:
                    parts = [int(x.strip()) for x in color_str.split(',')]
                    if len(parts) == 3 and all(0 <= x <= 255 for x in parts):
                        r, g, b = parts
                        return f"#{r:02X}{g:02X}{b:02X}"
                except (ValueError, TypeError):
                    pass
        
        return None
    
    @classmethod
    def to_rgb_tuple(cls, color_input: Union[str, tuple, list]) -> Optional[Tuple[int, int, int]]:
        """
        Convert color input to RGB tuple.
        
        Args:
            color_input: Color as string name, HEX string, RGB tuple/list, or comma-separated RGB
            
        Returns:
            RGB tuple (r, g, b) or None if invalid
        """
        # If already a valid tuple/list, validate and return
        if isinstance(color_input, (tuple, list)):
            if len(color_input) == 3:
                try:
                    r, g, b = [int(x) for x in color_input]
                    if all(0 <= x <= 255 for x in [r, g, b]):
                        return (r, g, b)
                except (ValueError, TypeError):
                    pass
            return None
        
        # Convert to HEX first, then to RGB
        hex_color = cls.parse_color_input(color_input)
        if hex_color:
            try:
                hex_val = hex_color[1:]  # Remove #
                r = int(hex_val[0:2], 16)
                g = int(hex_val[2:4], 16)
                b = int(hex_val[4:6], 16)
                return (r, g, b)
            except (ValueError, IndexError):
                pass
        
        return None
    
    @classmethod
    def to_hex_string(cls, color_input: Union[str, tuple, list]) -> Optional[str]:
        """
        Convert color input to HEX string.
        
        Args:
            color_input: Color as string name, HEX string, RGB tuple/list, or comma-separated RGB
            
        Returns:
            HEX color string (e.g., '#FF0000') or None if invalid
        """
        return cls.parse_color_input(color_input)
    
    @classmethod
    def validate_color(cls, color_input: Union[str, tuple, list]) -> bool:
        """
        Validate if color input is valid.
        
        Args:
            color_input: Color input to validate
            
        Returns:
            True if valid color, False otherwise
        """
        return cls.parse_color_input(color_input) is not None
    
    @classmethod
    def get_available_colors(cls) -> list:
        """
        Get list of available color names.
        
        Returns:
            List of available color name strings
        """
        return sorted(cls.COLOR_DICTIONARY.keys())
    
    @classmethod
    def get_discord_embed_color(cls, color_input: Union[str, tuple, list]) -> Optional[int]:
        """
        Convert color input to Discord embed color integer.
        
        Args:
            color_input: Color input to convert
            
        Returns:
            Integer color value for Discord embeds or None if invalid
        """
        hex_color = cls.parse_color_input(color_input)
        if hex_color:
            try:
                # Remove # and convert to integer
                return int(hex_color[1:], 16)
            except (ValueError, IndexError):
                pass
        return None

# Global instance for easy access
color_util = ColorUtil()

# Convenience functions for backward compatibility
def parse_color_input(color_input: Union[str, tuple, list]) -> Optional[str]:
    """Parse color input and return HEX string."""
    return color_util.parse_color_input(color_input)

def to_rgb_tuple(color_input: Union[str, tuple, list]) -> Optional[Tuple[int, int, int]]:
    """Convert color input to RGB tuple."""
    return color_util.to_rgb_tuple(color_input)

def to_hex_string(color_input: Union[str, tuple, list]) -> Optional[str]:
    """Convert color input to HEX string."""
    return color_util.to_hex_string(color_input)

def validate_color(color_input: Union[str, tuple, list]) -> bool:
    """Validate if color input is valid."""
    return color_util.validate_color(color_input)

def get_available_colors() -> list:
    """Get list of available color names."""
    return color_util.get_available_colors()

def get_discord_embed_color(color_input: Union[str, tuple, list]) -> Optional[int]:
    """Convert color input to Discord embed color integer."""
    return color_util.get_discord_embed_color(color_input)