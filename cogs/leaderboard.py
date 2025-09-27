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
MAZOKU_CHANNEL_ID = int(os.getenv("MAZOKU_CHANNEL_ID", "0"))

class Leaderboard(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.paused = {
            "all": False,
            "monthly": False,
            "autosummon": False,
            "summon": False,
        }

    # --- Commande principale ---
    @app_commands.command(name="leaderboard", description="View the leaderboard")
    async def leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if not self.bot.redis:
            await interaction.followup.send("❌ Redis not connected.", ephemeral=True)
            return

        data = await self.bot.redis.hgetall("leaderboard")
        if not data:
            await interaction.followup.send("⚠️ Leaderboard is empty.", ephemeral=True)
            return

        # Trier par score
        sorted_data = sorted(data.items(), key=lambda x: int(x[1]), reverse=True)
        lines = []
        for i, (uid, score) in enumerate(sorted_data[:10], start=1):
            member = interaction.guild.get_member(int(uid))
            name = member.display_name if member else f"User {uid}"
            lines.append(f"**{i}.** {name} — {score} pts")

        embed = discord.Embed(title="🏆 Leaderboard", description="\n".join(lines), color=discord.Color.gold())
        await interaction.followup.send(embed=embed, ephemeral=True)

    # --- Admin commands ---
    @app_commands.command(name="leaderboard-pause", description="Pause a leaderboard category (Admin only)")
    @app_commands.describe(category="Which category to pause (all, monthly, autosummon, summon)")
    async def leaderboard_pause(self, interaction: discord.Interaction, category: str):
        await interaction.response.defer(ephemeral=True)

        if not interaction.user.guild_permissions.administrator:
            await interaction.followup.send("❌ Admin only.", ephemeral=True)
            return
        if category not in self.paused:
            await interaction.followup.send("⚠️ Unknown category.", ephemeral=True)
            return
        self.paused[category] = True
        await interaction.followup.send(f"⏸️ Leaderboard category **{category}** paused.", ephemeral=True)

    @app_commands.command(name="leaderboard-resume", description="Resume a leaderboard category (Admin only)")
    @app_commands.describe(category="Which category to resume (all, monthly, autosummon, summon)")
    async def leaderboard_resume(self, interaction: discord.Interaction, category: str):
        await interaction.response.defer(ephemeral=True)

        if not interaction.user.guild_permissions.administrator:
            await interaction.followup.send("❌ Admin only.", ephemeral=True)
            return
        if category not in self.paused:
            await interaction.followup.send("⚠️ Unknown category.", ephemeral=True)
            return
        self.paused[category] = False
        await interaction.followup.send(f"▶️ Leaderboard category **{category}** resumed.", ephemeral=True)

    @app_commands.command(name="leaderboard-reset", description="Reset a leaderboard category (Admin only)")
    @app_commands.describe(category="Which category to reset (all, monthly, autosummon, summon)")
    async def leaderboard_reset(self, interaction: discord.Interaction, category: str):
        await interaction.response.defer(ephemeral=True)

        if not interaction.user.guild_permissions.administrator:
            await interaction.followup.send("❌ Admin only.", ephemeral=True)
            return
        if not self.bot.redis:
            await interaction.followup.send("❌ Redis not connected.", ephemeral=True)
            return

        if category == "all":
            await self.bot.redis.delete("leaderboard")
        elif category == "monthly":
            await self.bot.redis.delete("activity:monthly")
            await self.bot.redis.delete("activity:monthly:total")
        elif category == "autosummon":
            await self.bot.redis.delete("activity:autosummon")
        elif category == "summon":
            await self.bot.redis.delete("activity:summon")
        else:
            await interaction.followup.send("⚠️ Unknown category.", ephemeral=True)
            return

        await interaction.followup.send(f"🔄 Leaderboard category **{category}** reset!", ephemeral=True)

    @app_commands.command(name="leaderboard-debug", description="Debug: show raw points of a user (Admin only)")
    @app_commands.describe(member="The member to check")
    async def leaderboard_debug(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer(ephemeral=True)

        if not interaction.user.guild_permissions.administrator:
            await interaction.followup.send("❌ Admin only.", ephemeral=True)
            return
        if not self.bot.redis:
            await interaction.followup.send("❌ Redis not connected.", ephemeral=True)
            return

        uid = str(member.id)

        all_time = await self.bot.redis.hget("leaderboard", uid) or 0
        monthly = await self.bot.redis.hget("activity:monthly", uid) or 0
        autosummon = await self.bot.redis.hget("activity:autosummon", uid) or 0
        summon = await self.bot.redis.hget("activity:summon", uid) or 0

        msg = (
            f"📊 Debug for {member.mention}:\n"
            f"- All time: {int(all_time)}\n"
            f"- Monthly: {int(monthly)}\n"
            f"- AutoSummon: {int(autosummon)}\n"
            f"- Summon: {int(summon)}"
        )

        await interaction.followup.send(msg, ephemeral=True)

    # --- Debug: log all Mazoku messages ---
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.id != MAZOKU_BOT_ID:
            return
        if not message.guild or message.guild.id != GUILD_ID:
            return

        log.info("📩 Mazoku message detected (ID=%s)", message.id)
        log.info("Content: %s", message.content)

        if message.embeds:
            for i, e in enumerate(message.embeds):
                log.info("Embed %s:", i)
                log.info("  Title: %s", e.title)
                log.info("  Desc: %s", e.description)
                log.info("  Footer: %s", e.footer.text if e.footer else "")
                if e.fields:
                    for f in e.fields:
                        log.info("  Field: %s = %s", f.name, f.value)

    # --- Debug: log Mazoku edits too ---
    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if after.author.id != MAZOKU_BOT_ID:
            return
        if not after.guild or after.guild.id != GUILD_ID:
            return

        log.info("✏️ Mazoku message edited (ID=%s)", after.id)
        if after.embeds:
            for i, e in enumerate(after.embeds):
                log.info("Embed %s:", i)
                log.info("  Title: %s", e.title)
                log.info("  Desc: %s", e.description)
                log.info("  Footer: %s", e.footer.text if e.footer else "")
                if e.fields:
                    for f in e.fields:
                        log.info("  Field: %s = %s", f.name, f.value)


# Obligatoire pour charger l’extension
async def setup(bot: commands.Bot):
    await bot.add_cog(Leaderboard(bot))
