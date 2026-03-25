import logging
import re
import discord
from discord import app_commands
from discord.ext import commands

from config import GUILD_ID, MAZOKU_BOT_ID, Colors
from utils.embed_builder import (
    LilacEmbed,
    build_leaderboard_embed,
    CATEGORY_EMOJIS,
    CATEGORY_LABELS,
)

log = logging.getLogger("cog-leaderboard")


def is_admin():
    def predicate(interaction: discord.Interaction) -> bool:
        return interaction.user.guild_permissions.administrator
    return app_commands.check(predicate)


KEY_MAP = {
    "all":        "leaderboard",
    "monthly":    "activity:monthly",
    "autosummon": "activity:autosummon",
    "summon":     "activity:summon",
}


class LeaderboardView(discord.ui.View):
    def __init__(self, bot: commands.Bot, guild: discord.Guild):
        super().__init__(timeout=120)
        self.bot   = bot
        self.guild = guild

    @discord.ui.select(
        placeholder="📊  Choose a category…",
        options=[
            discord.SelectOption(
                label=CATEGORY_LABELS[k],
                value=k,
                emoji=CATEGORY_EMOJIS[k],
            )
            for k in ("all", "monthly", "autosummon", "summon")
        ],
    )
    async def select_callback(
        self, interaction: discord.Interaction, select: discord.ui.Select
    ):
        category = select.values[0]
        embed = await self._build(category, interaction.guild, interaction.user)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _build(self, category, guild, user):
        if not getattr(self.bot, "redis", None):
            return LilacEmbed.error("Redis unavailable", "The database is not connected.")
        data = await self.bot.redis.hgetall(KEY_MAP[category])
        if not data:
            embed = LilacEmbed(
                title=f"{CATEGORY_EMOJIS[category]}  {CATEGORY_LABELS[category]} Leaderboard",
                description="*No data yet — start claiming!*",
                color=Colors.GOLD,
            )
            embed.set_guild_thumbnail(guild)
            embed.set_requester_footer(user)
            return embed
        sorted_data = sorted(data.items(), key=lambda x: int(x[1]), reverse=True)
        return build_leaderboard_embed(category, sorted_data, guild, user)


class Leaderboard(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.paused = {k: False for k in KEY_MAP}
        log.info("⚙️ Leaderboard cog loaded (GUILD_ID=%s)", GUILD_ID)

    @app_commands.command(name="leaderboard", description="View the leaderboard")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.checks.cooldown(1, 120.0, key=lambda i: i.user.id)
    async def leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)
        view  = LeaderboardView(self.bot, interaction.guild)
        embed = await view._build("all", interaction.guild, interaction.user)
        await interaction.followup.send(embed=embed, view=view)

    @leaderboard.error
    async def leaderboard_error(self, interaction, error):
        if isinstance(error, app_commands.CommandOnCooldown):
            await interaction.response.send_message(
                embed=LilacEmbed.warning(
                    "Slow down!",
                    f"Please wait **{int(error.retry_after)}s** before using `/leaderboard` again.",
                ),
                ephemeral=True,
            )

    @app_commands.command(name="leaderboard-reset", description="Reset scores (admin)")
    @app_commands.choices(
        category=[
            app_commands.Choice(name="All time",   value="all"),
            app_commands.Choice(name="Monthly",    value="monthly"),
            app_commands.Choice(name="AutoSummon", value="autosummon"),
            app_commands.Choice(name="Summon",     value="summon"),
            app_commands.Choice(name="Everything", value="all_keys"),
        ]
    )
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @is_admin()
    async def leaderboard_reset(self, interaction, category: app_commands.Choice[str]):
        await interaction.response.defer(ephemeral=True)
        if not getattr(self.bot, "redis", None):
            return await interaction.followup.send(embed=LilacEmbed.error("Redis unavailable"), ephemeral=True)
        if category.value == "all_keys":
            for key in KEY_MAP.values():
                await self.bot.redis.delete(key)
            msg = "All leaderboard scores have been wiped."
        else:
            await self.bot.redis.delete(KEY_MAP[category.value])
            msg = f"Category **{CATEGORY_LABELS[category.value]}** has been reset."
        await interaction.followup.send(embed=LilacEmbed.success("Reset complete", f"🧹 {msg}"), ephemeral=True)

    @leaderboard_reset.error
    async def _reset_error(self, i, e): await self._admin_error(i, e, "reset")

    @app_commands.command(name="leaderboard-pause", description="Pause or resume counters (admin)")
    @app_commands.choices(
        category=[
            app_commands.Choice(name="All time",   value="all"),
            app_commands.Choice(name="Monthly",    value="monthly"),
            app_commands.Choice(name="AutoSummon", value="autosummon"),
            app_commands.Choice(name="Summon",     value="summon"),
        ],
        state=[
            app_commands.Choice(name="Pause",  value="pause"),
            app_commands.Choice(name="Resume", value="resume"),
        ],
    )
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @is_admin()
    async def leaderboard_pause(self, interaction, category: app_commands.Choice[str], state: app_commands.Choice[str]):
        await interaction.response.defer(ephemeral=True)
        self.paused[category.value] = state.value == "pause"
        icon   = "⏸️" if self.paused[category.value] else "▶️"
        label  = CATEGORY_LABELS[category.value]
        status = "paused" if self.paused[category.value] else "resumed"
        await interaction.followup.send(
            embed=LilacEmbed.info(f"{icon}  {label} {status}", f"Scoring for **{label}** is now **{status}**."),
            ephemeral=True,
        )

    @leaderboard_pause.error
    async def _pause_error(self, i, e): await self._admin_error(i, e, "pause")

    @app_commands.command(name="leaderboard-debug", description="View internal stats (admin)")
    @app_commands.choices(scope=[
        app_commands.Choice(name="Summary",     value="summary"),
        app_commands.Choice(name="Full detail", value="full"),
    ])
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @is_admin()
    async def leaderboard_debug(self, interaction, scope: app_commands.Choice[str]):
        await interaction.response.defer(ephemeral=True)
        if not getattr(self.bot, "redis", None):
            return await interaction.followup.send(embed=LilacEmbed.error("Redis unavailable"), ephemeral=True)
        total_monthly = await self.bot.redis.get("activity:monthly:total") or 0
        embed = LilacEmbed(title="🛠️  Leaderboard Debug", color=Colors.INFO)
        for k, redis_key in KEY_MAP.items():
            size = await self.bot.redis.hlen(redis_key)
            paused_label = " *(paused)*" if self.paused[k] else ""
            embed.add_field(
                name=f"{CATEGORY_EMOJIS[k]} {CATEGORY_LABELS[k]}{paused_label}",
                value=f"**{size}** entries", inline=True,
            )
        embed.add_field(name="📅 Monthly total claims", value=f"**{total_monthly}**", inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @leaderboard_debug.error
    async def _debug_error(self, i, e): await self._admin_error(i, e, "debug")

    async def _admin_error(self, interaction, error, action):
        try:
            if isinstance(error, app_commands.CheckFailure):
                await interaction.response.send_message(
                    embed=LilacEmbed.error("Access denied", "This command is reserved for admins."),
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    embed=LilacEmbed.error(f"Error during {action}", str(error)),
                    ephemeral=True,
                )
        except discord.InteractionResponded:
            await interaction.followup.send(embed=LilacEmbed.error(f"Error during {action}"), ephemeral=True)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if after.author.id != MAZOKU_BOT_ID:
            return
        if not after.guild or after.guild.id != GUILD_ID or not after.embeds:
            return
        embed = after.embeds[0]
        title = (embed.title or "").lower()
        if not any(x in title for x in ["card claimed", "auto summon claimed", "summon claimed"]):
            return
        match = re.search(r"<@!?(\d+)>", embed.description or "")
        if not match:
            return
        user_id = int(match.group(1))
        member  = after.guild.get_member(user_id)
        if not member or not getattr(self.bot, "redis", None):
            return
        claim_key = f"claim:{after.id}:{user_id}"
        if await self.bot.redis.get(claim_key):
            return
        await self.bot.redis.set(claim_key, "1", ex=86400)
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
        log.info("🏅 %s +1 point (%s)", member.display_name, embed.title)


async def setup(bot: commands.Bot):
    await bot.add_cog(Leaderboard(bot))
