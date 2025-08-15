# cogs/monitor.py
import discord
from discord.ext import commands
from discord import app_commands
import psutil
import platform
import subprocess
import os
import time
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import logging
import io
import json
from pathlib import Path

BOT_OWNER_ID = 485051896655249419

class FileSelect(discord.ui.Select):
    """Select menu for choosing files to download"""
    
    def __init__(self, available_files: List[Dict[str, str]]):
        self.available_files = {file['value']: file['path'] for file in available_files}
        
        options = [
            discord.SelectOption(
                label=file['label'],
                description=file['description'],
                value=file['value'],
                emoji=file['emoji']
            )
            for file in available_files[:25]  # Discord limit
        ]
        
        super().__init__(
            placeholder="Choose files to download...",
            min_values=1,
            max_values=min(len(options), 10),  # Allow up to 10 files
            options=options
        )
    
    async def callback(self, interaction: discord.Interaction):
        """Handle file selection"""
        await interaction.response.defer(ephemeral=True)
        
        try:
            files_to_send = []
            
            for selected_value in self.values:
                file_path = self.available_files.get(selected_value)
                
                if not file_path or not os.path.exists(file_path):
                    continue
                
                # Check file size (Discord limit: 25MB for non-nitro, 500MB for nitro)
                file_size = os.path.getsize(file_path)
                if file_size > 24 * 1024 * 1024:  # 24MB to be safe
                    await interaction.followup.send(
                        f"❌ File `{file_path}` is too large ({file_size / (1024*1024):.1f}MB). "
                        f"Discord limit is 25MB.",
                        ephemeral=True
                    )
                    continue
                
                # Read and prepare file
                try:
                    with open(file_path, 'rb') as f:
                        file_content = f.read()
                    
                    # Get just the filename for Discord
                    filename = os.path.basename(file_path)
                    discord_file = discord.File(
                        io.BytesIO(file_content),
                        filename=filename
                    )
                    files_to_send.append(discord_file)
                    
                except Exception as e:
                    await interaction.followup.send(
                        f"❌ Error reading file `{file_path}`: {str(e)}",
                        ephemeral=True
                    )
                    continue
            
            if not files_to_send:
                await interaction.followup.send(
                    "❌ No valid files found to send.",
                    ephemeral=True
                )
                return
            
            # Send files
            selected_names = [os.path.basename(self.available_files[v]) for v in self.values]
            await interaction.followup.send(
                f"📁 Here are your requested files: {', '.join(selected_names)}",
                files=files_to_send,
                ephemeral=True
            )
            
        except Exception as e:
            await interaction.followup.send(
                f"❌ Error preparing files: {str(e)}",
                ephemeral=True
            )

class MonitorView(discord.ui.View):
    """View for monitoring interactions with file download functionality"""
    
    def __init__(self, bot: commands.Bot, authorized_roles: List[int]):
        super().__init__(timeout=300)  # 5 minutes timeout
        self.bot = bot
        self.authorized_roles = authorized_roles
        
        # Add file select menu
        available_files = self._get_available_files()
        if available_files:
            self.add_item(FileSelect(available_files))
    
    def has_permission(self, user: discord.Member) -> bool:
        """Check if user has permission to download files"""
        return any(role.id in self.authorized_roles for role in user.roles)
    
    def _get_available_files(self) -> List[Dict[str, str]]:
        """Get list of available files for download"""
        files = []
        
        # Main bot file
        if os.path.exists('bot.py'):
            files.append({
                'label': 'bot.py',
                'description': 'Main bot file',
                'value': 'bot_py',
                'emoji': '🤖',
                'path': 'bot.py'
            })
        
        # Config files
        config_files = [
            ('config.yaml', 'YAML configuration file'),
            ('config.yml', 'YAML configuration file'),
            ('requirements.txt', 'Python dependencies'),
            ('.env.example', 'Environment variables example')
        ]
        
        for filename, description in config_files:
            if os.path.exists(filename):
                files.append({
                    'label': filename,
                    'description': description,
                    'value': filename.replace('.', '_'),
                    'emoji': '⚙️',
                    'path': filename
                })
        
        # Cog files
        if os.path.exists('cogs'):
            for file in os.listdir('cogs'):
                if file.endswith('.py') and not file.startswith('__'):
                    files.append({
                        'label': f'cogs/{file}',
                        'description': f'{file.replace(".py", "").title()} cog',
                        'value': f'cogs_{file.replace(".", "_")}',
                        'emoji': '🧩',
                        'path': f'cogs/{file}'
                    })

        # Core Files
        if os.path.exists('core'):
            for file in os.listdir('core'):
                if file.endswith('.py') and not file.startswith('__'):
                    files.append({
                        'label': f'core/{file}',
                        'description': f'{file.replace(".py", "").title()} cog',
                        'value': f'core_{file.replace(".", "_")}',
                        'emoji': '🔨',
                        'path': f'core/{file}'
                    })
                    
        # Recent log files (last 3 days)
        if os.path.exists('logs'):
            current_time = time.time()
            for file in os.listdir('logs'):
                if file.endswith('.log'):
                    file_path = f'logs/{file}'
                    if os.path.getmtime(file_path) > current_time - (3 * 24 * 3600):
                        # Get file size for description
                        size = os.path.getsize(file_path)
                        size_str = self._format_file_size(size)
                        files.append({
                            'label': f'logs/{file}',
                            'description': f'Log file ({size_str})',
                            'value': f'logs_{file.replace(".", "_")}',
                            'emoji': '📋',
                            'path': file_path
                        })
        
        return files
    
    def _format_file_size(self, size_bytes: int) -> str:
        """Format file size in human readable format"""
        if size_bytes == 0:
            return "0B"
        size_names = ["B", "KB", "MB", "GB"]
        i = 0
        while size_bytes >= 1024 and i < len(size_names) - 1:
            size_bytes /= 1024.0
            i += 1
        return f"{size_bytes:.1f}{size_names[i]}"
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Check if user has permission before any interaction"""
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "❌ This command can only be used in a server.", 
                ephemeral=True
            )
            return False
            
        if not self.has_permission(interaction.user):
            await interaction.response.send_message(
                "❌ You don't have permission to download bot files.", 
                ephemeral=True
            )
            return False
        
        return True

class Monitor(commands.Cog):
    """Monitor cog for system and bot health monitoring"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.log = bot.get_cog_logger("monitor")
        
        # Configuration - adjust these role IDs for your server
        self.authorized_roles = [
            1402526603057303653,
            1398500235541610639
        ]
        
        # System monitoring data storage
        self.cpu_history: List[float] = []
        self.ram_history: List[float] = []
        self.start_time = time.time()
        
        # Config file for storing message IDs and settings
        self.config_dir = Path("config")
        self.config_file = self.config_dir / "monitor_config.json"
        self.monitor_config = self.load_config()
        
        # Create config directory if it doesn't exist
        self.config_dir.mkdir(exist_ok=True)
        
        # Start monitoring task
        self.monitoring_task = None
        
        self.log.info("Monitor cog initialized")

    async def cog_load(self):
        """Start background task when cog is fully loaded"""
        self.monitoring_task = asyncio.create_task(self.collect_system_metrics())
        self.log.info("✅ Monitoring background task started")
        
    def load_config(self) -> Dict[str, Any]:
        """Load monitor configuration from file"""
        default_config = {
            "monitor_messages": {},  # channel_id: message_id
            "auto_update_interval": 300,  # 5 minutes
            "last_update": 0
        }
        
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    # Merge with defaults to ensure all keys exist
                    for key, value in default_config.items():
                        if key not in config:
                            config[key] = value
                    return config
            except Exception as e:
                self.log.error(f"Error loading monitor config: {e}")
        
        return default_config
    
    def save_config(self):
        """Save monitor configuration to file"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.monitor_config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.log.error(f"Error saving monitor config: {e}")
    
    def cog_unload(self):
        """Clean up when cog is unloaded"""
        if self.monitoring_task:
            self.monitoring_task.cancel()
        self.save_config()
        self.log.info("Monitor cog unloaded")
    
    async def collect_system_metrics(self):
        """Background task to collect system metrics and auto-update monitor messages"""
        self.log.info("🚀 Monitoring loop started")
        while True:
            try:
                self.log.debug("Collecting metrics...")
                # Collect CPU and RAM usage
                cpu_percent = psutil.cpu_percent(interval=1)
                ram_percent = psutil.virtual_memory().percent
                
                # Store in history (keep last hour = 60 samples)
                self.cpu_history.append(cpu_percent)
                self.ram_history.append(ram_percent)
                
                # Keep only last 60 minutes of data
                if len(self.cpu_history) > 60:
                    self.cpu_history.pop(0)
                if len(self.ram_history) > 60:
                    self.ram_history.pop(0)
                
                # Auto-update monitor messages if interval has passed
                current_time = time.time()
                if (current_time - self.monitor_config.get("last_update", 0) >= 
                    self.monitor_config.get("auto_update_interval", 300)):
                    
                    await self.auto_update_monitor_messages()
                    self.monitor_config["last_update"] = current_time
                    self.save_config()
                
                await asyncio.sleep(60)  # Collect every minute
                
            except Exception as e:
                self.log.error(f"Error collecting system metrics: {e}")
                await asyncio.sleep(60)
    
    async def auto_update_monitor_messages(self):
        """Automatically update existing monitor messages"""
        if time.time() - self.start_time < 120:
            self.log.debug("Skipping auto-update during 2min period after boot")
            return
        
        for channel_id, message_id in list(self.monitor_config["monitor_messages"].items()):
            try:
                channel = self.bot.get_channel(int(channel_id))
                if not channel:
                    # Channel not found, remove from config
                    del self.monitor_config["monitor_messages"][channel_id]
                    continue
                
                try:
                    message = await channel.fetch_message(int(message_id))
                    await self.update_monitor_message(message)
                except discord.NotFound:
                    # Message was deleted, remove from config
                    del self.monitor_config["monitor_messages"][channel_id]
                    self.log.info(f"Removed deleted monitor message from channel {channel_id}")
                except discord.Forbidden:
                    self.log.warning(f"No permission to update monitor message in channel {channel_id}")
                
            except Exception as e:
                self.log.error(f"Error auto-updating monitor message in channel {channel_id}: {e}")
    
    async def update_monitor_message(self, message: discord.Message):
        """Update an existing monitor message with fresh data"""
        try:
            # Generate fresh monitoring data
            embeds = await self.generate_monitor_embeds()
            view = MonitorView(self.bot, self.authorized_roles)
            
            # Update the message
            await message.edit(embeds=embeds, view=view)
            
        except Exception as e:
            self.log.error(f"Error updating monitor message: {e}")
            raise
    
    def get_device_info(self) -> Dict[str, Any]:
        """Get device information"""
        try:
            # System information
            uname = platform.uname()
            boot_time = psutil.boot_time()
            uptime = time.time() - boot_time
            
            # CPU information
            cpu_count = psutil.cpu_count()
            cpu_freq = psutil.cpu_freq()
            
            # Memory information
            memory = psutil.virtual_memory()
            
            # Disk information
            disk = psutil.disk_usage('/')
            
            # Calculate CPU/RAM stats
            cpu_max = max(self.cpu_history) if self.cpu_history else 0
            cpu_avg = sum(self.cpu_history) / len(self.cpu_history) if self.cpu_history else 0
            ram_max = max(self.ram_history) if self.ram_history else 0
            ram_avg = sum(self.ram_history) / len(self.ram_history) if self.ram_history else 0
            
            return {
                'device_name': uname.node,
                'system': f"{uname.system} {uname.release}",
                'architecture': uname.machine,
                'uptime_seconds': uptime,
                'cpu_count': cpu_count,
                'cpu_freq': cpu_freq.current if cpu_freq else None,
                'cpu_max_hour': cpu_max,
                'cpu_avg_hour': cpu_avg,
                'ram_total': memory.total,
                'ram_available': memory.available,
                'ram_max_hour': ram_max,
                'ram_avg_hour': ram_avg,
                'disk_total': disk.total,
                'disk_used': disk.used,
                'disk_free': disk.free
            }
        except Exception as e:
            self.log.error(f"Error getting device info: {e}")
            return {}
    
    def get_systemd_status(self) -> Dict[str, Any]:
        """Get systemd service status for the bot"""
        try:
            # Try to find the systemd service
            # Common service names - adjust as needed
            possible_services = ['tausendsassa', 'discord-bot', 'bot', 'rssbot']
            
            for service_name in possible_services:
                try:
                    result = subprocess.run(
                        ['systemctl', 'is-active', service_name],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    
                    if result.returncode == 0:  # Service found
                        # Get detailed status
                        status_result = subprocess.run(
                            ['systemctl', 'status', service_name, '--no-pager', '-l'],
                            capture_output=True,
                            text=True,
                            timeout=10
                        )
                        
                        return {
                            'service_name': service_name,
                            'status': result.stdout.strip(),
                            'details': status_result.stdout[:1000]  # Limit output
                        }
                except subprocess.TimeoutExpired:
                    continue
                except subprocess.CalledProcessError:
                    continue
            
            return {
                'service_name': 'unknown',
                'status': 'not found',
                'details': 'No systemd service found for common bot names'
            }
            
        except Exception as e:
            return {
                'service_name': 'error',
                'status': 'error',
                'details': f'Error checking systemd status: {e}'
            }
    
    def get_cog_info(self) -> List[Dict[str, Any]]:
        """Get information about loaded cogs"""
        cog_info = []
        
        for name, cog in self.bot.cogs.items():
            app_commands = 0
            if hasattr(cog, '__cog_app_commands__'):
                app_commands = len(cog.__cog_app_commands__)
            
            cog_info.append({
                'name': name,
                'active': True,
                'class_name': cog.__class__.__name__,
                'commands': app_commands
            })
        
        return cog_info
    
    def get_bot_info(self) -> Dict[str, Any]:
        """Get general bot information"""
        return {
            'guild_count': len(self.bot.guilds),
            'user_count': len(set(self.bot.get_all_members())),
            'command_count': len(self.bot.commands),
            'uptime_seconds': time.time() - self.start_time,
            'discord_py_version': discord.__version__,
            'python_version': platform.python_version()
        }
    
    def get_file_tree(self) -> str:
        """Get file tree structure"""
        try:
            # Use tree command if available
            try:
                result = subprocess.run(
                    ['tree', '.', '-I', '__pycache__|*.pyc|.git|.env|ne_10m*|ne_50m*|map_cache|data|__init__.py|info|*.yaml|*.json|config|*~'],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    cwd=os.getcwd()
                )
                if result.returncode == 0:
                    return result.stdout[:1500]  # Limit output
            except (subprocess.CalledProcessError, FileNotFoundError):
                pass
            
            # Fallback: manual tree generation
            def generate_tree(directory, prefix="", max_depth=3, current_depth=0):
                if current_depth >= max_depth:
                    return ""
                
                tree_str = ""
                try:
                    items = sorted(os.listdir(directory))
                    dirs = [item for item in items if os.path.isdir(os.path.join(directory, item))]
                    files = [item for item in items if os.path.isfile(os.path.join(directory, item))]
                    
                    # Filter relevant files and directories
                    relevant_dirs = [d for d in dirs if d in ['cogs', 'logs', 'core']]
                    relevant_files = [f for f in files if f in ['bot.py', 'requirements.txt']]
                    
                    all_items = relevant_dirs + relevant_files
                    
                    for i, item in enumerate(all_items):
                        is_last = i == len(all_items) - 1
                        current_prefix = "└── " if is_last else "├── "
                        tree_str += f"{prefix}{current_prefix}{item}\n"
                        
                        if item in relevant_dirs:
                            extension = "    " if is_last else "│   "
                            tree_str += generate_tree(
                                os.path.join(directory, item),
                                prefix + extension,
                                max_depth,
                                current_depth + 1
                            )
                except PermissionError:
                    tree_str += f"{prefix}└── [Permission Denied]\n"
                
                return tree_str
            
            tree_output = ".\n" + generate_tree(".")
            return tree_output[:1500]  # Limit output
            
        except Exception as e:
            return f"Error generating file tree: {e}"
    
    def format_uptime(self, seconds: float) -> str:
        """Format uptime in human-readable format"""
        days, remainder = divmod(int(seconds), 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0:
            parts.append(f"{minutes}m")
        if seconds > 0 or not parts:
            parts.append(f"{seconds}s")
        
        return " ".join(parts)
    
    async def generate_monitor_embeds(self) -> List[discord.Embed]:
        """Generate all monitor embeds with current data"""
        # Collect all monitoring data
        device_info = self.get_device_info()
        systemd_info = self.get_systemd_status()
        cog_info = self.get_cog_info()
        bot_info = self.get_bot_info()
        file_tree = self.get_file_tree()
        
        embeds = []
        
        # Device Health Embed (separate embed)
        device_embed = discord.Embed(
            title="🖥️ Device Health",
            color=0x00ff00,
            timestamp=datetime.utcnow()
        )
        
        if device_info:
            device_embed.add_field(
                name="System",
                value=f"Running on **{device_info.get('device_name', 'Unknown')}**\n"
                      f"OS: {device_info.get('system', 'Unknown')}\n"
                      f"Architecture: {device_info.get('architecture', 'Unknown')}",
                inline=False
            )
            
            device_embed.add_field(
                name="Uptime",
                value=f"⏱️ {self.format_uptime(device_info.get('uptime_seconds', 0))}",
                inline=True
            )
            
            cpu_cores = device_info.get('cpu_count', 0)
            cpu_freq = device_info.get('cpu_freq')
            cpu_info = f"🔥 Max: {device_info.get('cpu_max_hour', 0):.1f}%\n" \
                      f"📊 Avg: {device_info.get('cpu_avg_hour', 0):.1f}%\n" \
                      f"⚙️ Cores: {cpu_cores}"
            if cpu_freq:
                cpu_info += f" @ {cpu_freq:.0f}MHz"
            
            device_embed.add_field(
                name="CPU Usage (Past Hour)",
                value=cpu_info,
                inline=True
            )
            
            total_ram = device_info.get('ram_total', 0)
            available_ram = device_info.get('ram_available', 0)
            used_ram = total_ram - available_ram
            device_embed.add_field(
                name="RAM Usage (Past Hour)",
                value=f"🔥 Max: {device_info.get('ram_max_hour', 0):.1f}%\n"
                      f"📊 Avg: {device_info.get('ram_avg_hour', 0):.1f}%\n"
                      f"💾 Used: {self.format_bytes(used_ram)}/{self.format_bytes(total_ram)}",
                inline=True
            )
            
            disk_total = device_info.get('disk_total', 0)
            disk_used = device_info.get('disk_used', 0)
            disk_percent = (disk_used / disk_total * 100) if disk_total > 0 else 0
            device_embed.add_field(
                name="Storage",
                value=f"💿 Used: {self.format_bytes(disk_used)}\n"
                      f"📦 Total: {self.format_bytes(disk_total)}\n"
                      f"📊 Usage: {disk_percent:.1f}%",
                inline=True
            )
        
        embeds.append(device_embed)
        
        # Systemd Status Embed (separate embed)
        systemd_embed = discord.Embed(
            title="🔧 Systemd Service Status",
            color=0x0099ff,
            timestamp=datetime.utcnow()
        )
        
        status = systemd_info.get('status', 'unknown')
        color = 0x00ff00 if status == 'active' else 0xff9900 if status == 'inactive' else 0xff0000
        systemd_embed.color = color
        
        systemd_embed.add_field(
            name="Service Information",
            value=f"📋 Service: {systemd_info.get('service_name', 'unknown')}\n"
                  f"🔍 Status: **{status.upper()}**",
            inline=False
        )
        
        #details = systemd_info.get('details', '')
        #if details and len(details) > 50:  # Only show if meaningful
            # Truncate details to fit within field limits
            #truncated_details = details[:800] + ('...' if len(details) > 800 else '')
            #systemd_embed.add_field(
            #    name="Service Details",
            #    value=f"```\n{truncated_details}\n```",
            #    inline=False
            #)
        
        embeds.append(systemd_embed)
        
        # Cog Information Embed (separate embed)
        cog_embed = discord.Embed(
            title="🧩 Cog Status",
            color=0x9932cc,
            timestamp=datetime.utcnow()
        )
        
        active_cogs = []
        for cog in cog_info:
            status_emoji = "✅" if cog['active'] else "❌"
            active_cogs.append(f"{status_emoji} **{cog['name']}** ({cog['commands']} commands)")
        
        if active_cogs:
            # Check if we need to split into multiple fields to stay under 1024 char limit
            cog_text = "\n".join(active_cogs)
            if len(cog_text) > 1000:  # Leave some buffer
                mid = len(active_cogs) // 2
                cog_embed.add_field(
                    name="Active Cogs (Part 1)",
                    value="\n".join(active_cogs[:mid]),
                    inline=True
                )
                cog_embed.add_field(
                    name="Active Cogs (Part 2)",
                    value="\n".join(active_cogs[mid:]),
                    inline=True
                )
            else:
                cog_embed.add_field(
                    name="Active Cogs",
                    value=cog_text,
                    inline=False
                )
        else:
            cog_embed.add_field(
                name="Active Cogs",
                value="❌ No cogs loaded",
                inline=False
            )
        
        embeds.append(cog_embed)
        
        # Bot Information Embed (separate embed)
        bot_embed = discord.Embed(
            title="🤖 Bot Information",
            color=0xff6b6b,
            timestamp=datetime.utcnow()
        )
        
        bot_embed.add_field(
            name="Server Statistics",
            value=f"🏠 Installed on **{bot_info.get('guild_count', 0)}** servers\n"
                  f"👥 Serving **{bot_info.get('user_count', 0)}** users\n"
                  f"⚡ **{bot_info.get('command_count', 0)}** commands available",
            inline=True
        )
        
        bot_embed.add_field(
            name="Runtime Information",
            value=f"⏰ Bot Uptime: {self.format_uptime(bot_info.get('uptime_seconds', 0))}\n"
                  f"🐍 Python: {bot_info.get('python_version', 'Unknown')}\n"
                  f"📚 Discord.py: {bot_info.get('discord_py_version', 'Unknown')}",
            inline=True
        )
        
        embeds.append(bot_embed)
        
        # File Tree Embed (separate embed)
        tree_embed = discord.Embed(
            title="📁 Project Structure",
            color=0x4ecdc4,
            timestamp=datetime.utcnow()
        )
        
        # Ensure file tree doesn't exceed field limits
        truncated_tree = file_tree[:1000] + ('...' if len(file_tree) > 1000 else '')
        tree_embed.add_field(
            name="Directory Tree",
            value=f"```\n{truncated_tree}\n```",
            inline=False
        )
        
        embeds.append(tree_embed)
        
        return embeds
    
    def format_bytes(self, bytes_value: int) -> str:
        """Format bytes in human-readable format"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_value < 1024.0:
                return f"{bytes_value:.1f} {unit}"
            bytes_value /= 1024.0
        return f"{bytes_value:.1f} PB"
    
    @app_commands.command(name="owner_monitor", description="Display comprehensive bot and system monitoring information")
    async def monitor_command(self, interaction: discord.Interaction):
        if interaction.user.id != BOT_OWNER_ID:
            await interaction.response.send_message("Only available to owner.", ephemeral=True)
            return
        
        """Main monitoring command"""
        await interaction.response.defer()
        
        try:
            channel_id = str(interaction.channel_id)
            
            # Check if we already have a monitor message in this channel
            existing_message_id = self.monitor_config["monitor_messages"].get(channel_id)
            
            if existing_message_id:
                try:
                    # Try to fetch and update the existing message
                    existing_message = await interaction.channel.fetch_message(int(existing_message_id))
                    await self.update_monitor_message(existing_message)
                    
                    # Send confirmation that we updated the existing message
                    await interaction.followup.send(
                        "✅ Updated existing monitor message above!",
                        ephemeral=True
                    )
                    
                    self.log.info(f"Updated existing monitor message {existing_message_id} in channel {channel_id}")
                    return
                    
                except discord.NotFound:
                    # Message was deleted, remove from config and create new one
                    del self.monitor_config["monitor_messages"][channel_id]
                    self.save_config()
                    self.log.info(f"Existing monitor message {existing_message_id} was deleted, creating new one")
                
                except Exception as e:
                    self.log.error(f"Error updating existing monitor message: {e}")
                    # Continue to create a new message
            
            # Generate fresh monitoring data
            embeds = await self.generate_monitor_embeds()
            view = MonitorView(self.bot, self.authorized_roles)
            
            # Send new monitor message
            message = await interaction.followup.send(embeds=embeds, view=view)
            
            # Store the new message ID
            self.monitor_config["monitor_messages"][channel_id] = message.id
            self.save_config()
            
            self.log.info(f"Created new monitor message {message.id} in channel {channel_id}")
            
        except Exception as e:
            self.log.error(f"Error in monitor command: {e}", exc_info=True)
            error_embed = discord.Embed(
                title="❌ Monitor Error",
                description=f"An error occurred while gathering monitoring data:\n```\n{str(e)}\n```",
                color=0xff0000
            )
            await interaction.followup.send(embed=error_embed, ephemeral=True)
    
    @app_commands.command(name="owner_monitor_config", description="Configure monitor settings")
    @app_commands.describe(
        auto_update_interval="Auto-update interval in seconds (0 to disable)",
        clear_messages="Clear all stored monitor message IDs"
    )
    async def monitor_config_command(
        self, 
        interaction: discord.Interaction, 
        auto_update_interval: Optional[int] = None,
        clear_messages: Optional[bool] = False
    ):
        if interaction.user.id != BOT_OWNER_ID:
            await interaction.response.send_message("Only available to owner.", ephemeral=True)
            return
        
        """Configure monitor settings"""
        # Check permissions (only authorized users can change config)
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "❌ This command can only be used in a server.", 
                ephemeral=True
            )
            return
            
        if not any(role.id in self.authorized_roles for role in interaction.user.roles):
            await interaction.response.send_message(
                "❌ You don't have permission to configure monitor settings.", 
                ephemeral=True
            )
            return
        
        await interaction.response.defer(ephemeral=True)
        
        changes = []
        
        if auto_update_interval is not None:
            if auto_update_interval < 0:
                await interaction.followup.send(
                    "❌ Auto-update interval cannot be negative.",
                    ephemeral=True
                )
                return
            
            old_interval = self.monitor_config.get("auto_update_interval", 300)
            self.monitor_config["auto_update_interval"] = auto_update_interval
            
            if auto_update_interval == 0:
                changes.append("🔄 Auto-update **disabled**")
            else:
                changes.append(f"🔄 Auto-update interval: **{auto_update_interval}s** (was {old_interval}s)")
        
        if clear_messages is not None and clear_messages:
            message_count = len(self.monitor_config["monitor_messages"])
            self.monitor_config["monitor_messages"] = {}
            changes.append(f"🗑️ Cleared **{message_count}** stored message IDs")
        
        if changes:
            self.save_config()
            
            embed = discord.Embed(
                title="⚙️ Monitor Configuration Updated",
                description="\n".join(changes),
                color=0x00ff00,
                timestamp=datetime.utcnow()
            )
        else:
            # Show current configuration
            embed = discord.Embed(
                title="⚙️ Current Monitor Configuration",
                color=0x0099ff,
                timestamp=datetime.utcnow()
            )
            
            interval = self.monitor_config.get("auto_update_interval", 300)
            if interval == 0:
                interval_text = "Disabled"
            else:
                interval_text = f"{interval}s ({interval // 60}m {interval % 60}s)"
            
            embed.add_field(
                name="Settings",
                value=f"🔄 Auto-update interval: **{interval_text}**\n"
                      f"📨 Stored messages: **{len(self.monitor_config['monitor_messages'])}**",
                inline=False
            )
            
            if self.monitor_config["monitor_messages"]:
                embed.add_field(
                    name="Active Monitor Messages",
                    value="\n".join([
                        f"📍 <#{channel_id}> (ID: {message_id})"
                        for channel_id, message_id in self.monitor_config["monitor_messages"].items()
                    ])[:1024],  # Discord field limit
                    inline=False
                )
        
            await interaction.followup.send(embed=embed, ephemeral=True)

async def setup(bot: commands.Bot):
    """Setup function called when loading the cog"""
    await bot.add_cog(Monitor(bot))
