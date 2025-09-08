"""Central configuration for the Discord Map Bot."""

from typing import Union, Tuple, Dict


class MapConfig:
    """Central configuration for map appearance and behavior."""
    
    def __init__(self):
        # Line widths (consistent across all map types)
        self.RIVER_WIDTH_BASE = 1
        self.COUNTRY_WIDTH_BASE = 2
        self.STATE_WIDTH_BASE = 1
        
        # Default colors
        self.DEFAULT_LAND_COLOR = (240, 240, 220)
        self.DEFAULT_WATER_COLOR = (168, 213, 242)
        self.DEFAULT_PIN_COLOR = '#FF4444'
        self.DEFAULT_PIN_SIZE = 16  # Base size for scaling
        self.DEFAULT_COUNTRY_BORDER_COLOR = (0, 0, 0)  # Black
        self.DEFAULT_STATE_BORDER_COLOR = (100, 100, 100)  # Gray
        self.DEFAULT_RIVER_COLOR = (60, 60, 200)  # Blue
        
        # Region configurations
        self.MAP_REGIONS = {
            "world": {
                "center_lat": 0.0,
                "center_lng": 0.0,
                "bounds": [[-65.0, -180.0], [85.0, 180.0]]
            },
            "europe": {
                "center_lat": 57.5,
                "center_lng": 12.0,
                "bounds": [[34.5, -25.0], [73.0, 40.0]]
            },
            "germany": {
                "center_lat": 51.1657,
                "center_lng": 10.4515,
                "bounds": [[47.2701, 5.8663], [55.0583, 15.0419]]
            },
            "asia": {
                "bounds": [[-8.0, 24.0], [82.0, 180.0]] 
            },
            "northamerica": {
                "bounds": [[5.0, -180.0], [82.0, -50.0]]
            },
            "southamerica": {
                "bounds": [[-60.0, -85.0], [20.0, -33.0]]
            },
            "africa": {
                "bounds": [[-40.0, -20.0], [40.0, 60.0]]
            },
            "australia": {
                "bounds": [[-45.0, 110.0], [-10.0, 155.0]]
            },
            "usmainland": {
                "bounds": [[24.0, -126.0], [51.0, -66.0]]
            }
        }
        
        # Common color dictionary (name -> (hex, rgb))
        self.COLOR_DICTIONARY = {
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
            
            # Extended colors
            'orange': ('#FFA500', (255, 165, 0)),
            'purple': ('#800080', (128, 0, 128)),
            'brown': ('#A52A2A', (165, 42, 42)),
            'pink': ('#FFC0CB', (255, 192, 203)),
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
        }
        
        # German states with placeholder emoji IDs for coat of arms
        self.GERMAN_STATES = {
            "Baden-Württemberg": {"short": "BW", "emoji_id": 1414370527732306040},
            "Bayern": {"short": "BY", "emoji_id": 1414370930414588085},
            "Berlin": {"short": "BE", "emoji_id": 1414370969522278552},
            "Brandenburg": {"short": "BB", "emoji_id": 1414371232664780888},
            "Bremen": {"short": "HB", "emoji_id": 1414371279082885161},
            "Hamburg": {"short": "HH", "emoji_id": 1414371380962525254},
            "Hessen": {"short": "HE", "emoji_id": 1414371426789494856},
            "Mecklenburg-Vorpommern": {"short": "MV", "emoji_id": 1414371652527198378},
            "Niedersachsen": {"short": "NI", "emoji_id": 1414371713017188473},
            "Nordrhein-Westfalen": {"short": "NW", "emoji_id": 1414371769149558885},
            "Rheinland-Pfalz": {"short": "RP", "emoji_id": 1414371825311420466},
            "Saarland": {"short": "SL", "emoji_id": 1414371868496105554},
            "Sachsen": {"short": "SN", "emoji_id": 1414371912649543680},
            "Sachsen-Anhalt": {"short": "ST", "emoji_id": 1414371958396551179},
            "Schleswig-Holstein": {"short": "SH", "emoji_id": 1414371999920160800},
            "Thüringen": {"short": "TH", "emoji_id": 1414372049979179091}
        }
    
    def parse_color(self, color_input: str, default: Union[tuple, str]) -> Union[tuple, str]:
        """Parse color input (name, hex, or RGB) and return appropriate format."""
        if not color_input or not color_input.strip():
            return default
        
        color_input = color_input.strip().lower()
        
        # Check if it's a named color
        if color_input in self.COLOR_DICTIONARY:
            # Return RGB for tuple defaults, hex for string defaults
            if isinstance(default, tuple):
                return self.COLOR_DICTIONARY[color_input][1]  # RGB
            else:
                return self.COLOR_DICTIONARY[color_input][0]  # Hex
        
        # Check if it's a hex color
        if color_input.startswith('#') and len(color_input) == 7:
            if isinstance(default, tuple):
                # Convert hex to RGB
                try:
                    hex_val = color_input[1:]
                    r = int(hex_val[0:2], 16)
                    g = int(hex_val[2:4], 16)
                    b = int(hex_val[4:6], 16)
                    return (r, g, b)
                except:
                    return default
            else:
                return color_input.upper()
        
        # Check if it's RGB format (for tuple defaults only)
        if isinstance(default, tuple) and ',' in color_input:
            try:
                parts = [int(x.strip()) for x in color_input.split(',')]
                if len(parts) == 3 and all(0 <= x <= 255 for x in parts):
                    return tuple(parts)
            except:
                pass
        
        return default
    
    def get_line_widths(self, width: int, map_type: str = "default") -> Tuple[int, int, int]:
        """Calculate line widths based on image width and map type."""
        if map_type == "world":
            river_width = max(1, int(width / 3000)) * self.RIVER_WIDTH_BASE
            country_width = max(1, int(width / 1500)) * self.COUNTRY_WIDTH_BASE
            state_width = 0
        elif map_type == "europe":
            river_width = max(1, int(width / 2000)) * self.RIVER_WIDTH_BASE
            country_width = max(1, int(width / 1000)) * self.COUNTRY_WIDTH_BASE
            state_width = 0
        elif map_type == "proximity":
            river_width = max(1, int(width / 800)) * self.RIVER_WIDTH_BASE
            country_width = max(2, int(width / 400)) * self.COUNTRY_WIDTH_BASE
            state_width = max(1, int(width / 800)) * self.STATE_WIDTH_BASE
        else:  # germany, closeups
            river_width = max(2, int(width / 1200)) * self.RIVER_WIDTH_BASE
            country_width = max(2, int(width / 600)) * self.COUNTRY_WIDTH_BASE
            state_width = max(1, int(width / 1200)) * self.STATE_WIDTH_BASE
        
        return river_width, country_width, state_width
