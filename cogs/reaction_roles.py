import discord
from discord.ext import commands
from discord import app_commands

from config import (
    AUTOROLE_MESSAGE_ID,
    ROLE_TIER_1, ROLE_TIER_2, ROLE_TIER_3,
    REQUIRED_ROLES_FOR_T3,
    TARGET_CHANNEL_ID,
    BOT_ID,
    Colors,
)
from utils.embed_builder import LilacEmbed


class SimpleReactionRoles(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── /sendautorole ─────────────────────────────────────────

    @app_commands.command(
        name="sendautorole",
        description="Send the autorole message in the configured channel.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def sendautorole(self, interaction: discord.Interaction):
        channel = interaction.guild.get_channel(TARGET_CHANNEL_ID)
        if not channel:
            return await interaction.response.send_message(
                embed=LilacEmbed.error("Channel not found", f"<#{TARGET_CHANNEL_ID}> is missing."),
                ephemeral=True,
            )

        embed = LilacEmbed(
            title="🔔  React to get pinged for boss spawns!",
            description=(
                f"**1️⃣  Tier 1** — <@&{ROLE_TIER_1}>\n"
                f"**2️⃣  Tier 2** — <@&{ROLE_TIER_2}>\n"
                f"**3️⃣  Tier 3** — <@&{ROLE_TIER_3}>\n\n"
                "React below to toggle your notification role.\n"
                "React again to remove it."
            ),
            color=Colors.LILAC,
        )
        embed.set_footer(text="Tier 3 requires a special rank — keep grinding!")

        msg = await channel.send(embed=embed)
        for emoji in ("1️⃣", "2️⃣", "3️⃣"):
            await msg.add_reaction(emoji)

        await interaction.response.send_message(
            embed=LilacEmbed.success(
                "Autorole message sent",
                f"Posted in <#{TARGET_CHANNEL_ID}>.  Message ID: `{msg.id}`",
            ),
            ephemeral=True,
        )

    # ── Helpers ───────────────────────────────────────────────

    async def _remove_reaction(self, payload: discord.RawReactionActionEvent):
        guild   = self.bot.get_guild(payload.guild_id)
        channel = guild.get_channel(payload.channel_id)
        msg     = await channel.fetch_message(payload.message_id)
        try:
            await msg.remove_reaction(payload.emoji, payload.member)
        except Exception:
            pass

    # ── Reaction add (toggle) ─────────────────────────────────

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.message_id != AUTOROLE_MESSAGE_ID:
            return
        if payload.user_id == BOT_ID:
            return

        guild  = self.bot.get_guild(payload.guild_id)
        member = guild.get_member(payload.user_id)
        emoji  = str(payload.emoji)

        role_map = {
            "1️⃣": ROLE_TIER_1,
            "2️⃣": ROLE_TIER_2,
            "3️⃣": ROLE_TIER_3,
        }
        if emoji not in role_map:
            return

        role = guild.get_role(role_map[emoji])

        # Tier 3 gating
        if emoji == "3️⃣" and role not in member.roles:
            has_required = any(r.id in REQUIRED_ROLES_FOR_T3 for r in member.roles)
            if not has_required:
                await self._remove_reaction(payload)
                try:
                    await member.send(
                        "Keep grinding or join our clan to unlock Tier 3 notifications! 💪"
                    )
                except Exception:
                    pass
                return

        # Toggle
        if role in member.roles:
            await member.remove_roles(role)
        else:
            await member.add_roles(role)

        await self._remove_reaction(payload)

    # ── /clean_autorole_reactions ─────────────────────────────

    @app_commands.command(
        name="clean_autorole_reactions",
        description="Remove all user reactions from the autorole message.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def clean_autorole_reactions(self, interaction: discord.Interaction):
        channel = interaction.guild.get_channel(TARGET_CHANNEL_ID)
        if not channel:
            return await interaction.response.send_message(
                embed=LilacEmbed.error("Channel not found"), ephemeral=True
            )
        try:
            msg = await channel.fetch_message(AUTOROLE_MESSAGE_ID)
        except Exception:
            return await interaction.response.send_message(
                embed=LilacEmbed.error("Message not found"), ephemeral=True
            )

        for reaction in msg.reactions:
            async for user in reaction.users():
                if user.id != BOT_ID and not user.bot:
                    try:
                        await msg.remove_reaction(reaction.emoji, user)
                    except Exception:
                        pass

        await interaction.response.send_message(
            embed=LilacEmbed.success("Reactions cleaned", "All user reactions have been removed."),
            ephemeral=True,
        )

    # ── /fix_autorole_reactions ───────────────────────────────

    @app_commands.command(
        name="fix_autorole_reactions",
        description="Reset autorole reactions: remove all and re-add bot reactions.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def fix_autorole_reactions(self, interaction: discord.Interaction):
        channel = interaction.guild.get_channel(TARGET_CHANNEL_ID)
        if not channel:
            return await interaction.response.send_message(
                embed=LilacEmbed.error("Channel not found"), ephemeral=True
            )
        try:
            msg = await channel.fetch_message(AUTOROLE_MESSAGE_ID)
        except Exception:
            return await interaction.response.send_message(
                embed=LilacEmbed.error("Message not found"), ephemeral=True
            )

        for reaction in msg.reactions:
            try:
                await reaction.clear()
            except Exception:
                pass
        for emoji in ("1️⃣", "2️⃣", "3️⃣"):
            try:
                await msg.add_reaction(emoji)
            except Exception:
                pass

        await interaction.response.send_message(
            embed=LilacEmbed.success("Reactions reset", "All reactions have been restored."),
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(SimpleReactionRoles(bot))
