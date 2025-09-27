import asyncio
import time
import logging
import os
import re
import discord
from discord.ext import commands

log = logging.getLogger("cog-reminder")

# Cooldowns configurables (facile à étendre)
COOLDOWN_SECONDS = {
    "summon": 30 * 60,  # 30 minutes
    # "open-boxes": 60,
    # "open-pack": 60,
}

def cd_key(gid: int, uid: int, action: str) -> str:
    return f"cooldown:{action}:{gid}:{uid}"

def now_ts() -> int:
    return int(time.time())

class Reminder(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.guild_id = int(os.getenv("GUILD_ID", "0"))
        self.mazoku_id = int(os.getenv("MAZOKU_BOT_ID", "0"))

    async def start_reminder(self, action: str, user_id: int, channel: discord.TextChannel):
        """Démarre un cooldown + planifie un rappel pour une action donnée."""
        if action not in COOLDOWN_SECONDS:
            return  # action non supportée (future extension facile)

        if not getattr(self.bot, "redis", None):
            log.error("Redis not connected: cannot start reminder")
            return

        duration = COOLDOWN_SECONDS[action]
        key = cd_key(channel.guild.id, user_id, action)

        # Stocker le timestamp
        await self.bot.redis.set(key, str(now_ts()), ex=duration + 60)
        log.info("⏳ Reminder started: user=%s action=%s duration=%ss", user_id, action, duration)

        async def reminder_task():
            await asyncio.sleep(duration)
            marker = await self.bot.redis.get(key)
            if marker:
                try:
                    embed = discord.Embed(
                        title="🔔 Reminder",
                        description=f"<@{user_id}>, your **/{action}** is ready again!",
                        color=discord.Color.green()
                    )
                    await channel.send(embed=embed)
                    log.info("🔔 Reminder sent: user=%s action=%s", user_id, action)
                except Exception as e:
                    log.error("Failed to send reminder: %s", e)

        asyncio.create_task(reminder_task())

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        # Vérifier que c’est bien Mazoku dans le bon serveur
        if after.author.id != self.mazoku_id:
            return
        if not after.guild or after.guild.id != self.guild_id:
            return
        if not after.embeds:
            return

        embed = after.embeds[0]
        title = (embed.title or "").lower()

        # Détection Summon Claimed (extensible à d’autres actions plus tard)
        if "summon claimed" in title:
            match = re.search(r"<@!?(\d+)>", embed.description or "")
            if not match:
                return
            user_id = int(match.group(1))
            await self.start_reminder("summon", user_id, after.channel)

async def setup(bot: commands.Bot):
    await bot.add_cog(Reminder(bot))
