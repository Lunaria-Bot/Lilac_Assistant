import re
import logging
import discord
from discord.ext import commands

from config import GUILD_ID, MAZOKU_BOT_ID, RARITY_EMOJIS

log = logging.getLogger("cog-cooldowns")

EMOJI_REGEX = re.compile(r"<a?:\w+:(\d+)>")
# GUILD_IDS supports multi-guild via env; fall back to single GUILD_ID
import os
GUILD_IDS = {int(x) for x in os.getenv("GUILD_IDS", "").split(",") if x} or {GUILD_ID}


class Cooldowns(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not getattr(self.bot, "redis", None):
            return
        if not message.guild or message.guild.id not in GUILD_IDS:
            return
        if message.author.id != MAZOKU_BOT_ID:
            return
        if not message.embeds:
            return

        embed = message.embeds[0]
        title = (embed.title or "").lower()

        if "auto summon" not in title or "claimed" in title:
            return

        # Scan embed text for rarity emoji
        texts = [embed.title or "", embed.description or ""]
        texts += [f.name or "" for f in embed.fields] + [f.value or "" for f in embed.fields]
        if embed.footer and embed.footer.text:
            texts.append(embed.footer.text)

        for text in texts:
            for emote_id in EMOJI_REGEX.findall(text):
                if emote_id in RARITY_EMOJIS:
                    return  # rarity found — other cogs handle the ping


async def setup(bot: commands.Bot):
    await bot.add_cog(Cooldowns(bot))
    log.info("⚙️ Cooldowns cog loaded")
