import discord
from discord.ext import commands
from discord import app_commands

# Roles required to keep Tier 3
REQUIRED_ROLES = {
    1450472679021740043,
    1297161587744047106
}

# Tier 3 role to remove
ROLE_TIER_3 = 1439616971908972746

# Log channel
LOG_CHANNEL_ID = 1421465080238964796


class LuviChecker(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------------------------------------------------------
    # SLASH COMMAND: /luvi_check
    # ---------------------------------------------------------
    @app_commands.command(
        name="luvi_check",
        description="Remove Tier 3 ping from users who do not meet the requirements."
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def luvi_check(self, interaction: discord.Interaction):

        await interaction.response.send_message(
            "Checking members... This may take a few seconds.",
            ephemeral=True
        )

        guild = interaction.guild
        log_channel = guild.get_channel(LOG_CHANNEL_ID)
        removed_users = []

        role_t3 = guild.get_role(ROLE_TIER_3)

        # Loop through all members
        for member in guild.members:
            if role_t3 not in member.roles:
                continue  # skip users who don't have Tier 3

            # Check if member has at least one required role
            has_required = any(r.id in REQUIRED_ROLES for r in member.roles)

            if not has_required:
                # Remove Tier 3
                try:
                    await member.remove_roles(role_t3, reason="Failed Luvi check")
                    removed_users.append(member)
                except:
                    pass

        # ---------------------------------------------------------
        # LOGGING — SPLIT INTO CHUNKS OF 25
        # ---------------------------------------------------------
        if removed_users:
            chunk_size = 25
            chunks = [removed_users[i:i + chunk_size] for i in range(0, len(removed_users), chunk_size)]

            for index, chunk in enumerate(chunks, start=1):
                embed = discord.Embed(
                    title=f"Luvi Check — Removed Tier 3 (Page {index}/{len(chunks)})",
                    description="Users who lost Tier 3 due to missing required roles:",
                    color=0xe74c3c
                )

                for user in chunk:
                    embed.add_field(
                        name=user.display_name,
                        value=f"ID: {user.id}",
                        inline=False
                    )

                await log_channel.send(embed=embed)

        else:
            await log_channel.send(
                embed=discord.Embed(
                    title="Luvi Check",
                    description="No users were removed. All Tier 3 holders meet the requirements.",
                    color=0x2ecc71
                )
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(LuviChecker(bot))
