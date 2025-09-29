import discord
from discord import app_commands
from discord.ext import commands
import logging

log = logging.getLogger("cog-admin")


class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # --- Slash command /sync ---
    @app_commands.command(name="sync", description="Resynchroniser les commandes slash (guild + global)")
    @app_commands.describe(scope="Choisir 'guild' ou 'global'")
    @app_commands.choices(
        scope=[
            app_commands.Choice(name="Guild only", value="guild"),
            app_commands.Choice(name="Global only", value="global"),
        ]
    )
    async def sync_cmd(self, interaction: discord.Interaction, scope: app_commands.Choice[str] = None):
        if scope is None:
            synced_guild = await self.bot.tree.sync(guild=interaction.guild)
            synced_global = await self.bot.tree.sync()
            await interaction.response.send_message(
                f"✅ {len(synced_guild)} commandes resynchronisées sur **{interaction.guild.name}**\n"
                f"🌍 {len(synced_global)} commandes globales resynchronisées.",
                ephemeral=True
            )
        elif scope.value == "guild":
            synced = await self.bot.tree.sync(guild=interaction.guild)
            await interaction.response.send_message(
                f"✅ {len(synced)} commandes resynchronisées uniquement sur **{interaction.guild.name}**.",
                ephemeral=True
            )
        elif scope.value == "global":
            synced = await self.bot.tree.sync()
            await interaction.response.send_message(
                f"🌍 {len(synced)} commandes globales resynchronisées.",
                ephemeral=True
            )

    # --- Slash command /reminder ---
    @app_commands.command(name="reminder", description="Enable or disable summon reminders")
    @app_commands.describe(state="Enable or disable the summon reminder")
    @app_commands.choices(
        state=[
            app_commands.Choice(name="On", value="on"),
            app_commands.Choice(name="Off", value="off"),
        ]
    )
    async def reminder_cmd(self, interaction: discord.Interaction, state: app_commands.Choice[str]):
        """Slash command to toggle summon reminders for the user."""
        user_id = interaction.user.id
        guild_id = interaction.guild.id if interaction.guild else 0

        if not getattr(self.bot, "redis", None):
            await interaction.response.send_message("⚠️ Redis not available, cannot save reminder settings.", ephemeral=True)
            return

        key = f"reminder:settings:{guild_id}:{user_id}:summon"

        if state.value == "on":
            await self.bot.redis.set(key, "1")
            await interaction.response.send_message("✅ Summon reminder has been **enabled**.", ephemeral=True)
        else:
            await self.bot.redis.set(key, "0")
            await interaction.response.send_message("❌ Summon reminder has been **disabled**.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))
    log.info("⚙️ Admin cog loaded (sync + reminder commands)")
