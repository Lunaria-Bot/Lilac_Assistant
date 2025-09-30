import os
import logging
import asyncio
import time
import discord
from discord.ext import commands, tasks

log = logging.getLogger("cog-reminder")

COOLDOWN_SECONDS = int(os.getenv("COOLDOWN_SECONDS", "1800"))  # default 30 minutes
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
REMINDER_CLEANUP_MINUTES = int(os.getenv("REMINDER_CLEANUP_MINUTES", "10"))
SUMMON_COMMAND_ID = os.getenv("SUMMON_COMMAND_ID")  # optional: use </summon:ID> mention if provided


class Reminder(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active_reminders = {}
        self.cleanup_task.start()

    def cog_unload(self):
        self.cleanup_task.cancel()

    def get_summon_text(self) -> str:
        if SUMMON_COMMAND_ID and SUMMON_COMMAND_ID.isdigit():
            return f"</summon:{SUMMON_COMMAND_ID}>"
        return "/summon"

    async def send_reminder_message(self, member: discord.Member, channel: discord.TextChannel):
        summon_text = self.get_summon_text()
        content = f"⏱️ {member.mention}, your {summon_text} is ready again!"
        try:
            await channel.send(
                content,
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False)
            )
        except discord.Forbidden:
            log.warning("❌ Cannot send reminder in %s", channel.name)

    # --- Helper: check if reminder is enabled for a user ---
    async def is_reminder_enabled(self, member: discord.Member) -> bool:
        if not getattr(self.bot, "redis", None):
            return True  # ✅ par défaut activé
        key = f"reminder:settings:{member.guild.id}:{member.id}:summon"
        val = await self.bot.redis.get(key)
        if val is None:
            return True  # ✅ par défaut activé
        return val == "1"

    async def start_reminder(self, member: discord.Member, channel: discord.TextChannel):
        """Start a summon reminder only if enabled for the user."""
        if not await self.is_reminder_enabled(member):
            return

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
                if await self.is_reminder_enabled(member):
                    await self.send_reminder_message(member, channel)
            finally:
                self.active_reminders.pop(user_id, None)
                if getattr(self.bot, "redis", None):
                    await self.bot.redis.delete(f"reminder:summon:{user_id}")

        task = asyncio.create_task(reminder_task())
        self.active_reminders[user_id] = task

    async def restore_reminders(self):
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
                continue

            async def reminder_task():
                try:
                    await asyncio.sleep(remaining)
                    if await self.is_reminder_enabled(member):
                        await self.send_reminder_message(member, channel)
                finally:
                    self.active_reminders.pop(user_id, None)
                    await self.bot.redis.delete(key)

            task = asyncio.create_task(reminder_task())
            self.active_reminders[user_id] = task

    @tasks.loop(minutes=REMINDER_CLEANUP_MINUTES)
    async def cleanup_task(self):
        if not getattr(self.bot, "redis", None):
            return

        keys = await self.bot.redis.keys("reminder:summon:*")
        now = int(time.time())

        for key in keys:
            data = await self.bot.redis.hgetall(key)
            if not data:
                continue
            expire_at = int(data.get("expire_at", 0))
            if expire_at and expire_at <= now:
                await self.bot.redis.delete(key)

    @cleanup_task.before_loop
    async def before_cleanup(self):
        await self.bot.wait_until_ready()

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
    log.info("⚙️ Reminder cog loaded (logic only, no slash command)")
