import os
import re
import time
import logging
import discord
from discord.ext import commands, tasks

log = logging.getLogger("cog-message-forwarder")

GUILD_ID = int(os.getenv("GUILD_ID", "0"))
FORWARD_CHANNEL_ID = int(os.getenv("FORWARD_CHANNEL_ID", "0"))

class MessageForwarder(commands.Cog):
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

        # --- Vérifie le titre ---
        valid_titles = [
            "summon claimed",
            "autosummon claimed",
            "premium pack opened",
            "mazoku event opened"
        ]
        if not any(t in title for t in valid_titles):
            return

        # --- Vérifie les emojis ---
        emoji_ids = {
            "SSR": "1342202212948115510",
            "UR": "1342202203515125801",
            "SR": "1342202597389373530",
            "Common": "1342202221558763571",
            "Rare": "1342202219574857788",
        }

        v_match = re.search(r"\bv(10|[1-9])\b", desc, re.IGNORECASE)

        should_forward = False
        if emoji_ids["SSR"] in desc or emoji_ids["UR"] in desc:
            should_forward = True
        elif emoji_ids["SR"] in desc and v_match:
            should_forward = True
        elif (emoji_ids["Common"] in desc or emoji_ids["Rare"] in desc) and v_match:
            should_forward = True

        if not should_forward:
            return

        # --- Forward le message tel quel ---
        self.forwarded[after.id] = time.time()
        channel = after.guild.get_channel(FORWARD_CHANNEL_ID)
        if not channel:
            return

        files = []
        for attachment in after.attachments:
            try:
                files.append(await attachment.to_file())
            except Exception:
                pass

        await channel.send(content=after.content, embeds=after.embeds, files=files)
        log.info("📤 Message forwarded from #%s", after.channel.name)

# --- Extension setup ---
async def setup(bot: commands.Bot):
    await bot.add_cog(MessageForwarder(bot))
    log.info("⚙️ MessageForwarder cog loaded")
