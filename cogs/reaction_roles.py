import discord
from discord.ext import commands
from discord import app_commands

# Fixed autorole message ID (persists after restart)
MESSAGE_ID = 1460243538133520510

# Roles for each tier
ROLE_TIER_1 = 1439616771622572225
ROLE_TIER_2 = 1439616926170218669
ROLE_TIER_3 = 1439616971908972746

# Required roles for tier 3 (must have at least ONE)
REQUIRED_ROLES_FOR_T3 = {
    1295761591895064577,
    1450472679021740043,
    1297161626910462016
}

# Channel where the autorole message must be sent
TARGET_CHANNEL_ID = 1460226131830509662


class SimpleReactionRoles(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------------------------------------------------------
    # SLASH COMMAND: /sendautorole
    # ---------------------------------------------------------
    @app_commands.command(
        name="sendautorole",
        description="Send the autorole message in the configured channel."
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def sendautorole(self, interaction: discord.Interaction):

        channel = interaction.guild.get_channel(TARGET_CHANNEL_ID)
        if not channel:
            return await interaction.response.send_message(
                "Channel not found.", ephemeral=True
            )

        embed = discord.Embed(
            title="React to get pinged for specific tier boss spawns! 🤓",
            description=(
                f"**1️⃣ Ping Tier 1** — <@&{ROLE_TIER_1}>\n"
                f"**2️⃣ Ping Tier 2** — <@&{ROLE_TIER_2}>\n"
                f"**3️⃣ Ping Tier 3** — <@&{ROLE_TIER_3}>\n\n"
                "Choose your tier notifications!"
            ),
            color=0xf1c40f
        )

        msg = await channel.send(embed=embed)

        # Add reactions
        await msg.add_reaction("1️⃣")
        await msg.add_reaction("2️⃣")
        await msg.add_reaction("3️⃣")

        await interaction.response.send_message(
            f"Autorole message sent in <#{TARGET_CHANNEL_ID}>.\n"
            f"**Message ID is now fixed and persistent.**",
            ephemeral=True
        )

    # ---------------------------------------------------------
    # ADD ROLE
    # ---------------------------------------------------------
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.message_id != MESSAGE_ID:
            return

        if payload.user_id == self.bot.user.id:
            return

        guild = self.bot.get_guild(payload.guild_id)
        member = guild.get_member(payload.user_id)
        emoji = str(payload.emoji)

        # Tier 1
        if emoji == "1️⃣":
            role = guild.get_role(ROLE_TIER_1)
            await member.add_roles(role)
            return

        # Tier 2
        if emoji == "2️⃣":
            role = guild.get_role(ROLE_TIER_2)
            await member.add_roles(role)
            return

        # Tier 3 (requires roles)
        if emoji == "3️⃣":

            # Check if member has at least ONE required role
            has_required = any(role.id in REQUIRED_ROLES_FOR_T3 for role in member.roles)

            if not has_required:
                # Remove reaction immediately
                channel = guild.get_channel(payload.channel_id)
                msg = await channel.fetch_message(payload.message_id)
                await msg.remove_reaction("3️⃣", member)

                # DM user
                try:
                    await member.send("Keep grinding nub or join our clan to be strong")
                except:
                    pass

                return

            # User has required roles → give Tier 3
            role = guild.get_role(ROLE_TIER_3)
            await member.add_roles(role)
            return

    # ---------------------------------------------------------
    # REMOVE ROLE
    # ---------------------------------------------------------
    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if payload.message_id != MESSAGE_ID:
            return

        guild = self.bot.get_guild(payload.guild_id)
        member = guild.get_member(payload.user_id)
        emoji = str(payload.emoji)

        if emoji == "1️⃣":
            role = guild.get_role(ROLE_TIER_1)
            await member.remove_roles(role)

        elif emoji == "2️⃣":
            role = guild.get_role(ROLE_TIER_2)
            await member.remove_roles(role)

        elif emoji == "3️⃣":
            role = guild.get_role(ROLE_TIER_3)
            await member.remove_roles(role)


async def setup(bot: commands.Bot):
    await bot.add_cog(SimpleReactionRoles(bot))
