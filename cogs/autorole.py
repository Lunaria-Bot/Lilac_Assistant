import logging
import asyncio
import discord
from discord.ext import commands
from discord import app_commands

from config import (
    GUILD_ID, NOTIFY_CHANNEL_ID, REDIS_URL, REDIS_TTL,
    LVL10_ROLE_ID, CROSS_TRADE_ACCESS_ID, CROSS_TRADE_BAN_ID, MARKET_BAN_ID,
)
from utils.embed_builder import LilacEmbed
import redis.asyncio as redis

log = logging.getLogger("cog-autorole")


class AutoRole(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.scanning = False
        self.changed_members: list[discord.Member] = []
        self.redis = None

    async def cog_load(self):
        self.redis = redis.from_url(REDIS_URL, decode_responses=True)

    async def cog_unload(self):
        if self.redis:
            await self.redis.close()

    # ─────────────────────────────────────────────
    # Core logic
    # ─────────────────────────────────────────────

    async def update_cross_trade_access(self, member: discord.Member):
        guild        = member.guild
        access_role  = guild.get_role(CROSS_TRADE_ACCESS_ID)
        lvl10_role   = guild.get_role(LVL10_ROLE_ID)
        ban_role     = guild.get_role(CROSS_TRADE_BAN_ID)
        market_ban   = guild.get_role(MARKET_BAN_ID)

        if not access_role:
            return

        should_have = (
            lvl10_role in member.roles
            and ban_role not in member.roles
            and market_ban not in member.roles
        )

        key = f"autorole:{guild.id}:{member.id}"
        cached = await self.redis.get(key)
        if cached is not None and (cached == "1") == should_have:
            return  # already correct

        try:
            if should_have and access_role not in member.roles:
                await member.add_roles(access_role, reason="AutoRole: Lvl10 without ban")
                log.info("✅ Added Cross Trade Access to %s", member.display_name)
                self.changed_members.append(member)
            elif not should_have and access_role in member.roles:
                await member.remove_roles(access_role, reason="AutoRole: ban detected or not Lvl10")
                log.info("🚫 Removed Cross Trade Access from %s", member.display_name)
                self.changed_members.append(member)

            await self.redis.set(key, "1" if should_have else "0", ex=REDIS_TTL)
            await asyncio.sleep(1.2)  # rate-limit throttle

        except discord.Forbidden:
            log.error("❌ Missing permissions for %s", member.display_name)

    # ─────────────────────────────────────────────
    # Listener
    # ─────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if self.scanning or before.roles == after.roles:
            return
        await self.update_cross_trade_access(after)
        key = f"autorole:{after.guild.id}:{after.id}"
        has_access = CROSS_TRADE_ACCESS_ID in {r.id for r in after.roles}
        await self.redis.set(key, "1" if has_access else "0", ex=REDIS_TTL)

    # ─────────────────────────────────────────────
    # /check_autorole_all
    # ─────────────────────────────────────────────

    @app_commands.command(name="check_autorole_all", description="Force a global role check for all members")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.default_permissions(administrator=True)
    async def check_autorole_all(self, interaction: discord.Interaction):
        guild = interaction.guild
        access_role = guild.get_role(CROSS_TRADE_ACCESS_ID)
        if not access_role:
            return await interaction.response.send_message(
                embed=LilacEmbed.warning(
                    "Role not found",
                    "Cross Trade Access role is missing from this server.",
                ),
                ephemeral=True,
            )

        await interaction.response.send_message(
            embed=LilacEmbed.info(
                "Global check started",
                "🔍 Scanning all members… progress will be posted in this channel.",
            ),
            ephemeral=True,
        )

        total = len(guild.members)
        checked = 0
        self.scanning = True
        self.changed_members = []

        for member in guild.members:
            await self.update_cross_trade_access(member)
            checked += 1
            if checked % 25 == 0 or checked == total:
                await interaction.channel.send(
                    embed=LilacEmbed.info(
                        "Progress",
                        f"Checked **{checked}/{total}** members…",
                    )
                )

        self.scanning = False
        await interaction.channel.send(
            embed=LilacEmbed.success("Global check complete", f"All **{total}** members have been reviewed.")
        )
        log.info("♻️ Manual global role check completed in %s", guild.name)

        # Notify changed members
        if self.changed_members:
            channel = guild.get_channel(NOTIFY_CHANNEL_ID)
            if channel:
                await channel.send(
                    embed=LilacEmbed.info(
                        "AutoRole update complete 🎉",
                        f"**{len(self.changed_members)}** user(s) were updated.",
                    )
                )
                batch_size = 20
                for i in range(0, len(self.changed_members), batch_size):
                    mentions = " ".join(m.mention for m in self.changed_members[i:i + batch_size])
                    await channel.send(mentions)


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoRole(bot))
    log.info("⚙️ AutoRole cog loaded")
