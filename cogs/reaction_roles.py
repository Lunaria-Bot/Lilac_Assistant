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

# Bot ID (Minah)
BOT_ID = 1421466719678894280


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
    # Helper: remove the user's reaction after giving/removing the role
    # ---------------------------------------------------------
    async def remove_user_reaction(self, payload):
        guild = self.bot.get_guild(payload.guild_id)
        channel = guild.get_channel(payload.channel_id)
        msg = await channel.fetch_message(payload.message_id)

        try:
            await msg.remove_reaction(payload.emoji, payload.member)
        except:
            pass

    # ---------------------------------------------------------
    # ADD ROLE / REMOVE ROLE (TOGGLE)
    # ---------------------------------------------------------
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.message_id != MESSAGE_ID:
            return

        if payload.user_id == BOT_ID:
            return  # Ignore bot reactions

        guild = self.bot.get_guild(payload.guild_id)
        member = guild.get_member(payload.user_id)
        emoji = str(payload.emoji)

        # -------------------------
        # TIER 1
        # -------------------------
        if emoji == "1️⃣":
            role = guild.get_role(ROLE_TIER_1)

            if role in member.roles:
                await member.remove_roles(role)
                await self.remove_user_reaction(payload)
                return

            await member.add_roles(role)
            await self.remove_user_reaction(payload)
            return

        # -------------------------
        # TIER 2
        # -------------------------
        if emoji == "2️⃣":
            role = guild.get_role(ROLE_TIER_2)

            if role in member.roles:
                await member.remove_roles(role)
                await self.remove_user_reaction(payload)
                return

            await member.add_roles(role)
            await self.remove_user_reaction(payload)
            return

        # -------------------------
        # TIER 3 (requires roles)
        # -------------------------
        if emoji == "3️⃣":
            role = guild.get_role(ROLE_TIER_3)

            # Toggle OFF
            if role in member.roles:
                await member.remove_roles(role)
                await self.remove_user_reaction(payload)
                return

            # Check requirements
            has_required = any(r.id in REQUIRED_ROLES_FOR_T3 for r in member.roles)

            if not has_required:
                channel = guild.get_channel(payload.channel_id)
                msg = await channel.fetch_message(payload.message_id)
                await msg.remove_reaction("3️⃣", member)

                try:
                    await member.send("Keep grinding nub or join our clan to be strong")
                except:
                    pass

                return

            # Toggle ON
            await member.add_roles(role)
            await self.remove_user_reaction(payload)
            return

    # ---------------------------------------------------------
    # CLEAN COMMAND
    # ---------------------------------------------------------
    @app_commands.command(
        name="clean_autorole_reactions",
        description="Remove all user reactions from the autorole message, keeping only the bot's."
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def clean_autorole_reactions(self, interaction: discord.Interaction):

        guild = interaction.guild
        channel = guild.get_channel(TARGET_CHANNEL_ID)

        if not channel:
            return await interaction.response.send_message(
                "Autorole channel not found.", ephemeral=True
            )

        try:
            msg = await channel.fetch_message(MESSAGE_ID)
        except:
            return await interaction.response.send_message(
                "Autorole message not found.", ephemeral=True
            )

        # Remove all non-bot reactions
        for reaction in msg.reactions:
            async for user in reaction.users():
                if user.id != BOT_ID and not user.bot:
                    try:
                        await msg.remove_reaction(reaction.emoji, user)
                    except:
                        pass

        await interaction.response.send_message(
            "All user reactions have been removed from the autorole message.",
            ephemeral=True
        )

    # ---------------------------------------------------------
    # FIX COMMAND — restore bot reactions
    # ---------------------------------------------------------
    @app_commands.command(
        name="fix_autorole_reactions",
        description="Ensure the autorole message has the bot's reactions (1️⃣, 2️⃣, 3️⃣)."
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def fix_autorole_reactions(self, interaction: discord.Interaction):

        guild = interaction.guild
        channel = guild.get_channel(TARGET_CHANNEL_ID)

        if not channel:
            return await interaction.response.send_message(
                "Autorole channel not found.", ephemeral=True
            )

        try:
            msg = await channel.fetch_message(MESSAGE_ID)
        except:
            return await interaction.response.send_message(
                "Autorole message not found.", ephemeral=True
            )

        required_emojis = ["1️⃣", "2️⃣", "3️⃣"]
        existing_bot_reactions = set()

        # Detect bot reactions
        for reaction in msg.reactions:
            async for user in reaction.users():
                if user.id == BOT_ID:
                    existing_bot_reactions.add(str(reaction.emoji))

        # Add missing reactions
        added = []
        for emoji in required_emojis:
            if emoji not in existing_bot_reactions:
                try:
                    await msg.add_reaction(emoji)
                    added.append(emoji)
                except:
                    pass

        if added:
            await interaction.response.send_message(
                f"Missing reactions restored: {' '.join(added)}",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "All bot reactions are already present.",
                ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(SimpleReactionRoles(bot))
