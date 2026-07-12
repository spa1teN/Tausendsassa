"""Feedback cog — /feedback slash command, modal, DB storage."""

from __future__ import annotations

import logging
from typing import Optional

import discord
from discord.ext import commands

log = logging.getLogger("tausendsassa.feedback")




FEEDBACK_MODAL_ID = "feedback:modal"


class FeedbackModal(discord.ui.Modal, title="Feedback"):
    """Message-only modal. Subject and anonymity set by the CV2 menu."""

    message = discord.ui.TextInput(
        label="Your message",
        style=discord.TextStyle.long,
        placeholder="What would you like to tell Caspar?",
        required=True,
        max_length=2000,
    )

    def __init__(self, cog: FeedbackCog, guild_id: int, user_id: int,
                 subject: str = "other", anonymous: bool = False):
        super().__init__()
        self.cog = cog
        self.guild_id = guild_id
        self.user_id = user_id
        self._subject = subject
        self._anonymous = anonymous

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            if hasattr(self.cog.bot, "db") and self.cog.bot.db:
                await self.cog.bot.db.feedback.submit(
                    guild_id=self.guild_id,
                    user_id=0 if self._anonymous else self.user_id,
                    is_anonymous=self._anonymous,
                    subject=self._subject,
                    message=self.message.value,
                )
                log.info("Feedback: guild=%s user=%s subj=%s anon=%s",
                         self.guild_id, "anon" if self._anonymous else self.user_id,
                         self._subject, self._anonymous)
                await interaction.followup.send("✅ Feedback sent! Thank you.", ephemeral=True)
            else:
                log.warning("Feedback storage unavailable")
                await interaction.followup.send("⚠️ Feedback storage unavailable.", ephemeral=True)
        except Exception:
            log.exception("Failed to store feedback")
            await interaction.followup.send("❌ Failed to store feedback.", ephemeral=True)
        await interaction.delete_original_response()

class FeedbackCog(commands.Cog):
    """Feedback submission via /feedback command."""

    FeedbackModal = FeedbackModal  # expose for cross-cog access

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @discord.app_commands.command(
        name="feedback", description="Send feedback to the bot owner"
    )
    async def feedback_cmd(self, interaction: discord.Interaction):
        """Open the feedback menu."""
        if not interaction.guild:
            await interaction.response.send_message(
                "Feedback is only available in servers.", ephemeral=True)
            return
        from core.feedback_menu import build_feedback_menu
        view = build_feedback_menu(self, interaction.guild_id, interaction.user.id)
        await interaction.response.send_message(view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(FeedbackCog(bot))
