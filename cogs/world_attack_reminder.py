import logging
import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime
from zoneinfo import ZoneInfo
import redis.asyncio as redis

from config import (
    GUILD_ID, LOG_CHANNEL_ID, WORLD_ATTACK_ROLE_ID, WORLD_ATTACK_TEXT, REDIS_URL,
)
from utils.embed_builder import LilacEmbed

log = logging.getLogger("cog-worldattack")

REDIS_KEY = "worldattack:disabled"


class WorldAttackReminder(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot  = bot
        self.redis = None
        self.task.start()

    async def cog_load(self):
        self.redis = redis.from_url(REDIS_URL, decode_responses=True)

    async def cog_unload(self):
        if self.redis:
            await self.redis.close()
        self.task.cancel()

    # ─────────────────────────────────────────────
    # /toggle-worldattack
    # ─────────────────────────────────────────────

    @app_commands.command(name="toggle-worldattack", description="Enable or disable your daily World Attack reminder.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def toggle_worldattack(self, interaction: discord.Interaction):
        uid      = str(interaction.user.id)
        disabled = await self.redis.sismember(REDIS_KEY, uid)

        if disabled:
            await self.redis.srem(REDIS_KEY, uid)
            await interaction.response.send_message(
                embed=LilacEmbed.success("Reminder enabled", "You will receive World Attack reminders again."),
                ephemeral=True,
            )
        else:
            await self.redis.sadd(REDIS_KEY, uid)
            await interaction.response.send_message(
                embed=LilacEmbed.info("Reminder disabled", "⏸️ You will no longer receive World Attack reminders."),
                ephemeral=True,
            )

    # ─────────────────────────────────────────────
    # /test-worldattack (admin)
    # ─────────────────────────────────────────────

    @app_commands.command(name="test-worldattack", description="Send a test World Attack reminder to everyone.")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def test_worldattack(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                embed=LilacEmbed.error("Access denied", "This command is reserved for admins."),
                ephemeral=True,
            )

        role = interaction.guild.get_role(WORLD_ATTACK_ROLE_ID)
        if not role:
            return await interaction.response.send_message(
                embed=LilacEmbed.error("Role not found", f"Role ID `{WORLD_ATTACK_ROLE_ID}` is missing."),
                ephemeral=True,
            )

        disabled = await self.redis.smembers(REDIS_KEY)
        sent, failed = 0, 0
        for member in role.members:
            if member.bot or str(member.id) in disabled:
                continue
            try:
                await member.send(WORLD_ATTACK_TEXT)
                sent += 1
            except Exception:
                failed += 1

        await interaction.response.send_message(
            embed=LilacEmbed.success(
                "Test reminder sent",
                f"✅ Delivered: **{sent}**\n❌ Failed: **{failed}**",
            ),
            ephemeral=True,
        )

    # ─────────────────────────────────────────────
    # /world-attack target:<word> (admin)
    # ─────────────────────────────────────────────

    @app_commands.command(name="world-attack", description="Send a world attack target to all role members.")
    @app_commands.describe(target="Element or boss to focus on")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def world_attack(self, interaction: discord.Interaction, target: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                embed=LilacEmbed.error("Access denied"), ephemeral=True
            )

        role = interaction.guild.get_role(WORLD_ATTACK_ROLE_ID)
        log_channel = interaction.guild.get_channel(LOG_CHANNEL_ID)
        if not role:
            return await interaction.response.send_message(
                embed=LilacEmbed.error("Role not found"), ephemeral=True
            )

        msg    = f"Hello, please concentrate all your world attack on the **{target}** boss!"
        sent   = 0
        failed = []

        for member in role.members:
            if member.bot:
                continue
            try:
                await member.send(msg)
                sent += 1
            except Exception:
                failed.append(f"{member.display_name} (`{member.id}`)")

        # Log to channel
        if log_channel:
            embed = LilacEmbed(
                title="⚔️  World Attack Broadcast",
                description=f"**Target:** {target}\n✅ Delivered: **{sent}**\n❌ Failed: **{len(failed)}**",
            )
            if failed:
                embed.add_field(
                    name="Failed deliveries",
                    value="\n".join(failed[:20]) + (f"\n…and {len(failed)-20} more" if len(failed) > 20 else ""),
                    inline=False,
                )
            await log_channel.send(embed=embed)

        await interaction.response.send_message(
            embed=LilacEmbed.success(
                "Broadcast complete",
                f"Target **{target}** sent to all members.\n✅ Delivered: **{sent}** | ❌ Failed: **{len(failed)}**",
            ),
            ephemeral=True,
        )

    # ─────────────────────────────────────────────
    # Background task — runs every minute
    # ─────────────────────────────────────────────

    @tasks.loop(minutes=1)
    async def task(self):
        now = datetime.now(ZoneInfo("Europe/Paris"))
        if now.weekday() > 4:  # Saturday / Sunday
            return
        if now.hour == 1 and now.minute == 0:
            await self.send_reminders()

    @task.before_loop
    async def before_task(self):
        await self.bot.wait_until_ready()

    async def send_reminders(self):
        guild = self.bot.get_guild(GUILD_ID)
        if not guild:
            return

        log_channel = guild.get_channel(LOG_CHANNEL_ID)
        role        = guild.get_role(WORLD_ATTACK_ROLE_ID)
        if not role:
            if log_channel:
                await log_channel.send(embed=LilacEmbed.error("Role not found", f"ID `{WORLD_ATTACK_ROLE_ID}`"))
            return

        disabled = await self.redis.smembers(REDIS_KEY)
        sent, fail_list = 0, []

        for member in role.members:
            if member.bot or str(member.id) in disabled:
                continue
            try:
                await member.send(WORLD_ATTACK_TEXT)
                sent += 1
            except Exception as e:
                fail_list.append(f"{member.display_name}: {e}")

        if log_channel:
            embed = LilacEmbed.success(
                "World Attack reminders sent",
                f"✅ Delivered: **{sent}** | ❌ Failed: **{len(fail_list)}**",
            )
            await log_channel.send(embed=embed)
        log.info("⚔️ World Attack reminders: %s sent, %s failed", sent, len(fail_list))


async def setup(bot: commands.Bot):
    await bot.add_cog(WorldAttackReminder(bot))
    log.info("⚙️ WorldAttackReminder cog loaded")
