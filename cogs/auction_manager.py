import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timedelta, timezone
import asyncio
import logging

from config import GUILD_ID, BID_FORWARD_CHANNEL_ID, FORUM_IDS, ALLOWED_ROLE_IDS, ACTIVE_TAG_IDS
from utils.embed_builder import LilacEmbed

log = logging.getLogger("cog-auction-manager")

ACCEPT_KEYWORDS = {"accept", "accepted", "accepté", "accepter", "ok", "confirm"}


class JumpButton(discord.ui.View):
    def __init__(self, url: str):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(label="Jump to message", url=url, style=discord.ButtonStyle.link))


class AuctionManager(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.accepted_threads: set[int] = set()
        self._thread_locks: dict[int, asyncio.Lock] = {}

    def _get_lock(self, thread_id: int) -> asyncio.Lock:
        if thread_id not in self._thread_locks:
            self._thread_locks[thread_id] = asyncio.Lock()
        return self._thread_locks[thread_id]

    # ─────────────────────────────────────────────
    # /auction-end
    # ─────────────────────────────────────────────

    @app_commands.command(name="auction-end", description="Lock threads older than 20h with active tag")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def auction_end(self, interaction: discord.Interaction):
        if not any(role.id in ALLOWED_ROLE_IDS for role in interaction.user.roles):
            return await interaction.response.send_message(
                embed=LilacEmbed.error("Access denied", "You don't have permission to use this command."),
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)

        guild  = interaction.guild
        cutoff = datetime.now(timezone.utc) - timedelta(hours=20)
        locked = 0

        try:
            for name, forum_id in FORUM_IDS.items():
                forum = guild.get_channel(forum_id)
                if not isinstance(forum, discord.ForumChannel):
                    continue
                for thread in forum.threads:
                    if thread.locked or thread.created_at is None:
                        continue
                    if not any(t.id in ACTIVE_TAG_IDS for t in thread.applied_tags):
                        continue
                    if thread.created_at < cutoff:
                        new_tags = [t for t in thread.applied_tags if t.id not in ACTIVE_TAG_IDS]
                        await thread.edit(applied_tags=new_tags, locked=True)
                        locked += 1
                        log.info("🔒 Locked thread: %s", thread.name)

            await interaction.followup.send(
                embed=LilacEmbed.success(
                    "Auction-end complete",
                    f"🔒 Locked **{locked}** thread(s) with active tag older than 20h.",
                ),
                ephemeral=True,
            )
        except Exception as e:
            log.exception("❌ Error in /auction-end: %s", e)
            await interaction.followup.send(
                embed=LilacEmbed.error("Error", "An unexpected error occurred."),
                ephemeral=True,
            )

    # ─────────────────────────────────────────────
    # Bid forwarding + accept detection
    # ─────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or not isinstance(message.channel, discord.Thread):
            return
        if message.channel.guild.id != GUILD_ID:
            return
        if message.channel.parent_id not in FORUM_IDS.values():
            return

        # ── Forward bid embed ─────────────────────
        utc_minus_2 = timezone(timedelta(hours=-2))
        local_time  = message.created_at.astimezone(utc_minus_2)

        # Detect rarity from thread name for colour theming
        thread_name_lower = message.channel.name.lower()
        if "ur" in thread_name_lower:
            color = 0xFF4500   # orange-red for UR
        elif "ssr" in thread_name_lower:
            color = 0xC8A2C8   # lilac for SSR
        elif "sr" in thread_name_lower:
            color = 0x5865F2   # blurple for SR
        elif "rare" in thread_name_lower:
            color = 0x57F287   # green for Rare
        else:
            color = 0xFFD700   # gold default

        bid_content = message.content.strip() or "*No content*"

        embed = discord.Embed(color=color, timestamp=message.created_at)

        # Author line: avatar + name + ID
        embed.set_author(
            name=message.author.display_name,
            icon_url=message.author.display_avatar.url,
        )

        # Main bid amount front and centre
        embed.add_field(
            name="💰  Bid",
            value=f"```{bid_content}```",
            inline=False,
        )

        # Thread and time side by side
        embed.add_field(
            name="🧵  Thread",
            value=message.channel.name,
            inline=True,
        )
        embed.add_field(
            name="🕒  Time (UTC−2)",
            value=local_time.strftime("%d/%m/%Y  %H:%M"),
            inline=True,
        )

        # User ID subtly in footer
        embed.set_footer(
            text=f"User ID: {message.author.id}",
            icon_url=message.author.display_avatar.url,
        )

        forward_channel = message.guild.get_channel(BID_FORWARD_CHANNEL_ID)
        if forward_channel:
            await forward_channel.send(embed=embed, view=JumpButton(url=message.jump_url))

        # ── Accept detection ──────────────────────
        if any(w in message.content.lower() for w in ACCEPT_KEYWORDS):
            if message.channel.locked or message.channel.id in self.accepted_threads:
                return
            async with self._get_lock(message.channel.id):
                if message.channel.locked or message.channel.id in self.accepted_threads:
                    return
                new_tags = [t for t in message.channel.applied_tags if t.id not in ACTIVE_TAG_IDS]
                await message.channel.edit(applied_tags=new_tags)
                await message.channel.send(
                    "✅ This auction has been accepted — please proceed with the trade! "
                    "<:vei_drink:1298164325302931456>"
                )
                await message.channel.edit(locked=True)
                self.accepted_threads.add(message.channel.id)
                log.info("🔒 Auction accepted & locked: %s", message.channel.name)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if after.channel.id not in self.accepted_threads:
            await self.on_message(after)


async def setup(bot: commands.Bot):
    await bot.add_cog(AuctionManager(bot))
    log.info("⚙️ AuctionManager cog loaded")
