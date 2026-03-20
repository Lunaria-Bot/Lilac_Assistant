import time
import logging
import discord
from discord import app_commands
from discord.ext import commands, tasks

from config import (
    GUILD_ID, HIGH_TIER_ROLE_ID, HIGH_TIER_COOLDOWN, REQUIRED_ROLE_ID,
    RARITY_EMOJIS, RARITY_CUSTOM_EMOJIS, RARITY_PRIORITY,
)
from utils.embed_builder import LilacEmbed

log = logging.getLogger("cog-high-tier")

RARITY_MESSAGES = {
    "SR":  "{emoji} **SR** has summoned — claim it!",
    "SSR": "{emoji} **SSR** has summoned — claim it!",
    "UR":  "{emoji} **UR** has summoned — grab it NOW!!",
}


class HighTier(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.triggered_messages: dict[int, float] = {}
        self.cleanup_triggered.start()

    def cog_unload(self):
        self.cleanup_triggered.cancel()

    # ─────────────────────────────────────────────
    # Cooldown helper
    # ─────────────────────────────────────────────

    async def check_cooldown(self, user_id: int) -> int:
        """Returns remaining cooldown in seconds (0 = ready)."""
        if not getattr(self.bot, "redis", None):
            return 0
        key = f"cooldown:high-tier:{user_id}"
        last_ts = await self.bot.redis.get(key)
        now = int(time.time())
        if last_ts:
            elapsed = now - int(last_ts)
            if elapsed < HIGH_TIER_COOLDOWN:
                return HIGH_TIER_COOLDOWN - elapsed
        await self.bot.redis.set(key, str(now))
        return 0

    # ─────────────────────────────────────────────
    # /high-tier
    # ─────────────────────────────────────────────

    @app_commands.command(name="high-tier", description="Get the High Tier role to be notified of rare spawns")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def high_tier(self, interaction: discord.Interaction):
        remaining = await self.check_cooldown(interaction.user.id)
        if remaining > 0:
            return await interaction.response.send_message(
                embed=LilacEmbed.warning("Cooldown", f"Please wait **{remaining}s** before using this again."),
                ephemeral=True,
            )

        required_role = interaction.guild.get_role(REQUIRED_ROLE_ID)
        if required_role and required_role not in interaction.user.roles:
            return await interaction.response.send_message(
                embed=LilacEmbed.error(
                    "Access denied",
                    f"Only {required_role.mention} members can use this feature "
                    f"<:lilac_pensivebread:1415672792522952725>",
                ),
                ephemeral=True,
            )

        role = interaction.guild.get_role(HIGH_TIER_ROLE_ID)
        if not role:
            return await interaction.response.send_message(
                embed=LilacEmbed.error("Role not found", "The High Tier role is missing."),
                ephemeral=True,
            )

        if role in interaction.user.roles:
            return await interaction.response.send_message(
                embed=LilacEmbed.info("Already subscribed", f"You already have {role.mention}."),
                ephemeral=True,
            )

        try:
            await interaction.user.add_roles(role, reason="User opted in for High Tier notifications")
            await interaction.response.send_message(
                embed=LilacEmbed.success(
                    "High Tier role granted!",
                    f"You now have {role.mention}. You will be pinged on rare spawns. 🔥",
                ),
                ephemeral=True,
            )
            log.info("🎖️ %s received High Tier role", interaction.user.display_name)
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=LilacEmbed.error("Permission error", "I don't have permission to assign this role."),
                ephemeral=True,
            )

    # ─────────────────────────────────────────────
    # /high-tier-remove
    # ─────────────────────────────────────────────

    @app_commands.command(name="high-tier-remove", description="Remove the High Tier role and stop notifications")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def high_tier_remove(self, interaction: discord.Interaction):
        remaining = await self.check_cooldown(interaction.user.id)
        if remaining > 0:
            return await interaction.response.send_message(
                embed=LilacEmbed.warning("Cooldown", f"Please wait **{remaining}s** before using this again."),
                ephemeral=True,
            )

        role = interaction.guild.get_role(HIGH_TIER_ROLE_ID)
        if not role:
            return await interaction.response.send_message(
                embed=LilacEmbed.error("Role not found"), ephemeral=True
            )

        if role not in interaction.user.roles:
            return await interaction.response.send_message(
                embed=LilacEmbed.info("Not subscribed", "You don't have the High Tier role."),
                ephemeral=True,
            )

        try:
            await interaction.user.remove_roles(role, reason="User opted out of High Tier notifications")
            await interaction.response.send_message(
                embed=LilacEmbed.success(
                    "Unsubscribed",
                    f"{role.mention} has been removed. You will no longer be notified.",
                ),
                ephemeral=True,
            )
            log.info("🚫 %s removed High Tier role", interaction.user.display_name)
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=LilacEmbed.error("Permission error"), ephemeral=True
            )

    # ─────────────────────────────────────────────
    # Cleanup task
    # ─────────────────────────────────────────────

    @tasks.loop(minutes=30)
    async def cleanup_triggered(self):
        cutoff = time.time() - 6 * 3600
        self.triggered_messages = {
            mid: ts for mid, ts in self.triggered_messages.items() if ts > cutoff
        }

    @cleanup_triggered.before_loop
    async def before_cleanup(self):
        await self.bot.wait_until_ready()

    # ─────────────────────────────────────────────
    # Listener — rare spawn ping
    # ─────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if not after.guild or not after.embeds:
            return
        if after.id in self.triggered_messages:
            return

        embed = after.embeds[0]
        title = (embed.title or "").lower()
        desc  = embed.description or ""

        if "auto summon" not in title:
            return

        found_rarity   = None
        highest_prio   = 0
        for emoji_id, rarity in RARITY_EMOJIS.items():
            if emoji_id in desc and RARITY_PRIORITY[rarity] > highest_prio:
                found_rarity = rarity
                highest_prio = RARITY_PRIORITY[rarity]

        if not found_rarity:
            return

        role = after.guild.get_role(HIGH_TIER_ROLE_ID)
        if not role:
            return

        self.triggered_messages[after.id] = time.time()
        custom_emoji = RARITY_CUSTOM_EMOJIS.get(found_rarity, "🌸")
        msg = RARITY_MESSAGES[found_rarity].format(emoji=custom_emoji)
        await after.channel.send(f"{msg}\n🔥 {role.mention}")


async def setup(bot: commands.Bot):
    await bot.add_cog(HighTier(bot))
    log.info("⚙️ HighTier cog loaded")
