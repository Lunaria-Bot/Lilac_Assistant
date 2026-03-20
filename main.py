# main.py
import glob
import logging
import asyncio
import discord
from discord.ext import commands
import redis.asyncio as redis

from config import TOKEN, REDIS_URL, COMMAND_PREFIX

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
log = logging.getLogger("main")

# --- Intents ---
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
intents.messages = True

# --- Bot ---
bot = commands.Bot(
    command_prefix=COMMAND_PREFIX,
    intents=intents,
    case_insensitive=True
)

# ---------------------------------------------------------
# TEMPORARY ADMIN COMMAND TO WIPE OLD WORLDATTACK GROUP
# ---------------------------------------------------------
@bot.tree.command(name="wipe_worldattack", description="Delete the old /worldattack command group.")
@discord.app_commands.checks.has_permissions(administrator=True)
async def wipe_worldattack(interaction: discord.Interaction):
    bot.tree.remove_command("worldattack")
    await bot.tree.sync()
    await interaction.response.send_message(
        "Old /worldattack command group wiped. Reload the cog and sync again.",
        ephemeral=True
    )
    log.warning("⚠️ /worldattack group wiped manually by %s", interaction.user)


# --- Setup hook ---
async def setup_hook():
    # Shared Redis connection
    try:
        bot.redis = redis.from_url(REDIS_URL, decode_responses=True)
        await bot.redis.ping()
        log.info("✅ Connected to Redis at %s", REDIS_URL)
    except Exception as e:
        bot.redis = None
        log.error("❌ Redis connection failed: %s", e)

    # Auto-load all cogs
    cog_files = glob.glob("cogs/*.py")
    results = []
    for file in cog_files:
        cog_name = file.replace("/", ".").replace("\\", ".")[:-3]
        try:
            await bot.load_extension(cog_name)
            results.append((cog_name, "✅"))
        except Exception as e:
            results.append((cog_name, f"❌ ({type(e).__name__})"))
            log.exception("❌ Failed to load cog %s", cog_name, exc_info=e)

    log.info("📦 Cogs loading summary:")
    for name, status in results:
        log.info("   %s %s", status, name)

    # Global slash command sync
    try:
        synced = await bot.tree.sync()
        log.info("🌍 Global slash commands synced (%s commands)", len(synced))
    except Exception as e:
        log.exception("❌ Failed to sync global slash commands:", exc_info=e)

bot.setup_hook = setup_hook

# --- Events ---
@bot.event
async def on_ready():
    log.info("🤖 Logged in as %s (ID: %s)", bot.user, bot.user.id)
    log.info("🌍 Connected to %s guild(s)", len(bot.guilds))
    log.info("⌨️ Prefix: %s (slash always available)", COMMAND_PREFIX)

# --- Run ---
if __name__ == "__main__":
    if not TOKEN:
        log.error("❌ DISCORD_TOKEN missing from environment variables")
    else:
        bot.run(TOKEN)
