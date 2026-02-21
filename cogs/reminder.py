import os
import logging
import asyncio
import time
import re
import discord
from discord.ext import commands, tasks

log = logging.getLogger("cog-reminder")

# Summon cooldown (from env or default)
COOLDOWN_SECONDS = int(os.getenv("COOLDOWN_SECONDS", "1800"))  # 30 minutes default

# Lunar New Year cooldown (fixed 30 min)
LNY_COOLDOWN = 1800

GUILD_ID = int(os.getenv("GUILD_ID", "0"))
REMINDER_CLEANUP_MINUTES = int(os.getenv("REMINDER_CLEANUP_MINUTES", "10"))

# Optional: restrict LNY trigger to a specific bot ID (the one sending the red packet message)
LNY_BOT_ID = int(os.getenv("LNY_BOT_ID", "0"))  # put the bot ID here or leave 0 to allow all


class Reminder(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Use (type, user_id) as key to avoid collisions between summon and lny
        self.active_reminders: dict[tuple[str, int], asyncio.Task] = {}
        self.cleanup_task.start()

    def cog_unload(self):
        self.cleanup_task.cancel()

    # ---------------------------------------------------------
    # Reminder message (Summon)
    # ---------------------------------------------------------
    async def send_summon_reminder(self, member: discord.Member, channel: discord.TextChannel):
        content = (
            f"⏱️Hey ! {member.mention}, your </summon:1301277778385174601> "
            f"is available <:Kanna_Cool:1298168957420834816>"
        )
        try:
            await channel.send(
                content,
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False)
            )
            log.info("⏰ Summon reminder sent to %s in #%s", member.display_name, channel.name)
        except discord.Forbidden:
            log.warning("❌ Cannot send summon reminder in %s", channel.name)

    # ---------------------------------------------------------
    # Reminder message (Lunar New Year)
    # ---------------------------------------------------------
    async def send_lny_reminder(self, member: discord.Member, channel: discord.TextChannel):
        content = f"⏱️ {member.mention}, Your Lunar New Year gift is ready !"
        try:
            await channel.send(
                content,
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False)
            )
            log.info("🎉 LNY reminder sent to %s in #%s", member.display_name, channel.name)
        except discord.Forbidden:
            log.warning("❌ Cannot send LNY reminder in %s", channel.name)

    # ---------------------------------------------------------
    # Check if summon reminder is enabled
    # ---------------------------------------------------------
    async def is_summon_enabled(self, member: discord.Member) -> bool:
        if not getattr(self.bot, "redis", None):
            return True

        key = f"reminder:settings:{member.guild.id}:{member.id}:summon"
        val = await self.bot.redis.get(key)
        if val is None:
            return True
        return val == "1"

    # ---------------------------------------------------------
    # Start Summon reminder
    # ---------------------------------------------------------
    async def start_summon_reminder(self, member: discord.Member, channel: discord.TextChannel):
        if not await self.is_summon_enabled(member):
            return

        user_id = member.id
        rkey = ("summon", user_id)
        redis_key = f"reminder:summon:{user_id}"

        if rkey in self.active_reminders:
            return

        if getattr(self.bot, "redis", None):
            expire_at = int(time.time()) + COOLDOWN_SECONDS
            await self.bot.redis.hset(
                redis_key,
                mapping={"expire_at": expire_at, "channel_id": channel.id}
            )

        async def task_logic():
            try:
                await asyncio.sleep(COOLDOWN_SECONDS)
                if await self.is_summon_enabled(member):
                    await self.send_summon_reminder(member, channel)
            finally:
                self.active_reminders.pop(rkey, None)
                if getattr(self.bot, "redis", None):
                    await self.bot.redis.delete(redis_key)

        self.active_reminders[rkey] = asyncio.create_task(task_logic())
        log.info("▶️ Summon reminder started for %s", member.display_name)

    # ---------------------------------------------------------
    # Start Lunar New Year reminder
    # ---------------------------------------------------------
    async def start_lny_reminder(self, member: discord.Member, channel: discord.TextChannel):
        user_id = member.id
        rkey = ("lny", user_id)
        redis_key = f"reminder:lny:{user_id}"

        if rkey in self.active_reminders:
            return

        if getattr(self.bot, "redis", None):
            expire_at = int(time.time()) + LNY_COOLDOWN
            await self.bot.redis.hset(
                redis_key,
                mapping={"expire_at": expire_at, "channel_id": channel.id}
            )

        async def task_logic():
            try:
                await asyncio.sleep(LNY_COOLDOWN)
                await self.send_lny_reminder(member, channel)
            finally:
                self.active_reminders.pop(rkey, None)
                if getattr(self.bot, "redis", None):
                    await self.bot.redis.delete(redis_key)

        self.active_reminders[rkey] = asyncio.create_task(task_logic())
        log.info("🎁 LNY reminder started for %s", member.display_name)

    # ---------------------------------------------------------
    # Restore reminders after restart
    # ---------------------------------------------------------
    async def restore_reminders(self):
        if not getattr(self.bot, "redis", None):
            return

        now = int(time.time())

        # Restore summon reminders
        summon_keys = await self.bot.redis.keys("reminder:summon:*")
        for redis_key in summon_keys:
            try:
                user_id = int(redis_key.split(":")[-1])
            except ValueError:
                continue

            data = await self.bot.redis.hgetall(redis_key)
            if not data:
                continue

            expire_at = int(data.get("expire_at", 0))
            channel_id = int(data.get("channel_id", 0))
            remaining = expire_at - now

            if remaining <= 0:
                await self.bot.redis.delete(redis_key)
                continue

            guild = self.bot.get_guild(GUILD_ID)
            if not guild:
                continue

            member = guild.get_member(user_id)
            channel = guild.get_channel(channel_id)
            if not member or not channel:
                continue

            rkey = ("summon", user_id)

            async def summon_task(member=member, channel=channel, remaining=remaining, redis_key=redis_key, rkey=rkey):
                try:
                    await asyncio.sleep(remaining)
                    if await self.is_summon_enabled(member):
                        await self.send_summon_reminder(member, channel)
                finally:
                    self.active_reminders.pop(rkey, None)
                    await self.bot.redis.delete(redis_key)

            self.active_reminders[rkey] = asyncio.create_task(summon_task())
            log.info("♻️ Restored summon reminder for %s (%ss left)", member.display_name, remaining)

        # Restore LNY reminders
        lny_keys = await self.bot.redis.keys("reminder:lny:*")
        for redis_key in lny_keys:
            try:
                user_id = int(redis_key.split(":")[-1])
            except ValueError:
                continue

            data = await self.bot.redis.hgetall(redis_key)
            if not data:
                continue

            expire_at = int(data.get("expire_at", 0))
            channel_id = int(data.get("channel_id", 0))
            remaining = expire_at - now

            if remaining <= 0:
                await self.bot.redis.delete(redis_key)
                continue

            guild = self.bot.get_guild(GUILD_ID)
            if not guild:
                continue

            member = guild.get_member(user_id)
            channel = guild.get_channel(channel_id)
            if not member or not channel:
                continue

            rkey = ("lny", user_id)

            async def lny_task(member=member, channel=channel, remaining=remaining, redis_key=redis_key, rkey=rkey):
                try:
                    await asyncio.sleep(remaining)
                    await self.send_lny_reminder(member, channel)
                finally:
                    self.active_reminders.pop(rkey, None)
                    await self.bot.redis.delete(redis_key)

            self.active_reminders[rkey] = asyncio.create_task(lny_task())
            log.info("♻️ Restored LNY reminder for %s (%ss left)", member.display_name, remaining)

    # ---------------------------------------------------------
    # Cleanup expired Redis keys
    # ---------------------------------------------------------
    @tasks.loop(minutes=REMINDER_CLEANUP_MINUTES)
    async def cleanup_task(self):
        if not getattr(self.bot, "redis", None):
            return

        now = int(time.time())

        # Summon keys
        summon_keys = await self.bot.redis.keys("reminder:summon:*")
        for redis_key in summon_keys:
            data = await self.bot.redis.hgetall(redis_key)
            if not data:
                continue
            expire_at = int(data.get("expire_at", 0))
            if expire_at and expire_at <= now:
                await self.bot.redis.delete(redis_key)

        # LNY keys
        lny_keys = await self.bot.redis.keys("reminder:lny:*")
        for redis_key in lny_keys:
            data = await self.bot.redis.hgetall(redis_key)
            if not data:
                continue
            expire_at = int(data.get("expire_at", 0))
            if expire_at and expire_at <= now:
                await self.bot.redis.delete(redis_key)

    @cleanup_task.before_loop
    async def before_cleanup(self):
        await self.bot.wait_until_ready()

    # ---------------------------------------------------------
    # Summon detection (unchanged)
    # ---------------------------------------------------------
    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if not after.guild or not after.embeds:
            return

        embed = after.embeds[0]
        title = (embed.title or "").lower()
        desc = embed.description or ""
        footer = embed.footer.text.lower() if embed.footer and embed.footer.text else ""

        if "summon claimed" in title and "auto summon claimed" not in title:
            match = re.search(r"<@!?(\d+)>", desc)
            if not match and "claimed by" in footer:
                match = re.search(r"<@!?(\d+)>", footer)

            if not match:
                return

            user_id = int(match.group(1))
            member = after.guild.get_member(user_id)
            if not member:
                return

            await self.start_summon_reminder(member, after.channel)

    # ---------------------------------------------------------
    # Lunar New Year red packet detection
    # ---------------------------------------------------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # We *need* bot messages here, since the red packet message is usually sent by a bot.
        if message.author.bot:
            if LNY_BOT_ID and message.author.id != LNY_BOT_ID:
                # If LNY_BOT_ID is set, only allow that bot
                return

        pattern = r"<@!?(\d+)>\s+sent a\s+<:[^:]+:\d+>\s+red packet to\s+<@!?(\d+)>"
        match = re.search(pattern, message.content)
        if not match:
            return

        sender_id = int(match.group(1))

        guild = message.guild
        if not guild:
            return

        sender = guild.get_member(sender_id)
        if not sender:
            return

        await self.start_lny_reminder(sender, message.channel)
        log.info("🎁 LNY red packet detected: reminder started for sender %s", sender.display_name)


# ---------------------------------------------------------
# Setup
# ---------------------------------------------------------
async def setup(bot: commands.Bot):
    cog = Reminder(bot)
    await bot.add_cog(cog)
    await cog.restore_reminders()
    log.info("⚙️ Reminder cog loaded (Summon + LNY)")
