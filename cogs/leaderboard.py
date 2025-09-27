import os
import re
import logging
import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import View, Select

log = logging.getLogger("cog-leaderboard")

# --- Env ---
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
MAZOKU_BOT_ID = int(os.getenv("MAZOKU_BOT_ID", "0"))
MAZOKU_CHANNEL_ID = int(os.getenv("MAZOKU_CHANNEL_ID", "0"))  # optional filter

# Points per rarity (Mazoku emoji IDs)
RARITY_POINTS = {
    "1342202221558763571": 1,   # Common
    "1342202219574857788": 3,   # Rare
    "1342202597389373530": 7,   # Super Rare
    "1342202203515125801": 17   # Ultra Rare
}
EMOJI_REGEX = re.compile(r"<a?:\w+:(\d+)>")

# --- Dropdown View ---
class LeaderboardView(View):
    def __init__(self, cog, guild, user):
        super().__init__(timeout=60)
        self.cog = cog
        self.guild = guild
        self.user = user

        self.select = Select(
            placeholder="Choose leaderboard type...",
            options=[
                discord.SelectOption(label="All time", value="all"),
                discord.SelectOption(label="Monthly", value="monthly"),
                discord.SelectOption(label="AutoSummon", value="autosummon"),
                discord.SelectOption(label="Summon", value="summon"),
            ]
        )
        self.select.callback = self.select_callback
        self.add_item(self.select)

    async def select_callback(self, interaction: discord.Interaction):
        choice = self.select.values[0]
        embed = await self.cog.build_leaderboard_embed(self.guild, choice, self.user)
        await interaction.response.edit_message(embed=embed, view=self)

# --- Cog ---
class Leaderboard(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # état par catégorie
        self.paused = {
            "all": False,
            "monthly": False,
            "autosummon": False,
            "summon": False
        }

    # --- Slash command /leaderboard ---
    @app_commands.command(name="leaderboard", description="View the leaderboard")
    async def leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)  # 👈 évite Unknown interaction

        embed = await self.build_leaderboard_embed(interaction.guild, "all", interaction.user)
        view = LeaderboardView(self, interaction.guild, interaction.user)

        await interaction.followup.send(embed=embed, view=view)

    # --- Build embed depending on mode ---
    async def build_leaderboard_embed(self, guild, mode: str, user):
        if not self.bot.redis:
            return discord.Embed(title="❌ Redis not connected.")

        if mode == "all":
            scores = await self.bot.redis.hgetall("leaderboard")
            title = "🏆 All Time Leaderboard"
        elif mode == "monthly":
            scores = await self.bot.redis.hgetall("activity:monthly")
            title = "📈 Monthly Activity Leaderboard"
        elif mode == "autosummon":
            scores = await self.bot.redis.hgetall("activity:autosummon")
            title = "⚡ AutoSummon Leaderboard"
        elif mode == "summon":
            scores = await self.bot.redis.hgetall("activity:summon")
            title = "✨ Summon Leaderboard"
        else:
            scores = {}
            title = "Leaderboard"

        sorted_scores = sorted(scores.items(), key=lambda x: int(x[1]), reverse=True)
        medals = ["🥇", "🥈", "🥉"]
        description_lines = []
        for i, (user_id, points) in enumerate(sorted_scores[:10], start=1):
            member = guild.get_member(int(user_id))
            name = member.display_name if member else f"User {user_id}"
            prefix = medals[i-1] if i <= 3 else f"#{i}"
            description_lines.append(f"{prefix} **{name}** ➔ {points}")

        embed = discord.Embed(
            title=title,
            description="\n".join(description_lines) or "No data yet.",
            color=discord.Color.gold()
        )
        return embed
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

    # --- Events ---
    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if not self.bot.redis:
            return
        if after.author.id != MAZOKU_BOT_ID:
            return
        if not after.guild or after.guild.id != GUILD_ID:
            return
        if MAZOKU_CHANNEL_ID and after.channel.id != MAZOKU_CHANNEL_ID:
            return
        if not after.embeds:
            return

        embed = after.embeds[0]
        title = (embed.title or "").lower()

        # Auto Summon Claimed
        if "auto summon claimed" in title:
            match = re.search(r"<@!?(\d+)>", embed.description or "")
            if not match and embed.fields:
                for field in embed.fields:
                    match = re.search(r"<@!?(\d+)>", field.value or "")
                    if match:
                        break
            if not match and embed.footer and embed.footer.text:
                match = re.search(r"<@!?(\d+)>", embed.footer.text)
            if not match:
                return

            user_id = int(match.group(1))
            member = after.guild.get_member(user_id)
            if not member:
                return

            claim_key = f"claim:{after.id}:{user_id}"
            already = await self.bot.redis.get(claim_key)
            if already:
                return
            await self.bot.redis.set(claim_key, "1", ex=86400)

            # Monthly
            if not self.paused["monthly"]:
                await self.bot.redis.hincrby("activity:monthly", str(user_id), 1)
                await self.bot.redis.incr("activity:monthly:total")

            # AutoSummon
            if not self.paused["autosummon"]:
                await self.bot.redis.hincrby("activity:autosummon", str(user_id), 1)

            # All time (points par rareté)
            if not self.paused["all"]:
                rarity_points = 0
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
                        if emote_id in RARITY_POINTS:
                            rarity_points = RARITY_POINTS[emote_id]
                            break
                    if rarity_points:
                        break

                if rarity_points:
                    await self.bot.redis.hincrby("leaderboard", str(user_id), rarity_points)
                    log.info("🏅 %s gains %s points (All time)", member.display_name, rarity_points)

        # Summon Claimed (hors auto summon)
        elif "summon claimed" in title:
            match = re.search(r"<@!?(\d+)>", embed.description or "")
            if not match and embed.fields:
                for field in embed.fields:
                    match = re.search(r"<@!?(\d+)>", field.value or "")
                    if match:
                        break
            if not match and embed.footer and embed.footer.text:
                match = re.search(r"<@!?(\d+)>", embed.footer.text)
            if not match:
                return

            user_id = int(match.group(1))
            member = after.guild.get_member(user_id)
            if not member:
                return

            claim_key = f"claim:{after.id}:{user_id}"
            already = await self.bot.redis.get(claim_key)
            if already:
                return
            await self.bot.redis.set(claim_key, "1", ex=86400)

            # Monthly
            if not self.paused["monthly"]:
                await self.bot.redis.hincrby("activity:monthly", str(user_id), 1)
                await self.bot.redis.incr("activity:monthly:total")

            # Summon
            if not self.paused["summon"]:
                await self.bot.redis.hincrby("activity:summon", str(user_id), 1)


# Obligatoire pour charger l’extension
async def setup(bot: commands.Bot):
    await bot.add_cog(Leaderboard(bot))
