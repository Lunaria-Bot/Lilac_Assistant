import os
import logging
import asyncio
import redis.asyncio as aioredis
import discord
from discord.ext import commands

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    force=True
)
log = logging.getLogger("mazoku-main")

# --- Env ---
TOKEN = os.getenv("DISCORD_TOKEN")
REDIS_URL = os.getenv("REDIS_URL")
GUILD_IDS = [int(x) for x in os.getenv("GUILD_IDS", "").split(",") if x]

if not TOKEN or not REDIS_URL or not GUILD_IDS:
    raise RuntimeError("Missing env vars: DISCORD_TOKEN, REDIS_URL, GUILD_IDS")

# --- Intents ---
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.members = True

# --- Bot ---
class MainBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)
        self.redis: aioredis.Redis | None = None

    async def setup_hook(self):
        # Redis
        try:
            self.redis = await aioredis.from_url(REDIS_URL, decode_responses=True)
            await self.redis.ping()
            log.info("✅ Redis connected")
        except Exception:
            log.exception("❌ Redis connection failed")
            self.redis = None

        # Load cogs
        await self.load_extension("cogs.cooldowns")
        await self.load_extension("cogs.leaderboard")
        await self.load_extension("cogs.tasks")

        # Sync slash commands to all guilds
        for gid in GUILD_IDS:
            guild = discord.Object(id=gid)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info("✅ Slash commands synced to guild %s", gid)

bot = MainBot()

@bot.event
async def on_ready():
    log.info("🚀 Logged in as %s (%s)", bot.user, bot.user.id)

bot.run(TOKEN)

