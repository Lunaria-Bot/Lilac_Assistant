import re
import logging
import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime

from config import NAI_BOT_ID, NAI_TRACK_CHANNELS, Colors
from utils.embed_builder import LilacEmbed, MEDALS

log = logging.getLogger("nai-leaderboard")

NAI_KEY_MAP = {
    "all":     "nai:leaderboard",
    "monthly": "nai:monthly",
    "daily":   "nai:daily",
}
NAI_LABELS = {"all": "All Time", "monthly": "Monthly", "daily": "Daily"}
NAI_EMOJIS = {"all": "🏆", "monthly": "📅", "daily": "☀️"}


def _build_nai_embed(
    category: str,
    sorted_data: list[tuple[str, str]],
    guild: discord.Guild,
    user: discord.Member,
) -> discord.Embed:
    label = NAI_LABELS[category]
    emoji = NAI_EMOJIS[category]

    embed = LilacEmbed(title=f"{emoji}  {label} NAI Leaderboard", color=Colors.GOLD)
    embed.set_guild_thumbnail(guild)

    if not sorted_data:
        embed.description = "*No data yet!*"
        embed.set_requester_footer(user)
        return embed

    user_id_str = str(user.id)
    user_rank   = next((i for i, (uid, _) in enumerate(sorted_data, 1) if uid == user_id_str), None)
    lines       = []

    for i, (uid, score) in enumerate(sorted_data[:10], start=1):
        member  = guild.get_member(int(uid))
        mention = member.mention if member else f"<@{uid}>"
        medal   = MEDALS.get(i, f"**`#{i:>2}`**")
        hl      = " ◀" if uid == user_id_str else ""
        lines.append(f"{medal}  {mention} — **{score}** points{hl}")

    embed.description = "\n".join(lines)

    user_score = int(dict(sorted_data).get(user_id_str, 0))
    if user_rank and user_rank <= 3:
        rank_text = f"{MEDALS[user_rank]} You're on the podium!"
    elif user_rank:
        rank_text = f"📊 Your rank: **#{user_rank}** · {user_score} pts"
    else:
        rank_text = f"📊 Your points: **{user_score}**"

    embed.add_field(name="Your stats", value=rank_text, inline=False)
    embed.set_requester_footer(user)
    return embed


class NaiLeaderboardView(discord.ui.View):
    def __init__(self, bot: commands.Bot, guild: discord.Guild):
        super().__init__(timeout=120)
        self.bot   = bot
        self.guild = guild

    @discord.ui.select(
        placeholder="📊  Choose a category…",
        options=[
            discord.SelectOption(label=NAI_LABELS[k], value=k, emoji=NAI_EMOJIS[k])
            for k in ("all", "monthly", "daily")
        ],
    )
    async def select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        embed = await self._build(select.values[0], interaction.guild, interaction.user)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _build(self, category: str, guild: discord.Guild, user: discord.Member) -> discord.Embed:
        if not getattr(self.bot, "redis", None):
            return LilacEmbed.error("Redis unavailable")
        data = await self.bot.redis.hgetall(NAI_KEY_MAP[category])
        if not data:
            embed = LilacEmbed(title=f"{NAI_EMOJIS[category]}  {NAI_LABELS[category]} NAI Leaderboard", color=Colors.GOLD)
            embed.description = "*No data yet!*"
            embed.set_guild_thumbnail(guild)
            embed.set_requester_footer(user)
            return embed
        sorted_data = sorted(data.items(), key=lambda x: int(x[1]), reverse=True)
        return _build_nai_embed(category, sorted_data, guild, user)


class NaiLeaderboard(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.daily_reset_task.start()
        log.info("⚙️ NaiLeaderboard loaded")

    def cog_unload(self):
        self.daily_reset_task.cancel()

    # ─────────────────────────────────────────────
    # /nai-leaderboard
    # ─────────────────────────────────────────────

    @app_commands.command(name="nai-leaderboard", description="View the NAI leaderboard")
    async def nai_leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)
        view  = NaiLeaderboardView(self.bot, interaction.guild)
        embed = await view._build("all", interaction.guild, interaction.user)
        await interaction.followup.send(embed=embed, view=view)

    # ─────────────────────────────────────────────
    # /nai-reset-monthly (admin)
    # ─────────────────────────────────────────────

    @app_commands.command(name="nai-reset-monthly", description="Reset the monthly NAI leaderboard (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def nai_reset_monthly(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not getattr(self.bot, "redis", None):
            return await interaction.followup.send(embed=LilacEmbed.error("Redis unavailable"), ephemeral=True)
        await self.bot.redis.delete("nai:monthly")
        await interaction.followup.send(
            embed=LilacEmbed.success("Monthly reset", "🧹 NAI monthly leaderboard has been wiped."),
            ephemeral=True,
        )

    # ─────────────────────────────────────────────
    # Daily reset at midnight
    # ─────────────────────────────────────────────

    @tasks.loop(minutes=1)
    async def daily_reset_task(self):
        now = datetime.now()
        if now.hour == 0 and now.minute == 0 and getattr(self.bot, "redis", None):
            await self.bot.redis.delete("nai:daily")
            log.info("🕛 NAI daily leaderboard reset at midnight")

    @daily_reset_task.before_loop
    async def before_daily_reset(self):
        await self.bot.wait_until_ready()

    # ─────────────────────────────────────────────
    # Listener
    # ─────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.id != NAI_BOT_ID:
            return
        if message.channel.id not in NAI_TRACK_CHANNELS:
            return

        match = re.search(r"<@!?(\d+)> has taken \*\*(.+?)\*\*!", message.content)
        if not match or not getattr(self.bot, "redis", None):
            return

        user_id = match.group(1)
        for key in ("nai:leaderboard", "nai:monthly", "nai:daily"):
            await self.bot.redis.hincrby(key, user_id, 1)
        log.info("NAI +1 → %s", user_id)


async def setup(bot: commands.Bot):
    await bot.add_cog(NaiLeaderboard(bot))
