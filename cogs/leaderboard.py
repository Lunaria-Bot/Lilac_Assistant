import os
import re
import logging
import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger("cog-leaderboard")

# --- Env IDs ---
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
MAZOKU_BOT_ID = int(os.getenv("MAZOKU_BOT_ID", "0"))

def is_admin():
    def predicate(interaction: discord.Interaction) -> bool:
        return interaction.user.guild_permissions.administrator
    return app_commands.check(predicate)

# --- View avec Select ---
class LeaderboardView(discord.ui.View):
    def __init__(self, bot, guild):
        super().__init__(timeout=120)
        self.bot = bot
        self.guild = guild

    @discord.ui.select(
        placeholder="Choisis une catégorie",
        options=[
            discord.SelectOption(label="All time", value="all"),
            discord.SelectOption(label="Monthly", value="monthly"),
            discord.SelectOption(label="AutoSummon", value="autosummon"),
            discord.SelectOption(label="Summon", value="summon"),
        ]
    )
    async def select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        category = select.values[0]
        embed = await self.build_leaderboard(category, interaction.guild, interaction.user)
        await interaction.response.edit_message(embed=embed, view=self)

    async def build_leaderboard(self, category: str, guild: discord.Guild, user: discord.Member):
        key_map = {
            "all": "leaderboard",
            "monthly": "activity:monthly",
            "autosummon": "activity:autosummon",
            "summon": "activity:summon",
        }
        key = key_map.get(category, "leaderboard")

        if not getattr(self.bot, "redis", None):
            return discord.Embed(
                title=f"🏆 {category.title()} Leaderboard",
                description="❌ Redis not connected.",
                color=discord.Color.red()
            )

        data = await self.bot.redis.hgetall(key)
        if not data:
            return discord.Embed(
                title=f"🏆 {category.title()} Leaderboard",
                description="Empty",
                color=discord.Color.gold()
            )

        sorted_data = sorted(data.items(), key=lambda x: int(x[1]), reverse=True)[:10]
        lines = []
        for i, (uid, score) in enumerate(sorted_data, start=1):
            member = guild.get_member(int(uid))
            mention = member.mention if member else f"<@{uid}>"
            lines.append(f"**{i}.** {mention} — {score} pts")

        embed = discord.Embed(
            title=f"🏆 {category.title()} Leaderboard",
            description="\n".join(lines) if lines else "No entries yet.",
            color=discord.Color.gold()
        )
        embed.set_footer(text=f"Demandé par {user.display_name}")
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        return embed


class Leaderboard(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.paused = {
            "all": False,
            "monthly": False,
            "autosummon": False,
            "summon": False,
        }
        log.info("⚙️ Leaderboard cog loaded with GUILD_ID=%s, MAZOKU_BOT_ID=%s", GUILD_ID, MAZOKU_BOT_ID)

    # --- Commande principale ---
    @app_commands.command(name="leaderboard", description="View the leaderboard")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.checks.cooldown(1, 120.0, key=lambda i: (i.user.id))
    async def leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)
        view = LeaderboardView(self.bot, interaction.guild)
        embed = await view.build_leaderboard("all", interaction.guild, interaction.user)
        await interaction.followup.send(embed=embed, view=view, ephemeral=False)

    @leaderboard.error
    async def leaderboard_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.CommandOnCooldown):
            await interaction.response.send_message(
                f"⏳ Tu dois attendre encore {int(error.retry_after)}s avant de relancer `/leaderboard`.",
                ephemeral=True
            )

    # --- Commandes Admin avec menus déroulants ---
    @app_commands.command(name="leaderboard-reset", description="Reset des scores (admin)")
    @app_commands.choices(
        category=[
            app_commands.Choice(name="All", value="all"),
            app_commands.Choice(name="Monthly", value="monthly"),
            app_commands.Choice(name="AutoSummon", value="autosummon"),
            app_commands.Choice(name="Summon", value="summon"),
            app_commands.Choice(name="Tout", value="all_keys"),
        ]
    )
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @is_admin()
    async def leaderboard_reset(self, interaction: discord.Interaction, category: app_commands.Choice[str]):
        await interaction.response.defer(ephemeral=True)
        if not getattr(self.bot, "redis", None):
            await interaction.followup.send("❌ Redis not connected.", ephemeral=True)
            return

        if category.value == "all_keys":
            for key in ["leaderboard", "activity:monthly", "activity:autosummon", "activity:summon"]:
                await self.bot.redis.delete(key)
            msg = "🧹 Tous les scores ont été réinitialisés."
        else:
            key_map = {
                "all": "leaderboard",
                "monthly": "activity:monthly",
                "autosummon": "activity:autosummon",
                "summon": "activity:summon",
            }
            await self.bot.redis.delete(key_map[category.value])
            msg = f"🧹 Catégorie `{category.value}` réinitialisée."

        await interaction.followup.send(msg, ephemeral=True)

    @leaderboard_reset.error
    async def leaderboard_reset_error(self, interaction: discord.Interaction, error):
        try:
            if isinstance(error, app_commands.CheckFailure):
                await interaction.response.send_message("❌ Commande réservée aux admins.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Erreur pendant le reset.", ephemeral=True)
        except discord.InteractionResponded:
            await interaction.followup.send("❌ Erreur pendant le reset.", ephemeral=True)

    @app_commands.command(name="leaderboard-pause", description="Pause/reprise des compteurs (admin)")
    @app_commands.choices(
        category=[
            app_commands.Choice(name="All", value="all"),
            app_commands.Choice(name="Monthly", value="monthly"),
            app_commands.Choice(name="AutoSummon", value="autosummon"),
            app_commands.Choice(name="Summon", value="summon"),
        ],
        state=[
            app_commands.Choice(name="Pause", value="pause"),
            app_commands.Choice(name="Resume", value="resume"),
        ]
    )
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @is_admin()
    async def leaderboard_pause(
        self,
        interaction: discord.Interaction,
        category: app_commands.Choice[str],
        state: app_commands.Choice[str]
    ):
        await interaction.response.defer(ephemeral=True)

        if category.value not in self.paused:
            await interaction.followup.send(f"❌ Catégorie inconnue: {category.value}", ephemeral=True)
            return

        self.paused[category.value] = (state.value == "pause")
        log.info("Pause command: category=%s state=%s", category.value, state.value)

        await interaction.followup.send(
            f"⏸️ `{category.value}` → {'pause' if self.paused[category.value] else 'reprise'}.",
            ephemeral=True
        )

    @leaderboard_pause.error
    async def leaderboard_pause_error(self, interaction: discord.Interaction, error):
        try:
            if isinstance(error, app_commands.CheckFailure):
                await interaction.response.send_message("❌ Commande réservée aux admins.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Erreur pendant la mise en pause.", ephemeral=True)
        except discord.InteractionResponded:
            await interaction.followup.send("❌ Erreur pendant la mise en pause.", ephemeral=True)

    @app_commands.command(name="leaderboard-debug", description="Voir les stats internes (admin)")
    @app_commands.choices(
        scope=[
            app_commands.Choice(name="Résumé", value="summary"),
            app_commands.Choice(name="Détail complet", value="full"),
        ]
    )
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @is_admin()
    async def leaderboard_debug(self, interaction: discord.Interaction, scope: app_commands.Choice[str]):
        await interaction.response.defer(ephemeral=True)
        if not getattr(self.bot, "redis", None):
            await interaction.followup.send("❌ Redis not connected.", ephemeral=True)
            return

        total_monthly = await self.bot.redis.get("activity:monthly:total") or 0
        sizes = {}
        for key in ["leaderboard", "activity:monthly", "activity:autosummon", "activity:summon"]:
            sizes[key] = await self.bot.redis.hlen(key)

        lines = [
            f"- **Monthly total**: {total_monthly}",
            f"- **leaderboard** size: {sizes['leaderboard']}",
            f"- **activity:monthly** size: {sizes['activity:monthly']}",
            f"- **activity:autosummon** size: {sizes['activity:autosummon']}",
            f"- **activity:summon** size: {sizes['activity:summon']}",
        ]

        if scope.value == "summary":
            msg = "🛠️ Debug (résumé):\n" + "\n".join(lines)
        else:
            msg = "🛠️ Debug (détail complet):\n" + "\n".join(lines)

        await interaction.followup.send(msg, ephemeral=True)

    @leaderboard_debug.error
    async def leaderboard_debug_error(self, interaction: discord.Interaction, error):
        try:
            if isinstance(error, app_commands.CheckFailure):
                await interaction.response.send_message("❌ Commande réservée aux admins.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Erreur pendant le debug.", ephemeral=True)
        except discord.InteractionResponded:
            await interaction.followup.send("❌ Erreur pendant le debug.", ephemeral=True)

    # --- Listeners (claims) ---
    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if after.author.id != MAZOKU_BOT_ID:
            return
        if not after.guild or after.guild.id != GUILD_ID:
            return
        if not after.embeds:
            return

        embed = after.embeds[0]
        title = (embed.title or "").lower()
        if any(x in title for x in ["card claimed", "auto summon claimed", "summon claimed"]):
            # Trouver l'utilisateur mentionné dans la description
            match = re.search(r"<@!?(\d+)>", embed.description or "")
            if not match:
                return
            user_id = int(match.group(1))
            member = after.guild.get_member(user_id)
            if not member:
                return
            if not getattr(self.bot, "redis", None):
                return

            # Anti double-compte par message
            claim_key = f"claim:{after.id}:{user_id}"
            already = await self.bot.redis.get(claim_key)
            if already:
                return
            await self.bot.redis.set(claim_key, "1", ex=86400)

            # Compteurs
            if not self.paused["monthly"]:
                await self.bot.redis.hincrby("activity:monthly", str(user_id), 1)
                await self.bot.redis.incr("activity:monthly:total")

            if "auto summon claimed" in title:
                if not self.paused["autosummon"]:
                    await self.bot.redis.hincrby("activity:autosummon", str(user_id), 1)
            else:
                if not self.paused["summon"]:
                    await self.bot.redis.hincrby("activity:summon", str(user_id), 1)

            if not self.paused["all"]:
                await self.bot.redis.hincrby("leaderboard", str(user_id), 1)

            log.info("🏅 %s gained +1 point from %s", member.display_name, embed.title)

# --- Extension setup ---
async def setup(bot: commands.Bot):
    await bot.add_cog(Leaderboard(bot))
