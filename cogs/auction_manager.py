import os
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timedelta, timezone
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

ACTIVE_TAG_ID = 1395407621544087583
ACCEPT_KEYWORDS = {"accept", "accepted", "accepté", "accepter", "ok", "confirm"}

class JumpButton(discord.ui.View):
    def __init__(self, url: str):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(label="Jump to the message", url=url))

class AuctionManager(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.accepted_threads = set()

    @app_commands.command(name="auction-end", description="Lock all auction threads older than 20h and remove active tag")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def auction_end(self, interaction: discord.Interaction):
        if not any(role.id in ALLOWED_ROLE_IDS for role in interaction.user.roles):
            await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        cutoff = datetime.utcnow() - timedelta(hours=20)

        locked = 0
        for name, forum_id in FORUM_IDS.items():
            forum = guild.get_channel(forum_id)
            if not isinstance(forum, discord.ForumChannel):
                continue

            for thread in forum.threads:
                if thread.locked or thread.created_at > cutoff:
                    continue

                active_tag = discord.utils.find(lambda t: t.id == ACTIVE_TAG_ID, forum.available_tags)
                if active_tag and active_tag in thread.applied_tags:
                    new_tags = [t for t in thread.applied_tags if t.id != ACTIVE_TAG_ID]
                    await thread.edit(applied_tags=new_tags)

                await thread.edit(locked=True)
                locked += 1

        await interaction.followup.send(f"🔒 Locked {locked} auction threads older than 20h.", ephemeral=True)

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

        user = message.author
        avatar_url = user.display_avatar.url
        user_id = user.id
        thread_name = message.channel.name
        content = message.content.strip() or "*No content*"

        utc_minus_2 = timezone(timedelta(hours=-2))
        local_time = message.created_at.astimezone(utc_minus_2)
        timestamp_str = local_time.strftime("%d/%m/%Y %H:%M")

        embed = discord.Embed(
            title=f"📨 Bid in {thread_name}",
            description=content,
            color=discord.Color.gold(),
            timestamp=message.created_at
        )
        embed.set_author(name=f"{user.display_name} ({user_id})", icon_url=avatar_url)
        embed.add_field(name="🕒 Time (UTC−2)", value=timestamp_str, inline=True)
        embed.set_footer(text=f"Thread: {thread_name}")

        view = JumpButton(url=message.jump_url)
        forward_channel = message.guild.get_channel(BID_FORWARD_CHANNEL_ID)
        if forward_channel:
            await forward_channel.send(embed=embed, view=view)

        lowered = message.content.lower()
        if any(word in lowered for word in ACCEPT_KEYWORDS):
            if message.channel.locked or message.channel.id in self.accepted_threads:
                return

            forum = message.guild.get_channel(message.channel.parent_id)
            active_tag = discord.utils.find(lambda t: t.id == ACTIVE_TAG_ID, forum.available_tags)
            if active_tag and active_tag in message.channel.applied_tags:
                new_tags = [t for t in message.channel.applied_tags if t.id != ACTIVE_TAG_ID]
                await message.channel.edit(applied_tags=new_tags)

            await message.channel.send(
                "✅ This auction has been accepted please proceed with the trade <:vei_drink:1298164325302931456>"
            )
            await message.channel.edit(locked=True)
            self.accepted_threads.add(message.channel.id)
            log.info("🔒 Auction thread accepted and locked: %s", message.channel.name)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if after.channel.id in self.accepted_threads:
            return
        await self.on_message(after)

async def setup(bot: commands.Bot):
    await bot.add_cog(AuctionManager(bot))
    log.info("⚙️ AuctionManager cog loaded")
