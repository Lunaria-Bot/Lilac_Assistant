import os
import logging
import asyncio
import discord
from discord.ext import commands
import redis.asyncio as redis  # ✅ on utilise redis.asyncio

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,  # Mets DEBUG si tu veux plus de détails
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
log = logging.getLogger("main")

# --- Token & Redis ---
TOKEN = os.getenv("DISCORD_TOKEN")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

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
    for cog in ["cogs.leaderboard", "cogs.reminder", "cogs.log","cogs.reminder"]:
        try:
            await bot.load_extension(cog)
            log.info("✅ Loaded cog: %s", cog)
        except Exception as e:
            log.exception("❌ Failed to load cog %s", cog, exc_info=e)

bot.setup_hook = setup_hook

# --- Events ---
@bot.event
async def on_ready():
    log.info("🤖 Bot connecté en tant que %s (ID: %s)", bot.user, bot.user.id)
    log.info("🌍 Connecté sur %s serveurs", len(bot.guilds))

# --- Run ---
if __name__ == "__main__":
    if not TOKEN:
        log.error("❌ DISCORD_TOKEN manquant dans les variables d'environnement")
    else:
        bot.run(TOKEN)
