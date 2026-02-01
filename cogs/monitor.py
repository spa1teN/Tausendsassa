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
from pathlib import Path

# Import German timezone utilities
from core.timezone_util import get_german_time


def is_running_in_docker() -> bool:
    """Check if we're running inside a Docker container."""
    # Check for .dockerenv file
    if Path("/.dockerenv").exists():
        return True
    # Check cgroup for docker/container references
    try:
        with open("/proc/1/cgroup", "r") as f:
            content = f.read()
            if "docker" in content or "container" in content:
                return True
    except (FileNotFoundError, PermissionError):
        pass
    return False


class Monitor(commands.Cog):
    """Monitor cog for system and bot health monitoring"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.log = bot.get_cog_logger("monitor")

        # Import config here to avoid circular imports
        from core.config import config

        # Configuration from centralized config
        self.authorized_roles = config.monitor_authorized_roles
        self.config = config  # Store reference for use in other methods

        # System monitoring data storage
        self.cpu_history: List[float] = []
        self.ram_history: List[float] = []
        self.start_time = time.time()

        # In-memory cache for monitor config
        self._monitor_messages: Dict[str, str] = {}  # channel_id -> message_id
        self._auto_update_interval: int = config.monitor_update_interval
        self._last_update: float = 0

        # Start monitoring task
        self.monitoring_task = None

        self.log.info("Monitor cog initialized")

    async def cog_load(self):
        """Start background task when cog is fully loaded"""
        # Load config from database
        await self._load_config()

        self.monitoring_task = asyncio.create_task(self.collect_system_metrics())
        self.log.info("Monitoring background task started")

    async def _load_config(self):
        """Load monitor configuration from database"""
        if self.bot.db:
            config = await self.bot.db.monitor.get_monitor_config('system')
            self._monitor_messages = config.get('monitor_messages', {})
            self._auto_update_interval = config.get('auto_update_interval', self.config.monitor_update_interval)
            self._last_update = config.get('last_update', 0)

    async def _save_config(self):
        """Save monitor configuration to database"""
        if self.bot.db:
            # Delete removed messages first
            existing = await self.bot.db.monitor.get_all_monitor_messages_dict('system')
            for channel_id in existing:
                if channel_id not in self._monitor_messages:
                    await self.bot.db.monitor.delete_message(int(channel_id), 'system')

            # Save current messages
            for channel_id, message_id in self._monitor_messages.items():
                await self.bot.db.monitor.set_message(
                    channel_id=int(channel_id),
                    message_id=int(message_id),
                    monitor_type='system',
                    auto_update_interval=self._auto_update_interval
                )

    def cog_unload(self):
        """Clean up when cog is unloaded"""
        if self.monitoring_task:
            self.monitoring_task.cancel()
        # Note: Can't await in cog_unload, but we save after each change
        self.log.info("Monitor cog unloaded")

    async def collect_system_metrics(self):
        """Background task to collect system metrics and auto-update monitor messages"""
        self.log.info("Monitoring loop started")
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
                if (current_time - self._last_update >= self._auto_update_interval):
                    await self.auto_update_monitor_messages()
                    self._last_update = current_time

                await asyncio.sleep(self.config.system_metrics_interval)  # Configurable interval

            except Exception as e:
                self.log.error(f"Error collecting system metrics: {e}")
                await asyncio.sleep(60)

    async def auto_update_monitor_messages(self):
        """Automatically update existing monitor messages"""
        if time.time() - self.start_time < 120:
            self.log.debug("Skipping auto-update during 2min period after boot")
            return

        for channel_id, message_id in list(self._monitor_messages.items()):
            try:
                channel = self.bot.get_channel(int(channel_id))
                if not channel:
                    # Channel not found, remove from config
                    del self._monitor_messages[channel_id]
                    continue

                try:
                    message = await channel.fetch_message(int(message_id))
                    await self.update_monitor_message(message)
                except discord.NotFound:
                    # Message was deleted, remove from config
                    del self._monitor_messages[channel_id]
                    self.log.info(f"Removed deleted monitor message from channel {channel_id}")
                except discord.Forbidden:
                    self.log.warning(f"No permission to update monitor message in channel {channel_id}")

            except Exception as e:
                self.log.error(f"Error auto-updating monitor message in channel {channel_id}: {e}")

        # Save after cleanup
        await self._save_config()

    async def update_monitor_message(self, message: discord.Message):
        """Update an existing monitor message with fresh data"""
        try:
            # Generate fresh monitoring data
            embeds = await self.generate_monitor_embeds()

            # Update the message
            await message.edit(embeds=embeds, view=None)

        except Exception as e:
            self.log.error(f"Error updating monitor message: {e}")
            raise

    def get_cpu_temperature(self) -> Optional[float]:
        """Get CPU temperature in Celsius"""
        try:
            # Try different methods to get CPU temperature
            temperatures = psutil.sensors_temperatures()

            if temperatures:
                # Common temperature sensor names
                sensor_names = ['coretemp', 'cpu_thermal', 'acpi', 'k10temp', 'zenpower']

                for sensor_name in sensor_names:
                    if sensor_name in temperatures:
                        temps = temperatures[sensor_name]
                        if temps:
                            # Return the first temperature reading
                            return temps[0].current

                # If no common sensor found, use the first available
                for sensor_temps in temperatures.values():
                    if sensor_temps:
                        return sensor_temps[0].current

            # Fallback: try reading from common thermal files on Linux
            thermal_files = [
                '/sys/class/thermal/thermal_zone0/temp',
                '/sys/class/thermal/thermal_zone1/temp',
                '/sys/class/hwmon/hwmon0/temp1_input',
                '/sys/class/hwmon/hwmon1/temp1_input'
            ]

            for thermal_file in thermal_files:
                try:
                    with open(thermal_file, 'r') as f:
                        temp_str = f.read().strip()
                        temp = float(temp_str)
                        # Convert from millicelsius to celsius if needed
                        if temp > 1000:
                            temp = temp / 1000
                        if 0 < temp < 150:  # Reasonable temperature range
                            return temp
                except (FileNotFoundError, ValueError, PermissionError):
                    continue

            return None

        except Exception as e:
            self.log.debug(f"Error getting CPU temperature: {e}")
            return None

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
            cpu_temp = self.get_cpu_temperature()

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
                'cpu_temperature': cpu_temp,
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

    def get_runtime_status(self) -> Dict[str, Any]:
        """Get runtime status - Docker or Systemd depending on environment."""
        if is_running_in_docker():
            return self.get_docker_status()
        return self.get_systemd_status()

    def get_docker_status(self) -> Dict[str, Any]:
        """Get Docker container status for the bot."""
        try:
            # Get container info from environment or process
            container_id = None

            # Try to get container ID from cgroup
            try:
                with open("/proc/1/cgroup", "r") as f:
                    for line in f:
                        if "docker" in line:
                            # Extract container ID from path
                            parts = line.strip().split("/")
                            if parts:
                                container_id = parts[-1][:12]
                                break
            except (FileNotFoundError, PermissionError):
                pass

            # Get container uptime from PID 1
            uptime_str = "Unknown"
            try:
                proc = psutil.Process(1)
                start_time = datetime.fromtimestamp(proc.create_time())
                uptime = datetime.now() - start_time
                days = uptime.days
                hours, remainder = divmod(uptime.seconds, 3600)
                minutes, _ = divmod(remainder, 60)
                if days > 0:
                    uptime_str = f"{days}d {hours}h {minutes}m"
                else:
                    uptime_str = f"{hours}h {minutes}m"
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

            return {
                'runtime_mode': 'docker',
                'service_name': 'tausendsassa-bot',
                'container_id': container_id or 'unknown',
                'status': 'running',
                'uptime': uptime_str,
                'details': f'Container ID: {container_id or "unknown"}\nUptime: {uptime_str}'
            }

        except Exception as e:
            self.log.error(f"Error in Docker status check: {e}")
            return {
                'runtime_mode': 'docker',
                'service_name': 'docker',
                'status': 'error',
                'details': f'Error checking Docker status: {e}'
            }

    def get_systemd_status(self) -> Dict[str, Any]:
        """Get systemd service status for the bot."""
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
                        timeout=self.config.http_timeout // 2  # Half of HTTP timeout
                    )

                    if result.returncode == 0:  # Service found
                        # Get detailed status with timeout
                        status_result = subprocess.run(
                            ['systemctl', 'status', service_name, '--no-pager', '-l'],
                            capture_output=True,
                            text=True,
                            timeout=self.config.http_timeout
                        )

                        return {
                            'runtime_mode': 'systemd',
                            'service_name': service_name,
                            'status': result.stdout.strip(),
                            'details': status_result.stdout[:1000]  # Limit output
                        }
                except subprocess.TimeoutExpired as e:
                    self.log.warning(f"Timeout checking systemd service {service_name}: {e}")
                    continue
                except subprocess.CalledProcessError as e:
                    self.log.debug(f"Service {service_name} not found or error: {e}")
                    continue
                except Exception as e:
                    self.log.warning(f"Unexpected error checking service {service_name}: {e}")
                    continue

            return {
                'runtime_mode': 'systemd',
                'service_name': 'unknown',
                'status': 'not found',
                'details': 'No systemd service found for common bot names'
            }

        except Exception as e:
            self.log.error(f"Error in systemd status check: {e}")
            return {
                'runtime_mode': 'systemd',
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
        runtime_info = self.get_runtime_status()
        cog_info = self.get_cog_info()
        bot_info = self.get_bot_info()

        embeds = []

        # Device Health Embed (separate embed)
        device_embed = discord.Embed(
            title="Device Health",
            color=0x00ff00,
            timestamp=get_german_time()
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
                value=f"{self.format_uptime(device_info.get('uptime_seconds', 0))}",
                inline=True
            )

            cpu_cores = device_info.get('cpu_count', 0)
            cpu_freq = device_info.get('cpu_freq')
            cpu_temp = device_info.get('cpu_temperature')

            cpu_info = f"Max: {device_info.get('cpu_max_hour', 0):.1f}%\n" \
                      f"Avg: {device_info.get('cpu_avg_hour', 0):.1f}%\n" \
                      f"Cores: {cpu_cores}"

            if cpu_freq:
                cpu_info += f" @ {cpu_freq:.0f}MHz"

            if cpu_temp is not None:
                cpu_info += f"\nTemperature: {cpu_temp:.1f}C"

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
                value=f"Max: {device_info.get('ram_max_hour', 0):.1f}%\n"
                      f"Avg: {device_info.get('ram_avg_hour', 0):.1f}%\n"
                      f"Used: {self.format_bytes(used_ram)}/{self.format_bytes(total_ram)}",
                inline=True
            )

            disk_total = device_info.get('disk_total', 0)
            disk_used = device_info.get('disk_used', 0)
            disk_percent = (disk_used / disk_total * 100) if disk_total > 0 else 0
            device_embed.add_field(
                name="Storage",
                value=f"Used: {self.format_bytes(disk_used)}\n"
                      f"Total: {self.format_bytes(disk_total)}\n"
                      f"Usage: {disk_percent:.1f}%",
                inline=True
            )

        embeds.append(device_embed)

        # Runtime Status Embed (Docker or Systemd)
        runtime_mode = runtime_info.get('runtime_mode', 'unknown')
        is_docker = runtime_mode == 'docker'

        runtime_embed = discord.Embed(
            title="Docker Container Status" if is_docker else "Systemd Service Status",
            color=0x0099ff,
            timestamp=get_german_time()
        )

        status = runtime_info.get('status', 'unknown')
        color = 0x00ff00 if status in ('active', 'running') else 0xff9900 if status == 'inactive' else 0xff0000
        runtime_embed.color = color

        if is_docker:
            runtime_embed.add_field(
                name="Container Information",
                value=f"Container: {runtime_info.get('service_name', 'unknown')}\n"
                      f"Container ID: `{runtime_info.get('container_id', 'unknown')}`\n"
                      f"Status: **{status.upper()}**\n"
                      f"Uptime: {runtime_info.get('uptime', 'unknown')}",
                inline=False
            )
        else:
            runtime_embed.add_field(
                name="Service Information",
                value=f"Service: {runtime_info.get('service_name', 'unknown')}\n"
                      f"Status: **{status.upper()}**",
                inline=False
            )

        embeds.append(runtime_embed)

        # Cog Information Embed (separate embed)
        cog_embed = discord.Embed(
            title="Cog Status",
            color=0x9932cc,
            timestamp=get_german_time()
        )

        active_cogs = []
        for cog in cog_info:
            status_emoji = "+" if cog['active'] else "-"
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
                value="No cogs loaded",
                inline=False
            )

        embeds.append(cog_embed)

        # Bot Information Embed (separate embed)
        bot_embed = discord.Embed(
            title="Bot Information",
            color=0xff6b6b,
            timestamp=get_german_time()
        )

        bot_embed.add_field(
            name="Server Statistics",
            value=f"Installed on **{bot_info.get('guild_count', 0)}** servers\n"
                  f"Serving **{bot_info.get('user_count', 0)}** users",
            inline=True
        )

        bot_embed.add_field(
            name="Runtime Information",
            value=f"Bot Uptime: {self.format_uptime(bot_info.get('uptime_seconds', 0))}\n"
                  f"Python: {bot_info.get('python_version', 'Unknown')}\n"
                  f"Discord.py: {bot_info.get('discord_py_version', 'Unknown')}",
            inline=True
        )

        embeds.append(bot_embed)


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
        if interaction.user.id != self.config.owner_id:
            await interaction.response.send_message("Only available to owner.", ephemeral=True)
            return

        """Main monitoring command"""
        await interaction.response.defer()

        try:
            channel_id = str(interaction.channel_id)

            # Check if we already have a monitor message in this channel
            existing_message_id = self._monitor_messages.get(channel_id)

            if existing_message_id:
                try:
                    # Try to fetch and update the existing message
                    existing_message = await interaction.channel.fetch_message(int(existing_message_id))
                    await self.update_monitor_message(existing_message)

                    # Send confirmation that we updated the existing message
                    await interaction.followup.send(
                        "Updated existing monitor message above!",
                        ephemeral=True
                    )

                    self.log.info(f"Updated existing monitor message {existing_message_id} in channel {channel_id}")
                    return

                except discord.NotFound:
                    # Message was deleted, remove from config and create new one
                    del self._monitor_messages[channel_id]
                    await self._save_config()
                    self.log.info(f"Existing monitor message {existing_message_id} was deleted, creating new one")

                except Exception as e:
                    self.log.error(f"Error updating existing monitor message: {e}")
                    # Continue to create a new message

            # Generate fresh monitoring data
            embeds = await self.generate_monitor_embeds()

            # Send new monitor message
            message = await interaction.followup.send(embeds=embeds)

            # Store the new message ID
            self._monitor_messages[channel_id] = str(message.id)
            await self._save_config()

            self.log.info(f"Created new monitor message {message.id} in channel {channel_id}")

        except Exception as e:
            self.log.error(f"Error in monitor command: {e}", exc_info=True)
            error_embed = discord.Embed(
                title="Monitor Error",
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
        if interaction.user.id != self.config.owner_id:
            await interaction.response.send_message("Only available to owner.", ephemeral=True)
            return

        """Configure monitor settings"""
        # Check permissions (only authorized users can change config)
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True
            )
            return

        if not any(role.id in self.authorized_roles for role in interaction.user.roles):
            await interaction.response.send_message(
                "You don't have permission to configure monitor settings.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        changes = []

        if auto_update_interval is not None:
            if auto_update_interval < 0:
                await interaction.followup.send(
                    "Auto-update interval cannot be negative.",
                    ephemeral=True
                )
                return

            old_interval = self._auto_update_interval
            self._auto_update_interval = auto_update_interval

            if auto_update_interval == 0:
                changes.append("Auto-update **disabled**")
            else:
                changes.append(f"Auto-update interval: **{auto_update_interval}s** (was {old_interval}s)")

        if clear_messages is not None and clear_messages:
            message_count = len(self._monitor_messages)
            # Delete from database
            if self.bot.db:
                for channel_id in list(self._monitor_messages.keys()):
                    await self.bot.db.monitor.delete_message(int(channel_id), 'system')
            self._monitor_messages = {}
            changes.append(f"Cleared **{message_count}** stored message IDs")

        if changes:
            await self._save_config()

            embed = discord.Embed(
                title="Monitor Configuration Updated",
                description="\n".join(changes),
                color=0x00ff00,
                timestamp=get_german_time()
            )
        else:
            # Show current configuration
            embed = discord.Embed(
                title="Current Monitor Configuration",
                color=0x0099ff,
                timestamp=get_german_time()
            )

            interval = self._auto_update_interval
            if interval == 0:
                interval_text = "Disabled"
            else:
                interval_text = f"{interval}s ({interval // 60}m {interval % 60}s)"

            embed.add_field(
                name="Settings",
                value=f"Auto-update interval: **{interval_text}**\n"
                      f"Stored messages: **{len(self._monitor_messages)}**",
                inline=False
            )

            if self._monitor_messages:
                embed.add_field(
                    name="Active Monitor Messages",
                    value="\n".join([
                        f"<#{channel_id}> (ID: {message_id})"
                        for channel_id, message_id in self._monitor_messages.items()
                    ])[:1024],  # Discord field limit
                    inline=False
                )

        await interaction.followup.send(embed=embed, ephemeral=True)

async def setup(bot: commands.Bot):
    """Setup function called when loading the cog"""
    await bot.add_cog(Monitor(bot))
