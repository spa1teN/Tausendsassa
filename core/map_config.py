"""Central configuration for the Discord Map Bot."""

from typing import Union, Tuple, Dict
import math
import geopandas as gpd
from pathlib import Path


class MapConfig:
    """Central configuration for map appearance and behavior."""
    
    def __init__(self):
        # Line widths - REDUCED for better geographic scaling
        self.RIVER_WIDTH_BASE = 1  # Reduced from 2
        self.COUNTRY_WIDTH_BASE = 1  # Reduced from 3  
        self.STATE_WIDTH_BASE = 1   # Reduced from 2
        
        # Default colors
        self.DEFAULT_LAND_COLOR = (240, 240, 220)
        self.DEFAULT_WATER_COLOR = (168, 213, 242)
        self.DEFAULT_PIN_COLOR = '#FF4444'
        self.DEFAULT_PIN_SIZE = 16
        self.DEFAULT_COUNTRY_BORDER_COLOR = (0, 0, 0)
        self.DEFAULT_RIVER_COLOR = (60, 60, 200)
        
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
            },
            # European countries
            "france": {
                "bounds": [[41.0, -5.5], [51.5, 9.5]]
            },
            "spain": {
                "bounds": [[35.0, -10.0], [44.0, 5.0]]
            },
            "italy": {
                "bounds": [[35.5, 6.0], [47.5, 19.0]]
            },
            "poland": {
                "bounds": [[49.0, 14.0], [55.0, 24.5]]
            },
            "netherlands": {
                "bounds": [[50.5, 3.0], [54.0, 7.5]]
            },
            "belgium": {
                "bounds": [[49.0, 2.0], [52.0, 6.5]]
            },
            "austria": {
                "bounds": [[46.0, 9.0], [49.5, 17.5]]
            },
            "czech": {
                "bounds": [[48.0, 12.0], [51.5, 19.0]]
            },
            "hungary": {
                "bounds": [[45.5, 16.0], [48.5, 23.0]]
            },
            "portugal": {
                "bounds": [[36.0, -10.0], [42.5, -6.0]]
            },
            "greece": {
                "bounds": [[34.5, 19.0], [42.0, 29.0]]
            },
            "sweden": {
                "bounds": [[55.0, 10.0], [69.5, 25.0]]
            },
            "norway": {
                "bounds": [[57.5, 4.0], [71.5, 32.0]]
            },
            "denmark": {
                "bounds": [[54.0, 7.0], [58.0, 16.0]]
            },
            "finland": {
                "bounds": [[59.5, 19.0], [70.5, 32.0]]
            },
            "romania": {
                "bounds": [[43.5, 20.0], [48.5, 30.0]]
            },
            "bulgaria": {
                "bounds": [[41.0, 22.0], [44.5, 29.0]]
            },
            "croatia": {
                "bounds": [[42.0, 13.0], [46.5, 19.5]]
            },
            "slovenia": {
                "bounds": [[45.0, 13.0], [47.0, 16.5]]
            },
            "slovakia": {
                "bounds": [[47.5, 16.5], [49.5, 22.5]]
            },
            "ireland": {
                "bounds": [[51.0, -11.0], [55.5, -5.5]]
            },
            "lithuania": {
                "bounds": [[53.5, 20.5], [56.5, 27.0]]
            },
            "latvia": {
                "bounds": [[55.5, 20.5], [58.5, 28.5]]
            },
            "estonia": {
                "bounds": [[57.5, 21.5], [59.5, 28.5]]
            },
            "luxembourg": {
                "bounds": [[49.0, 5.5], [50.5, 6.5]]
            },
            "malta": {
                "bounds": [[35.7, 14.0], [36.2, 14.8]]
            },
            "cyprus": {
                "bounds": [[34.5, 32.0], [35.8, 34.8]]
            },
            # Other European countries
            "switzerland": {
                "bounds": [[45.5, 5.5], [48.0, 11.0]]
            },
            "ukraine": {
                "bounds": [[44.0, 22.0], [53.0, 41.0]]
            },
            "russia": {
                "bounds": [[41.0, 19.0], [82.0, 180.0]]
            },
            "turkey": {
                "bounds": [[35.5, 25.5], [42.5, 45.0]]
            },
            "unitedkingdom": {
                "bounds": [[49.0, -8.0], [61.0, 2.0]]
            },
            # Asian countries
            "japan": {
                "bounds": [[24.0, 123.0], [46.0, 146.0]]
            },
            "southkorea": {
                "bounds": [[33.0, 124.5], [39.0, 132.0]]
            },
            # American countries
            "brazil": {
                "bounds": [[-34.0, -74.5], [6.0, -34.0]]
            },
            "canada": {
                "bounds": [[42.0, -141.0], [84.0, -52.0]]
            },
            "mexico": {
                "bounds": [[14.0, -118.0], [33.0, -86.0]]
            }
        }
        
        # Country names mapping for shapefile lookup
        self.COUNTRY_NAME_MAPPING = {
            "france": "France",
            "spain": "Spain", 
            "italy": "Italy",
            "poland": "Poland",
            "netherlands": "Netherlands",
            "belgium": "Belgium",
            "austria": "Austria",
            "czech": "Czech Republic",
            "hungary": "Hungary",
            "portugal": "Portugal",
            "greece": "Greece",
            "sweden": "Sweden",
            "norway": "Norway",
            "denmark": "Denmark",
            "finland": "Finland",
            "romania": "Romania",
            "bulgaria": "Bulgaria",
            "croatia": "Croatia",
            "slovenia": "Slovenia",
            "slovakia": "Slovakia",
            "ireland": "Ireland",
            "lithuania": "Lithuania",
            "latvia": "Latvia",
            "estonia": "Estonia",
            "luxembourg": "Luxembourg",
            "malta": "Malta",
            "cyprus": "Cyprus",
            "switzerland": "Switzerland",
            "ukraine": "Ukraine", 
            "russia": "Russia",
            "turkey": "Turkey",
            "unitedkingdom": "United Kingdom",
            "japan": "Japan",
            "southkorea": "South Korea",
            "brazil": "Brazil",
            "canada": "Canada",
            "mexico": "Mexico"
        }
        
        # Color dictionary
        self.COLOR_DICTIONARY = {
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
            'lime': ('#00FF00', (0, 255, 0)),
            'navy': ('#000080', (0, 0, 128)),
            'teal': ('#008080', (0, 128, 128)),
            'olive': ('#808000', (128, 128, 0)),
            'maroon': ('#800000', (128, 0, 0)),
            'aqua': ('#00FFFF', (0, 255, 255)),
            'lightblue': ('#ADD8E6', (173, 216, 230)),
            'lightgreen': ('#90EE90', (144, 238, 144)),
            'lightgray': ('#D3D3D3', (211, 211, 211)),
            'lightgrey': ('#D3D3D3', (211, 211, 211)),
            'lightyellow': ('#FFFFE0', (255, 255, 224)),
            'lightpink': ('#FFB6C1', (255, 182, 193)),
            'darkblue': ('#00008B', (0, 0, 139)),
            'darkgreen': ('#006400', (0, 100, 0)),
            'darkgray': ('#A9A9A9', (169, 169, 169)),
            'darkgrey': ('#A9A9A9', (169, 169, 169)),
            'darkred': ('#8B0000', (139, 0, 0)),
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
        
        # Country to flag emoji mapping
        self.COUNTRY_FLAG_EMOJIS = {
            "france": "🇫🇷",
            "spain": "🇪🇸", 
            "italy": "🇮🇹",
            "poland": "🇵🇱",
            "netherlands": "🇳🇱",
            "belgium": "🇧🇪",
            "austria": "🇦🇹",
            "czech": "🇨🇿",
            "hungary": "🇭🇺",
            "portugal": "🇵🇹",
            "greece": "🇬🇷",
            "sweden": "🇸🇪",
            "norway": "🇳🇴",
            "denmark": "🇩🇰",
            "finland": "🇫🇮",
            "romania": "🇷🇴",
            "bulgaria": "🇧🇬",
            "croatia": "🇭🇷",
            "slovenia": "🇸🇮",
            "slovakia": "🇸🇰",
            "ireland": "🇮🇪",
            "lithuania": "🇱🇹",
            "latvia": "🇱🇻",
            "estonia": "🇪🇪",
            "luxembourg": "🇱🇺",
            "malta": "🇲🇹",
            "cyprus": "🇨🇾",
            "switzerland": "🇨🇭",
            "ukraine": "🇺🇦",
            "russia": "🇷🇺",
            "turkey": "🇹🇷",
            "unitedkingdom": "🇬🇧",
            "germany": "🇩🇪",
            "japan": "🇯🇵",
            "southkorea": "🇰🇷",
            "brazil": "🇧🇷",
            "canada": "🇨🇦",
            "mexico": "🇲🇽",
            "usmainland": "🇺🇸",
            # Continents get general emojis
            "world": "🌍",
            "europe": "🇪🇺",
            "asia": "🌏",
            "africa": "🌍",
            "northamerica": "🌎",
            "southamerica": "🌎",
            "australia": "🇦🇺"
        }
        
        # German states with emoji IDs
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
    
    def calculate_geographic_scale_factor(self, region: str, custom_bounds: Tuple[float, float, float, float] = None) -> float:
        """Calculate geographic scale factor relative to Germany (reference = 1.0).
        
        This ensures line widths are proportional to the geographic area being displayed,
        not just the image size. Germany serves as the baseline with factor 1.0.
        
        Uses a gentler logarithmic scaling to avoid overly thin lines.
        """
        # Germany bounds as reference
        germany_bounds = self.MAP_REGIONS["germany"]["bounds"]
        germany_lat_range = germany_bounds[1][0] - germany_bounds[0][0]  # max_lat - min_lat
        germany_lng_range = germany_bounds[1][1] - germany_bounds[0][1]  # max_lng - min_lng
        
        # Calculate approximate area (lat * lng) for Germany
        # Use middle latitude for more accurate longitude scaling
        germany_center_lat = (germany_bounds[0][0] + germany_bounds[1][0]) / 2
        germany_lng_corrected = germany_lng_range * math.cos(math.radians(germany_center_lat))
        germany_area = germany_lat_range * germany_lng_corrected
        
        # Get bounds for target region
        if custom_bounds:
            min_lat, min_lng, max_lat, max_lng = custom_bounds
            target_bounds = [[min_lat, min_lng], [max_lat, max_lng]]
        elif region in self.MAP_REGIONS:
            target_bounds = self.MAP_REGIONS[region]["bounds"]
        else:
            # Fallback to Germany for unknown regions
            return 1.0
        
        # Calculate area for target region
        target_lat_range = target_bounds[1][0] - target_bounds[0][0]
        target_lng_range = target_bounds[1][1] - target_bounds[0][1]
        
        # Use middle latitude for longitude correction
        target_center_lat = (target_bounds[0][0] + target_bounds[1][0]) / 2
        target_lng_corrected = target_lng_range * math.cos(math.radians(target_center_lat))
        target_area = target_lat_range * target_lng_corrected
        
        # Calculate area ratio
        area_ratio = target_area / germany_area
        
        # Use gentler logarithmic scaling instead of square root
        # This prevents overly aggressive line thinning for large regions
        if area_ratio > 1.0:
            # For larger regions, use log scaling: 1 + log10(ratio) * 0.5
            scale_factor = 1.0 + math.log10(area_ratio) * 0.5
        else:
            # For smaller regions, use linear scaling
            scale_factor = area_ratio
        
        # Apply reasonable limits to prevent extreme scaling
        scale_factor = max(0.3, min(scale_factor, 8.0))
        
        return scale_factor
    
    def get_country_bounds_from_shapefile(self, country_key: str, data_path: Path = None) -> Union[Tuple[Tuple[float, float], Tuple[float, float]], None]:
        """Get country bounds from shapefile data with padding."""
        try:
            if data_path is None:
                data_path = Path(__file__).parent.parent / "cogs/map_data"
            
            # Skip if no mapping available
            if country_key not in self.COUNTRY_NAME_MAPPING:
                return None
                
            country_name = self.COUNTRY_NAME_MAPPING[country_key]
            
            # Load the world countries shapefile
            world_file = data_path / "ne_10m_admin_0_countries.shp"
            if not world_file.exists():
                return None
                
            world = gpd.read_file(world_file)
            
            # Special handling for Ukraine - include all territories (including Crimea)
            if country_key == 'ukraine':
                country_rows = world[world["SOVEREIGNT"] == country_name]
            else:
                # For countries with overseas territories, use ADMIN == country_name to get mainland only
                # This excludes dependencies that have different ADMIN names
                country_rows = world[world["ADMIN"] == country_name]
                
                # Additional filter: exclude very small or distant territories
                if not country_rows.empty and len(country_rows) > 1:
                    # If multiple rows, keep only the largest by area
                    country_rows['area'] = country_rows.geometry.area
                    largest_idx = country_rows['area'].idxmax()
                    country_rows = country_rows.loc[[largest_idx]]
            
            if country_rows.empty:
                return None
            
            # Get geometry and bounds
            country_geom = country_rows.geometry.unary_union
            bounds = country_geom.bounds
            minx, miny, maxx, maxy = bounds
            
            # Add padding (5% of the range) so countries don't touch edges
            width_range = maxx - minx
            height_range = maxy - miny
            padding_x = width_range * 0.05
            padding_y = height_range * 0.05
            
            minx -= padding_x
            maxx += padding_x
            miny -= padding_y
            maxy += padding_y
            
            return [[miny, minx], [maxy, maxx]]  # Return in the expected [[lat0, lon0], [lat1, lon1]] format
            
        except Exception as e:
            # Return None if any error occurs, will fall back to hardcoded bounds
            return None
    
    def get_region_bounds(self, region_key: str, data_path: Path = None) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        """Get region bounds, using hardcoded values for countries with overseas territories."""
        # Countries with problematic overseas territories - use hardcoded bounds
        overseas_territory_countries = {'france', 'spain', 'unitedkingdom', 'netherlands', 'denmark', 'portugal'}
        
        # For countries without overseas territory issues, try shapefile first
        if (region_key in self.COUNTRY_NAME_MAPPING and 
            region_key not in overseas_territory_countries):
            shapefile_bounds = self.get_country_bounds_from_shapefile(region_key, data_path)
            if shapefile_bounds:
                return shapefile_bounds
        
        # Fall back to hardcoded bounds (used for overseas territory countries and fallback)
        if region_key in self.MAP_REGIONS:
            return self.MAP_REGIONS[region_key]["bounds"]
        
        # Default fallback to world bounds
        return self.MAP_REGIONS["world"]["bounds"]
    
    def parse_color(self, color_input: str, default: Union[tuple, str]) -> Union[tuple, str]:
        """Parse color input and return appropriate format."""
        if not color_input or not color_input.strip():
            return default
        
        color_input = color_input.strip().lower()
        
        if color_input in self.COLOR_DICTIONARY:
            if isinstance(default, tuple):
                return self.COLOR_DICTIONARY[color_input][1]
            else:
                return self.COLOR_DICTIONARY[color_input][0]
        
        if color_input.startswith('#') and len(color_input) == 7:
            if isinstance(default, tuple):
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
        
        if isinstance(default, tuple) and ',' in color_input:
            try:
                parts = [int(x.strip()) for x in color_input.split(',')]
                if len(parts) == 3 and all(0 <= x <= 255 for x in parts):
                    return tuple(parts)
            except:
                pass
        
        return default
    
    def get_line_widths(self, width: int, map_type: str = "default", region: str = None, custom_bounds: Tuple[float, float, float, float] = None) -> Tuple[int, int, int]:
        """Calculate line widths based on image width, map type, and geographic scale.
        
        Now considers the geographic extent of the map region to ensure consistent
        visual proportions across different map scales. Germany serves as the reference.
        """
        # Calculate geographic scale factor
        if region or custom_bounds:
            geo_scale = self.calculate_geographic_scale_factor(region, custom_bounds)
        else:
            # Fallback to old behavior for legacy calls
            geo_scale = 1.0
        
        # Special handling for Germany to maintain original line thickness
        if region == "germany":
            # Germany keeps thicker lines regardless of geographic scale
            base_divisor_river = 400   # Even thicker (was 600)
            base_divisor_country = 200 # Even thicker (was 300) 
            base_divisor_state = 400   # Even thicker (was 600)
            river_width = max(2, int(width / base_divisor_river)) * self.RIVER_WIDTH_BASE
            country_width = max(2, int(width / base_divisor_country)) * self.COUNTRY_WIDTH_BASE
            state_width = max(1, int(width / base_divisor_state)) * self.STATE_WIDTH_BASE
        elif map_type == "world":
            # World maps need extra thin lines due to large geographic area
            # Apply additional 0.5x factor to make them even thinner
            base_divisor_river = 3000
            base_divisor_country = 1500
            river_width = max(1, int(width / (base_divisor_river * geo_scale * 2.0))) * self.RIVER_WIDTH_BASE  # 2.0 = extra thinning
            country_width = max(1, int(width / (base_divisor_country * geo_scale * 2.0))) * self.COUNTRY_WIDTH_BASE  # 2.0 = extra thinning
            state_width = 0  # No state borders on world maps
        elif map_type == "europe":
            # Europe maps get moderate scaling
            base_divisor_river = 2000
            base_divisor_country = 1000
            river_width = max(1, int(width / (base_divisor_river * geo_scale))) * self.RIVER_WIDTH_BASE
            country_width = max(1, int(width / (base_divisor_country * geo_scale))) * self.COUNTRY_WIDTH_BASE
            state_width = 0  # No state borders on Europe maps for cleaner look
        elif map_type == "proximity":
            # Proximity maps should have thinner lines for better visibility
            base_divisor_river = 1200  # Increased from 800 to make lines thinner
            base_divisor_country = 800  # Increased from 400 to make lines thinner
            base_divisor_state = 1200   # Increased from 800 to make lines thinner
            river_width = max(1, int(width / (base_divisor_river * geo_scale))) * self.RIVER_WIDTH_BASE
            country_width = max(1, int(width / (base_divisor_country * geo_scale))) * self.COUNTRY_WIDTH_BASE
            state_width = max(1, int(width / (base_divisor_state * geo_scale))) * self.STATE_WIDTH_BASE
        else:  # default, state_closeup
            # Default scaling with geographic awareness
            base_divisor_river = 1200
            base_divisor_country = 600
            base_divisor_state = 1200
            river_width = max(1, int(width / (base_divisor_river * geo_scale))) * self.RIVER_WIDTH_BASE
            country_width = max(1, int(width / (base_divisor_country * geo_scale))) * self.COUNTRY_WIDTH_BASE
            state_width = max(1, int(width / (base_divisor_state * geo_scale))) * self.STATE_WIDTH_BASE
        
        # Ensure minimum line widths for visibility
        river_width = max(1, river_width)
        country_width = max(1, country_width)
        state_width = max(1, state_width)
        
        return river_width, country_width, state_width