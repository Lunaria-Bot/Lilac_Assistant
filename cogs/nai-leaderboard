import os
import re
import logging
import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime

log = logging.getLogger("nai-leaderboard")

BOT_ID = 1312830013573169252
TRACK_CHANNELS = {1435259140464443454, 1449113593709727777, 1449114801686183999}


# ---------------- VIEW ---------------- #

class NaiLeaderboardView(discord.ui.View):
    def __init__(self, bot, guild):
        super().__init__(timeout=120)
        self.bot = bot
        self.guild = guild

    @discord.ui.select(
        placeholder="Choose a category",
        options=[
            discord.SelectOption(label="All Time", value="all"),
            discord.SelectOption(label="Monthly", value="monthly"),
            discord.SelectOption(label="Daily", value="daily"),
        ]
    )
    async def select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        category = select.values[0]
        embed = await self.build_leaderboard(category, interaction.guild, interaction.user)
        await interaction.response.edit_message(embed=embed, view=self)

    async def build_leaderboard(self, category: str, guild: discord.Guild, user: discord.Member):
        key_map = {
            "all": "nai:leaderboard",
            "monthly": "nai:monthly",
            "daily": "nai:daily",
        }
        key = key_map.get(category, "nai:leaderboard")

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
                description="Empty leaderboard.",
                color=discord.Color.gold()
            )

        sorted_data = sorted(data.items(), key=lambda x: int(x[1]), reverse=True)
        lines = []
        user_rank = None

        for i, (uid, score) in enumerate(sorted_data, start=1):
            if str(user.id) == uid:
                user_rank = i
            if i <= 10:
                member = guild.get_member(int(uid))
                mention = member.mention if member else f"<@{uid}>"
                lines.append(f"**{i}.** {mention} — {score} points")

        user_score = int(data.get(str(user.id), 0))
        if user_rank and user_rank <= 10:
            user_line = f"\n\n🎉 {user.mention} is ranked **#{user_rank}** with **{user_score}** points!"
        else:
            user_line = f"\n\n{user.mention} has **{user_score}** points in **{category.title()}**."

        embed = discord.Embed(
            title=f"🏆 {category.title()} Leaderboard",
            description="\n".join(lines) + user_line,
            color=discord.Color.gold()
        )
        embed.set_footer(text=f"Requested by {user.display_name}")
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        return embed


# ---------------- COG ---------------- #

class NaiLeaderboard(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.daily_reset_task.start()
        log.info("Nai Leaderboard loaded with daily reset enabled.")

    # ---------------- COMMAND ---------------- #

    @app_commands.command(name="nai-leaderboard", description="View the NAI leaderboard")
    async def nai_leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)
        view = NaiLeaderboardView(self.bot, interaction.guild)
        embed = await view.build_leaderboard("all", interaction.guild, interaction.user)
        await interaction.followup.send(embed=embed, view=view)

    # ---------------- ADMIN RESET MONTHLY ---------------- #

    @app_commands.command(name="nai-reset-monthly", description="Reset the monthly leaderboard (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def nai_reset_monthly(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if not getattr(self.bot, "redis", None):
            await interaction.followup.send("❌ Redis not connected.", ephemeral=True)
            return

        await self.bot.redis.delete("nai:monthly")
        await interaction.followup.send("🧹 Monthly leaderboard has been reset.", ephemeral=True)

    # ---------------- DAILY RESET TASK ---------------- #

    @tasks.loop(minutes=1)
    async def daily_reset_task(self):
        now = datetime.now()
        if now.hour == 0 and now.minute == 0:  # 00:00
            if getattr(self.bot, "redis", None):
                await self.bot.redis.delete("nai:daily")
                log.info("🕛 Daily leaderboard reset at midnight.")

    @daily_reset_task.before_loop
    async def before_daily_reset(self):
        await self.bot.wait_until_ready()

    # ---------------- LISTENER ---------------- #

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.id != BOT_ID:
            return
        if message.channel.id not in TRACK_CHANNELS:
            return

        match = re.search(r"<@!?(\d+)> has taken \*\*(.+?)\*\*!", message.content)
        if not match:
            return

        user_id = match.group(1)

        if not getattr(self.bot, "redis", None):
            return

        await self.bot.redis.hincrby("nai:leaderboard", user_id, 1)
        await self.bot.redis.hincrby("nai:monthly", user_id, 1)
        await self.bot.redis.hincrby("nai:daily", user_id, 1)

        log.info(f"NAI +1 → {user_id}")

# ---------------- SETUP ---------------- #

async def setup(bot: commands.Bot):
    await bot.add_cog(NaiLeaderboard(bot))
