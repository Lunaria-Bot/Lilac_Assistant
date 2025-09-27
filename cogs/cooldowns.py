import os
import re
import asyncio
import logging
import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger("cog-cooldowns")

# --- Env IDs ---
GUILD_IDS = [int(x) for x in os.getenv("GUILD_IDS", "").split(",") if x]
MAZOKU_BOT_ID = int(os.getenv("MAZOKU_BOT_ID", "0"))
HIGHTIER_ROLE_ID = int(os.getenv("HIGHTIER_ROLE_ID", "0"))

# --- Cooldowns in seconds ---
COOLDOWN_SECONDS = {
    "summon": 1800,
    "open-boxes": 60,
    "open-pack": 60
}

# --- Rarity emojis ---
RARITY_EMOTES = {
    "1342202597389373530": "SR",
    "1342202212948115510": "SSR",
    "1342202203515125801": "UR"
}
EMOJI_REGEX = re.compile(r"<a?:\w+:(\d+)>")

async def safe_send(channel: discord.TextChannel, *args, **kwargs):
    try:
        return await channel.send(*args, **kwargs)
    except Exception:
        pass

class Cooldowns(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # --- Slash command /high-tier ---
    @app_commands.command(name="high-tier", description="Get the special high-tier role")
    async def high_tier(self, interaction: discord.Interaction):
        guild = interaction.guild
        member = interaction.user
        if not guild:
            await interaction.response.send_message("❌ This command must be used in a server.", ephemeral=True)
            return

        special_role = guild.get_role(HIGHTIER_ROLE_ID)
        if not special_role:
            await interaction.response.send_message("⚠️ High-tier role not configured.", ephemeral=True)
            return

        await member.add_roles(special_role)
        await interaction.response.send_message(
            f"I just gave you the role {special_role.mention} 🎉",
            ephemeral=True
        )

    # --- Events ---
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not self.bot.redis:
            return
        if not message.guild or message.guild.id not in GUILD_IDS:
            return
        if message.author.id == self.bot.user.id:
            return
        if not (message.author.bot and message.author.id == MAZOKU_BOT_ID):
            return
        if not message.embeds:
            return

        embed = message.embeds[0]
        title = (embed.title or "").lower()

        # Auto Summon spawn
        if "auto summon" in title and "claimed" not in title:
            found_rarity = None
            text_to_scan = [embed.title or "", embed.description or ""]
            if embed.fields:
                for field in embed.fields:
                    text_to_scan.append(field.name or "")
                    text_to_scan.append(field.value or "")
            if embed.footer and embed.footer.text:
                text_to_scan.append(embed.footer.text)

            for text in text_to_scan:
                matches = EMOJI_REGEX.findall(text)
                for emote_id in matches:
                    if emote_id in RARITY_EMOTES:
                        found_rarity = RARITY_EMOTES[emote_id]
                        break
                if found_rarity:
                    break

            if found_rarity:
                special_role = message.guild.get_role(HIGHTIER_ROLE_ID)
                msg = f"A {found_rarity} has summoned, claim it !"
                embed_msg = discord.Embed(description=msg, color=discord.Color.gold())
                if special_role:
                    await safe_send(message.channel, content=f"{special_role.mention}", embed=embed_msg)
                else:
                    await safe_send(message.channel, embed=embed_msg)
                log.info("⚡ High-tier spawn detected: %s", found_rarity)

async def setup(bot: commands.Bot):
    await bot.add_cog(Cooldowns(bot))

