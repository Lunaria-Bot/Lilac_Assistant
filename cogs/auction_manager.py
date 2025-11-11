import os
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timedelta
import logging

log = logging.getLogger("cog-auction-manager")

GUILD_ID = int(os.getenv("GUILD_ID", "0"))
BID_FORWARD_CHANNEL_ID = 1333042802405408789

FORUM_IDS = {
    "Common": 1304507540645740666,
    "Rare": 1304507516423766098,
    "SR": 1304536219677626442,
    "SSR": 1304502617472503908,
    "UR": 1304052056109350922,
    "CM": 1395405043431116871,
}

ALLOWED_ROLE_IDS = {
    1305252546608365599,
    1296831373599965296,
    1334130181073539192,
    1304102244462886982,
}

ACCEPT_KEYWORDS = {"accept", "accepted", "accepté", "accepter", "ok", "confirm"}

class JumpButton(discord.ui.View):
    def __init__(self, url: str):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(label="Jump to the message", url=url))

class AuctionManager(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="auction-end", description="Lock all auction threads from yesterday and remove active tags")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def auction_end(self, interaction: discord.Interaction):
        # Vérifie les rôles autorisés
        if not any(role.id in ALLOWED_ROLE_IDS for role in interaction.user.roles):
            await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        yesterday = datetime.utcnow() - timedelta(days=1)

        locked = 0
        for name, forum_id in FORUM_IDS.items():
            forum = guild.get_channel(forum_id)
            if not isinstance(forum, discord.ForumChannel):
                continue

            for thread in forum.threads:
                if thread.locked:
                    continue
                if thread.created_at.date() != yesterday.date():
                    continue

                # Remove "active" tag if present
                active_tag = discord.utils.find(lambda t: t.name.lower() == "active", forum.available_tags)
                if active_tag and active_tag in thread.applied_tags:
                    new_tags = [t for t in thread.applied_tags if t != active_tag]
                    await thread.edit(applied_tags=new_tags)

                await thread.edit(locked=True)
                locked += 1

        await interaction.followup.send(f"🔒 Locked {locked} auction threads from yesterday.", ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None or message.channel is None:
            return
        if message.channel.guild.id != GUILD_ID:
            return
        if not isinstance(message.channel, discord.Thread):
            return
        if message.channel.parent_id not in FORUM_IDS.values():
            return

        # Format du timestamp
        timestamp = message.created_at.strftime("%-m/%-d/%Y %-I:%M %p") if os.name != "nt" else message.created_at.strftime("%m/%d/%Y %I:%M %p")

        # Auteur du thread (fallback si fetch échoue)
        try:
            thread_owner_msg = await message.channel.fetch_message(message.channel.id)
            author_id = thread_owner_msg.author.id
            author_tag = thread_owner_msg.author.mention
        except Exception:
            author_id = message.channel.owner_id or 0
            author_tag = f"<@{author_id}>"

        thread_title = message.channel.name
        content = message.content.strip() or "*No content*"

        embed = discord.Embed(
            description=(
                f"💬 {message.author.display_name} {timestamp}\n"
                f"{content}\n"
                f"🔮 {thread_title}\n"
                f"Message: {message.id} | Author: {author_id} ({author_tag})"
            ),
            color=discord.Color.blurple()
        )

        view = JumpButton(url=message.jump_url)
        forward_channel = message.guild.get_channel(BID_FORWARD_CHANNEL_ID)
        if forward_channel:
            await forward_channel.send(embed=embed, view=view)

        # Check for acceptance
        lowered = message.content.lower()
        if any(word in lowered for word in ACCEPT_KEYWORDS):
            if not message.channel.locked:
                await message.channel.send(
                    "✅ This auction has been accepted please proceed with the trade <:vei_drink:1298164325302931456>"
                )
                await message.channel.edit(locked=True)
                log.info("🔒 Auction thread accepted and locked: %s", message.channel.name)

async def setup(bot: commands.Bot):
    await bot.add_cog(AuctionManager(bot))
    log.info("⚙️ AuctionManager cog loaded")
