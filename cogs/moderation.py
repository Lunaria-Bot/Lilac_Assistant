import logging
import json
from datetime import datetime, timezone

import discord
from discord.ext import commands
from discord import app_commands
import redis.asyncio as redis

log = logging.getLogger("cog-moderation")

# --------- Configure these IDs/URL for your server ---------
GUILD_ID = 1293611593845706793
LOG_CHANNEL_ID = 1421465080238964796
REDIS_URL = "redis://default:WEQfFAaMkvNPFvEzOpAQsGdDTTbaFzOr@redis-436594b0.railway.internal:6379"

# --------- Auction warning caps (no auto-sanctions) ---------
LOW_CAP = 6
HIGH_CAP = 3


class Moderation(commands.Cog):
    staff_key = "staff:members"

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.redis = None

    async def cog_load(self):
        self.redis = redis.from_url(REDIS_URL, decode_responses=True)
        log.info("Moderation cog connected to Redis")

    async def cog_unload(self):
        if self.redis:
            await self.redis.close()
            log.info("Moderation cog disconnected from Redis")

    # --------- Access control helpers ---------
    async def is_staff_or_admin(self, user: discord.Member) -> bool:
        if user.guild_permissions.administrator:
            return True
        return await self.redis.sismember(self.staff_key, str(user.id))

    # --------- Logging with embeds + case IDs ---------
    async def log_action(
        self,
        guild: discord.Guild,
        moderator: discord.Member,
        action: str,
        target: discord.Member = None,
        reason: str = None,
        severity: str = None,
        category: str = None
    ):
        """Log staff actions as a color-coded embed and store case data."""
        log_channel = guild.get_channel(LOG_CHANNEL_ID)
        if not log_channel:
            return

        # Increment global case ID
        case_id = await self.redis.incr("moderation:case_id")

        # Color coding
        action_l = (action or "").lower()
        if category == "auction" and severity == "low":
            color = discord.Color.gold()
        elif category == "auction" and severity == "high":
            color = discord.Color.red()
        elif category == "general":
            color = discord.Color.blue()
        elif action_l.startswith("context"):
            color = discord.Color.purple()
        elif action_l.startswith("staff"):
            color = discord.Color.green()
        else:
            color = discord.Color.orange()

        # Build embed
        now = datetime.now(timezone.utc)
        embed = discord.Embed(
            title="👮 Staff Action",
            description=f"**{action}**",
            color=color,
            timestamp=now
        )
        embed.add_field(name="Moderator", value=moderator.mention, inline=True)
        embed.add_field(name="Target", value=(target.mention if target else "—"), inline=True)
        embed.add_field(name="Reason/Details", value=(reason or "No reason provided"), inline=False)
        embed.set_footer(text=f"Case ID #{case_id} • Guild: {guild.name}")

        await log_channel.send(embed=embed)

        # Store case data for retrieval
        case_data = {
            "action": action,
            "moderator_id": moderator.id,
            "target_id": target.id if target else None,
            "reason": reason,
            "severity": severity,
            "category": category,
            "color": color.value,
            "timestamp": now.isoformat()
        }
        await self.redis.set(f"moderation:case:{case_id}", json.dumps(case_data))

    # --------- Warning management (no auto-sanctions) ---------
    async def add_warning(
        self,
        member: discord.Member,
        category: str,
        severity: str,
        reason: str,
        moderator: discord.Member
    ):
        """Add a warning, log the action, and log threshold alerts (no auto-sanctions)."""
        key = f"warns:{category}:{member.id}:{severity}"
        count = await self.redis.incr(key)

        # Log the warning itself
        await self.log_action(
            member.guild,
            moderator,
            f"Warn ({category.capitalize()} - {severity.capitalize()})",
            target=member,
            reason=f"{reason} • Count: {count}",
            severity=severity,
            category=category
        )

        # Threshold alerts for auction warnings
        if category == "auction":
            if severity == "low" and count >= LOW_CAP:
                await self.log_action(
                    member.guild,
                    moderator,
                    f"Threshold reached ({LOW_CAP} low severity auction warnings)",
                    target=member,
                    reason=f"Count: {count}",
                    severity=severity,
                    category=category
                )
            elif severity == "high" and count >= HIGH_CAP:
                await self.log_action(
                    member.guild,
                    moderator,
                    f"Threshold reached ({HIGH_CAP} high severity auction warnings)",
                    target=member,
                    reason=f"Count: {count}",
                    severity=severity,
                    category=category
                )

    # --------- Commands: Warnings ---------
    @app_commands.command(name="warn-auction-low", description="Issue a low severity auction warning")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def warn_auction_low(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        if not await self.is_staff_or_admin(interaction.user):
            await interaction.response.send_message("⛔ Unauthorized.", ephemeral=True)
            return
        await self.add_warning(member, "auction", "low", reason, interaction.user)
        await interaction.response.send_message(f"⚠️ Low severity auction warning issued to {member.mention}", ephemeral=True)

    @app_commands.command(name="warn-auction-high", description="Issue a high severity auction warning")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def warn_auction_high(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        if not await self.is_staff_or_admin(interaction.user):
            await interaction.response.send_message("⛔ Unauthorized.", ephemeral=True)
            return
        await self.add_warning(member, "auction", "high", reason, interaction.user)
        await interaction.response.send_message(f"⚠️ High severity auction warning issued to {member.mention}", ephemeral=True)

    @app_commands.command(name="warn-general", description="Issue a general warning")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def warn_general(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        if not await self.is_staff_or_admin(interaction.user):
            await interaction.response.send_message("⛔ Unauthorized.", ephemeral=True)
            return
        key = f"warns:general:{member.id}"
        count = await self.redis.incr(key)
        await self.log_action(
            interaction.guild,
            interaction.user,
            "Warn (General)",
            target=member,
            reason=f"{reason} • Count: {count}",
            category="general"
        )
        await interaction.response.send_message(f"⚠️ General warning issued to {member.mention}", ephemeral=True)

    @app_commands.command(name="warnings", description="Check a user's warnings")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def warnings(self, interaction: discord.Interaction, member: discord.Member):
        if not await self.is_staff_or_admin(interaction.user):
            await interaction.response.send_message("⛔ Unauthorized.", ephemeral=True)
            return
        low = int(await self.redis.get(f"warns:auction:{member.id}:low") or 0)
        high = int(await self.redis.get(f"warns:auction:{member.id}:high") or 0)
        general = int(await self.redis.get(f"warns:general:{member.id}") or 0)

        text = (
            f"📊 Warnings for {member.mention}:\n"
            f"- Auction (low): {low}/{LOW_CAP}\n"
            f"- Auction (high): {high}/{HIGH_CAP}\n"
            f"- General: {general}"
        )
        await interaction.response.send_message(text, ephemeral=True)

        # Audit log for viewing warnings
        await self.log_action(
            interaction.guild,
            interaction.user,
            "Warnings View",
            target=member,
            reason=f"Auction low={low}, high={high}; General={general}"
        )

    @app_commands.command(name="clear-warnings", description="Clear a user's warnings")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def clear_warnings(self, interaction: discord.Interaction, member: discord.Member, category: str):
        if not await self.is_staff_or_admin(interaction.user):
            await interaction.response.send_message("⛔ Unauthorized.", ephemeral=True)
            return

        if category == "auction":
            await self.redis.delete(f"warns:auction:{member.id}:low")
            await self.redis.delete(f"warns:auction:{member.id}:high")
        elif category == "general":
            await self.redis.delete(f"warns:general:{member.id}")
        else:
            await interaction.response.send_message("❌ Category must be 'auction' or 'general'.", ephemeral=True)
            return

        await interaction.response.send_message(f"✅ Cleared {category} warnings for {member.mention}", ephemeral=True)
        await self.log_action(
            interaction.guild,
            interaction.user,
            f"Clear Warnings ({category})",
            target=member
        )

    # --------- Commands: Context notes ---------
    @app_commands.command(name="context", description="Add, list, or clear context notes for a user")
    @app_commands.describe(action="add/list/clear", note="Only required if action is 'add'")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def context(self, interaction: discord.Interaction, member: discord.Member, action: str, note: str = None):
        if not await self.is_staff_or_admin(interaction.user):
            await interaction.response.send_message("⛔ Unauthorized.", ephemeral=True)
            return

        key = f"context:{member.id}"

        if action == "add":
            if not note:
                await interaction.response.send_message("❌ You must provide a note when adding.", ephemeral=True)
                return
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            entry = f"[{timestamp}] {interaction.user.display_name}: {note}"
            await self.redis.rpush(key, entry)
            await interaction.response.send_message(f"📝 Added context note for {member.mention}", ephemeral=True)
            await self.log_action(
                interaction.guild,
                interaction.user,
                "Context Add",
                target=member,
                reason=entry
            )

        elif action == "list":
            notes = await self.redis.lrange(key, 0, -1)
            if not notes:
                await interaction.response.send_message("📭 No context notes for this user.", ephemeral=True)
                await self.log_action(
                    interaction.guild,
                    interaction.user,
                    "Context List",
                    target=member,
                    reason="No notes"
                )
                return
            formatted = "\n".join(notes)
            await interaction.response.send_message(f"📒 Context notes for {member.mention}:\n{formatted}", ephemeral=True)
            await self.log_action(
                interaction.guild,
                interaction.user,
                "Context List",
                target=member,
                reason=f"Listed {len(notes)} notes"
            )

        elif action == "clear":
            await self.redis.delete(key)
            await interaction.response.send_message(f"🗑️ Cleared all context notes for {member.mention}", ephemeral=True)
            await self.log_action(
                interaction.guild,
                interaction.user,
                "Context Clear",
                target=member,
                reason="Cleared notes"
            )

        else:
            await interaction.response.send_message("❌ Action must be 'add', 'list', or 'clear'.", ephemeral=True)

    # --------- Commands: Staff management (admins only) ---------
    @app_commands.command(name="staff", description="Manage staff list (admins only)")
    @app_commands.describe(action="add/remove/list")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def staff(self, interaction: discord.Interaction, action: str, member: discord.Member = None):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⛔ Only administrators can manage staff.", ephemeral=True)
            return

        if action == "add":
            if not member:
                await interaction.response.send_message("❌ You must specify a user to add.", ephemeral=True)
                return
            await self.redis.sadd(self.staff_key, str(member.id))
            await interaction.response.send_message(f"✅ {member.mention} added to staff list.", ephemeral=True)
            await self.log_action(
                interaction.guild,
                interaction.user,
                "Staff Add",
                target=member,
                reason="Added to internal staff list"
            )

        elif action == "remove":
            if not member:
                await interaction.response.send_message("❌ You must specify a user to remove.", ephemeral=True)
                return
            await self.redis.srem(self.staff_key, str(member.id))
            await interaction.response.send_message(f"✅ {member.mention} removed from staff list.", ephemeral=True)
            await self.log_action(
                interaction.guild,
                interaction.user,
                "Staff Remove",
                target=member,
                reason="Removed from internal staff list"
            )

        elif action == "list":
            staff_ids = await self.redis.smembers(self.staff_key)
            if not staff_ids:
                await interaction.response.send_message("📭 No staff members registered.", ephemeral=True)
                await self.log_action(
                    interaction.guild,
                    interaction.user,
                    "Staff List",
                    reason="No staff in list"
                )
                return

            mentions = []
            for uid in staff_ids:
                m = interaction.guild.get_member(int(uid))
                mentions.append(m.mention if m else f"<@{uid}>")

            await interaction.response.send_message("👥 Staff list:\n" + ", ".join(mentions), ephemeral=True)
            await self.log_action(
                interaction.guild,
                interaction.user,
                "Staff List",
                reason=f"Listed {len(mentions)} staff members"
            )

        else:
            await interaction.response.send_message("❌ Action must be 'add', 'remove', or 'list'.", ephemeral=True)

    # --------- Commands: Case retrieval ---------
    @app_commands.command(name="case", description="Retrieve details of a specific moderation case")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def case(self, interaction: discord.Interaction, case_id: int):
        if not await self.is_staff_or_admin(interaction.user):
            await interaction.response.send_message("⛔ Unauthorized.", ephemeral=True)
            return

        data = await self.redis.get(f"moderation:case:{case_id}")
        if not data:
            await interaction.response.send_message(f"❌ Case ID #{case_id} not found.", ephemeral=True)
            return

        case = json.loads(data)
        guild = interaction.guild

        moderator = guild.get_member(case["moderator_id"])
        target = guild.get_member(case["target_id"]) if case["target_id"] else None

        # Rebuild embed
        try:
            ts = datetime.fromisoformat(case["timestamp"])
        except Exception:
            ts = datetime.now(timezone.utc)

        embed = discord.Embed(
            title="👮 Staff Action (Retrieved)",
            description=f"**{case['action']}**",
            color=discord.Color(case["color"]),
            timestamp=ts
        )
        mod_val = moderator.mention if moderator else f"<@{case['moderator_id']}>"
        tgt_val = target.mention if target else (f"<@{case['target_id']}>" if case["target_id"] else "—")
        embed.add_field(name="Moderator", value=mod_val, inline=True)
        embed.add_field(name="Target", value=tgt_val, inline=True)
        embed.add_field(name="Reason/Details", value=(case["reason"] or "No reason provided"), inline=False)
        embed.set_footer(text=f"Case ID #{case_id} • Guild: {guild.name}")

        await interaction.response.send_message(embed=embed, ephemeral=True)

        # Audit that a case was retrieved
        await self.log_action(
            interaction.guild,
            interaction.user,
            "Case Retrieve",
            reason=f"Retrieved Case #{case_id}"
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
    log.info("⚙️ Moderation cog loaded")
