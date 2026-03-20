"""
config.py — Centralized configuration for Lilac Assistant
All IDs and environment variables in one place.
"""
import os

# ─────────────────────────────────────────────
# Core
# ─────────────────────────────────────────────
DISCORD_TOKEN = TOKEN = os.getenv("DISCORD_TOKEN")
REDIS_URL       = os.getenv("REDIS_URL", "redis://localhost:6379")
COMMAND_PREFIX  = os.getenv("COMMAND_PREFIX", "m?")
GUILD_ID        = int(os.getenv("GUILD_ID", "0"))

# ─────────────────────────────────────────────
# External bots
# ─────────────────────────────────────────────
MAZOKU_BOT_ID   = int(os.getenv("MAZOKU_BOT_ID", "0"))
LNY_BOT_ID      = int(os.getenv("LNY_BOT_ID", "0"))
BOT_ID          = int(os.getenv("BOT_ID", "1421466719678894280"))

# ─────────────────────────────────────────────
# Roles
# ─────────────────────────────────────────────
HIGH_TIER_ROLE_ID       = int(os.getenv("HIGH_TIER_ROLE_ID", "0"))
REQUIRED_ROLE_ID        = int(os.getenv("REQUIRED_ROLE_ID", "0"))

LVL10_ROLE_ID           = int(os.getenv("LVL10_ROLE_ID",           "1297161587744047106"))
CROSS_TRADE_ACCESS_ID   = int(os.getenv("CROSS_TRADE_ACCESS_ID",   "1332804856918052914"))
CROSS_TRADE_BAN_ID      = int(os.getenv("CROSS_TRADE_BAN_ID",      "1306954214106202144"))
MARKET_BAN_ID           = int(os.getenv("MARKET_BAN_ID",           "1306958134245457970"))

ROLE_TIER_1             = int(os.getenv("ROLE_TIER_1", "1439616771622572225"))
ROLE_TIER_2             = int(os.getenv("ROLE_TIER_2", "1439616926170218669"))
ROLE_TIER_3             = int(os.getenv("ROLE_TIER_3", "1439616971908972746"))
REQUIRED_ROLES_FOR_T3   = {
    int(x) for x in os.getenv(
        "REQUIRED_ROLES_FOR_T3",
        "1295761591895064577,1450472679021740043,1297161626910462016"
    ).split(",") if x.strip()
}

# ─────────────────────────────────────────────
# Channels
# ─────────────────────────────────────────────
NOTIFY_CHANNEL_ID       = int(os.getenv("NOTIFY_CHANNEL_ID",   "1421465080238964796"))
TARGET_CHANNEL_ID       = int(os.getenv("TARGET_CHANNEL_ID",   "1460226131830509662"))
AUTOROLE_MESSAGE_ID     = int(os.getenv("AUTOROLE_MESSAGE_ID", "1460243538133520510"))

# ─────────────────────────────────────────────
# Cooldowns / timers
# ─────────────────────────────────────────────
COOLDOWN_SECONDS            = int(os.getenv("COOLDOWN_SECONDS",            "1800"))
HIGH_TIER_COOLDOWN          = int(os.getenv("HIGH_TIER_COOLDOWN",          "300"))
REMINDER_CLEANUP_MINUTES    = int(os.getenv("REMINDER_CLEANUP_MINUTES",    "10"))
REDIS_TTL                   = int(os.getenv("REDIS_TTL",                   str(60 * 60 * 24 * 7)))

# ─────────────────────────────────────────────
# Lilac brand colours (discord.Color-compatible int)
# ─────────────────────────────────────────────
class Colors:
    LILAC       = 0xC8A2C8   # main brand
    GOLD        = 0xFFD700   # leaderboard / achievements
    SUCCESS     = 0x57F287   # green
    ERROR       = 0xED4245   # red
    WARNING     = 0xFEE75C   # yellow
    INFO        = 0x5865F2   # blurple
    MUTED       = 0x99AAB5   # grey

# ─────────────────────────────────────────────
# Auction Manager
# ─────────────────────────────────────────────
BID_FORWARD_CHANNEL_ID  = int(os.getenv("BID_FORWARD_CHANNEL_ID", "1333042802405408789"))
FORUM_IDS: dict[str, int] = {
    "Common": int(os.getenv("FORUM_COMMON", "1304507540645740666")),
    "Rare":   int(os.getenv("FORUM_RARE",   "1304507516423766098")),
    "SR":     int(os.getenv("FORUM_SR",     "1304536219677626442")),
    "SSR":    int(os.getenv("FORUM_SSR",    "1304502617472503908")),
    "UR":     int(os.getenv("FORUM_UR",     "1304052056109350922")),
    "CM":     int(os.getenv("FORUM_CM",     "1395405043431116871")),
}
ALLOWED_ROLE_IDS: set[int] = {
    int(x) for x in os.getenv(
        "AUCTION_ALLOWED_ROLES",
        "1305252546608365599,1296831373599965296,1334130181073539192,1304102244462886982"
    ).split(",") if x.strip()
}
ACTIVE_TAG_IDS: set[int] = {
    int(x) for x in os.getenv(
        "AUCTION_ACTIVE_TAGS",
        "1304523670374453268,1304523716868177942,1304823742358224938,"
        "1304523623863685201,1304523581442756619,1395407621544087583"
    ).split(",") if x.strip()
}

# ─────────────────────────────────────────────
# World Attack
# ─────────────────────────────────────────────
LOG_CHANNEL_ID          = int(os.getenv("LOG_CHANNEL_ID",   "1421465080238964796"))
WORLD_ATTACK_ROLE_ID    = int(os.getenv("WORLD_ATTACK_ROLE_ID", "1450472679021740043"))
WORLD_ATTACK_TEXT       = os.getenv(
    "WORLD_ATTACK_TEXT",
    "Hey Guild Member of Lilac, do not forget to do your world attack!"
)

# ─────────────────────────────────────────────
# Daily Reminder
# ─────────────────────────────────────────────
DAILY_MESSAGE = os.getenv("DAILY_MESSAGE", "Hello just to remind you that your Mazoku Daily is ready !")

# ─────────────────────────────────────────────
# NAI Leaderboard
# ─────────────────────────────────────────────
NAI_BOT_ID       = int(os.getenv("NAI_BOT_ID", "1312830013573169252"))
NAI_TRACK_CHANNELS: set[int] = {
    int(x) for x in os.getenv(
        "NAI_TRACK_CHANNELS",
        "1435259140464443454,1449113593709727777,1449114801686183999"
    ).split(",") if x.strip()
}

# ─────────────────────────────────────────────
# Rarity detection (shared between cogs)
# ─────────────────────────────────────────────
RARITY_EMOJIS: dict[str, str] = {
    "1342202597389373530": "SR",
    "1342202212948115510": "SSR",
    "1342202203515125801": "UR",
}
RARITY_CUSTOM_EMOJIS: dict[str, str] = {
    "SR":  "<a:SuperRare:1342208034482425936>",
    "SSR": "<a:SuperSuperRare:1342208039918370857>",
    "UR":  "<a:UltraRare:1342208044351623199>",
}
RARITY_PRIORITY: dict[str, int] = {"SR": 1, "SSR": 2, "UR": 3}
