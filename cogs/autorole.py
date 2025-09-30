import logging
import asyncio
import discord
from discord.ext import commands
from discord import app_commands

log = logging.getLogger("cog-autorole")

# Role IDs
LVL10_ROLE_ID = 1297161587744047106
CROSS_TRADE_ACCESS_ID = 1306954214106202145  # ⚠️ Put the exact Cross Trade Access role ID here
CROSS_TRADE_BAN_ID = 1306954214106202144
MARKET_BAN_ID = 1306958134245457970


class AutoRole(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def update_cross_trade_access(self, member: discord.Member):
        """Check member roles and adjust Cross Trade Access accordingly."""
        guild = member.guild
        access_role = guild.get_role(CROSS_TRADE_ACCESS_ID)
        lvl10_role = guild.get_role(LVL10_ROLE_ID)
        ban_role = guild.get_role(CROSS_TRADE_BAN_ID)
        market_ban_role = guild.get_role(MARKET_BAN_ID)

        if not access_role:
            return  # Skip if the role does not exist in this guild

        try:
            # Condition: must have lvl10 AND must not have ban roles
            if lvl10_role in member.roles and ban_role not in member.roles and market_ban_role not in member.roles:
                if access_role not in member.roles:
                    await member.add_roles(access_role, reason="AutoRole: Lvl10 without ban")
                    log.info("✅ Added Cross Trade Access to %s", member.display_name)
            else:
                if access_role in member.roles:
                    await member.remove_roles(access_role, reason="AutoRole: Ban detected or not lvl10")
                    log.info("🚫 Removed Cross Trade Access from %s", member.display_name)

            # 🔑 Throttle to avoid hitting Discord rate limits
            await asyncio.sleep(1.2)

        except discord.Forbidden:
            log.error("❌ Missing permissions to modify roles for %s", member.display_name)

    # --- Event: when a member's roles are updated ---
    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.roles != after.roles:
            await self.update_cross_trade_access(after)

    # --- Global check at startup ---
    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            log.info("🔍 Running global role check in %s...", guild.name)
            access_role = guild.get_role(CROSS_TRADE_ACCESS_ID)
            if not access_role:
                log.warning("⚠️ Cross Trade Access role not found in %s, skipping.", guild.name)
                continue

            for member in guild.members:
                await self.update_cross_trade_access(member)
        log.info("✅ Global role check completed.")

    # --- Slash command: check one member ---
    @app_commands.command(name="check_autorole", description="Force a role check for a specific member")
    @app_commands.default_permissions(administrator=True)
    async def check_autorole(self, interaction: discord.Interaction, member: discord.Member = None):
        if not member:
            member = interaction.user
        await self.update_cross_trade_access(member)
        await interaction.response.send_message(
            f"🔄 Role check completed for {member.display_name}", ephemeral=True
        )

    # --- Slash command: check all members with progress updates ---
    @app_commands.command(name="check_autorole_all", description="Force a global role check for all members")
    @app_commands.default_permissions(administrator=True)
    async def check_autorole_all(self, interaction: discord.Interaction):
        guild = interaction.guild
        access_role = guild.get_role(CROSS_TRADE_ACCESS_ID)
        if not access_role:
            await interaction.response.send_message(
                "⚠️ Cross Trade Access role not found in this server, skipping.", ephemeral=True
            )
            return

        await interaction.response.send_message(
            "🔍 Starting global role check... This may take a while.", ephemeral=True
        )

        total = len(guild.members)
        checked = 0

        # Send progress updates every 25 members
        for member in guild.members:
            await self.update_cross_trade_access(member)
            checked += 1
            if checked % 25 == 0 or checked == total:
                await interaction.followup.send(
                    f"Progress: {checked}/{total} members checked...", ephemeral=True
                )

        await interaction.followup.send("✅ Global role check completed.", ephemeral=True)
        log.info("♻️ Manual global role check completed in %s", guild.name)


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoRole(bot))
    log.info("⚙️ AutoRole cog loaded")
