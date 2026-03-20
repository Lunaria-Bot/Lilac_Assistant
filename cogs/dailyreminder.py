import logging
import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timedelta, timezone
import redis.asyncio as redis

from config import GUILD_ID, LOG_CHANNEL_ID, REDIS_URL, DAILY_MESSAGE
from utils.embed_builder import LilacEmbed

log = logging.getLogger("cog-dailyreminder")

DAILY_KEY = "dailyreminder:subscribers"


class DailyReminder(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot   = bot
        self.redis = None
        self.daily_task.start()

    async def cog_load(self):
        self.redis = redis.from_url(REDIS_URL, decode_responses=True)

    async def cog_unload(self):
        if self.redis:
            await self.redis.close()
        self.daily_task.cancel()

    # ─────────────────────────────────────────────
    # /toggle-daily
    # ─────────────────────────────────────────────

    @app_commands.command(name="toggle-daily", description="Toggle your daily Mazoku reminder on/off")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def toggle_daily(self, interaction: discord.Interaction):
        uid        = str(interaction.user.id)
        subscribed = await self.redis.sismember(DAILY_KEY, uid)

        if subscribed:
            await self.redis.srem(DAILY_KEY, uid)
            await interaction.response.send_message(
                embed=LilacEmbed.info("Reminder disabled", "⏸️ You will no longer receive daily reminders."),
                ephemeral=True,
            )
        else:
            await self.redis.sadd(DAILY_KEY, uid)
            await interaction.response.send_message(
                embed=LilacEmbed.success("Reminder enabled", "You will now receive daily Mazoku reminders! 🎉"),
                ephemeral=True,
            )

    # ─────────────────────────────────────────────
    # /list-daily (admin)
    # ─────────────────────────────────────────────

    @app_commands.command(name="list-daily", description="List all subscribers (admin)")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def list_daily(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                embed=LilacEmbed.error("Access denied", "This command is reserved for admins."),
                ephemeral=True,
            )

        subscribers = await self.redis.smembers(DAILY_KEY)
        if not subscribers:
            return await interaction.response.send_message(
                embed=LilacEmbed.info("No subscribers", "📭 Nobody is currently subscribed to daily reminders."),
                ephemeral=True,
            )

        guild    = interaction.guild
        mentions = [
            guild.get_member(int(uid)).mention if guild.get_member(int(uid)) else f"<@{uid}>"
            for uid in subscribers
        ]
        embed = LilacEmbed.info(
            f"Daily subscribers — {len(subscribers)}",
            ", ".join(mentions),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ─────────────────────────────────────────────
    # Daily task (fires at midnight UTC)
    # ─────────────────────────────────────────────

    @tasks.loop(hours=24)
    async def daily_task(self):
        guild = self.bot.get_guild(GUILD_ID)
        if not guild:
            return

        subscribers = await self.redis.smembers(DAILY_KEY)
        if not subscribers:
            return

        success, failed = 0, 0
        for uid in subscribers:
            member = guild.get_member(int(uid))
            if member:
                try:
                    await member.send(DAILY_MESSAGE)
                    success += 1
                except discord.Forbidden:
                    failed += 1

        log_channel = guild.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            embed = LilacEmbed.success(
                "Daily reminder summary",
                f"🕛 {now}\n✅ Sent: **{success}** | ❌ Failed: **{failed}** | 👥 Total: **{len(subscribers)}**",
            )
            await log_channel.send(embed=embed)

    @daily_task.before_loop
    async def before_daily_task(self):
        await self.bot.wait_until_ready()
        now    = datetime.now(timezone.utc)
        target = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        await discord.utils.sleep_until(target)


async def setup(bot: commands.Bot):
    await bot.add_cog(DailyReminder(bot))
    log.info("⚙️ DailyReminder cog loaded")
