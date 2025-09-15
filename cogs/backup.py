# cogs/backup.py
import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiohttp
import zipfile
import os
import asyncio
from datetime import datetime, time, timezone
from pathlib import Path
import logging
import traceback

# Import German timezone utilities
from core.timezone_util import get_german_time, get_german_timestamp, format_german_time

class BackupTask(commands.Cog):
    """Automated config backup system"""
    
    def __init__(self, bot):
        self.bot = bot
        self.logger = bot.get_cog_logger("backup") if hasattr(bot, 'get_cog_logger') else logging.getLogger("tausendsassa.backup")
        
        # Configuration
        self.config_path = Path("config")
        self.backup_path = Path("backups")
        self.log_webhook_url = os.getenv("BACKUP_WEBHOOK_URL")
        
        # Ensure backup directory exists
        self.backup_path.mkdir(exist_ok=True)
        
        # Validate webhook URL
        if not self.log_webhook_url:
            self.logger.warning("⚠️ BACKUP_WEBHOOK_URL not set - backup uploads to Discord disabled")
        else:
            self.logger.info(f"✅ Backup webhook configured")
        
        # Start the daily backup task
        self.daily_backup.start()
        self.logger.info("📄 Daily backup task initialized")
    
    def cog_unload(self):
        """Cleanup when cog is unloaded"""
        self.daily_backup.cancel()
        self.logger.info("🛑 Daily backup task cancelled")
    
    @tasks.loop(time=time(hour=0, minute=0, tzinfo=timezone.utc))  # Daily at midnight UTC
    async def daily_backup(self):
        """Daily backup task that runs at midnight UTC"""
        try:
            self.logger.info("📄 Starting daily config backup...")
            
            # Check if config directory exists
            if not self.config_path.exists():
                self.logger.warning(f"Config directory '{self.config_path}' does not exist")
                await self.send_backup_notification(
                    "⚠️ Backup Warning", 
                    f"Config directory `{self.config_path}` not found", 
                    0xff9900
                )
                return
            
            # Create backup
            backup_file = await self.create_config_backup()
            
            if backup_file:
                # Send backup to webhook (if configured)
                if self.log_webhook_url:
                    await self.upload_backup_to_webhook(backup_file)
                else:
                    self.logger.info("📄 Backup created locally (webhook not configured)")
                
                # Clean up old backups (keep last 7 days)
                await self.cleanup_old_backups()
                
                self.logger.info(f"✅ Daily backup completed successfully: {backup_file.name}")
            else:
                self.logger.error("❌ Daily backup failed")
                
        except Exception as e:
            self.logger.error(f"❌ Error in daily backup task: {e}", exc_info=True)
            await self.send_backup_notification(
                "❌ Backup Error", 
                f"Daily backup failed with error: {str(e)}", 
                0xff0000
            )
    
    @daily_backup.before_loop
    async def before_daily_backup(self):
        """Wait for bot to be ready before starting the loop"""
        await self.bot.wait_until_ready()
        self.logger.info("🤖 Bot ready - daily backup task will start")
    
    async def create_config_backup(self) -> Path:
        """Create a zip backup of the config directory"""
        try:
            # Generate timestamp for filename
            timestamp = format_german_time(format_str="%Y%m%d_%H%M%S")
            backup_filename = f"config_backup_{timestamp}.zip"
            backup_file_path = self.backup_path / backup_filename
            
            # Count files to backup
            file_count = 0
            total_size = 0
            
            # Create zip file
            with zipfile.ZipFile(backup_file_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # Walk through config directory
                for root, dirs, files in os.walk(self.config_path):
                    for file in files:
                        file_path = Path(root) / file
                        
                        # Skip hidden files and non-config files
                        if file.startswith('.'):
                            continue
                            
                        # Skip map cache images (they can be re-rendered)
                        if file.endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')):
                            self.logger.debug(f"Skipping map cache image: {file_path}")
                            continue
                        
                        # Only include config files
                        if file.endswith(('.py', '.json', '.yaml', '.yml', '.txt', '.md')):
                            # Calculate relative path for zip
                            relative_path = file_path.relative_to(self.config_path.parent)
                            zipf.write(file_path, relative_path)
                            file_count += 1
                            total_size += file_path.stat().st_size
            
            # Verify backup was created
            if backup_file_path.exists() and backup_file_path.stat().st_size > 0:
                backup_size = backup_file_path.stat().st_size
                self.logger.info(
                    f"📦 Backup created: {backup_filename} "
                    f"({file_count} files, {total_size:,} bytes → {backup_size:,} bytes compressed)"
                )
                return backup_file_path
            else:
                self.logger.error("❌ Backup file was not created or is empty")
                return None
                
        except Exception as e:
            self.logger.error(f"❌ Error creating backup: {e}", exc_info=True)
            return None
    
    async def upload_backup_to_webhook(self, backup_file: Path):
        """Upload the backup file to Discord via webhook"""
        if not self.log_webhook_url:
            self.logger.warning("⚠️ Cannot upload backup - webhook URL not configured")
            return
            
        try:
            # Check file size (Discord limit is 25MB for webhooks)
            file_size = backup_file.stat().st_size
            max_size = 25 * 1024 * 1024  # 25MB in bytes
            
            if file_size > max_size:
                self.logger.warning(f"⚠️ Backup file too large ({file_size:,} bytes > {max_size:,} bytes)")
                await self.send_backup_notification(
                    "⚠️ Backup Too Large",
                    f"Backup file `{backup_file.name}` is {file_size:,} bytes (limit: {max_size:,} bytes)\n"
                    f"Backup created locally but not uploaded to Discord.",
                    0xff9900
                )
                return
            
            # Create embed for backup info
            embed = {
                "title": "📦 Daily Config Backup",
                "description": f"Automated daily backup completed successfully",
                "color": 0x00ff00,
                "timestamp": get_german_time().isoformat(),
                "fields": [
                    {
                        "name": "📁 Filename",
                        "value": f"`{backup_file.name}`",
                        "inline": True
                    },
                    {
                        "name": "📊 File Size",
                        "value": f"{file_size:,} bytes ({file_size / 1024 / 1024:.2f} MB)",
                        "inline": True
                    },
                    {
                        "name": "🕐 Created",
                        "value": f"<t:{get_german_timestamp()}:F>",
                        "inline": True
                    }
                ],
                "footer": {
                    "text": "Tausendsassa Backup System",
                    "icon_url": "https://cdn.discordapp.com/attachments/1398436953422037013/1409705616817127556/1473097.png"
                }
            }
            
            # Upload file with embed
            async with aiohttp.ClientSession() as session:
                # Prepare multipart form data
                data = aiohttp.FormData()
                
                # Add embed as JSON (properly formatted)
                payload = {
                    "embeds": [embed],
                    "username": "Backup Bot",
                    "avatar_url": "https://cdn.discordapp.com/attachments/1398436953422037013/1409705616817127556/1473097.png"
                }
                
                # Convert to proper JSON string
                import json
                data.add_field('payload_json', json.dumps(payload))
                
                # Add file
                with open(backup_file, 'rb') as f:
                    data.add_field('file', f, filename=backup_file.name, content_type='application/zip')
                    
                    # Send webhook
                    async with session.post(self.log_webhook_url, data=data) as response:
                        if response.status in (200, 204):
                            self.logger.info(f"✅ Backup uploaded to Discord: {backup_file.name}")
                        else:
                            self.logger.error(f"❌ Failed to upload backup to Discord: HTTP {response.status}")
                            response_text = await response.text()
                            self.logger.error(f"Response: {response_text}")
                        
        except Exception as e:
            self.logger.error(f"❌ Error uploading backup to webhook: {e}", exc_info=True)
            await self.send_backup_notification(
                "❌ Upload Error",
                f"Failed to upload backup to Discord: {str(e)}",
                0xff0000
            )
    
    async def send_backup_notification(self, title: str, description: str, color: int):
        """Send a notification embed to the webhook"""
        if not self.log_webhook_url:
            self.logger.warning(f"⚠️ Cannot send notification '{title}' - webhook URL not configured")
            return
            
        try:
            embed = {
                "title": title,
                "description": description,
                "color": color,
                "timestamp": get_german_time().isoformat(),
                "footer": {
                    "text": "Tausendsassa Backup System"
                }
            }
            
            payload = {
                "embeds": [embed],
                "username": "Backup Bot"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.log_webhook_url,
                    json=payload,
                    headers={"Content-Type": "application/json"}
                ) as response:
                    if response.status not in (200, 204):
                        self.logger.error(f"Failed to send notification: HTTP {response.status}")
                        
        except Exception as e:
            self.logger.error(f"Error sending notification: {e}")
    
    async def cleanup_old_backups(self, keep_days: int = 7):
        """Clean up old backup files, keeping only the last N days"""
        try:
            if not self.backup_path.exists():
                return
            
            # Get all backup files
            backup_files = list(self.backup_path.glob("config_backup_*.zip"))
            
            if len(backup_files) <= keep_days:
                return  # Don't delete if we have fewer than keep_days backups
            
            # Sort by modification time (oldest first)
            backup_files.sort(key=lambda f: f.stat().st_mtime)
            
            # Keep only the newest files
            files_to_delete = backup_files[:-keep_days]
            
            deleted_count = 0
            for file_path in files_to_delete:
                try:
                    file_path.unlink()
                    deleted_count += 1
                    self.logger.info(f"🗑️ Deleted old backup: {file_path.name}")
                except Exception as e:
                    self.logger.error(f"❌ Failed to delete {file_path.name}: {e}")
            
            if deleted_count > 0:
                self.logger.info(f"🧹 Cleaned up {deleted_count} old backup files")
                
        except Exception as e:
            self.logger.error(f"❌ Error cleaning up old backups: {e}", exc_info=True)
    
    # Manual backup commands for testing/emergency use
    @app_commands.command(name="owner_backup_now", description="📄 Create an immediate config backup (Owner only)")
    async def owner_backup_now(self, interaction: discord.Interaction):
        """Create an immediate backup of the config directory"""
        
        # Check if user is bot owner
        if interaction.user.id != getattr(self.bot, 'owner_id', 0):
            await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            self.logger.info(f"📄 Manual backup initiated by {interaction.user} (ID: {interaction.user.id})")
            
            backup_file = await self.create_config_backup()
            
            if backup_file:
                if self.log_webhook_url:
                    await self.upload_backup_to_webhook(backup_file)
                else:
                    self.logger.info("📄 Manual backup created locally (webhook not configured)")
                
                webhook_status = "and uploaded" if self.log_webhook_url else "(local only - webhook not configured)"
                embed = discord.Embed(
                    title="✅ Manual Backup Complete",
                    description=f"Config backup created {webhook_status}.\n\n**File:** `{backup_file.name}`",
                    color=0x00ff00
                )
                await interaction.followup.send(embed=embed)
                
                self.logger.info(f"✅ Manual backup completed: {backup_file.name}")
            else:
                embed = discord.Embed(
                    title="❌ Backup Failed",
                    description="Failed to create config backup. Check logs for details.",
                    color=0xff0000
                )
                await interaction.followup.send(embed=embed)
                
        except Exception as e:
            self.logger.error(f"❌ Error in manual backup: {e}", exc_info=True)
            
            embed = discord.Embed(
                title="❌ Backup Error",
                description=f"An error occurred during backup: {str(e)}",
                color=0xff0000
            )
            await interaction.followup.send(embed=embed)
    
    @app_commands.command(name="owner_backup_status", description="📊 Show backup system status (Owner only)")
    async def owner_backup_status(self, interaction: discord.Interaction):
        """Show the status of the backup system"""
        
        if interaction.user.id != getattr(self.bot, 'owner_id', 0):
            await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Check backup directory
            backup_files = list(self.backup_path.glob("config_backup_*.zip")) if self.backup_path.exists() else []
            backup_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
            
            # Check config directory
            config_exists = self.config_path.exists()
            config_file_count = len(list(self.config_path.rglob("*"))) if config_exists else 0
            
            # Task status
            task_running = self.daily_backup.is_running()
            next_run = self.daily_backup.next_iteration
            
            embed = discord.Embed(
                title="📊 Backup System Status",
                color=0x0099ff,
                timestamp=get_german_time()
            )
            
            # Task info
            embed.add_field(
                name="📄 Daily Task",
                value=f"**Status:** {'✅ Running' if task_running else '❌ Stopped'}\n"
                      f"**Next Run:** {f'<t:{int(next_run.timestamp())}:R>' if next_run else 'Unknown'}",
                inline=False
            )
            
            # Config directory info
            embed.add_field(
                name="📁 Config Directory",
                value=f"**Path:** `{self.config_path}`\n"
                      f"**Exists:** {'✅ Yes' if config_exists else '❌ No'}\n"
                      f"**Files:** {config_file_count}",
                inline=True
            )
            
            # Backup directory info
            embed.add_field(
                name="📦 Backup Directory",
                value=f"**Path:** `{self.backup_path}`\n"
                      f"**Backups:** {len(backup_files)}\n"
                      f"**Last Backup:** {backup_files[0].name if backup_files else 'None'}",
                inline=True
            )
            
            # Recent backups
            if backup_files:
                recent_backups = "\n".join([
                    f"• `{bf.name}` ({bf.stat().st_size:,} bytes)"
                    for bf in backup_files[:5]
                ])
                embed.add_field(
                    name="📋 Recent Backups",
                    value=recent_backups,
                    inline=False
                )
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            self.logger.error(f"❌ Error getting backup status: {e}", exc_info=True)
            
            embed = discord.Embed(
                title="❌ Status Error",
                description=f"Failed to get backup status: {str(e)}",
                color=0xff0000
            )
            await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(BackupTask(bot))
