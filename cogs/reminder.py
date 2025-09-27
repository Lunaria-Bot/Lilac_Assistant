import logging
import asyncio
import discord
from discord.ext import commands

log = logging.getLogger("cog-reminder")

class Reminder(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Dictionnaire pour stocker les reminders actifs par utilisateur
        self.active_reminders = {}

    async def start_reminder(self, member: discord.Member, channel: discord.TextChannel):
        """Démarre un reminder pour un joueur après un summon claim classique."""
        user_id = member.id

        # Si un reminder est déjà actif pour ce joueur, on ne le relance pas
        if user_id in self.active_reminders:
            log.debug("⏸️ Reminder déjà actif pour %s", member.display_name)
            return

        async def reminder_task():
            try:
                # ⏳ Cooldown = 30 minutes (1800 secondes)
                await asyncio.sleep(1800)
                try:
                    await channel.send(
                        f"⏰ {member.mention} ton cooldown de summon est terminé, tu peux relancer un summon !"
                    )
                    log.info("📩 Reminder envoyé dans %s pour %s", channel.name, member.display_name)
                except discord.Forbidden:
                    log.warning("❌ Impossible d’envoyer un message dans %s", channel.name)
            finally:
                # Nettoyage
                self.active_reminders.pop(user_id, None)

        task = asyncio.create_task(reminder_task())
        self.active_reminders[user_id] = task
        log.info("▶️ Reminder démarré pour %s dans %s", member.display_name, channel.name)

    async def cancel_reminder(self, member: discord.Member):
        """Annule un reminder actif pour un joueur."""
        task = self.active_reminders.pop(member.id, None)
        if task:
            task.cancel()
            log.info("⏹️ Reminder annulé pour %s", member.display_name)

    # --- Listener : déclenche uniquement sur summon claim ---
    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if not after.guild or not after.embeds:
            return

        embed = after.embeds[0]
        title = (embed.title or "").lower()

        # On ne déclenche PAS sur auto summon
        if "summon claimed" in title and "auto summon claimed" not in title:
            if not embed.description:
                return
            import re
            match = re.search(r"<@!?(\d+)>", embed.description)
            if not match:
                return

            user_id = int(match.group(1))
            member = after.guild.get_member(user_id)
            if not member:
                return

            # 👉 Ici on démarre le reminder dans le channel du message
            await self.start_reminder(member, after.channel)


async def setup(bot: commands.Bot):
    await bot.add_cog(Reminder(bot))
