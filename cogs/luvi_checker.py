import discord
from discord.ext import commands
from discord import app_commands

from config import REQUIRED_ROLES_FOR_T3, ROLE_TIER_3, LOG_CHANNEL_ID
from utils.embed_builder import LilacEmbed

import logging
log = logging.getLogger("cog-luvi-checker")


class LuviChecker(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="luvi_check",
        description="Remove Tier 3 from users who no longer meet the requirements.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def luvi_check(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            embed=LilacEmbed.info("Luvi check started", "Scanning members… this may take a moment."),
            ephemeral=True,
        )

        guild        = interaction.guild
        log_channel  = guild.get_channel(LOG_CHANNEL_ID)
        role_t3      = guild.get_role(ROLE_TIER_3)
        removed      = []

        for member in guild.members:
            if role_t3 not in member.roles:
                continue
            if not any(r.id in REQUIRED_ROLES_FOR_T3 for r in member.roles):
                try:
                    await member.remove_roles(role_t3, reason="Failed Luvi check")
                    removed.append(member)
                except Exception:
                    pass

        if not log_channel:
            return

        if not removed:
            await log_channel.send(
                embed=LilacEmbed.success(
                    "Luvi Check — No changes",
                    "All Tier 3 members meet the requirements. ✅",
                )
            )
            return

        # Send results in pages of 25
        chunk_size = 25
        chunks     = [removed[i:i + chunk_size] for i in range(0, len(removed), chunk_size)]
        for idx, chunk in enumerate(chunks, start=1):
            embed = LilacEmbed(
                title=f"🔍  Luvi Check — Removed Tier 3 ({idx}/{len(chunks)})",
                description=f"**{len(removed)}** user(s) lost Tier 3 due to missing required roles.",
                color=0xED4245,
            )
            for user in chunk:
                embed.add_field(name=user.display_name, value=f"`{user.id}`", inline=True)
            await log_channel.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(LuviChecker(bot))
    log.info("⚙️ LuviChecker cog loaded")
