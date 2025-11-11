import os
import re
import time
import logging
import discord
from discord.ext import commands, tasks

log = logging.getLogger("cog-message-forwarder")

GUILD_ID = int(os.getenv("GUILD_ID", "0"))
FORWARD_CHANNEL_ID = int(os.getenv("FORWARD_CHANNEL_ID", "0"))

RARITY_IDS = {
    "SSR": "1342202212948115510",
    "UR": "1342202203515125801",
    "SR": "1342202597389373530",
    "Common": "1342202221558763571",
    "Rare": "1342202219574857788",
}

RARITY_EMOJIS = {
    "SR": "<a:SuperRare:1342208034482425936>",
    "SSR": "<a:SuperSuperRare:1342208039918370857>",
    "UR": "<a:UltraRare:1342208044351623199>",
    "Common": "<a:Common:1342208021853634781>",
    "Rare": "<a:Rare:1342208028342091857>",
}

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
            log.debug("⏭ Message %s already forwarded, skipping", after.id)
            return
        if before.content == after.content and before.embeds == after.embeds:
            log.debug("⏭ Message %s unchanged, skipping", after.id)
            return

        embed = after.embeds[0]
        desc = (embed.description or "")
        title = (embed.title or "").lower()

        valid_titles = [
            "summon claimed",
            "autosummon claimed",
            "premium pack opened",
            "mazoku event opened"
        ]
        if not any(t in title for t in valid_titles):
            return

        v_match = re.search(r"\bv(10|[1-9])\b", desc, re.IGNORECASE)

        # Détection de la rareté via l'emoji ID
        rarity = None
        for key, emoji_id in RARITY_IDS.items():
            if emoji_id in desc:
                if key in {"SR", "Common", "Rare"} and not v_match:
                    continue
                rarity = key
                break

        if not rarity:
            return

        # Remplacement de :e: par l'emoji animé correspondant
        new_desc = desc.replace(":e:", RARITY_EMOJIS[rarity])

        new_embed = discord.Embed(
            title=embed.title,
            description=new_desc,
            color=embed.color or discord.Color.purple()
        )
        if embed.image:
            new_embed.set_image(url=embed.image.url)
        if embed.thumbnail:
            new_embed.set_thumbnail(url=embed.thumbnail.url)
        if embed.footer:
            new_embed.set_footer(text=embed.footer.text, icon_url=embed.footer.icon_url)

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

        await channel.send(content=after.content, embeds=[new_embed], files=files)
        log.info("🗂 Message forwarded with rarity emoji from %s", after.channel.name)

async def setup(bot: commands.Bot):
    await bot.add_cog(MessageForwarder(bot))
    log.info("⚙️ MessageForwarder cog loaded")
