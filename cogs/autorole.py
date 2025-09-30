import logging
import discord
from discord.ext import commands

log = logging.getLogger("cog-autorole")

# IDs des rôles
LVL10_ROLE_ID = 1297161587744047106
CROSS_TRADE_ACCESS_ID = 1306954214106202145  # ⚠️ Mets ici l’ID exact du rôle Cross Trade Access
CROSS_TRADE_BAN_ID = 1306954214106202144
MARKET_BAN_ID = 1306958134245457970


class AutoRole(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def update_cross_trade_access(self, member: discord.Member):
        """Vérifie les rôles d’un membre et ajuste Cross Trade Access."""
        guild = member.guild
        access_role = guild.get_role(CROSS_TRADE_ACCESS_ID)
        lvl10_role = guild.get_role(LVL10_ROLE_ID)
        ban_role = guild.get_role(CROSS_TRADE_BAN_ID)
        market_ban_role = guild.get_role(MARKET_BAN_ID)

        if not access_role:
            log.warning("⚠️ Cross Trade Access role introuvable dans le serveur.")
            return

        # Condition : doit avoir lvl10 ET ne pas avoir de ban
        if lvl10_role in member.roles and ban_role not in member.roles and market_ban_role not in member.roles:
            if access_role not in member.roles:
                try:
                    await member.add_roles(access_role, reason="AutoRole: Lvl10 sans ban")
                    log.info("✅ Ajout de Cross Trade Access à %s", member.display_name)
                except discord.Forbidden:
                    log.error("❌ Permissions insuffisantes pour ajouter le rôle à %s", member.display_name)
        else:
            if access_role in member.roles:
                try:
                    await member.remove_roles(access_role, reason="AutoRole: Ban détecté ou pas lvl10")
                    log.info("🚫 Retrait de Cross Trade Access à %s", member.display_name)
                except discord.Forbidden:
                    log.error("❌ Permissions insuffisantes pour retirer le rôle à %s", member.display_name)

    # --- Event : quand un rôle est ajouté ou retiré ---
    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.roles != after.roles:
            await self.update_cross_trade_access(after)

    # --- Vérification globale au démarrage ---
    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            log.info("🔍 Vérification globale des rôles dans %s...", guild.name)
            for member in guild.members:
                await self.update_cross_trade_access(member)
        log.info("✅ Vérification globale terminée.")

    # --- Commande admin pour forcer une vérification ---
    @commands.command(name="check_autorole")
    @commands.has_permissions(administrator=True)
    async def check_autorole(self, ctx: commands.Context, member: discord.Member = None):
        """Force la vérification des rôles (admin only)."""
        if not member:
            member = ctx.author
        await self.update_cross_trade_access(member)
        await ctx.send(f"🔄 Vérification terminée pour {member.display_name}", delete_after=5)


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoRole(bot))
    log.info("⚙️ AutoRole cog chargé")
