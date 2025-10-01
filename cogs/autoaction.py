import logging
import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timedelta, timezone

log = logging.getLogger("cog-autoaction")

CHANNEL_ID = 1306721777686417448  # channel to clean + post
LOG_CHANNEL_ID = 1421465080238964796  # channel for logs

MESSAGE = (
    "# New Week <:lilacduck:1397290897200250950>\n"
    "You can post your ads, remember to follow "
    "https://discord.com/channels/1293611593845706793/1306692387342385317"
)

GUILD_ID = 1293611593845706793  # your server ID
RESET_ROLE_ID = 1305252546608365599  # ✅ role allowed to use /reset_ads


class AutoAction(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.weekly_task.start()

    def cog_unload(self):
        self.weekly_task.cancel()

    def next_sunday_midnight(self):
        """Return datetime of next Sunday 00:00 UTC."""
        now = datetime.now(timezone.utc)
        days_ahead = (6 - now.weekday()) % 7
        if days_ahead == 0 and now.hour >= 0:
            days_ahead = 7
        next_sunday = (now + timedelta(days=days_ahead)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return next_sunday

    @tasks.loop(hours=168)  # 7 days
    async def weekly_task(self):
        await self.bot.wait_until_ready()
        await self.clean_and_post(trigger="Automatic weekly reset")

    @weekly_task.before_loop
    async def before_weekly_task(self):
        await self.bot.wait_until_ready()
        now = datetime.now(timezone.utc)
        target = self.next_sunday_midnight()
        wait_time = (target - now).total_seconds()
        log.info("⏳ Waiting %.2f seconds until next Sunday midnight UTC", wait_time)
        await discord.utils.sleep_until(target)

    async def clean_and_post(self, trigger: str):
        """Helper to purge channel and post the weekly message."""
        channel = self.bot.get_channel(CHANNEL_ID)
        log_channel = self.bot.get_channel(LOG_CHANNEL_ID)

        if not channel:
            log.error("❌ Could not find channel %s", CHANNEL_ID)
            return

        try:
            # Purge all messages
            await channel.purge(limit=None)
            log.info("🧹 Cleared channel %s", channel.name)

            # Post new weekly message
            await channel.send(MESSAGE)
            log.info("📢 Posted new weekly message in %s", channel.name)

            # Log in the log channel
            if log_channel:
                now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                await log_channel.send(f"📝 {trigger} at {now}: Channel {channel.mention} has been reset.")

        except discord.Forbidden:
            log.error("❌ Missing permissions to manage messages in %s", channel.name)

    # --- Manual slash command ---
    @app_commands.command(name="reset_ads", description="Manually reset the ads channel")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def reset_ads(self, interaction: discord.Interaction):
        # Allow if user has the required role OR is an administrator
        is_admin = interaction.user.guild_permissions.administrator
        has_role = any(role.id == RESET_ROLE_ID for role in interaction.user.roles)

        if not (is_admin or has_role):
            await interaction.response.send_message(
                "⛔ You don’t have permission to use this command.", ephemeral=True
            )
            return

        await interaction.response.send_message("🔄 Resetting ads channel...", ephemeral=True)
        await self.clean_and_post(trigger=f"Manual reset by {interaction.user.mention}")
        await interaction.followup.send("✅ Ads channel has been reset and new message posted.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoAction(bot))
    log.info("⚙️ AutoAction cog loaded")
