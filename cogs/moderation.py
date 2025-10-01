import logging
import json
from datetime import datetime, timezone, timedelta

import discord
from discord.ext import commands
from discord import app_commands
import redis.asyncio as redis

log = logging.getLogger("cog-moderation")

# --------- Config ---------
GUILD_ID = 1293611593845706793
LOG_CHANNEL_ID = 1421465080238964796
REDIS_URL = "redis://default:WEQfFAaMkvNPFvEzOpAQsGdDTTbaFzOr@redis-436594b0.railway.internal:6379"

AUCTION_CAP = 5  # seuil unique pour auction warnings
ALL_BAN_ROLE_ID = 123456789012345678  # à remplacer par l'ID de ton rôle global de ban

CATEGORY_ROLES = {
    "Auction": 1303763640951767041,
    "Crosstrade": 1306954214106202144,
    "Market": 1306958134245457970,
    "Pricing": 1313628932611768350,
    "Spawn": 1326322514002968727
}


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

    # --------- Access control ---------
    async def is_staff_or_admin(self, user: discord.Member) -> bool:
        if user.guild_permissions.administrator:
            return True
        return await self.redis.sismember(self.staff_key, str(user.id))

    # --------- Logging (embeds + case IDs) ---------
    async def log_action(
        self,
        guild: discord.Guild,
        moderator: discord.Member,
        action: str,
        target: discord.Member = None,
        reason: str = None,
        category: str = None
    ):
        log_channel = guild.get_channel(LOG_CHANNEL_ID)
        if not log_channel:
            return

        case_id = await self.redis.incr("moderation:case_id")

        # Color coding
        action_l = (action or "").lower()
        if category == "auction":
            color = discord.Color.gold()
        elif category == "general":
            color = discord.Color.blue()
        elif category == "ban":
            color = discord.Color.red()
        elif category == "timeout":
            color = discord.Color.orange()
        elif action_l.startswith("context"):
            color = discord.Color.purple()
        elif action_l.startswith("staff"):
            color = discord.Color.green()
        elif action_l.startswith("case"):
            color = discord.Color.dark_gray()
        else:
            color = discord.Color.blurple()

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
            "category": category,
            "color": color.value,
            "timestamp": now.isoformat()
        }
        await self.redis.set(f"moderation:case:{case_id}", json.dumps(case_data))

    # --------- Commands: Warnings ---------
    @app_commands.command(name="warn-auction", description="Issue an auction warning")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def warn_auction(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        if not await self.is_staff_or_admin(interaction.user):
            await interaction.response.send_message("⛔ Unauthorized.", ephemeral=True)
            return

        key = f"warns:auction:{member.id}"
        count = await self.redis.incr(key)

        # DM the user
        try:
            await member.send(
                f"⚠️ You have received an **Auction Warning** in **{interaction.guild.name}**.\n"
                f"**Reason:** {reason}\n"
                f"**Issued by:** {interaction.user.display_name}\n"
                f"**Total Auction Warnings:** {count}/{AUCTION_CAP}"
            )
        except discord.Forbidden:
            pass

        await self.log_action(
            interaction.guild,
            interaction.user,
            "Warn (Auction)",
            target=member,
            reason=f"{reason} • Count: {count}",
            category="auction"
        )

        await interaction.response.send_message(
            f"⚠️ Auction warning issued to {member.mention} (now at {count}/{AUCTION_CAP})",
            ephemeral=True
        )

        if count >= AUCTION_CAP:
            await self.log_action(
                interaction.guild,
                interaction.user,
                f"Auction Warning Threshold Reached ({AUCTION_CAP})",
                target=member,
                reason=f"Count: {count}",
                category="auction"
            )

    @app_commands.command(name="warn-general", description="Issue a general warning")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def warn_general(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        if not await self.is_staff_or_admin(interaction.user):
            await interaction.response.send_message("⛔ Unauthorized.", ephemeral=True)
            return

        key = f"warns:general:{member.id}"
        count = await self.redis.incr(key)

        try:
            await member.send(
                f"⚠️ You have received a **General Warning** in **{interaction.guild.name}**.\n"
                f"**Reason:** {reason}\n"
                f"**Issued by:** {interaction.user.display_name}\n"
                f"**Total General Warnings:** {count}"
            )
        except discord.Forbidden:
            pass

        await self.log_action(
            interaction.guild,
            interaction.user,
            "Warn (General)",
            target=member,
            reason=f"{reason} • Count: {count}",
            category="general"
        )

        await interaction.response.send_message(
            f"⚠️ General warning issued to {member.mention} (now at {count})",
            ephemeral=True
        )

    # --------- Commands: Warnings view/clear ---------
    @app_commands.command(name="warnings", description="Check a user's warnings")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def warnings(self, interaction: discord.Interaction, member: discord.Member):
        if not await self.is_staff_or_admin(interaction.user):
            await interaction.response.send_message("⛔ Unauthorized.", ephemeral=True)
            return

        auction = int(await self.redis.get(f"warns:auction:{member.id}") or 0)
        general = int(await self.redis.get(f"warns:general:{member.id}") or 0)

        text = (
            f"📊 Warnings for {member.mention}:\n"
            f"- Auction: {auction}/{AUCTION_CAP}\n"
            f"- General: {general}"
        )
        await interaction.response.send_message(text, ephemeral=True)

        # Audit log (view)
        await self.log_action(
            interaction.guild,
            interaction.user,
            "Warnings View",
            target=member,
            reason=f"Auction={auction}, General={general}"
        )

    @app_commands.command(name="clear-warnings", description="Clear a user's warnings")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def clear_warnings(self, interaction: discord.Interaction, member: discord.Member, category: str):
        if not await self.is_staff_or_admin(interaction.user):
            await interaction.response.send_message("⛔ Unauthorized.", ephemeral=True)
            return

        if category == "auction":
            await self.redis.delete(f"warns:auction:{member.id}")
        elif category == "general":
            await self.redis.delete(f"warns:general:{member.id}")
        else:
            await interaction.response.send_message("❌ Category must be 'auction' or 'general'.", ephemeral=True)
            return

        await interaction.response.send_message(f"✅ Cleared {category} warnings for {member.mention}", ephemeral=True)
        await self.log_action(interaction.guild, interaction.user, f"Clear Warnings ({category})", target=member)

    # --------- Commands: Context Notes ---------
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

        color = discord.Color(case["color"])

        embed = discord.Embed(
            title="👮 Staff Action (Retrieved)",
            description=f"**{case['action']}**",
            color=color,
            timestamp=ts
        )
        mod_val = moderator.mention if moderator else f"<@{case['moderator_id']}>"
        tgt_val = target.mention if target else (f"<@{case['target_id']}>" if case["target_id"] else "—")
        embed.add_field(name="Moderator", value=mod_val, inline=True)
        embed.add_field(name="Target", value=tgt_val, inline=True)
        embed.add_field(name="Reason/Details", value=(case["reason"] or "No reason provided"), inline=False)
        embed.set_footer(text=f"Case ID #{case_id} • Guild: {guild.name}")

        await interaction.response.send_message(embed=embed, ephemeral=True)

        await self.log_action(
            interaction.guild,
            interaction.user,
            "Case Retrieve",
            reason=f"Retrieved Case #{case_id}"
        )

    # --------- Commands: Ban (roles par catégorie) ---------
    @app_commands.command(name="ban", description="Give a ban role to a member by category")
    @app_commands.describe(reason="Reason for the ban", time="Optional duration")
    @app_commands.choices(category=[
        app_commands.Choice(name="Auction", value="Auction"),
        app_commands.Choice(name="Market", value="Market"),
        app_commands.Choice(name="Crosstrade", value="Crosstrade"),
        app_commands.Choice(name="Spawn", value="Spawn"),
        app_commands.Choice(name="Pricing", value="Pricing")
    ])
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def ban(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        category: app_commands.Choice[str],
        reason: str,
        time: str = None
    ):
        if not await self.is_staff_or_admin(interaction.user):
            await interaction.response.send_message("⛔ Unauthorized.", ephemeral=True)
            return

        role_id = CATEGORY_ROLES[category.value]
        role = interaction.guild.get_role(role_id)
        if not role:
            await interaction.response.send_message("❌ Role not found in guild.", ephemeral=True)
            return

        await member.add_roles(role, reason=reason)

        sanction = {
            "type": "ban-role",
            "category": category.value,
            "reason": reason,
            "moderator": interaction.user.id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "duration": time
        }
        await self.redis.rpush(f"sanctions:{member.id}", json.dumps(sanction))

        await self.log_action(
            interaction.guild,
            interaction.user,
            f"Ban Role ({category.value})",
            target=member,
            reason=f"{reason} • Duration: {time or 'Permanent'}",
            category="ban"
        )

        await interaction.response.send_message(
            f"🔨 {member.mention} has been given the **{category.value} ban role**.\nReason: {reason}",
            ephemeral=True
        )

    # --------- Commands: All-Ban (rôle global) ---------
    @app_commands.command(name="all-ban", description="Give a global ban role to a member")
    @app_commands.describe(reason="Reason for the ban", time="Optional duration")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def all_ban(self, interaction: discord.Interaction, member: discord.Member, reason: str, time: str = None):
        if not await self.is_staff_or_admin(interaction.user):
            await interaction.response.send_message("⛔ Unauthorized.", ephemeral=True)
            return

        role = interaction.guild.get_role(ALL_BAN_ROLE_ID)
        if not role:
            await interaction.response.send_message("❌ Global ban role not found.", ephemeral=True)
            return

        await member.add_roles(role, reason=reason)

        sanction = {
            "type": "all-ban",
            "reason": reason,
            "moderator": interaction.user.id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "duration": time
        }
        await self.redis.rpush(f"sanctions:{member.id}", json.dumps(sanction))

        await self.log_action(
            interaction.guild,
            interaction.user,
            "All-Ban",
            target=member,
            reason=f"{reason} • Duration: {time or 'Permanent'}",
            category="ban"
        )

        await interaction.response.send_message(
            f"🚫 {member.mention} has been given the **All-Ban role**.\nReason: {reason}",
            ephemeral=True
        )

    # --------- Commands: Timeout ---------
    @app_commands.command(name="timeout", description="Timeout a member")
    @app_commands.describe(reason="Reason for the timeout", time="Duration in minutes")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def timeout(self, interaction: discord.Interaction, member: discord.Member, reason: str, time: int):
        if not await self.is_staff_or_admin(interaction.user):
            await interaction.response.send_message("⛔ Unauthorized.", ephemeral=True)
            return

        until = datetime.now(timezone.utc) + timedelta(minutes=time)
        try:
            await member.timeout(until, reason=reason)
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to timeout: {e}", ephemeral=True)
            return

        sanction = {
            "type": "timeout",
            "reason": reason,
            "moderator": interaction.user.id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "duration": f"{time} minutes"
        }
        await self.redis.rpush(f"sanctions:{member.id}", json.dumps(sanction))

        await self.log_action(
            interaction.guild,
            interaction.user,
            "Timeout",
            target=member,
            reason=f"{reason} • Duration: {time} minutes",
            category="timeout"
        )

        await interaction.response.send_message(
            f"⏳ {member.mention} has been timed out for {time} minutes.\nReason: {reason}",
            ephemeral=True
        )

    # --------- User profile + Sanctions button ---------
    class SanctionsView(discord.ui.View):
        def __init__(self, cog: "Moderation", member_id: int, *, timeout: float = 180):
            super().__init__(timeout=timeout)
            self.cog = cog
            self.member_id = member_id

        @discord.ui.button(label="Sanctions", style=discord.ButtonStyle.red)
        async def show_sanctions(self, interaction: discord.Interaction, button: discord.ui.Button):
            # Staff-only
            if not await self.cog.is_staff_or_admin(interaction.user):
                await interaction.response.send_message("⛔ Unauthorized.", ephemeral=True)
                return

            sanctions = await self.cog.redis.lrange(f"sanctions:{self.member_id}", 0, -1)
            if not sanctions:
                await interaction.response.send_message("📭 No sanctions found.", ephemeral=True)
                return

            lines = []
            for raw in sanctions:
                s = json.loads(raw)
                t = s.get("type", "unknown")
                cat = s.get("category")
                rsn = s.get("reason") or "No reason"
                dur = s.get("duration")
                mod = s.get("moderator")
                ts = s.get("timestamp")
                line = f"- [{ts}] {t}{f' ({cat})' if cat else ''} • {rsn}{f' • Duration: {dur}' if dur else ''} • by <@{mod}>"
                lines.append(line)

            text = "📒 Sanctions:\n" + "\n".join(lines)
            await interaction.response.send_message(text, ephemeral=True)

    @app_commands.command(name="user", description="Show user profile with sanctions")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def user_profile(self, interaction: discord.Interaction, member: discord.Member):
        # Staff-only
        if not await self.is_staff_or_admin(interaction.user):
            await interaction.response.send_message("⛔ Unauthorized.", ephemeral=True)
            return

        sanctions = await self.redis.lrange(f"sanctions:{member.id}", 0, -1)
        sanction_count = len(sanctions)

        joined = member.joined_at.strftime("%Y-%m-%d %H:%M UTC") if member.joined_at else "Unknown"
        roles = [r.mention for r in member.roles if r != interaction.guild.default_role]
        roles_text = ", ".join(roles) if roles else "None"

        embed = discord.Embed(
            title=f"User Profile: {member.display_name}",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_thumbnail(url=member.display_avatar.url if member.display_avatar else discord.Embed.Empty)
        embed.add_field(name="Joined", value=joined, inline=True)
        embed.add_field(name="Roles", value=roles_text, inline=False)
        embed.add_field(name="Sanctions", value=str(sanction_count), inline=True)

        view = Moderation.SanctionsView(self, member.id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

        await self.log_action(
            interaction.guild,
            interaction.user,
            "User Profile View",
            target=member,
            reason=f"Sanctions count: {sanction_count}"
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
    log.info("⚙️ Moderation cog loaded")
