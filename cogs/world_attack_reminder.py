import logging
import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, time
from zoneinfo import ZoneInfo
import json
import os

log = logging.getLogger("cog-worldattack")

GUILD_ID = 1293611593845706793  # your server ID
LOG_CHANNEL_ID = 1421465080238964796
ROLE_ID = 1450472679021740043

REMINDER_TEXT = "Hey Guild Member of Lilac, do not forget to do your world attack!"
SETTINGS_FILE = "world_attack_settings.json"


# -----------------------------
# Load / Save JSON
# -----------------------------
def load_settings():
    if not os.path.exists(SETTINGS_FILE):
        return {"disabled": []}
    with open(SETTINGS_FILE, "r") as f:
        return json.load(f)


def save_settings(data):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(data, f, indent=4)


class WorldAttackReminder(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.settings = load_settings()
        self.task.start()

    def cog_unload(self):
        self.task.cancel()

    # -----------------------------
    # /toggle-worldattack
    # -----------------------------
    @app_commands.command(
        name="toggle-worldattack",
        description="Enable or disable your daily World Attack reminder."
    )
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def toggle_worldattack(self, interaction: discord.Interaction):

        uid = interaction.user.id

        if uid in self.settings["disabled"]:
            self.settings["disabled"].remove(uid)
            save_settings(self.settings)
            await interaction.response.send_message(
                "✅ Your World Attack reminder is now enabled.",
                ephemeral=True
            )
        else:
            self.settings["disabled"].append(uid)
            save_settings(self.settings)
            await interaction.response.send_message(
                "❌ Your World Attack reminder is now disabled.",
                ephemeral=True
            )

    # -----------------------------
    # /test-worldattack (admin)
    # -----------------------------
    @app_commands.command(
        name="test-worldattack",
        description="Send yourself a test World Attack reminder."
    )
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def test_worldattack(self, interaction: discord.Interaction):

        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "⛔ You do not have permission to use this command.",
                ephemeral=True
            )
            return

        try:
            await interaction.user.send(REMINDER_TEXT)
            await interaction.response.send_message(
                "📨 Test reminder sent to your DMs.",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                f"❌ Failed to send DM: {e}",
                ephemeral=True
            )

    # -----------------------------
    # Background task
    # -----------------------------
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

    # -----------------------------
    # Send reminders
    # -----------------------------
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

        for member in role.members:
            if member.bot:
                continue

            if member.id in self.settings["disabled"]:
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
    log.info("⚙️ WorldAttackReminder cog loaded")
