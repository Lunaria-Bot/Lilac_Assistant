import os
import logging
import asyncio
import discord
from discord.ext import commands
import redis.asyncio as redis  # ✅ on utilise redis.asyncio
from discord import app_commands

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,  # Mets DEBUG si tu veux plus de détails
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
log = logging.getLogger("main")

# --- Token & Redis ---
TOKEN = os.getenv("DISCORD_TOKEN")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))  # 🔑 ID du serveur cible

# --- Intents ---
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
intents.messages = True

# --- Bot ---
bot = commands.Bot(command_prefix="!", intents=intents)

# --- Setup hook ---
async def setup_hook():
    # Connexion Redis
    try:
        bot.redis = redis.from_url(REDIS_URL, decode_responses=True)
        await bot.redis.ping()  # test rapide
        log.info("✅ Connected to Redis at %s", REDIS_URL)
    except Exception as e:
        bot.redis = None
        log.error("❌ Redis connection failed: %s", e)

    # Charger les cogs
    for cog in ["cogs.leaderboard", "cogs.reminder", "cogs.log", "cogs.tasks"]:
        try:
            await bot.load_extension(cog)
            log.info("✅ Loaded cog: %s", cog)
        except Exception as e:
            log.exception("❌ Failed to load cog %s", cog, exc_info=e)

bot.setup_hook = setup_hook

# --- Commande admin /sync ---
def is_admin():
    def predicate(interaction: discord.Interaction) -> bool:
        return interaction.user.guild_permissions.administrator
    return app_commands.check(predicate)

@app_commands.command(name="sync", description="Resynchroniser les commandes slash (admin)")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@is_admin()
async def sync_commands(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        guild = discord.Object(id=GUILD_ID)
        synced = await bot.tree.sync(guild=guild)
        await interaction.followup.send(
            f"✅ {len(synced)} commandes resynchronisées sur le serveur {interaction.guild.name}.",
            ephemeral=True
        )
        log.info("🔄 Slash commands resynced via /sync by %s", interaction.user)
    except Exception as e:
        log.exception("❌ Sync failed:", exc_info=e)
        await interaction.followup.send("❌ Erreur pendant la resynchronisation.", ephemeral=True)

# On ajoute la commande à l'arbre
bot.tree.add_command(sync_commands)

# --- Events ---
@bot.event
async def on_ready():
    log.info("🤖 Bot connecté en tant que %s (ID: %s)", bot.user, bot.user.id)
    log.info("🌍 Connecté sur %s serveurs", len(bot.guilds))

    # 🔑 Synchronisation automatique au démarrage
    try:
        guild = discord.Object(id=GUILD_ID)
        synced = await bot.tree.sync(guild=guild)
        log.info("✅ Slash commands synced to guild %s (%s commandes)", GUILD_ID, len(synced))
    except Exception as e:
        log.exception("❌ Failed to sync slash commands:", exc_info=e)

# --- Run ---
if __name__ == "__main__":
    if not TOKEN:
        log.error("❌ DISCORD_TOKEN manquant dans les variables d'environnement")
    else:
        bot.run(TOKEN)
