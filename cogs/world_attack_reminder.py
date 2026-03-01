import logging
import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime
from zoneinfo import ZoneInfo
import redis.asyncio as redis

log = logging.getLogger("cog-worldattack")

GUILD_ID = 1293611593845706793
LOG_CHANNEL_ID = 1421465080238964796
ROLE_ID = 1450472679021740043

REMINDER_TEXT = "Hey Guild Member of Lilac, do not forget to do your world attack!"

REDIS_URL = "redis://default:WEQfFAaMkvNPFvEzOpAQsGdDTTbaFzOr@redis-436594b0.railway.internal:6379"
REDIS_KEY = "worldattack:disabled"  # Redis set of opted‑out users


class WorldAttackReminder(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.redis = None
        self.task.start()

    async def cog_load(self):
        self.redis = redis.from_url(REDIS_URL, decode_responses=True)

    async def cog_unload(self):
        if self.redis:
            await self.redis.close()
        self.task.cancel()

    # ---------------------------------------------------------
    # /toggle-worldattack
    # ---------------------------------------------------------
    @app_commands.command(
        name="toggle-worldattack",
        description="Enable or disable your daily World Attack reminder."
    )
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def toggle_worldattack(self, interaction: discord.Interaction):

        uid = str(interaction.user.id)
        disabled = await self.redis.sismember(REDIS_KEY, uid)

        if disabled:
            await self.redis.srem(REDIS_KEY, uid)
            await interaction.response.send_message(
                "✅ Your World Attack reminder is now enabled.",
                ephemeral=True
            )
        else:
            await self.redis.sadd(REDIS_KEY, uid)
            await interaction.response.send_message(
                "❌ Your World Attack reminder is now disabled.",
                ephemeral=True
            )

    # ---------------------------------------------------------
    # /test-worldattack (admin)
    # Sends reminder to EVERYONE with the role (respecting opt‑out)
    # ---------------------------------------------------------
    @app_commands.command(
        name="test-worldattack",
        description="Send a test World Attack reminder to everyone with the role."
    )
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def test_worldattack(self, interaction: discord.Interaction):

        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "⛔ You do not have permission to use this command.",
                ephemeral=True
            )
            return

        guild = interaction.guild
        role = guild.get_role(ROLE_ID)

        if not role:
            await interaction.response.send_message(
                f"❌ Role {ROLE_ID} not found.",
                ephemeral=True
            )
            return

        disabled = await self.redis.smembers(REDIS_KEY)
        sent = 0
        failed = 0

        for member in role.members:
            if member.bot:
                continue

            if str(member.id) in disabled:
                continue

            try:
                await member.send(REMINDER_TEXT)
                sent += 1
            except Exception:
                failed += 1

        await interaction.response.send_message(
            f"📨 Test reminder sent to all role members.\n"
            f"✅ Delivered: {sent}\n"
            f"❌ Failed: {failed}",
            ephemeral=True
        )

    # ---------------------------------------------------------
    # /world-attack target:<word>
    # DM ALL role users with a custom target (ignores opt‑out)
    # ---------------------------------------------------------
    @app_commands.command(
        name="world-attack",
        description="Send a world attack target message to all role members."
    )
    @app_commands.describe(target="Element or target to focus on")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def world_attack(self, interaction: discord.Interaction, target: str):

        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "⛔ You do not have permission to use this command.",
                ephemeral=True
            )
            return

        guild = interaction.guild
        role = guild.get_role(ROLE_ID)
        log_channel = guild.get_channel(LOG_CHANNEL_ID)

        if not role:
            await interaction.response.send_message(
                f"❌ Role {ROLE_ID} not found.",
                ephemeral=True
            )
            return

        msg = f"Hello, do please concentrate all your world attack to {target} Boss"

        sent = 0
        failed = 0

        for member in role.members:
            if member.bot:
                continue

            try:
                await member.send(msg)
                sent += 1
            except Exception:
                failed += 1

        if log_channel:
            await log_channel.send(
                f"[WorldAttack] Target broadcast: **{target}**\n"
                f"✅ Delivered: {sent} | ❌ Failed: {failed}"
            )

        await interaction.response.send_message(
            f"📨 Target **{target}** broadcast to all role members.\n"
            f"✅ Delivered: {sent}\n"
            f"❌ Failed: {failed}",
            ephemeral=True
        )

    # ---------------------------------------------------------
    # Background task — runs every minute
    # ---------------------------------------------------------
    @tasks.loop(minutes=1)
    async def task(self):
        now = datetime.now(ZoneInfo("Europe/Paris"))

        # Monday=0, Friday=4
        if now.weekday() > 4:
            return

        if now.hour == 1 and now.minute == 0:
            await self.send_reminders()

    @task.before_loop
    async def before_task(self):
        await self.bot.wait_until_ready()

    # ---------------------------------------------------------
    # Send reminders
    # ---------------------------------------------------------
    async def send_reminders(self):
        guild = self.bot.get_guild(GUILD_ID)
        if not guild:
            return

        log_channel = guild.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send("[WorldAttack] Starting reminder dispatch...")

        role = guild.get_role(ROLE_ID)
        if not role:
            if log_channel:
                await log_channel.send(f"[WorldAttack] Role {ROLE_ID} not found.")
            return

        disabled = await self.redis.smembers(REDIS_KEY)

        for member in role.members:
            if member.bot:
                continue

            if str(member.id) in disabled:
                if log_channel:
                    await log_channel.send(f"[WorldAttack] Skipped {member} (opted out).")
                continue

            try:
                await member.send(REMINDER_TEXT)
                if log_channel:
                    await log_channel.send(f"[WorldAttack] DM sent to {member}.")
            except Exception as e:
                if log_channel:
                    await log_channel.send(f"[WorldAttack] Failed to DM {member}: {e}")

        if log_channel:
            await log_channel.send("[WorldAttack] Reminder dispatch completed.")


async def setup(bot: commands.Bot):
    await bot.add_cog(WorldAttackReminder(bot))
    log.info("⚙️ WorldAttackReminder cog loaded (Redis mode)")
