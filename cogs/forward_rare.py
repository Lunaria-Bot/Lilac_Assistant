import os
import re
import time
import logging
import discord
from discord.ext import commands, tasks

log = logging.getLogger("cog-forward-rare")

GUILD_ID = int(os.getenv("GUILD_ID", "0"))
FORWARD_CHANNEL_ID = int(os.getenv("FORWARD_CHANNEL_ID", "0"))

RARITY_IDS = {
    "SSR": "1342202212948115510",
    "UR": "1342202203515125801",
    "SR": "1342202597389373530",
    "Rare": "1342202219574857788",
    "Common": "1342202221558763571",
}

class ForwardRare(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.forwarded = {}
        self.cleanup.start()

    def cog_unload(self):
        self.cleanup.cancel()

    @tasks.loop(minutes=30)
    async def cleanup(self):
        now = time.time()
        self.forwarded = {
            mid: ts for mid, ts in self.forwarded.items()
            if now - ts < 6 * 3600
        }

    @cleanup.before_loop
    async def before_cleanup(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if not after.guild or not after.embeds:
            return
        if after.guild.id != GUILD_ID:
            return
        if after.id in self.forwarded:
            return

        embed = after.embeds[0]
        desc = (embed.description or "")
        title = (embed.title or "").lower()

        if "auto summon" not in title:
            return

        forward = False

        # Match v1 à v10
        v_match = re.search(r"\bv(10|[1-9])\b", desc, re.IGNORECASE)

        if RARITY_IDS["SSR"] in desc or RARITY_IDS["UR"] in desc:
            forward = True
        elif RARITY_IDS["SR"] in desc and v_match:
            forward = True
        elif (RARITY_IDS["Common"] in desc or RARITY_IDS["Rare"] in desc) and v_match:
            forward = True

        if forward:
            self.forwarded[after.id] = time.time()
            channel = after.guild.get_channel(FORWARD_CHANNEL_ID)
            if channel:
                await channel.send(f"🔔 **High value spawn detected!**\n[Jump to message]({after.jump_url})")

async def setup(bot: commands.Bot):
    await bot.add_cog(ForwardRare(bot))
    log.info("⚙️ ForwardRare cog loaded")
