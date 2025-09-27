import os
import re
import logging
import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger("cog-leaderboard")

# --- Env IDs ---
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
MAZOKU_BOT_ID = int(os.getenv("MAZOKU_BOT_ID", "0"))

class Leaderboard(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.paused = {
            "all": False,
            "monthly": False,
            "autosummon": False,
            "summon": False,
        }
        log.info("⚙️ Leaderboard cog loaded with GUILD_ID=%s, MAZOKU_BOT_ID=%s", GUILD_ID, MAZOKU_BOT_ID)

    # --- Debug: log uniquement Mazoku ---
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        log.debug("DEBUG: on_message triggered from %s (%s)", message.author, message.author.id)

        if message.author.id != MAZOKU_BOT_ID:
            return
        if not message.guild or message.guild.id != GUILD_ID:
            return

        log.info("📩 Mazoku message (ID=%s): %s", message.id, message.content)
        if message.embeds:
            for i, e in enumerate(message.embeds):
                log.info("Embed %s:", i)
                log.info("  Title: %s", e.title)
                log.info("  Desc: %s", e.description)
                log.info("  Footer: %s", e.footer.text if e.footer else "")

    # --- Détection des claims sur édition (Mazoku uniquement) ---
    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        log.debug("DEBUG: on_message_edit triggered from %s (%s)", after.author, after.author.id)

        if after.author.id != MAZOKU_BOT_ID:
            return
        if not after.guild or after.guild.id != GUILD_ID:
            return
        if not after.embeds:
            return

        embed = after.embeds[0]
        title = (embed.title or "").lower()

        if "card claimed" in title or "auto summon claimed" in title:
            log.info("✏️ Claim detected in edited message %s", after.id)

            match = re.search(r"<@!?(\d+)>", embed.description or "")
            if not match:
                log.warning("⚠️ Aucun joueur trouvé dans l’embed.")
                return

            user_id = int(match.group(1))
            member = after.guild.get_member(user_id)
            if not member:
                log.warning("⚠️ Impossible de trouver le membre %s dans le serveur.", user_id)
                return

            claim_key = f"claim:{after.id}:{user_id}"
            already = await self.bot.redis.get(claim_key)
            if already:
                log.debug("⏸️ Claim déjà compté pour %s", user_id)
                return
            await self.bot.redis.set(claim_key, "1", ex=86400)

            log.info("➡️ Adding points for user %s", user_id)

            if not self.paused["monthly"]:
                await self.bot.redis.hincrby("activity:monthly", str(user_id), 1)
                await self.bot.redis.incr("activity:monthly:total")

            if "auto summon claimed" in title:
                if not self.paused["autosummon"]:
                    await self.bot.redis.hincrby("activity:autosummon", str(user_id), 1)
            else:
                if not self.paused["summon"]:
                    await self.bot.redis.hincrby("activity:summon", str(user_id), 1)

            if not self.paused["all"]:
                await self.bot.redis.hincrby("leaderboard", str(user_id), 1)

            log.info("🏅 %s gained +1 point from %s", member.display_name, embed.title)


# Obligatoire pour charger l’extension
async def setup(bot: commands.Bot):
    await bot.add_cog(Leaderboard(bot))
