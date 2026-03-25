import logging
import asyncio
import time
import discord
from discord.ext import commands, tasks

from config import GUILD_ID, COOLDOWN_SECONDS, REMINDER_CLEANUP_MINUTES

log = logging.getLogger("cog-clan-reminder")


class ClanReminder(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active_reminders: dict[int, asyncio.Task] = {}
        self.cleanup_task.start()

    def cog_unload(self):
        self.cleanup_task.cancel()

    # ─────────────────────────────────────────────
    # Send helper
    # ─────────────────────────────────────────────

    async def send_reminder_message(self, member: discord.Member, channel: discord.TextChannel):
        try:
            await channel.send(
                f"⚔️ Hey {member.mention}! Your clan summon spell is ready to cast! "
                f"Choose wisely <:Kanna_Cool:1298168957420834816>",
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            )
            log.info("⏰ Clan reminder sent to %s in #%s", member.display_name, channel.name)
        except discord.Forbidden:
            log.warning("❌ Cannot send clan reminder in #%s", channel.name)

    # ─────────────────────────────────────────────
    # Settings check
    # ─────────────────────────────────────────────

    async def is_reminder_enabled(self, member: discord.Member) -> bool:
        if not getattr(self.bot, "redis", None):
            return True
        val = await self.bot.redis.get(
            f"reminder:settings:{member.guild.id}:{member.id}:clan"
        )
        return val != "0"

    # ─────────────────────────────────────────────
    # Start / restore reminders
    # ─────────────────────────────────────────────

    async def start_reminder(self, member: discord.Member, channel: discord.TextChannel):
        if not await self.is_reminder_enabled(member):
            return
        user_id   = member.id
        redis_key = f"reminder:clan:{user_id}"

        if user_id in self.active_reminders:
            return

        if getattr(self.bot, "redis", None):
            await self.bot.redis.hset(
                redis_key,
                mapping={"expire_at": int(time.time()) + COOLDOWN_SECONDS, "channel_id": channel.id},
            )

        async def _task():
            try:
                await asyncio.sleep(COOLDOWN_SECONDS)
                if await self.is_reminder_enabled(member):
                    await self.send_reminder_message(member, channel)
            finally:
                self.active_reminders.pop(user_id, None)
                if getattr(self.bot, "redis", None):
                    await self.bot.redis.delete(redis_key)

        self.active_reminders[user_id] = asyncio.create_task(_task())
        log.info("▶️ Clan reminder started for %s (%ss)", member.display_name, COOLDOWN_SECONDS)

    async def restore_reminders(self):
        if not getattr(self.bot, "redis", None):
            return
        guild = self.bot.get_guild(GUILD_ID)
        if not guild:
            return

        now  = int(time.time())
        keys = await self.bot.redis.keys("reminder:clan:*")

        for redis_key in keys:
            try:
                user_id = int(redis_key.split(":")[-1])
            except ValueError:
                continue

            data = await self.bot.redis.hgetall(redis_key)
            if not data:
                continue

            remaining = int(data.get("expire_at", 0)) - now
            if remaining <= 0:
                await self.bot.redis.delete(redis_key)
                continue

            member  = guild.get_member(user_id)
            channel = guild.get_channel(int(data.get("channel_id", 0)))
            if not member or not channel:
                continue

            async def _task(member=member, channel=channel, remaining=remaining, key=redis_key, uid=user_id):
                try:
                    await asyncio.sleep(remaining)
                    if await self.is_reminder_enabled(member):
                        await self.send_reminder_message(member, channel)
                finally:
                    self.active_reminders.pop(uid, None)
                    await self.bot.redis.delete(key)

            self.active_reminders[user_id] = asyncio.create_task(_task())
            log.info("♻️ Restored clan reminder for %s (%ss left)", member.display_name, remaining)

    # ─────────────────────────────────────────────
    # Cleanup task
    # ─────────────────────────────────────────────

    @tasks.loop(minutes=REMINDER_CLEANUP_MINUTES)
    async def cleanup_task(self):
        if not getattr(self.bot, "redis", None):
            return
        now = int(time.time())
        for redis_key in await self.bot.redis.keys("reminder:clan:*"):
            data      = await self.bot.redis.hgetall(redis_key)
            expire_at = int(data.get("expire_at", 0)) if data else 0
            if expire_at and expire_at <= now:
                await self.bot.redis.delete(redis_key)

    @cleanup_task.before_loop
    async def before_cleanup(self):
        await self.bot.wait_until_ready()

    # ─────────────────────────────────────────────
    # Listener
    # ─────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if not after.guild or not after.embeds:
            return

        embed  = after.embeds[0]
        title  = (embed.title or "").lower()
        footer = after.embeds[0].footer.text if after.embeds[0].footer else ""

        if "casting for round" not in title or not footer:
            return

        guild  = after.guild
        member = guild.get_member_named(footer) or discord.utils.find(
            lambda m: m.display_name.lower() == footer.lower(), guild.members
        )

        if not member:
            log.warning("❌ ClanReminder: could not find member '%s'", footer)
            return

        await self.start_reminder(member, after.channel)


async def setup(bot: commands.Bot):
    cog = ClanReminder(bot)
    await bot.add_cog(cog)
    await cog.restore_reminders()
    log.info("⚙️ ClanReminder cog loaded")
