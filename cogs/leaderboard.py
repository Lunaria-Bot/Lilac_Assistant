# cogs/leaderboard.py

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

# --- View avec Select ---
class LeaderboardView(discord.ui.View):
    def __init__(self, bot, guild):
        super().__init__(timeout=120)
        self.bot = bot
        self.guild = guild

    @discord.ui.select(
        placeholder="Choisis une catégorie",
        options=[
            discord.SelectOption(label="All time", value="all"),
            discord.SelectOption(label="Monthly", value="monthly"),
            discord.SelectOption(label="AutoSummon", value="autosummon"),
            discord.SelectOption(label="Summon", value="summon"),
        ]
    )
    async def select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        category = select.values[0]
        embed = await self.build_leaderboard(category, interaction.guild)
        await interaction.response.edit_message(embed=embed, view=self)

    async def build_leaderboard(self, category: str, guild: discord.Guild):
        key_map = {
            "all": "leaderboard",
            "monthly": "activity:monthly",
            "autosummon": "activity:autosummon",
            "summon": "activity:summon",
        }
        key = key_map.get(category, "leaderboard")

        # Vérifier Redis
        if not getattr(self.bot, "redis", None):
            return discord.Embed(
                title=f"🏆 {category.title()} Leaderboard",
                description="❌ Redis not connected.",
                color=discord.Color.red()
            )

        data = await self.bot.redis.hgetall(key)
        if not data:
            return discord.Embed(
                title=f"🏆 {category.title()} Leaderboard",
                description="Empty",
                color=discord.Color.gold()
            )

        # Trier top 10
        try:
            sorted_data = sorted(data.items(), key=lambda x: int(x[1]), reverse=True)[:10]
        except Exception:
            sorted_data = sorted(
                ((k, int(v) if str(v).isdigit() else 0) for k, v in data.items()),
                key=lambda x: x[1],
                reverse=True
            )[:10]

        lines = []
        for i, (uid, score) in enumerate(sorted_data, start=1):
            member = guild.get_member(int(uid))
            name = member.display_name if member else f"User {uid}"
            lines.append(f"**{i}.** {name} — {score} pts")

        return discord.Embed(
            title=f"🏆 {category.title()} Leaderboard",
            description="\n".join(lines) if lines else "No entries yet.",
            color=discord.Color.gold()
        )


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

    # --- Commande principale ---
    @app_commands.command(name="leaderboard", description="View the leaderboard")
    async def leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        view = LeaderboardView(self.bot, interaction.guild)
        embed = await view.build_leaderboard("all", interaction.guild)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

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
        if not getattr(self.bot, "redis", None):
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
        if not getattr(self.bot, "redis", None):
            await interaction.followup.send("❌ Redis not connected.", ephemeral=True)
            return

        uid = str(member.id)
        all_time = await self.bot.redis.hget("leaderboard", uid) or 0
        monthly = await self.bot.redis.hget("activity:monthly", uid) or 0
        autosummon = await self.bot.redis.hget("activity:autosummon", uid) or 0
        summon = await self.bot.redis.hget("activity:summon", uid) or 0

        embed = discord.Embed(title=f"📊 Stats for {member.display_name}", color=discord.Color.blurple())
        embed.add_field(name="All time", value=int(all_time), inline=False)
        embed.add_field(name="Monthly", value=int(monthly), inline=False)
        embed.add_field(name="AutoSummon", value=int(autosummon), inline=False)
        embed.add_field(name="Summon", value=int(summon), inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    # --- Listeners ---
    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        # Filtre: uniquement Mazoku dans le bon serveur
        if after.author.id != MAZOKU_BOT_ID:
            return
        if not after.guild or after.guild.id != GUILD_ID:
            return
        if not after.embeds:
            return

        embed = after.embeds[0]
        title = (embed.title or "").lower()
        log.debug("Embed title detected: %s", title)

        # Prendre en compte plusieurs libellés possibles
        if any(x in title for x in ["card claimed", "auto summon claimed", "summon claimed"]):
            log.info("✏️ Claim detected in edited message %s", after.id)

            # Extraire le joueur
            match = re.search(r"<@!?(\d+)>", embed.description or "")
            if not match:
                log.warning("⚠️ Aucun joueur trouvé dans l’embed.")
                return

            user_id = int(match.group(1))
            member = after.guild.get_member(user_id)
            if not member:
                log.warning("⚠️ Impossible de trouver le membre %s dans le serveur.", user_id)
                return

            if not getattr(self.bot, "redis", None):
                log.error("❌ Redis not connected: cannot add points.")
                return

            # Anti double comptage
            claim_key = f"claim:{after.id}:{user_id}"
            already = await self.bot.redis.get(claim_key)
            if already:
                log.debug("⏸️ Claim déjà compté pour %s", user_id)
                return
            await self.bot.redis.set(claim_key, "1", ex=86400)

            log.info("➡️ Adding points for user %s", user_id)

            # Monthly
            if not self.paused["monthly"]:
                await self.bot.redis.hincrby("activity:monthly", str(user_id), 1)
                await self.bot.redis.incr("activity:monthly:total")

            # Autosummon vs Summon (selon le titre)
            if "auto summon claimed" in title:
                if not self.paused["autosummon"]:
                    await self.bot.redis.hincrby("activity:autosummon", str(user_id), 1)
            else:
                if not self.paused["summon"]:
                    await self.bot.redis.hincrby("activity:summon", str(user_id), 1)

            # Global
            if not self.paused["all"]:
                await self.bot.redis.hincrby("leaderboard", str(user_id), 1)

            log.info("🏅 %s gained +1 point from %s", member.display_name, embed.title)


# --- Extension setup ---
async def setup(bot: commands.Bot):
    await bot.add_cog(Leaderboard(bot))
