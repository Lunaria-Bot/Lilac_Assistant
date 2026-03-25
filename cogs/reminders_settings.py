"""
reminders_settings.py — Slash command /reminders
Allows users to configure their reminder preferences:
  - Enable/disable summon reminders
  - Toggle premium mode (15 min cooldown vs 30 min default)
"""

import logging
import discord
from discord import app_commands
from discord.ext import commands

from config import COOLDOWN_SECONDS, PREMIUM_COOLDOWN_SECONDS, GUILD_ID

log = logging.getLogger("cog-reminders-settings")


class RemindersSettings(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ─────────────────────────────────────────────
    # Redis helpers
    # ─────────────────────────────────────────────

    def _key(self, guild_id: int, user_id: int, setting: str) -> str:
        return f"reminder:settings:{guild_id}:{user_id}:{setting}"

    async def _get(self, guild_id: int, user_id: int, setting: str) -> str | None:
        if not getattr(self.bot, "redis", None):
            return None
        return await self.bot.redis.get(self._key(guild_id, user_id, setting))

    async def _set(self, guild_id: int, user_id: int, setting: str, value: str):
        if not getattr(self.bot, "redis", None):
            return
        await self.bot.redis.set(self._key(guild_id, user_id, setting), value)

    # ─────────────────────────────────────────────
    # /reminders group
    # ─────────────────────────────────────────────

    reminders_group = app_commands.Group(
        name="reminders",
        description="Manage your personal reminder settings.",
        guild_ids=[GUILD_ID],
    )

    @reminders_group.command(name="status", description="Show your current reminder settings.")
    async def reminders_status(self, interaction: discord.Interaction):
        """Displays the user's current reminder configuration."""
        if not getattr(self.bot, "redis", None):
            await interaction.response.send_message(
                "⚠️ Redis is not available. Settings cannot be read.", ephemeral=True
            )
            return

        guild_id = interaction.guild_id
        user_id  = interaction.user.id

        summon_val  = await self._get(guild_id, user_id, "summon")
        premium_val = await self._get(guild_id, user_id, "premium")

        summon_enabled  = summon_val != "0"
        premium_enabled = premium_val == "1"

        cooldown_min = PREMIUM_COOLDOWN_SECONDS // 60 if premium_enabled else COOLDOWN_SECONDS // 60

        embed = discord.Embed(
            title="⚙️ Your Reminder Settings",
            color=0xC8A2C8,  # Lilac brand color
        )
        embed.add_field(
            name="🔔 Summon Reminders",
            value="✅ Enabled" if summon_enabled else "❌ Disabled",
            inline=True,
        )
        embed.add_field(
            name="⭐ Premium Mode",
            value=f"✅ Active — **{cooldown_min} min** cooldown" if premium_enabled
                  else f"❌ Inactive — **{cooldown_min} min** cooldown (default)",
            inline=True,
        )
        embed.set_footer(text="Use /reminders premium or /reminders summon to change settings.")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @reminders_group.command(
        name="premium",
        description="Toggle premium mode (15 min cooldown instead of 30 min).",
    )
    @app_commands.describe(enabled="Enable or disable premium mode.")
    async def reminders_premium(self, interaction: discord.Interaction, enabled: bool):
        """Toggles premium cooldown (15 min) for summon reminders."""
        if not getattr(self.bot, "redis", None):
            await interaction.response.send_message(
                "⚠️ Redis is not available. Settings cannot be saved.", ephemeral=True
            )
            return

        await self._set(interaction.guild_id, interaction.user.id, "premium", "1" if enabled else "0")

        cooldown_min = PREMIUM_COOLDOWN_SECONDS // 60 if enabled else COOLDOWN_SECONDS // 60
        status_text  = (
            f"✅ **Premium mode enabled!** Your summon reminder cooldown is now **{cooldown_min} min**."
            if enabled else
            f"❌ **Premium mode disabled.** Your summon reminder cooldown is back to **{cooldown_min} min**."
        )

        embed = discord.Embed(description=status_text, color=0xC8A2C8)
        await interaction.response.send_message(embed=embed, ephemeral=True)

        log.info(
            "⭐ Premium mode %s for %s (guild %s)",
            "enabled" if enabled else "disabled",
            interaction.user,
            interaction.guild_id,
        )

    @reminders_group.command(
        name="summon",
        description="Enable or disable summon reminders for yourself.",
    )
    @app_commands.describe(enabled="Enable or disable summon reminders.")
    async def reminders_summon(self, interaction: discord.Interaction, enabled: bool):
        """Toggles whether the bot sends you a summon reminder."""
        if not getattr(self.bot, "redis", None):
            await interaction.response.send_message(
                "⚠️ Redis is not available. Settings cannot be saved.", ephemeral=True
            )
            return

        await self._set(interaction.guild_id, interaction.user.id, "summon", "1" if enabled else "0")

        status_text = (
            "✅ **Summon reminders enabled!** You'll be pinged when your summon is ready."
            if enabled else
            "❌ **Summon reminders disabled.** You won't receive summon pings anymore."
        )

        embed = discord.Embed(description=status_text, color=0xC8A2C8)
        await interaction.response.send_message(embed=embed, ephemeral=True)

        log.info(
            "🔔 Summon reminders %s for %s (guild %s)",
            "enabled" if enabled else "disabled",
            interaction.user,
            interaction.guild_id,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(RemindersSettings(bot))
    log.info("⚙️ RemindersSettings cog loaded (/reminders group ready)")
