import logging
import asyncio
import time
import re
import discord
from discord.ext import commands, tasks

from config import GUILD_ID, COOLDOWN_SECONDS, REMINDER_CLEANUP_MINUTES

log = logging.getLogger("cog-reminder")

LNY_COOLDOWN = 1800  # fixed 30 min for Lunar New Year


class Reminder(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active_reminders: dict[tuple[str, int], asyncio.Task] = {}
        self.cleanup_task.start()

    def cog_unload(self):
        self.cleanup_task.cancel()

    # ─────────────────────────────────────────────
    # Send helpers
    # ─────────────────────────────────────────────

    async def _send(self, channel: discord.TextChannel, content: str, label: str):
        try:
            await channel.send(
                content,
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            )
            log.info("⏰ %s reminder sent in #%s", label, channel.name)
        except discord.Forbidden:
            log.warning("❌ Cannot send %s reminder in #%s", label, channel.name)

    async def send_summon_reminder(self, member: discord.Member, channel: discord.TextChannel):
        await self._send(
            channel,
            f"⏱️ Hey {member.mention}! Your </summon:1301277778385174601> "
            f"is ready <:Kanna_Cool:1298168957420834816>",
            "summon",
        )

    async def send_lny_reminder(self, member: discord.Member, channel: discord.TextChannel):
        await self._send(
            channel,
            f"⏱️ {member.mention}, your Lunar New Year gift is ready! 🧧",
            "LNY",
        )

    # ─────────────────────────────────────────────
    # Settings check
    # ─────────────────────────────────────────────

    async def is_summon_enabled(self, member: discord.Member) -> bool:
        if not getattr(self.bot, "redis", None):
            return True
        val = await self.bot.redis.get(
            f"reminder:settings:{member.guild.id}:{member.id}:summon"
        )
        return val != "0"

    # ─────────────────────────────────────────────
    # Start reminders
    # ─────────────────────────────────────────────

    async def _start_reminder(
        self,
        kind: str,
        member: discord.Member,
        channel: discord.TextChannel,
        delay: int,
        send_fn,
    ):
        rkey     = (kind, member.id)
        redis_key = f"reminder:{kind}:{member.id}"

        if rkey in self.active_reminders:
            return

        if getattr(self.bot, "redis", None):
            await self.bot.redis.hset(
                redis_key,
                mapping={"expire_at": int(time.time()) + delay, "channel_id": channel.id},
            )

        async def _task():
            try:
                await asyncio.sleep(delay)
                if kind == "summon" and not await self.is_summon_enabled(member):
                    return
                await send_fn(member, channel)
            finally:
                self.active_reminders.pop(rkey, None)
                if getattr(self.bot, "redis", None):
                    await self.bot.redis.delete(redis_key)

        self.active_reminders[rkey] = asyncio.create_task(_task())
        log.info("▶️ %s reminder started for %s (%ss)", kind, member.display_name, delay)

    async def start_summon_reminder(self, member: discord.Member, channel: discord.TextChannel):
        if not await self.is_summon_enabled(member):
            return
        await self._start_reminder("summon", member, channel, COOLDOWN_SECONDS, self.send_summon_reminder)

    async def start_lny_reminder(self, member: discord.Member, channel: discord.TextChannel):
        await self._start_reminder("lny", member, channel, LNY_COOLDOWN, self.send_lny_reminder)

    # ─────────────────────────────────────────────
    # Restore after restart
    # ─────────────────────────────────────────────

    async def restore_reminders(self):
        if not getattr(self.bot, "redis", None):
            return
        now = int(time.time())
        guild = self.bot.get_guild(GUILD_ID)
        if not guild:
            return

        for kind, send_fn in (("summon", self.send_summon_reminder), ("lny", self.send_lny_reminder)):
            keys = await self.bot.redis.keys(f"reminder:{kind}:*")
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

                await self._start_reminder(kind, member, channel, remaining, send_fn)
                log.info("♻️ Restored %s reminder for %s (%ss left)", kind, member.display_name, remaining)

    # ─────────────────────────────────────────────
    # Cleanup expired Redis keys
    # ─────────────────────────────────────────────

    @tasks.loop(minutes=REMINDER_CLEANUP_MINUTES)
    async def cleanup_task(self):
        if not getattr(self.bot, "redis", None):
            return
        now = int(time.time())
        for kind in ("summon", "lny"):
            for redis_key in await self.bot.redis.keys(f"reminder:{kind}:*"):
                data = await self.bot.redis.hgetall(redis_key)
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
        desc   = embed.description or ""
        footer = embed.footer.text.lower() if embed.footer and embed.footer.text else ""

        # Summon detection
        if "summon claimed" in title and "auto summon claimed" not in title:
            match = re.search(r"<@!?(\d+)>", desc) or (
                re.search(r"<@!?(\d+)>", footer) if "claimed by" in footer else None
            )
            if match:
                member = after.guild.get_member(int(match.group(1)))
                if member:
                    await self.start_summon_reminder(member, after.channel)

        # Lunar New Year detection
        lny_match = re.search(
            r"<@!?(\d+)>\s+sent a\s+<:[^:]+:\d+>\s+red packet to\s+<@!?(\d+)>", desc
        )
        if lny_match:
            sender = after.guild.get_member(int(lny_match.group(1)))
            if sender:
                await self.start_lny_reminder(sender, after.channel)
                log.info("🎁 LNY red packet detected: reminder for %s", sender.display_name)


async def setup(bot: commands.Bot):
    cog = Reminder(bot)
    await bot.add_cog(cog)
    await cog.restore_reminders()
    log.info("⚙️ Reminder cog loaded (Summon + LNY)")
