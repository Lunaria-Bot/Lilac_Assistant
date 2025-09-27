import os
import time
import logging
import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger("cog-high-tier")

GUILD_ID = int(os.getenv("GUILD_ID", "0"))
HIGH_TIER_ROLE_ID = int(os.getenv("HIGH_TIER_ROLE_ID", "0"))
HIGH_TIER_COOLDOWN = int(os.getenv("HIGH_TIER_COOLDOWN", "300"))  # default 5 min

# Emoji IDs mapped to rarities
RARITY_EMOJIS = {
    "1342202597389373530": "SR",
    "1342202212948115510": "SSR",
    "1342202203515125801": "UR",
}

RARITY_MESSAGES = {
    "SR":  "🌸 A Super Rare Flower just bloomed! Catch it!",
    "SSR": "🌸 A Super Super Rare Flower just bloomed! Catch it!",
    "UR":  "🌸 An Ultra Rare Flower just bloomed! Grab it!",
}

# Define rarity priority (higher index = higher priority)
RARITY_PRIORITY = {"SR": 1, "SSR": 2, "UR": 3}

class HighTier(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def check_cooldown(self, user_id: int) -> int:
        """Check Redis for cooldown. Returns remaining seconds if still on cooldown, else 0."""
        if not getattr(self.bot, "redis", None):
            return 0  # fallback: no cooldown if Redis not connected

        key = f"cooldown:high-tier:{user_id}"
        last_ts = await self.bot.redis.get(key)
        now = int(time.time())

        if last_ts:
            elapsed = now - int(last_ts)
            if elapsed < HIGH_TIER_COOLDOWN:
                return HIGH_TIER_COOLDOWN - elapsed

        # Not on cooldown → update timestamp
        await self.bot.redis.set(key, str(now))
        return 0

    # --- Slash command to self-assign High Tier role ---
    @app_commands.command(name="high-tier", description="Get the High Tier role to be notified of rare flowers")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def high_tier(self, interaction: discord.Interaction):
        remaining = await self.check_cooldown(interaction.user.id)
        if remaining > 0:
            await interaction.response.send_message(
                f"⏳ You must wait {remaining}s before using this command again.",
                ephemeral=True
            )
            return

        role = interaction.guild.get_role(HIGH_TIER_ROLE_ID)
        if not role:
            await interaction.response.send_message("❌ High Tier role not found.", ephemeral=True)
            return

        member = interaction.user
        if role in member.roles:
            await interaction.response.send_message("✅ You already have the High Tier role.", ephemeral=True)
            return

        try:
            await member.add_roles(role, reason="User opted in for High Tier notifications")
            await interaction.response.send_message(
                f"You just got the {role.mention}. You will be notified now.",
                ephemeral=True
            )
            log.info("🎖️ %s received High Tier role", member.display_name)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Missing permissions to assign the role.", ephemeral=True)

    # --- Slash command to remove High Tier role ---
    @app_commands.command(name="high-tier-remove", description="Remove the High Tier role and stop notifications")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def high_tier_remove(self, interaction: discord.Interaction):
        remaining = await self.check_cooldown(interaction.user.id)
        if remaining > 0:
            await interaction.response.send_message(
                f"⏳ You must wait {remaining}s before using this command again.",
                ephemeral=True
            )
            return

        role = interaction.guild.get_role(HIGH_TIER_ROLE_ID)
        if not role:
            await interaction.response.send_message("❌ High Tier role not found.", ephemeral=True)
            return

        member = interaction.user
        if role not in member.roles:
            await interaction.response.send_message("ℹ️ You don’t have the High Tier role.", ephemeral=True)
            return

        try:
            await member.remove_roles(role, reason="User opted out of High Tier notifications")
            await interaction.response.send_message(
                f"✅ The {role.mention} has been removed. You will no longer be notified.",
                ephemeral=True
            )
            log.info("🚫 %s removed High Tier role", member.display_name)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Missing permissions to remove the role.", ephemeral=True)

    # --- Listener: detect AUTO Summon embeds with rarity emojis ---
    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if not after.guild or not after.embeds:
            return

        embed = after.embeds[0]
        desc = (embed.description or "")

        found_rarity = None
        highest_priority = 0

        # Look for emoji IDs in the embed description
        for emoji_id, rarity in RARITY_EMOJIS.items():
            if str(emoji_id) in desc:
                if RARITY_PRIORITY[rarity] > highest_priority:
                    found_rarity = rarity
                    highest_priority = RARITY_PRIORITY[rarity]

        if found_rarity:
            role = after.guild.get_role(HIGH_TIER_ROLE_ID)
            if role:
                msg = RARITY_MESSAGES.get(found_rarity, f"A {found_rarity} flower appeared!")
                await after.channel.send(f"{msg}\n🔥 {role.mention}")
                log.info("🌸 High Tier ping sent once for rarity %s in %s", found_rarity, after.channel.name)


async def setup(bot: commands.Bot):
    await bot.add_cog(HighTier(bot))
