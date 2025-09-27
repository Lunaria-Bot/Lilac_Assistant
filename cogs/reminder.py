import logging
import asyncio
import time
import discord
from discord.ext import commands

log = logging.getLogger("cog-reminder")

COOLDOWN_SECONDS = 1800  # 30 minutes

class Reminder(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active_reminders = {}

    async def start_reminder(self, member: discord.Member, channel: discord.TextChannel):
        """Start a summon reminder and persist it in Redis with channel info."""
        user_id = member.id

        if user_id in self.active_reminders:
            return

        if getattr(self.bot, "redis", None):
            expire_at = int(time.time()) + COOLDOWN_SECONDS
            # Store both expiry and channel_id
            await self.bot.redis.hset(
                f"reminder:summon:{user_id}",
                mapping={"expire_at": expire_at, "channel_id": channel.id}
            )

        async def reminder_task():
            try:
                await asyncio.sleep(COOLDOWN_SECONDS)
                try:
                    await channel.send(
                        f"⏰ {member.mention} your summon cooldown is over, you can summon again!"
                    )
                except discord.Forbidden:
                    log.warning("❌ Cannot send reminder in %s", channel.name)
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

            guild = self.bot.get_guild(self.bot.guild_id)  # set guild_id in main
            if not guild:
                continue
            member = guild.get_member(user_id)
            if not member:
                continue
            channel = guild.get_channel(channel_id)
            if not channel:
                continue

            async def reminder_task():
                try:
                    await asyncio.sleep(remaining)
                    await channel.send(
                        f"⏰ {member.mention} your summon cooldown is over, you can summon again!"
                    )
                finally:
                    self.active_reminders.pop(user_id, None)
                    await self.bot.redis.delete(key)

            task = asyncio.create_task(reminder_task())
            self.active_reminders[user_id] = task
            log.info("♻️ Restored reminder for %s in #%s (%ss left)", member.display_name, channel.name, remaining)

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
