import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, time
from zoneinfo import ZoneInfo
import json
import os

# Role to ping
ROLE_ID = 1450472679021740043

# Log channel
LOG_CHANNEL_ID = 1421465080238964796

# Reminder message
REMINDER_TEXT = "Hey Guild Member of Lilac, do not forget to do your world attack!"

# Settings file (opt-out list)
SETTINGS_FILE = "world_attack_settings.json"


# ---------------------------------------------------------
# LOAD / SAVE SETTINGS
# ---------------------------------------------------------
def load_settings():
    if not os.path.exists(SETTINGS_FILE):
        return {"disabled_users": []}
    with open(SETTINGS_FILE, "r") as f:
        return json.load(f)


def save_settings(data):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(data, f, indent=4)


class WorldAttackReminder(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.settings = load_settings()
        self.reminder_loop.start()

    def cog_unload(self):
        self.reminder_loop.cancel()

    # ---------------------------------------------------------
    # SLASH COMMAND GROUP: /worldattack
    # ---------------------------------------------------------
    worldattack = app_commands.Group(
        name="worldattack",
        description="Manage your World Attack reminder settings."
    )

    # ---------------------------------------------------------
    # SUBCOMMAND: /worldattack toggle
    # ---------------------------------------------------------
    @worldattack.command(
        name="toggle",
        description="Enable or disable your daily World Attack reminder."
    )
    async def toggle(self, interaction: discord.Interaction):

        user_id = interaction.user.id

        if user_id in self.settings["disabled_users"]:
            self.settings["disabled_users"].remove(user_id)
            save_settings(self.settings)
            await interaction.response.send_message(
                "Your World Attack reminder is now **enabled**.",
                ephemeral=True
            )
        else:
            self.settings["disabled_users"].append(user_id)
            save_settings(self.settings)
            await interaction.response.send_message(
                "Your World Attack reminder is now **disabled**.",
                ephemeral=True
            )

    # ---------------------------------------------------------
    # BACKGROUND LOOP — CHECK TIME EVERY MINUTE
    # ---------------------------------------------------------
    @tasks.loop(minutes=1)
    async def reminder_loop(self):
        now = datetime.now(ZoneInfo("Europe/Paris"))

        # Monday = 0, Friday = 4
        if now.weekday() > 4:
            return

        target = time(1, 0)  # 01:00
        if now.hour == target.hour and now.minute == target.minute:
            await self.send_reminders()

    @reminder_loop.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()

    # ---------------------------------------------------------
    # REMINDER DISPATCH
    # ---------------------------------------------------------
    async def send_reminders(self):
        log_channel = self.bot.get_channel(LOG_CHANNEL_ID)

        if log_channel:
            await log_channel.send("[WorldAttack] Starting reminder dispatch...")

        for guild in self.bot.guilds:
            role = guild.get_role(ROLE_ID)
            if not role:
                if log_channel:
                    await log_channel.send(f"[WorldAttack] Role {ROLE_ID} not found in {guild.name}.")
                continue

            for member in role.members:
                if member.bot:
                    continue

                if member.id in self.settings["disabled_users"]:
                    if log_channel:
                        await log_channel.send(f"[WorldAttack] Skipped {member} (opted out).")
                    continue

                try:
                    await member.send(REMINDER_TEXT)
                    if log_channel:
                        await log_channel.send(f"[WorldAttack] DM sent to {member} ({member.id}).")
                except Exception as e:
                    if log_channel:
                        await log_channel.send(f"[WorldAttack] Failed to DM {member}: {e}")

        if log_channel:
            await log_channel.send("[WorldAttack] Reminder dispatch completed.")


async def setup(bot: commands.Bot):
    await bot.add_cog(WorldAttackReminder(bot))
