# cogs/reminder.py

import asyncio
import time
import logging
import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger("cog-reminder")

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

def format_time(seconds: int) -> str:
    m, s = divmod(seconds, 60)
    return f"{m}m {s}s" if m else f"{s}s"

class Reminder(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def start_cooldown(self, interaction: discord.Interaction, action: str):
        """Démarre un cooldown et programme un rappel dans le canal."""
        if not getattr(self.bot, "redis", None):
            await interaction.followup.send("❌ Redis not connected.", ephemeral=True)
            log.error("Redis not connected: cannot start cooldown for %s", action)
            return

        gid = interaction.guild.id
        uid = interaction.user.id
        channel_id = interaction.channel.id
        key = cd_key(gid, uid, action)
        duration = COOLDOWN_SECONDS[action]

        # Vérifier si déjà en cooldown
        last = await self.bot.redis.get(key)
        if last:
            remaining = int(last) + duration - now_ts()
            if remaining > 0:
                await interaction.followup.send(
                    f"⏳ You already used **/{action}**. Ready again in {format_time(remaining)}.",
                    ephemeral=True
                )
                log.info("Cooldown active: user=%s action=%s remaining=%ss", uid, action, remaining)
                return

        # Stocker le timestamp, TTL un peu plus long pour tolérance
        await self.bot.redis.set(key, str(now_ts()), ex=duration + 120)

        # Confirmation immédiate
        await interaction.followup.send(
            f"✨ You used **/{action}**! I'll remind you in {format_time(duration)}.",
            ephemeral=True
        )
        log.info("Cooldown started: guild=%s user=%s channel=%s action=%s duration=%ss",
                 gid, uid, channel_id, action, duration)

        async def reminder_task(guild_id: int, target_channel_id: int, target_user_id: int, action_name: str, redis_key: str):
            try:
                await asyncio.sleep(duration)
                # Vérifier que le cooldown est toujours présent (pas reset)
                marker = await self.bot.redis.get(redis_key)
                if not marker:
                    log.info("Cooldown marker missing, skip reminder: user=%s action=%s", target_user_id, action_name)
                    return

                channel = self.bot.get_channel(target_channel_id)
                if channel is None:
                    # Essayer de récupérer via fetch_channel
                    try:
                        channel = await self.bot.fetch_channel(target_channel_id)
                    except Exception as e:
                        log.error("Cannot resolve channel %s for reminder: %s", target_channel_id, e)
                        return

                # Construire l’embed de rappel
                embed = discord.Embed(
                    title="🔔 Reminder",
                    description=f"<@{target_user_id}>, your **/{action_name}** is ready!",
                    color=discord.Color.green()
                )
                await channel.send(embed=embed)
                log.info("Reminder sent: guild=%s channel=%s user=%s action=%s",
                         guild_id, target_channel_id, target_user_id, action_name)
            except Exception as e:
                log.error("Failed reminder task for user=%s action=%s: %s", target_user_id, action_name, e)

        asyncio.create_task(reminder_task(gid, channel_id, uid, action, key))

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

    # Optionnel: voir ses cooldowns actuels
    @app_commands.command(name="cooldowns", description="Show your active cooldowns")
    async def cooldowns(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not getattr(self.bot, "redis", None):
            await interaction.followup.send("❌ Redis not connected.", ephemeral=True)
            return

        gid = interaction.guild.id
        uid = interaction.user.id
        lines = []
        for action, seconds in COOLDOWN_SECONDS.items():
            key = cd_key(gid, uid, action)
            last = await self.bot.redis.get(key)
            if last:
                remaining = int(last) + seconds - now_ts()
                if remaining > 0:
                    lines.append(f"- **/{action}**: {format_time(remaining)} remaining")

        if not lines:
            await interaction.followup.send("✅ You have no active cooldowns.", ephemeral=True)
        else:
            await interaction.followup.send("⏳ Active cooldowns:\n" + "\n".join(lines), ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Reminder(bot))
