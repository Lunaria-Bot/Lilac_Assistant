import logging
import discord
from discord.ext import commands

from config import GUILD_ID, MAZOKU_BOT_ID

log = logging.getLogger("cog-log")


class MazokuLog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        log.info("⚙️ MazokuLog loaded (GUILD_ID=%s, MAZOKU_BOT_ID=%s)", GUILD_ID, MAZOKU_BOT_ID)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.id != MAZOKU_BOT_ID:
            return
        if not message.guild or message.guild.id != GUILD_ID:
            return
        log.info("📩 Mazoku msg (ID=%s): %s", message.id, message.content)
        for i, e in enumerate(message.embeds):
            log.info("  Embed %s | title=%s | desc=%s | footer=%s",
                     i, e.title, e.description, e.footer.text if e.footer else "")

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if after.author.id != MAZOKU_BOT_ID:
            return
        if not after.guild or after.guild.id != GUILD_ID or not after.embeds:
            return
        e = after.embeds[0]
        log.info("✏️ Mazoku edit (ID=%s) | title=%s | desc=%s | footer=%s",
                 after.id, e.title, e.description, e.footer.text if e.footer else "")


async def setup(bot: commands.Bot):
    await bot.add_cog(MazokuLog(bot))
    log.info("⚙️ MazokuLog cog loaded")
