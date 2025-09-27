import asyncio
import time
import discord
from discord import app_commands
from discord.ext import commands

# Cooldowns configurables (en secondes)
COOLDOWN_SECONDS = {
    "summon": 30 * 60,       # 30 minutes
    "open-boxes": 60,        # 1 minute
    "open-pack": 60,         # 1 minute
}

def cd_key(gid: int, uid: int, action: str) -> str:
    return f"cooldown:{action}:{gid}:{uid}"

def now_ts() -> int:
    return int(time.time())

class Reminder(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def start_cooldown(self, interaction: discord.Interaction, action: str):
        """Démarre un cooldown et programme un rappel dans le canal."""
        if not self.bot.redis:
            await interaction.followup.send("❌ Redis not connected.", ephemeral=True)
            return

        gid = interaction.guild.id
        uid = interaction.user.id
        key = cd_key(gid, uid, action)
        duration = COOLDOWN_SECONDS[action]

        # Vérifier si déjà en cooldown
        last = await self.bot.redis.get(key)
        if last:
            remaining = int(last) + duration - now_ts()
            if remaining > 0:
                m, s = divmod(remaining, 60)
                await interaction.followup.send(
                    f"⏳ You already used **/{action}**. Ready again in {m}m {s}s.",
                    ephemeral=True
                )
                return

        # Stocker le timestamp
        await self.bot.redis.set(key, str(now_ts()), ex=duration + 60)

        # Confirmation immédiate
        await interaction.followup.send(
            f"✨ You used **/{action}**! I'll remind you in {duration//60} minutes.",
            ephemeral=True
        )

        # Planifier le rappel
        async def reminder():
            await asyncio.sleep(duration)
            marker = await self.bot.redis.get(key)
            if not marker:
                return
            try:
                await interaction.channel.send(
                    f"{interaction.user.mention} 🔔 your **/{action}** is ready !"
                )
            except Exception:
                pass

        self.bot.loop.create_task(reminder())

    # --- Commandes disponibles ---
    @app_commands.command(name="summon", description="Use summon and get a reminder when cooldown ends")
    async def summon(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.start_cooldown(interaction, "summon")

    @app_commands.command(name="open-boxes", description="Open boxes and get a reminder when cooldown ends")
    async def open_boxes(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.start_cooldown(interaction, "open-boxes")

    @app_commands.command(name="open-pack", description="Open a pack and get a reminder when cooldown ends")
    async def open_pack(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.start_cooldown(interaction, "open-pack")

async def setup(bot: commands.Bot):
    await bot.add_cog(Reminder(bot))
