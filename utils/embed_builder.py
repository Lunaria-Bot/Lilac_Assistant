"""
utils/embed_builder.py — Lilac Assistant embed helpers
Provides a consistent, on-brand look for every message the bot sends.
"""
from __future__ import annotations

import discord
from config import Colors


# ─────────────────────────────────────────────────────────────
# Core builder
# ─────────────────────────────────────────────────────────────

class LilacEmbed(discord.Embed):
    """
    A discord.Embed subclass pre-styled for Lilac Assistant.
    Usage:
        embed = LilacEmbed.success("Done!", "Role assigned.")
        embed = LilacEmbed.error("Oops", "No permission.")
        embed = LilacEmbed(title="Custom", color=Colors.GOLD)
    """

    @classmethod
    def success(cls, title: str, description: str = "", **kwargs) -> "LilacEmbed":
        return cls(title=f"✅  {title}", description=description, color=Colors.SUCCESS, **kwargs)

    @classmethod
    def error(cls, title: str, description: str = "", **kwargs) -> "LilacEmbed":
        return cls(title=f"❌  {title}", description=description, color=Colors.ERROR, **kwargs)

    @classmethod
    def warning(cls, title: str, description: str = "", **kwargs) -> "LilacEmbed":
        return cls(title=f"⚠️  {title}", description=description, color=Colors.WARNING, **kwargs)

    @classmethod
    def info(cls, title: str, description: str = "", **kwargs) -> "LilacEmbed":
        return cls(title=f"ℹ️  {title}", description=description, color=Colors.INFO, **kwargs)

    @classmethod
    def lilac(cls, title: str, description: str = "", **kwargs) -> "LilacEmbed":
        return cls(title=title, description=description, color=Colors.LILAC, **kwargs)

    def set_author_member(self, member: discord.Member) -> "LilacEmbed":
        self.set_author(name=member.display_name, icon_url=member.display_avatar.url)
        return self

    def set_guild_thumbnail(self, guild: discord.Guild) -> "LilacEmbed":
        if guild.icon:
            self.set_thumbnail(url=guild.icon.url)
        return self

    def set_requester_footer(self, user: discord.User | discord.Member, extra: str = "") -> "LilacEmbed":
        suffix = f" • {extra}" if extra else ""
        self.set_footer(
            text=f"Requested by {user.display_name}{suffix}",
            icon_url=user.display_avatar.url,
        )
        return self


# ─────────────────────────────────────────────────────────────
# Leaderboard helpers
# ─────────────────────────────────────────────────────────────

MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}
CATEGORY_EMOJIS = {
    "all":        "🏆",
    "monthly":    "📅",
    "autosummon": "🤖",
    "summon":     "🎴",
}
CATEGORY_LABELS = {
    "all":        "All Time",
    "monthly":    "Monthly",
    "autosummon": "AutoSummon",
    "summon":     "Summon",
}


def build_leaderboard_embed(
    category: str,
    sorted_data: list[tuple[str, str]],
    guild: discord.Guild,
    user: discord.Member,
) -> discord.Embed:
    emoji = CATEGORY_EMOJIS.get(category, "🏆")
    label = CATEGORY_LABELS.get(category, category.title())

    embed = LilacEmbed(title=f"{emoji}  {label} Leaderboard", color=Colors.GOLD)
    embed.set_guild_thumbnail(guild)

    if not sorted_data:
        embed.description = "*No data yet — start claiming!*"
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
        lines.append(f"{medal}  {mention} — **{score}** claims{hl}")

    embed.description = "\n".join(lines)

    user_score = int(dict(sorted_data).get(user_id_str, 0))
    if user_rank and user_rank <= 3:
        rank_text = f"{MEDALS[user_rank]} You're on the podium!"
    elif user_rank and user_rank <= 10:
        rank_text = f"🎉 You're **#{user_rank}** with **{user_score}** claims"
    elif user_rank:
        rank_text = f"📊 Your rank: **#{user_rank}** · {user_score} claims"
    else:
        rank_text = f"📊 Your claims: **{user_score}**"

    embed.add_field(name="Your stats", value=rank_text, inline=False)
    embed.set_requester_footer(user)
    return embed


# ─────────────────────────────────────────────────────────────
# Quick one-liner helpers
# ─────────────────────────────────────────────────────────────

async def reply_success(interaction: discord.Interaction, title: str,
                         description: str = "", ephemeral: bool = True):
    await interaction.followup.send(embed=LilacEmbed.success(title, description), ephemeral=ephemeral)


async def reply_error(interaction: discord.Interaction, title: str,
                       description: str = "", ephemeral: bool = True):
    await interaction.followup.send(embed=LilacEmbed.error(title, description), ephemeral=ephemeral)
