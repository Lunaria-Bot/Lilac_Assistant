import os
import logging
import asyncio
import time
import discord
from discord.ext import commands, tasks

log = logging.getLogger("cog-reminder")

COOLDOWN_SECONDS = 1800  # 30 minutes
GUILD_ID = int(os.getenv("GUILD_ID", "0"))  # ✅ use env var

class Reminder(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active_reminders = {}
        self.cleanup_task.start()  # start background cleanup

    def cog_unload(self):
        self.cleanup_task.cancel()

    async def send_reminder_message(self, member: discord.Member, channel: discord.TextChannel):
        """Send a styled reminder message (slash-like)."""
        embed = discord.Embed(
            description=f"⏱️ {member.mention}, ton `/summon` est de nouveau disponible !",
            color=discord.Color.green()
        )
        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            log.warning("❌ Cannot send reminder in %s", channel.name)

    async def start_reminder(self, member: discord.Member, channel: discord.TextChannel):
        """Start a summon reminder and persist it in Redis with channel info."""
        user_id = member.id

        if user_id in self.active_reminders:
            return

        if getattr(self.bot, "redis", None):
            expire_at = int(time.time()) + COOLDOWN_SECONDS
            await self.bot.redis.hset(
                f"reminder:summon:{user_id}",
                mapping={"expire_at": expire_at, "channel_id": channel.id}
            )

        async def reminder_task():
            try:
                await asyncio.sleep(COOLDOWN_SECONDS)
                await self.send_reminder_message(member, channel)
            finally:
                self.active_reminders.pop(user_id, None)
                if getattr(self.bot, "redis", None):
                    await self.bot.redis.delete(f"reminder:summon:{user_id}")

        task = asyncio.create_task(reminder_task())
        self.active_reminders[user_id] = task
        log.info("▶️ Reminder started for %s in %s", member.display_name, channel.name)

    async def restore_reminders(self):
        """Reload reminders from Redis on startup."""
        if not getattr(self.bot, "redis", None):
            return

        keys = await self.bot.redis.keys("reminder:summon:*")
        now = int(time.time())

        for key in keys:
            user_id = int(key.split(":")[-1])
            data = await self.bot.redis.hgetall(key)
            if not data:
                continue

            expire_at = int(data.get("expire_at", 0))
            channel_id = int(data.get("channel_id", 0))
            remaining = expire_at - now
            if remaining <= 0:
                await self.bot.redis.delete(key)
                continue

            guild = self.bot.get_guild(GUILD_ID)
            if not guild:
                continue
            member = guild.get_member(user_id)
            if not member:
                continue
            channel = guild.get_channel(channel_id)
            if not channel:
                continue  # ✅ silently skip if channel missing

            async def reminder_task():
                try:
                    await asyncio.sleep(remaining)
                    await self.send_reminder_message(member, channel)
                finally:
                    self.active_reminders.pop(user_id, None)
                    await self.bot.redis.delete(key)

            task = asyncio.create_task(reminder_task())
            self.active_reminders[user_id] = task
            log.info("♻️ Restored reminder for %s in #%s (%ss left)", member.display_name, channel.name, remaining)

    # --- Background cleanup loop ---
    @tasks.loop(minutes=10)
    async def cleanup_task(self):
        """Periodically remove expired reminders from Redis."""
        if not getattr(self.bot, "redis", None):
            return

        keys = await self.bot.redis.keys("reminder:summon:*")
        now = int(time.time())
        removed = 0

        for key in keys:
            data = await self.bot.redis.hgetall(key)
            if not data:
                continue
            expire_at = int(data.get("expire_at", 0))
            if expire_at and expire_at <= now:
                await self.bot.redis.delete(key)
                removed += 1

        if removed:
            log.info("🧹 Cleanup removed %s expired reminders", removed)

    @cleanup_task.before_loop
    async def before_cleanup(self):
        await self.bot.wait_until_ready()

    # --- Listener: trigger only on summon claim (not auto summon) ---
    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if not after.guild or not after.embeds:
            return

        embed = after.embeds[0]
        title = (embed.title or "").lower()

        if "summon claimed" in title and "auto summon claimed" not in title:
            if not embed.description:
                return
            import re
            match = re.search(r"<@!?(\d+)>", embed.description)
            if not match:
                return

            user_id = int(match.group(1))
            member = after.guild.get_member(user_id)
            if not member:
                return

            await self.start_reminder(member, after.channel)


async def setup(bot: commands.Bot):
    cog = Reminder(bot)
    await bot.add_cog(cog)
    await cog.restore_reminders()
