"""Ephemeral CV2 menu for selecting feedback subject + anonymity before opening the modal."""

from __future__ import annotations

import discord


SUBJECT_OPTIONS = [
    discord.SelectOption(label="📰 Feeds", value="feeds"),
    discord.SelectOption(label="🗺️ Map", value="map"),
    discord.SelectOption(label="🛡️ Moderation", value="moderation"),
    discord.SelectOption(label="📅 Calendar", value="calendar"),
    discord.SelectOption(label="💡 Proposals", value="proposals"),
    discord.SelectOption(label="💬 Other", value="other"),
]


def build_feedback_menu(
    cog,
    guild_id: int,
    user_id: int,
) -> discord.ui.LayoutView:
    """Build an ephemeral CV2 view with subject select + anonymous toggle + submit."""

    view = discord.ui.LayoutView(timeout=300)
    container = discord.ui.Container(accent_colour=discord.Colour(0x5865F2))

    container.add_item(discord.ui.TextDisplay(
        "## 💬 Feedback\n-# Pick subject and anonymity, then write your message."))
    container.add_item(discord.ui.Separator())
    view.add_item(container)

    # Select must be in a top-level ActionRow — CV2 containers do not accept selects
    subject_select = discord.ui.Select(
        custom_id="feedback_menu:subject",
        placeholder="Subject…",
        options=SUBJECT_OPTIONS,
        min_values=1, max_values=1,
    )
    select_row = discord.ui.ActionRow()
    select_row.add_item(subject_select)
    view.add_item(select_row)

    # Anonymity toggle
    state: dict[str, str | bool] = {"subject": "other", "anonymous": False}
    toggle_row = discord.ui.ActionRow()
    anon_btn = discord.ui.Button(
        label="Anonymous: No", emoji="👤",
        style=discord.ButtonStyle.secondary,
        custom_id="feedback_menu:anon",
    )
    toggle_row.add_item(anon_btn)
    view.add_item(toggle_row)

    # Submit button
    submit_row = discord.ui.ActionRow()
    submit_btn = discord.ui.Button(
        label="Write Message", emoji="✏️",
        style=discord.ButtonStyle.primary,
        custom_id="feedback_menu:submit",
    )
    submit_row.add_item(submit_btn)
    view.add_item(submit_row)

    async def on_subject(interaction: discord.Interaction) -> None:
        state["subject"] = subject_select.values[0]
        await interaction.response.defer()

    async def on_anon(interaction: discord.Interaction) -> None:
        state["anonymous"] = not state["anonymous"]
        anon_btn.label = f"Anonymous: {'Yes' if state['anonymous'] else 'No'}"
        anon_btn.emoji = "🕶️" if state["anonymous"] else "👤"
        await interaction.response.edit_message(view=view)

    async def on_submit(interaction: discord.Interaction) -> None:
        fb_cog = cog.bot.get_cog("FeedbackCog") if hasattr(cog, "bot") else cog
        modal = fb_cog.FeedbackModal(
            fb_cog, guild_id, user_id,
            subject=state["subject"],
            anonymous=state["anonymous"],
        )
        await interaction.response.send_modal(modal)

    subject_select.callback = on_subject
    anon_btn.callback = on_anon
    submit_btn.callback = on_submit

    return view
