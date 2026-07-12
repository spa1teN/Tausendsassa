"""Simplified Map Cog for Discord Bot — CV2 edition."""

import asyncio
import math
import time
import geopandas as gpd
from pathlib import Path
from typing import Optional, Dict, Tuple, List
from datetime import datetime, timedelta
from copy import deepcopy
from PIL import Image as PILImage
from io import BytesIO
import discord
from discord import app_commands
from discord.ext import commands

APOLOGY_TEXT = (
    "## Apology for Spam\n"
    "-# Hey everyone, sorry for the frequent pings and new posts earlier today. "
    "I had an issue and hope it's now fixed. This Map message is the correct one "
    "that's registered in my database. If there are still any others I could not "
    "remotely delete, feel free to do so.\n"
    "-# Mea culpa, enjoy the Sunday\n"
    "-# — [spa1teN](https://discord.com/users/485051896655249419)"
)
DEV_GUILD = 1398409754967015647
# Apology expiry: set to time.time() + 86400 on first load, survives restarts
_APOLOGY_EXPIRY: float = 0.0
from core.map_gen import MapGenerator
from core.map_storage import MapStorage
from core.map_views import LocationModal, UserPinOptionsView, UpdateLocationModal
from core.config import config as bot_config
from core.map_config import MapConfig

from core.timezone_util import get_german_time, format_german_time


class MapV2Cog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.log = bot.get_cog_logger("map")
        self.config = MapConfig()
        self.data_dir = Path(__file__).parent / "map_data"
        self.cache_dir = Path(__file__).parent / "map_data/map_cache"
        self.storage = MapStorage(self.data_dir, self.cache_dir, self.log)
        self.map_generator = MapGenerator(self.data_dir, self.cache_dir, self.log)
        self.global_config: Dict = {}
        self.maps: Dict = {}
        self._guild_names: dict = {}
        self._snapshots: dict = {}
    def _snapshot_settings(self, guild_id: str):
        """Store a snapshot of current settings for potential revert."""
        md = self.maps.get(guild_id, {})
        self._snapshots[guild_id] = deepcopy(md.get('settings', {}))

    def _revert_settings(self, guild_id: str):
        """Revert to the stored snapshot settings."""
        if guild_id in self._snapshots:
            if guild_id in self.maps:
                self.maps[guild_id]['settings'] = self._snapshots.pop(guild_id)

    # ── CV2 builders ──────────────────────────────────────────────────

    def _build_map_card_view(self, guild_id: int) -> discord.ui.LayoutView:
        map_data = self.maps.get(str(guild_id), {})
        region = map_data.get("region", "world")
        pin_count = len(map_data.get("pins", {}))
        server_name = self._guild_names.get(str(guild_id))
        if not server_name:
            guild = self.bot.get_guild(guild_id)
            server_name = guild.name if guild else str(guild_id)
        view = discord.ui.LayoutView(timeout=None)

        # Temporary apology — auto-removed after 24h
        if time.time() < _APOLOGY_EXPIRY:
            apology = discord.ui.Container(accent_colour=discord.Colour(0x7289DA))
            apology.add_item(discord.ui.TextDisplay(APOLOGY_TEXT))
            view.add_item(apology)
            view.add_item(discord.ui.Separator())

        container = discord.ui.Container(accent_colour=discord.Colour(0x7289DA))
        title = f"## {server_name} — Map\n-# {pin_count} Pins · {region.capitalize()} · Last changed: <t:{int(time.time())}:R>"
        container.add_item(discord.ui.TextDisplay(title))
        gallery = discord.ui.MediaGallery()
        gallery.add_item(media="attachment://map.png")
        container.add_item(gallery)
        container.add_item(discord.ui.TextDisplay("-# Customise via `/map` (admin only)"))
        container.add_item(discord.ui.Separator())

        row = discord.ui.ActionRow()
        pin_btn = discord.ui.Button(label="Pin", emoji="📍", style=discord.ButtonStyle.primary,
                                    custom_id=f"map_cv2_pin:{guild_id}")
        pin_btn.callback = self._cv2_pin_callback
        row.add_item(pin_btn)
        if bot_config.webapp_url:
            row.add_item(discord.ui.Button(label="3D View", emoji="🌍", style=discord.ButtonStyle.link,
                                           url=f"{bot_config.webapp_url}/map/{guild_id}"))
        fb_btn = discord.ui.Button(label="Feedback", emoji="💬", style=discord.ButtonStyle.secondary,
                                   custom_id=f"map_cv2_feedback:{guild_id}")
        fb_btn.callback = self._cv2_feedback_callback
        row.add_item(fb_btn)
        container.add_item(row)
        view.add_item(container)
        return view

    @staticmethod
    def _parse_color_to_rgb(c: str):
        """Parse a hex string like '#FF4444' or 'FF4444' to an RGB tuple."""
        c = c.lstrip('#')
        try:
            return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))
        except (ValueError, IndexError):
            return (255, 0, 0)

    def _build_admin_view(self, guild_id: int, show_preview_btn: bool = False) -> discord.ui.LayoutView:
        map_data = self.maps.get(str(guild_id), {})
        settings = map_data.get('settings', {})
        colors = settings.get('colors', {})
        borders = settings.get('borders', {})
        pins_cfg = settings.get('pins', {})

        def _hex(rgb):
            if not isinstance(rgb, (list, tuple)) or len(rgb) < 3:
                return "—"
            return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"

        from PIL import ImageDraw, ImageFont
        swatch_w, swatch_h = 420, 30
        specs = [("Land", colors.get("land"), [128, 128, 128]),
                 ("Water", colors.get("water"), [64, 64, 128]),
                 ("Borders", borders.get("country"), [0, 0, 0])]
        combined = PILImage.new("RGB", (swatch_w, swatch_h))
        for i, (label, c, fallback) in enumerate(specs):
            rgb = (c if isinstance(c, (list, tuple)) and len(c) >= 3 else fallback)[:3]
            x0, x1 = i * swatch_w // 3, (i + 1) * swatch_w // 3
            for x in range(x0, x1):
                for y in range(swatch_h):
                    combined.putpixel((x, y), tuple(rgb))
            lum = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
            tc = (0, 0, 0) if lum > 140 else (255, 255, 255)
            try:
                d = ImageDraw.Draw(combined)
                f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
                bb = d.textbbox((0, 0), label, font=f)
                d.text(((x0 + x1) // 2 - (bb[2] - bb[0]) // 2, (swatch_h - (bb[3] - bb[1])) // 2), label, fill=tc, font=f)
            except Exception:
                pass
        buf = BytesIO(); combined.save(buf, format="PNG"); buf.seek(0)

        pin_c = pins_cfg.get("color") or colors.get("pin")
        if isinstance(pin_c, str):
            pin_c = self._parse_color_to_rgb(pin_c)
        pin_rgb = (pin_c if isinstance(pin_c, (list, tuple)) and len(pin_c) >= 3 else [255, 0, 0])[:3]
        pin_img = PILImage.new("RGB", (swatch_w, swatch_h), tuple(pin_rgb))
        try:
            d = ImageDraw.Draw(pin_img)
            f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
            bb = d.textbbox((0, 0), "Pin", font=f)
            d.text(((swatch_w - (bb[2] - bb[0])) // 2, (swatch_h - (bb[3] - bb[1])) // 2), "Pin", fill=tc, font=f)
        except Exception:
            pass
        pin_buf = BytesIO(); pin_img.save(pin_buf, format="PNG"); pin_buf.seek(0)

        view = discord.ui.LayoutView(timeout=300)
        container = discord.ui.Container(accent_colour=discord.Colour(0x7289DA))
        container.add_item(discord.ui.TextDisplay("## ⚙️ Map Settings"))

        gallery = discord.ui.MediaGallery()
        gallery.add_item(media="attachment://colors.png",
            description=f"Land `{_hex(colors.get('land'))}` · Water `{_hex(colors.get('water'))}` · Borders `{_hex(borders.get('country'))}`")
        container.add_item(gallery)
        row1 = discord.ui.ActionRow()
        edit_c_btn = discord.ui.Button(label="Edit Colors", emoji="🎨", style=discord.ButtonStyle.primary,
                                       custom_id=f"map_cv2_colors:{guild_id}")
        edit_c_btn.callback = self._cv2_color_modal_callback
        row1.add_item(edit_c_btn)
        container.add_item(row1)

        container.add_item(discord.ui.Separator())
        pin_gal = discord.ui.MediaGallery()
        pin_gal.add_item(media="attachment://pin.png", description=f"`{_hex(pin_c)}`")
        container.add_item(pin_gal)
        row_pin = discord.ui.ActionRow()
        edit_p_btn = discord.ui.Button(label="Edit Pin", emoji="📍", style=discord.ButtonStyle.secondary,
                                       custom_id=f"map_cv2_editpinbtn:{guild_id}")
        edit_p_btn.callback = self._cv2_pinconfig_modal_callback
        row_pin.add_item(edit_p_btn)
        row_pin.add_item(discord.ui.Button(label=f"Size: {pins_cfg.get('size', 14)}", emoji="📏",
                          style=discord.ButtonStyle.secondary, custom_id=f"map_cv2_pinsize_dummy:{guild_id}", disabled=True))
        container.add_item(row_pin)

        if show_preview_btn:
            container.add_item(discord.ui.Separator())
            row_preview = discord.ui.ActionRow()
            preview_btn = discord.ui.Button(label="Render Preview", emoji="🖼️", style=discord.ButtonStyle.success,
                                            custom_id=f"map_cv2_renderpreview:{guild_id}")
            preview_btn.callback = self._cv2_render_preview_callback
            row_preview.add_item(preview_btn)
            container.add_item(row_preview)

        container.add_item(discord.ui.Separator())
        row_bottom = discord.ui.ActionRow()
        back_btn = discord.ui.Button(label="Back", emoji="◀️", style=discord.ButtonStyle.secondary,
                                     custom_id=f"map_cv2_styleback:{guild_id}")
        back_btn.callback = self._cv2_style_back_callback
        row_bottom.add_item(back_btn)
        container.add_item(row_bottom)

        view.add_item(container)
        view._swatch_attachments = [discord.File(buf, "colors.png"), discord.File(pin_buf, "pin.png")]
        return view

    # ── Callbacks ─────────────────────────────────────────────────────

    async def _cv2_pin_callback(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild.id)
        user_id = str(interaction.user.id)
        try:
            if guild_id in self.maps and user_id in self.maps[guild_id].get('pins', {}):
                up = self.maps[guild_id]['pins'][user_id]
                ts = up.get('timestamp', '')
                try:
                    ts_fmt = f"<t:{int(datetime.fromisoformat(ts).timestamp())}:F>"
                except Exception:
                    ts_fmt = ts or "Unknown"
                view = discord.ui.LayoutView(timeout=300)
                c = discord.ui.Container(accent_colour=discord.Colour(0x7289DA))
                c.add_item(discord.ui.TextDisplay(
                    f"## 📍 Your Pin\n**Location:** {up.get('display_name', 'Unknown')}\n**Added:** {ts_fmt}"))
                row = discord.ui.ActionRow()
                edit_btn = discord.ui.Button(label="Edit", emoji="📍", style=discord.ButtonStyle.primary,
                                             custom_id=f"map_cv2_editpin:{guild_id}")
                edit_btn.callback = self._cv2_edit_pin_callback
                row.add_item(edit_btn)
                rem_btn = discord.ui.Button(label="Remove", emoji="❌", style=discord.ButtonStyle.danger,
                                            custom_id=f"map_cv2_removepin:{guild_id}")
                rem_btn.callback = self._cv2_remove_pin_callback
                row.add_item(rem_btn)
                c.add_item(row)
                view.add_item(c)
                await interaction.response.send_message(view=view, ephemeral=True)
            else:
                await interaction.response.send_modal(LocationModal(self, int(guild_id)))
        except discord.NotFound:
            pass


    async def _stale_map_response(self, interaction: discord.Interaction):
        """Show CV2 notice that the map no longer exists."""
        v = discord.ui.LayoutView(timeout=0)
        c = discord.ui.Container()
        c.add_item(discord.ui.TextDisplay("⛔ This map no longer exists. It may have been deleted."))
        v.add_item(c)
        try:
            await interaction.response.edit_message(view=v)
        except Exception:
            await interaction.response.send_message(view=v, ephemeral=True)
    async def _cv2_style_back_callback(self, interaction: discord.Interaction):
        """Return from the style/settings view to the /map dashboard."""
        from core.map_dashboard import build_map_dashboard
        view = await build_map_dashboard(self, interaction.guild.id)
        await interaction.response.edit_message(view=view, attachments=[])

    async def _cv2_admin_callback(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild.id)
        if guild_id not in self.maps:
            await self._stale_map_response(interaction)
            return
        self._snapshot_settings(guild_id)
        view = self._build_admin_view(interaction.guild.id)
        await interaction.response.edit_message(view=view,
            attachments=getattr(view, '_swatch_attachments', []))

    async def _cv2_color_modal_callback(self, interaction: discord.Interaction):
        from core.map_views_admin import ColorSettingsModal
        modal = ColorSettingsModal(self, interaction.guild.id, interaction)
        await interaction.response.send_modal(modal)

    async def _cv2_pinconfig_modal_callback(self, interaction: discord.Interaction):
        from core.map_views_admin import PinSettingsModal
        modal = PinSettingsModal(self, interaction.guild.id, interaction)
        await interaction.response.send_modal(modal)

    async def _cv2_edit_pin_callback(self, interaction: discord.Interaction):
        modal = UpdateLocationModal(self, interaction.guild.id, interaction)
        await interaction.response.send_modal(modal)

    async def _cv2_remove_pin_callback(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild.id)
        user_id = str(interaction.user.id)
        if guild_id in self.maps and user_id in self.maps[guild_id].get('pins', {}):
            del self.maps[guild_id]['pins'][user_id]
            await self._delete_pin(int(guild_id), int(user_id))
            await self._invalidate_map_cache(int(guild_id))
            channel_id = self.maps[guild_id]['channel_id']
            await self._update_map(int(guild_id), channel_id)
            await self._update_global_overview()
            v = discord.ui.LayoutView(timeout=0)
            v.add_item(discord.ui.Container().add_item(discord.ui.TextDisplay("❌ Pin removed.")))
            await interaction.response.edit_message(view=v)

    async def _cv2_render_preview_callback(self, interaction: discord.Interaction):
        """Generate a preview map and replace the admin card with preview."""
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild.id
        if str(guild_id) not in self.maps:
            v = discord.ui.LayoutView(timeout=0)
            v.add_item(discord.ui.Container().add_item(
                discord.ui.TextDisplay("⛔ Map no longer exists.")))
            await interaction.followup.edit_message(
                message_id=interaction.message.id, attachments=[], view=v)
            return
        map_data = self.maps.get(str(guild_id), {})
        settings = map_data.get('settings', {})

        result = await self._generate_preview_map(guild_id, settings)
        preview_file, _ = result if result else (None, None)
        if not preview_file:
            await interaction.followup.send("⛔ Failed to generate preview.", ephemeral=True)
            return
        container = discord.ui.Container(accent_colour=discord.Colour(0x57F287))
        container.add_item(discord.ui.TextDisplay(
            "## 🖼️ Map Preview\n-# This is how your map will look with the new settings."))
        gallery = discord.ui.MediaGallery()
        gallery.add_item(media="attachment://preview.png")
        container.add_item(gallery)
        row = discord.ui.ActionRow()
        apply_btn = discord.ui.Button(label="Apply", emoji="✅", style=discord.ButtonStyle.success,
                                      custom_id=f"map_cv2_applypreview:{guild_id}")
        apply_btn.callback = self._cv2_apply_preview_callback
        row.add_item(apply_btn)
        cancel_btn = discord.ui.Button(label="Cancel", emoji="❌", style=discord.ButtonStyle.danger,
                                       custom_id=f"map_cv2_cancelpreview:{guild_id}")
        cancel_btn.callback = self._cv2_cancel_preview_callback
        row.add_item(cancel_btn)
        container.add_item(row)
        view = discord.ui.LayoutView(timeout=300)
        view.add_item(container)
        await interaction.followup.edit_message(
            message_id=interaction.message.id,
            attachments=[preview_file], view=view)

    async def _cv2_apply_preview_callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild.id)
        if guild_id not in self.maps:
            v = discord.ui.LayoutView(timeout=0)
            v.add_item(discord.ui.Container().add_item(
                discord.ui.TextDisplay("⛔ Map no longer exists.")))
            await interaction.followup.edit_message(
                message_id=interaction.message.id, attachments=[], view=v)
            return
        self._snapshots.pop(guild_id, None)
        await self._save_data(guild_id)
        await self._invalidate_map_cache(int(guild_id))
        await self._update_map(int(guild_id), self.maps[guild_id]['channel_id'])
        await self._update_global_overview()
        v = discord.ui.LayoutView(timeout=1)
        v.add_item(discord.ui.Container().add_item(
            discord.ui.TextDisplay("✅ Settings applied. Map updated.")))
        await interaction.followup.edit_message(
            message_id=interaction.message.id, attachments=[], view=v)

    async def _cv2_cancel_preview_callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild.id)
        if guild_id not in self.maps:
            v = discord.ui.LayoutView(timeout=0)
            v.add_item(discord.ui.Container().add_item(
                discord.ui.TextDisplay("⛔ Map no longer exists.")))
            await interaction.followup.edit_message(
                message_id=interaction.message.id, attachments=[], view=v)
            return
        self._revert_settings(guild_id)
        await self._save_data(guild_id)
        v = discord.ui.LayoutView(timeout=1)
        v.add_item(discord.ui.Container().add_item(
            discord.ui.TextDisplay("❌ Preview cancelled. Settings reverted.")))
        await interaction.followup.edit_message(
            message_id=interaction.message.id, attachments=[], view=v)

    async def _cv2_feedback_callback(self, interaction: discord.Interaction):
        """Show ephemeral CV2 menu to pick subject + anonymity, then open modal."""
        try:
            await interaction.response.defer(ephemeral=True)
            from core.feedback_menu import build_feedback_menu
            fb_cog = self.bot.get_cog("FeedbackCog")
            if not fb_cog:
                self.log.error("Feedback callback: FeedbackCog not found")
                await interaction.followup.send("Feedback system unavailable.", ephemeral=True)
                return
            view = build_feedback_menu(fb_cog, interaction.guild_id, interaction.user.id)
            await interaction.followup.send(view=view, ephemeral=True)
        except Exception as e:
            self.log.error(f"Feedback callback failed: {e}", exc_info=True)
            try:
                await interaction.followup.send("Something went wrong. Try `/feedback` instead.", ephemeral=True)
            except Exception:
                pass
    async def cog_load(self):
        try:
            if not (hasattr(self.bot, 'db') and self.bot.db):
                self.log.error("Database not available")
                return
            self.maps = await self.bot.db.maps.load_all_maps()
            self.global_config = await self.bot.db.maps.get_all_global_config()
            await self.storage.cache.memory_cache.clear()

            for guild_id in list(self.maps.keys()):
                try:
                    guild = await self.bot.fetch_guild(int(guild_id))
                    self._guild_names[guild_id] = guild.name
                except Exception:
                    self._guild_names[guild_id] = str(guild_id)

            # Edit existing views on messages that still have IDs
            # NOTE: _update_map handles proper attachment+view regeneration.
            # Schedule cleanup + regen after guilds are synced
            global _APOLOGY_EXPIRY
            if _APOLOGY_EXPIRY == 0.0:
                exp_file = self.data_dir / ".apology_expiry"
                if exp_file.exists():
                    _APOLOGY_EXPIRY = float(exp_file.read_text().strip())
                    if time.time() > _APOLOGY_EXPIRY:
                        self.log.info("Apology expired — removing")
                        exp_file.unlink(missing_ok=True)
                        _APOLOGY_EXPIRY = 0.0
                    else:
                        self.log.info(f"Apology active until {_APOLOGY_EXPIRY} (from file)")
                else:
                    _APOLOGY_EXPIRY = time.time() + 86400
                    exp_file.write_text(str(_APOLOGY_EXPIRY))
                    self.log.info(f"Apology active until {_APOLOGY_EXPIRY} (24h from now)")
            self.bot.loop.create_task(self._delayed_regen())
        except Exception as e:
            self.log.error(f"cog_load failed: {e}")

    async def _update_map(self, guild_id: int, channel_id: int, interaction=None):
        try:
            channel = self.bot.get_channel(channel_id)
            if not channel:
                try:
                    channel = await self.bot.fetch_channel(channel_id)
                except (discord.NotFound, discord.Forbidden):
                    return

            map_file = await self._generate_map_image(guild_id)
            if not map_file:
                return
            map_file.filename = "map.png"

            map_data = self.maps.get(str(guild_id), {})
            view = self._build_map_card_view(guild_id)

            existing_message_id = map_data.get('message_id')
            if existing_message_id:
                try:
                    message = await channel.fetch_message(existing_message_id)
                    await message.edit(attachments=[map_file], view=view)
                    return
                except discord.NotFound:
                    pass

            message = await channel.send(file=map_file, view=view)
            if str(guild_id) not in self.maps:
                self.maps[str(guild_id)] = {}
            self.maps[str(guild_id)]['message_id'] = message.id
            await self._save_data(str(guild_id))
        except Exception as e:
            self.log.error(f"_update_map failed: {e}")

    async def cog_unload(self):
        for guild_id in list(self.maps.keys()):
            try:
                await self._save_data(guild_id)
            except Exception as e:
                self.log.warning(f"Save failed for {guild_id}: {e}")
    async def _delayed_regen(self):
        """Regenerate maps after guild cache is fully populated."""
        await asyncio.sleep(12)
        # Directly delete known orphan message IDs across all map channels
        known_orphans = {1525778227442876487, 1525778211303329882, 1525776468918009926,
                         1525776317172285511, 1525655394662350848}
        deleted_total = 0
        for guild_id_str, map_data in list(self.maps.items()):
            cid = map_data.get('channel_id')
            keep_id = str(map_data.get('message_id') or '')
            if not cid:
                continue
            try:
                channel = self.bot.get_channel(cid) or await self.bot.fetch_channel(cid)
            except discord.NotFound:
                self.log.info("Channel %s for guild %s was deleted — clearing stale map refs", cid, guild_id_str)
                self.maps[guild_id_str].pop('channel_id', None)
                self.maps[guild_id_str].pop('message_id', None)
                if hasattr(self.bot, 'db') and self.bot.db:
                    try:
                        await self.bot.db.maps.save_map_data(int(guild_id_str), self.maps[guild_id_str])
                    except Exception:
                        pass
                continue
            except discord.Forbidden:
                self.log.info("No access to channel %s for guild %s — skipping cleanup", cid, guild_id_str)
                continue
            except Exception as e:
                self.log.warning("Cleanup failed for guild %s: %s", guild_id_str, e)
                continue

            # Channel is accessible — clean up orphan messages
            try:
                # Targeted delete of known orphans
                for oid in list(known_orphans):
                    try:
                        msg = await channel.fetch_message(oid)
                        await msg.delete()
                        deleted_total += 1
                        known_orphans.discard(oid)
                        self.log.info(f"Deleted orphan {oid} from channel {cid}")
                    except discord.NotFound:
                        known_orphans.discard(oid)
                    except Exception:
                        pass
                # Broad sweep: delete all bot messages except the configured one
                async for msg in channel.history(limit=200):
                    if msg.author.id == self.bot.user.id and str(msg.id) != keep_id:
                        try:
                            await msg.delete()
                            deleted_total += 1
                            self.log.info(f"Deleted extra map message {msg.id} in channel {cid}")
                        except Exception as e:
                            self.log.warning(f"Failed to delete {msg.id}: {e}")
            except Exception as e:
                self.log.warning(f"Orphan cleanup failed for guild {guild_id_str}: {e}")

        if known_orphans:
            self.log.info(f"Could not delete orphans: {known_orphans}")
        if deleted_total:
            self.log.info(f"Deleted {deleted_total} map messages total")
        # Regenerate all maps that have a valid message_id
        for guild_id_str, map_data in list(self.maps.items()):
            cid = map_data.get('channel_id')
            gid_int = int(guild_id_str)
            if cid and map_data.get('message_id'):
                try:
                    await self._update_map(gid_int, cid)
                except Exception:
                    pass

    async def _save_data(self, guild_id: str):
        """Save map data for specific guild to database."""
        if hasattr(self.bot, 'db') and self.bot.db:
            guild_id_int = int(guild_id)
            if guild_id in self.maps:
                await self.bot.db.maps.save_map_data(guild_id_int, self.maps[guild_id])
            else:
                await self.bot.db.maps.delete_settings(guild_id_int)

    async def _delete_pin(self, guild_id: int, user_id: int):
        if hasattr(self.bot, 'db') and self.bot.db:
            await self.bot.db.maps.delete_pin(guild_id, user_id)

    async def _invalidate_map_cache(self, guild_id: int):
        await self.storage.invalidate_map_cache(guild_id)

    async def _delete_map_message(self, map_data: dict):
        channel_id = map_data.get('channel_id')
        message_id = map_data.get('message_id')
        if channel_id and message_id:
            try:
                channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
                message = await channel.fetch_message(message_id)
                await message.delete()
            except Exception:
                pass

    async def _generate_map_image(self, guild_id: int, progress_callback=None) -> Optional[discord.File]:
        try:
            map_data = self.maps.get(str(guild_id), {})
            region = map_data.get('region', 'world')
            pins = map_data.get('pins', {})
            width, height = self.map_generator.calculate_image_dimensions(region)

            base_map = await self.storage.get_cached_base_map(region, width, height, str(guild_id), self.maps)
            projection_func = None
            if not base_map:
                base_map, projection_func = await self.map_generator.render_geopandas_map(
                    region, width, height, str(guild_id), self.maps)
                if base_map:
                    await self.storage.cache_base_map(region, width, height, base_map, str(guild_id), self.maps)
            else:
                projection_func = self._create_projection_function(region, width, height)

            if not base_map or not projection_func:
                land_color, water_color = self.map_generator.get_map_colors(str(guild_id), self.maps)
                base_map = PILImage.new('RGB', (width, height), color=water_color)
                projection_func = self._create_projection_function(region, width, height)

            pin_color, custom_pin_size = self.map_generator.get_pin_settings(str(guild_id), self.maps)
            base_pin_size = int(height * custom_pin_size / 2400)
            pin_groups = self.map_generator.group_overlapping_pins(pins, projection_func, base_pin_size)
            self.map_generator.draw_pins_on_map(base_map, pin_groups, width, height, base_pin_size,
                                                str(guild_id), self.maps)
            img_buffer = BytesIO()
            base_map.save(img_buffer, format='PNG', optimize=True)
            img_buffer.seek(0)
            return discord.File(img_buffer, filename=f"map_{region}.png")
        except Exception as e:
            self.log.error(f"generate_map_image failed: {e}")
            return None

    async def _generate_preview_map(self, guild_id: int, preview_settings: Dict, progress_callback=None):
        """Generate map with override settings without modifying self.maps."""
        try:
            map_data = self.maps.get(str(guild_id), {})
            region = map_data.get('region', 'world')
            pins = map_data.get('pins', {})
            width, height = self.map_generator.calculate_image_dimensions(region)

            # Merge preview settings over original for color generation
            temp_maps = {str(guild_id): {**map_data, 'settings': preview_settings}}
            # Force cache miss so colors apply
            base_map, projection_func = await self.map_generator.render_geopandas_map(
                region, width, height, str(guild_id), temp_maps)

            if not base_map or not projection_func:
                land_color, water_color = self.map_generator.get_map_colors(str(guild_id), temp_maps)
                base_map = PILImage.new('RGB', (width, height), color=water_color)
                projection_func = self._create_projection_function(region, width, height)

            pin_color, custom_pin_size = self.map_generator.get_pin_settings(str(guild_id), temp_maps)
            base_pin_size = int(height * custom_pin_size / 2400)
            pin_groups = self.map_generator.group_overlapping_pins(pins, projection_func, base_pin_size)
            self.map_generator.draw_pins_on_map(base_map, pin_groups, width, height, base_pin_size,
                                                str(guild_id), temp_maps)

            img_buffer = BytesIO()
            base_map.save(img_buffer, format='PNG', optimize=True)
            img_buffer.seek(0)
            return (discord.File(img_buffer, filename="preview.png"), base_map)
        except Exception as e:
            self.log.error(f"_generate_preview_map failed: {e}")
            return (None, None)

    def _create_projection_function(self, region: str, width: int, height: int):
        data_path = Path(__file__).parent / "map_data"
        bounds = self.map_generator.map_config.get_region_bounds(region, data_path)
        (lat0, lon0), (lat1, lon1) = bounds
        minx, miny, maxx, maxy = lon0, lat0, lon1, lat1
        if region == "germany":
            try:
                base_path = Path(__file__).parent / "map_data"
                world = gpd.read_file(base_path / "ne_10m_admin_0_countries.shp")
                de = world[world["ADMIN"] == "Germany"].geometry.unary_union
                if de is not None:
                    minx, miny, maxx, maxy = de.bounds
            except Exception:
                pass
        # Mercator projection matching calculate_image_dimensions() aspect ratio
        def _merc_y(lat):
            return math.log(math.tan((90 + lat) * math.pi / 360))
        y_min = _merc_y(miny)
        y_max = _merc_y(maxy)
        y_range = y_max - y_min
        def to_px(lat, lon):
            x = (lon - minx) / (maxx - minx) * width
            y = (y_max - _merc_y(lat)) / y_range * height if y_range else 0
            return (int(x), int(y))
        return to_px

    async def _update_global_overview(self):
        pass

    # ── Dashboard helpers ──────────────────────────────────────────────

    async def dash_create_map(self, guild_id: int, channel_id: int, region: str, created_by: int):
        gid = str(guild_id)
        if gid in self.maps:
            return False, "A map already exists for this server."
        self.maps[gid] = {'region': region, 'channel_id': channel_id, 'pins': {},
                           'created_at': datetime.now().isoformat(), 'created_by': created_by}
        await self._save_data(gid)
        await self._update_map(guild_id, channel_id)
        await self._update_global_overview()
        return True, None

    async def dash_regenerate(self, guild_id: int):
        gid = str(guild_id)
        if gid not in self.maps:
            return
        await self._invalidate_map_cache(int(gid))
        await self._update_map(guild_id, self.maps[gid]['channel_id'])
        await self._update_global_overview()

    async def dash_delete_map(self, guild_id: int):
        gid = str(guild_id)
        if gid not in self.maps:
            return 0
        pin_count = len(self.maps[gid].get('pins', {}))
        await self._delete_map_message(self.maps[gid])
        await self._invalidate_map_cache(int(gid))
        del self.maps[gid]
        await self._save_data(gid)
        await self._update_global_overview()
        return pin_count

    async def dash_set_region(self, guild_id: int, region: str):
        gid = str(guild_id)
        if gid not in self.maps:
            return
        self.maps[gid]['region'] = region
        await self._save_data(gid)
        await self._invalidate_map_cache(int(gid))
        await self._update_map(guild_id, self.maps[gid]['channel_id'])

    async def dash_set_channel(self, guild_id: int, new_channel_id: int):
        gid = str(guild_id)
        if gid not in self.maps:
            return
        await self._delete_map_message(self.maps[gid])
        self.maps[gid]['channel_id'] = new_channel_id
        self.maps[gid].pop('message_id', None)
        await self._save_data(gid)
        await self._update_map(guild_id, new_channel_id)
        await self._update_global_overview()

    # ── Legacy pin handlers (called by map_views) ──────────────────────

    async def _handle_pin_location(self, interaction: discord.Interaction, location: str):
        """Geocode location, save pin, regenerate map — CV2."""
        guild_id = str(interaction.guild.id)
        user_id = str(interaction.user.id)

        if guild_id not in self.maps:
            v = discord.ui.LayoutView(timeout=0)
            c = discord.ui.Container()
            c.add_item(discord.ui.TextDisplay("⛔ No map exists for this server."))
            v.add_item(c)
            await interaction.followup.send(view=v, ephemeral=True)
            return

        is_update = user_id in self.maps[guild_id].get('pins', {})

        result = await self.map_generator.geocode_location(location)
        if not result:
            v = discord.ui.LayoutView(timeout=0)
            c = discord.ui.Container()
            c.add_item(discord.ui.TextDisplay(f"⛔ Could not find **'{location}'**. Try a more specific location."))
            v.add_item(c)
            await interaction.followup.send(view=v, ephemeral=True)
            return

        lat, lng, display_name, country_code = result

        region = self.maps[guild_id]['region']
        data_path = Path(__file__).parent / "map_data"
        bounds = self.map_generator.map_config.get_region_bounds(region, data_path)
        if not (bounds[0][0] <= lat <= bounds[1][0] and bounds[0][1] <= lng <= bounds[1][1]):
            v = discord.ui.LayoutView(timeout=0)
            c = discord.ui.Container()
            c.add_item(discord.ui.TextDisplay(f"⛔ **'{location}'** is outside the **{region}** map region."))
            v.add_item(c)
            await interaction.followup.send(view=v, ephemeral=True)
            return

        avatar_hash = interaction.user.avatar.key if interaction.user.avatar else None
        pin_data = {
            'username': interaction.user.display_name,
            'location': location,
            'display_name': display_name,
            'lat': lat,
            'lng': lng,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'avatar_hash': avatar_hash,
            'country_code': country_code,
        }
        self.maps[guild_id].setdefault('pins', {})[user_id] = pin_data

        await self._save_data(guild_id)
        await self._invalidate_map_cache(int(guild_id))
        channel_id = self.maps[guild_id]['channel_id']
        await self._update_map(int(guild_id), channel_id)
        await self._update_global_overview()

        v = discord.ui.LayoutView(timeout=0)
        c = discord.ui.Container()
        if is_update:
            c.add_item(discord.ui.TextDisplay(f"📌 Pin updated — **{display_name}**"))
        else:
            c.add_item(discord.ui.TextDisplay(f"📌 Pin added — **{display_name}**"))
        v.add_item(c)
        await interaction.followup.send(view=v, ephemeral=True)

    async def _handle_pin_location_update(self, interaction: discord.Interaction, location: str, modal_interaction: discord.Interaction, source_interaction: discord.Interaction = None):
        """Same as _handle_pin_location but via Edit button — uses modal followup.

        source_interaction is the button interaction whose message shows the
        pre-update "Your Pin" card; it's removed once the update succeeds so the
        stale location card doesn't linger next to the confirmation."""
        guild_id = str(interaction.guild.id)
        user_id = str(interaction.user.id)

        def _err(text):
            v = discord.ui.LayoutView(timeout=0)
            v.add_item(discord.ui.Container().add_item(discord.ui.TextDisplay(text)))
            return v

        if guild_id not in self.maps or user_id not in self.maps[guild_id].get('pins', {}):
            await modal_interaction.followup.send(view=_err("⛔ No pin found to update."), ephemeral=True)
            return

        result = await self.map_generator.geocode_location(location)
        if not result:
            await modal_interaction.followup.send(
                view=_err(f"⛔ Could not find **'{location}'**."), ephemeral=True)
            return

        lat, lng, display_name, country_code = result

        region = self.maps[guild_id]['region']
        data_path = Path(__file__).parent / "map_data"
        bounds = self.map_generator.map_config.get_region_bounds(region, data_path)
        if not (bounds[0][0] <= lat <= bounds[1][0] and bounds[0][1] <= lng <= bounds[1][1]):
            await modal_interaction.followup.send(
                view=_err(f"⛔ **'{location}'** is outside the **{region}** map region."), ephemeral=True)
            return

        old_location = self.maps[guild_id]['pins'][user_id].get('location', 'Unknown')
        avatar_hash = interaction.user.avatar.key if interaction.user.avatar else None
        pin_data = {
            'username': interaction.user.display_name,
            'location': location,
            'display_name': display_name,
            'lat': lat,
            'lng': lng,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'avatar_hash': avatar_hash,
            'country_code': country_code,
        }
        self.maps[guild_id]['pins'][user_id] = pin_data

        await self._save_data(guild_id)
        await self._invalidate_map_cache(int(guild_id))
        channel_id = self.maps[guild_id]['channel_id']
        await self._update_map(int(guild_id), channel_id)
        await self._update_global_overview()

        # Remove the stale "Your Pin" card that launched this edit.
        if source_interaction is not None and source_interaction.message is not None:
            try:
                await source_interaction.followup.delete_message(source_interaction.message.id)
            except Exception:
                pass

        v = discord.ui.LayoutView(timeout=0)
        c = discord.ui.Container()
        c.add_item(discord.ui.TextDisplay(
            f"📌 Pin updated\n{old_location} → **{display_name}**"))
        v.add_item(c)
        await modal_interaction.followup.send(view=v, ephemeral=True)
    async def _apply_cached_preview_as_map(self, guild_id: int, cached_preview: BytesIO) -> bool:
        pass

    async def _generate_fast_pin_preview(self, guild_id: int, preview_settings: Dict):
        pass

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        try:
            guild_id = str(member.guild.id)
            user_id = str(member.id)
            if guild_id in self.maps and user_id in self.maps[guild_id].get('pins', {}):
                del self.maps[guild_id]['pins'][user_id]
                await self._delete_pin(int(guild_id), int(user_id))
                await self._invalidate_map_cache(int(guild_id))
                channel_id = self.maps[guild_id]['channel_id']
                await self._update_map(int(guild_id), channel_id)
                await self._update_global_overview()
        except Exception as e:
            self.log.info(f"Error removing pin for leaving member: {e}")

    @app_commands.command(name="map", description="Manage the server map")
    @app_commands.default_permissions(administrator=True)
    async def map_dashboard(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Admin only.", ephemeral=True)
            return
        from core.map_dashboard import build_map_dashboard
        view = await build_map_dashboard(self, interaction.guild.id)
        await interaction.response.send_message(view=view, ephemeral=True)

    @app_commands.command(name="map_pin", description="Manage your location on the server map")
    async def pin_on_map_v2(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild.id)
        if guild_id not in self.maps:
            await interaction.response.send_message("⛔ No map exists.", ephemeral=True)
            return
        user_id = str(interaction.user.id)
        if user_id in self.maps[guild_id].get('pins', {}):
            up = self.maps[guild_id]['pins'][user_id]
            embed = discord.Embed(title="📍 Your Current Location",
                description=f"**Location:** {up.get('display_name', 'Unknown')}\n**Added:** {up.get('timestamp', 'Unknown')}",
                color=0x7289da)
            view = UserPinOptionsView(self, int(guild_id))
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        else:
            await interaction.response.send_modal(LocationModal(self, int(guild_id)))


async def setup(bot: commands.Bot):
    await bot.add_cog(MapV2Cog(bot))
