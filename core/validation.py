# core/validation.py
import os
import re
import logging
from typing import Dict, List, Tuple, Union, Any, Optional
from pathlib import Path
import feedparser
import requests

log = logging.getLogger("tausendsassa.validation")

class ValidationError(Exception):
    """Custom exception for validation errors"""
    pass

class ConfigValidator:
    """Validates bot configuration and provides helpful error messages"""
    
    @staticmethod
    def validate_discord_token(token: str) -> Tuple[bool, str]:
        """Validate Discord bot token format"""
        if not token:
            return False, "Discord token is required. Set DISCORD_TOKEN environment variable."
        
        # Basic Discord token format validation
        # Discord tokens are typically base64 encoded and contain dots
        if len(token) < 50:
            return False, "Discord token appears to be too short. Check your DISCORD_TOKEN."
        
        if not re.match(r'^[A-Za-z0-9._-]+$', token):
            return False, "Discord token contains invalid characters."
        
        # More specific validation for bot tokens
        parts = token.split('.')
        if len(parts) != 3:
            return False, "Discord token format is invalid. Bot tokens should have 3 parts separated by dots."
        
        return True, "Discord token format is valid."
    
    @staticmethod
    def validate_webhook_url(url: str) -> Tuple[bool, str]:
        """Validate Discord webhook URL"""
        if not url:
            return True, "Webhook URL is optional."
        
        webhook_pattern = r'^https://discord\.com/api/webhooks/\d+/[A-Za-z0-9_-]+$'
        if not re.match(webhook_pattern, url):
            return False, (
                "Invalid webhook URL format. Should be: "
                "https://discord.com/api/webhooks/WEBHOOK_ID/WEBHOOK_TOKEN"
            )
        
        return True, "Webhook URL format is valid."
    
    @staticmethod
    def validate_numeric_config(value: str, name: str, min_val: int = 0, max_val: int = None) -> Tuple[bool, str]:
        """Validate numeric configuration values"""
        try:
            num_val = int(value) if isinstance(value, str) else value
            
            if num_val < min_val:
                return False, f"{name} must be at least {min_val}, got {num_val}."
            
            if max_val is not None and num_val > max_val:
                return False, f"{name} must be at most {max_val}, got {num_val}."
            
            return True, f"{name} is valid ({num_val})."
            
        except (ValueError, TypeError):
            return False, f"{name} must be a valid integer, got '{value}'."
    
    @staticmethod
    def validate_user_ids(user_ids_str: str) -> Tuple[bool, str]:
        """Validate comma-separated user IDs"""
        if not user_ids_str.strip():
            return False, "At least one authorized user ID is required."
        
        try:
            user_ids = [int(uid.strip()) for uid in user_ids_str.split(",") if uid.strip()]
            
            if not user_ids:
                return False, "No valid user IDs found."
            
            # Discord user IDs should be 17-19 digits (snowflakes)
            invalid_ids = [uid for uid in user_ids if len(str(uid)) < 17 or len(str(uid)) > 19]
            if invalid_ids:
                return False, f"Invalid user IDs (should be 17-19 digits): {invalid_ids}"
            
            return True, f"Found {len(user_ids)} valid authorized user IDs."
            
        except ValueError as e:
            return False, f"User IDs must be numeric values separated by commas: {e}"
    
    @staticmethod
    def validate_directory_permissions(path: str) -> Tuple[bool, str]:
        """Validate directory exists and is writable"""
        try:
            dir_path = Path(path)
            
            if not dir_path.exists():
                # Try to create it
                dir_path.mkdir(parents=True, exist_ok=True)
                return True, f"Created directory: {path}"
            
            if not dir_path.is_dir():
                return False, f"Path exists but is not a directory: {path}"
            
            # Test write permissions
            test_file = dir_path / ".write_test"
            try:
                test_file.touch()
                test_file.unlink()
                return True, f"Directory is writable: {path}"
            except PermissionError:
                return False, f"Directory is not writable: {path}"
                
        except Exception as e:
            return False, f"Error validating directory {path}: {e}"
    
    @staticmethod
    async def validate_rss_feed(feed_url: str, timeout: int = 30) -> Tuple[bool, str]:
        """Validate RSS feed URL by attempting to fetch and parse it"""
        if not feed_url:
            return False, "Feed URL is required."
        
        # Basic URL format validation
        if not feed_url.startswith(('http://', 'https://')):
            return False, "Feed URL must start with http:// or https://"
        
        try:
            # Try to fetch and parse the feed
            response = requests.get(feed_url, timeout=timeout, headers={
                'User-Agent': 'Tausendsassa-Bot/1.0 (Feed Validator)'
            })
            response.raise_for_status()
            
            # Parse the feed
            feed = feedparser.parse(response.content)
            
            if hasattr(feed, 'bozo') and feed.bozo:
                if hasattr(feed, 'bozo_exception'):
                    return False, f"Feed parsing error: {feed.bozo_exception}"
                return False, "Feed format is invalid or malformed."
            
            if not hasattr(feed, 'feed') or not feed.feed:
                return False, "No feed data found. This may not be a valid RSS/Atom feed."
            
            entry_count = len(feed.entries) if hasattr(feed, 'entries') else 0
            feed_title = getattr(feed.feed, 'title', 'Unknown')
            
            return True, f"Valid feed: '{feed_title}' with {entry_count} entries."
            
        except requests.RequestException as e:
            return False, f"Could not fetch feed: {e}"
        except Exception as e:
            return False, f"Error validating feed: {e}"
    
    @staticmethod
    def validate_geocoding_location(location: str) -> Tuple[bool, str]:
        """Validate location string for geocoding"""
        if not location or not location.strip():
            return False, "Location cannot be empty."
        
        if len(location) < 2:
            return False, "Location must be at least 2 characters long."
        
        if len(location) > 200:
            return False, "Location must be less than 200 characters."
        
        # Check for potentially problematic characters
        if re.search(r'[<>"\']', location):
            return False, "Location contains invalid characters."
        
        return True, "Location format is valid."

class SystemValidator:
    """Validates system requirements and dependencies"""
    
    @staticmethod
    def validate_python_version() -> Tuple[bool, str]:
        """Validate Python version requirements"""
        import sys
        
        version = sys.version_info
        if version.major < 3 or (version.major == 3 and version.minor < 8):
            return False, f"Python 3.8+ required, found {version.major}.{version.minor}.{version.micro}"
        
        return True, f"Python version is compatible: {version.major}.{version.minor}.{version.micro}"
    
    @staticmethod
    def validate_required_packages() -> Tuple[bool, str, List[str]]:
        """Validate that required packages are installed"""
        required_packages = {
            'discord': 'discord.py',
            'aiohttp': 'aiohttp',
            'feedparser': 'feedparser',
            'geopandas': 'geopandas',
            'psutil': 'psutil',
            'requests': 'requests',
            'yaml': 'PyYAML',
            'PIL': 'Pillow'
        }
        
        missing_packages = []
        for import_name, package_name in required_packages.items():
            try:
                __import__(import_name)
            except ImportError:
                missing_packages.append(package_name)
        
        if missing_packages:
            return False, f"Missing required packages: {', '.join(missing_packages)}", missing_packages
        
        return True, "All required packages are installed.", []
    
    @staticmethod
    def validate_geospatial_data(data_dir: Path) -> Tuple[bool, str]:
        """Validate that required geospatial data files exist"""
        required_files = [
            "ne_10m_admin_0_countries.shp",
            "ne_10m_admin_1_states_provinces.shp",
            "ne_10m_land.shp",
            "ne_10m_lakes.shp"
        ]
        
        missing_files = []
        for filename in required_files:
            file_path = data_dir / filename
            if not file_path.exists():
                missing_files.append(filename)
        
        if missing_files:
            return False, (
                f"Missing geospatial data files: {', '.join(missing_files)}. "
                f"Download from Natural Earth and extract to {data_dir}/"
            )
        
        return True, "All required geospatial data files are present."

def run_full_validation() -> Dict[str, Any]:
    """Run complete validation and return results"""
    results = {
        "valid": True,
        "errors": [],
        "warnings": [],
        "info": []
    }
    
    def add_result(is_valid: bool, message: str, category: str = "error"):
        if not is_valid:
            results["valid"] = False
            results["errors"].append(message)
        else:
            results["info"].append(message)
    
    # System validation
    valid, msg = SystemValidator.validate_python_version()
    add_result(valid, f"Python Version: {msg}")
    
    valid, msg, missing = SystemValidator.validate_required_packages()
    add_result(valid, f"Required Packages: {msg}")
    
    # Configuration validation
    token = os.getenv("DISCORD_TOKEN", "")
    valid, msg = ConfigValidator.validate_discord_token(token)
    add_result(valid, f"Discord Token: {msg}")
    
    webhook_url = os.getenv("LOG_WEBHOOK_URL", "")
    if webhook_url:
        valid, msg = ConfigValidator.validate_webhook_url(webhook_url)
        add_result(valid, f"Webhook URL: {msg}")
    
    # User IDs validation
    user_ids = os.getenv("AUTHORIZED_USERS", "")
    if user_ids:
        valid, msg = ConfigValidator.validate_user_ids(user_ids)
        add_result(valid, f"Authorized Users: {msg}")
    
    # Directory validation
    for dir_name in ["logs", "config", "data"]:
        valid, msg = ConfigValidator.validate_directory_permissions(dir_name)
        add_result(valid, f"Directory {dir_name}: {msg}")
    
    # Geospatial data validation
    data_dir = Path("data")
    valid, msg = SystemValidator.validate_geospatial_data(data_dir)
    add_result(valid, f"Geospatial Data: {msg}")
    
    return results

def log_validation_results(results: Dict[str, Any]):
    """Log validation results with appropriate levels"""
    if results["valid"]:
        log.info("✅ All validations passed successfully!")
    else:
        log.error("❌ Configuration validation failed!")
    
    for error in results["errors"]:
        log.error(f"  ❌ {error}")
    
    for warning in results["warnings"]:
        log.warning(f"  ⚠️ {warning}")
    
    for info in results["info"]:
        log.info(f"  ✅ {info}")
    
    if not results["valid"]:
        log.error("Please fix the above issues before starting the bot.")