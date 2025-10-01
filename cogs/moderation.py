# cogs/moderation.py
import os
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List

import discord
from discord.ext import commands, tasks
from discord import app_commands
import redis.asyncio as redis

log = logging.getLogger("cog-moderation")

# --------- Config via Railway environment ---------
GUILD_ID = int(os.getenv("GUILD_ID"))
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID"))
REDIS_URL = os.getenv("REDIS_URL")

AUCTION_CAP = int(os.getenv("AUCTION_CAP", "5"))
ALL_BAN_ROLE_ID = int(os.getenv("ALL_BAN_ROLE_ID"))

CATEGORY_ROLES = {
    "Auction": int(os.getenv("ROLE_AUCTION")),
    "Crosstrade": int(os.getenv("ROLE_CROSSTRADE")),
    "Market": int(os.getenv("ROLE_MARKET")),
    "Pricing": int(os.getenv("ROLE_PRICING")),
    "Spawn": int(os.getenv("ROLE_SPAWN")),
}


def parse_duration_to_timedelta(duration: Optional[str]) -> Optional[timedelta]:
    if not duration:
        return None
    s = duration.strip().lower()
    try:
        if "min" in s:
            n = int(s.split()[0])
            return timedelta(minutes=n)
        if "hour" in s or s.endswith("h"):
            n = int(s.split()[0].replace("h", "")) if " " in s else int(s.strip("h"))
            return timedelta(hours=n)
        if "day" in s or s.endswith("d"):
            n = int(s.split()[0].replace("d", "")) if " " in s else int(s.strip("d"))
            return timedelta(days=n)
    except Exception:
        return None
    return None


class Moderation(commands.Cog):
    staff_key = "staff:members"

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.redis: Optional[redis.Redis] = None
        self.check_expired.start()

    async def cog_load(self):
        self.redis = redis.from_url(REDIS_URL, decode_responses=True)
        log.info("Moderation cog connected to Redis")

    async def cog_unload(self):
        if self.redis:
            await self.redis.close()
        self.check_expired.cancel()
        log.info("Moderation cog disconnected from Redis")

    # --------- Background task: remove expired ban roles ---------
    @tasks.loop(minutes=1)
    async def check_expired(self):
        guild = self.bot.get_guild(GUILD_ID)
        if not guild or not self.redis:
            return

        keys = await self.redis.keys("sanctions:*")
        for key in keys:
            member_id = int(key.split(":")[1])
            member = guild.get_member(member_id)
            if not member:
                continue

            sanctions = await self.redis.lrange(key, 0, -1)
            keep: List[str] = []
            now = datetime.now(timezone.utc)

            for raw in sanctions:
                try:
                    s = json.loads(raw)
                except Exception:
                    keep.append(raw)
                    continue

                duration = s.get("duration")
                start_iso = s.get("timestamp")
                td = parse_duration_to_timedelta(duration)
                if td and start_iso:
                    try:
                        start = datetime.fromisoformat(start_iso)
                    except Exception:
                        start = None
                    if start and now >= (start + td):
                        stype = s.get("type")
                        if stype == "ban-role":
                            cat = s.get("category")
                            role_id = CATEGORY_ROLES.get(cat)
                            role = guild.get_role(role_id) if role_id else None
                            if role and role in member.roles:
                                try:
                                    await member.remove_roles(role, reason="Ban expired")
                                except discord.Forbidden:
                                    pass
                        elif stype == "all-ban":
                            role = guild.get_role(ALL_BAN_ROLE_ID)
                            if role and role in member.roles:
                                try:
                                    await member.remove_roles(role, reason="All-ban expired")
                                except discord.Forbidden:
                                    pass
                        continue
                keep.append(raw)

            await self.redis.delete(key)
            if keep:
                await self.redis.rpush(key, *keep)

    # --------- Access control ---------
    async def is_staff_or_admin(self, user: discord.Member) -> bool:
        if user.guild_permissions.administrator:
            return True
        return await self.redis.sismember(self.staff_key, str(user.id))

    # --------- Logging ---------
    async def log_action(self, guild, moderator, action, target=None, reason=None, category=None):
        log_channel = guild.get_channel(LOG_CHANNEL_ID)
        if not log_channel:
            return
        case_id = await self.redis.incr("moderation:case_id")
        embed = discord.Embed(
            title="👮 Staff Action",
            description=f"**{action}**",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="Moderator", value=moderator.mention, inline=True)
        embed.add_field(name="Target", value=(target.mention if target else "—"), inline=True)
        embed.add_field(name="Reason/Details", value=(reason or "No reason"), inline=False)
        embed.set_footer(text=f"Case ID #{case_id}")
        await log_channel.send(embed=embed)
        await self.redis.set(f"moderation:case:{case_id}", json.dumps({
            "action": action,
            "moderator_id": moderator.id,
            "target_id": target.id if target else None,
            "reason": reason,
            "category": category,
            "color": embed.color.value,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }))

    # --------- Warns ---------
    @app_commands.command(name="warn-auction", description="Issue an auction warning")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def warn_auction(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        if not await self.is_staff_or_admin(interaction.user):
            return await interaction.response.send_message("⛔ Unauthorized.", ephemeral=True)
        key = f"warns:auction:{member.id}"
        count = await self.redis.incr(key)
        sanction = {
            "type": "warn-auction",
            "reason": reason,
            "moderator": interaction.user.id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "count": count
        }
        await self.redis.rpush(f"sanctions:{member.id}", json.dumps(sanction))
        # DM
        try:
            await member.send(
                f"⚠️ You have received an Auction Warning in {interaction.guild.name}.\n"
                f"Reason: {reason}\nTotal Auction Warnings: {count}/{AUCTION_CAP}"
            )
        except discord.Forbidden:
            pass
        await self.log_action(interaction.guild, interaction.user, "Warn (Auction)", target=member, reason=f"{reason} • Count {count}", category="auction")
        await interaction.response.send_message(f"⚠️ Auction warning issued to {member.mention} ({count}/{AUCTION_CAP})", ephemeral=True)

        if count >= AUCTION_CAP:
            ban_role = interaction.guild.get_role(ALL_BAN_ROLE_ID)
            applied = False
            if ban_role:
                try:
                    await member.add_roles(ban_role, reason=f"Auction warnings >= {AUCTION_CAP}")
                    applied = True
                except discord.Forbidden:
                    pass
            auction_role_id = CATEGORY_ROLES.get("Auction")
            if auction_role_id:
                role = interaction.guild.get_role(auction_role_id)
                if role:
                    try:
                        await member.add_roles(role, reason="Auction threshold reached")
                        applied = True
                    except discord.Forbidden:
                        pass
            await self.log_action(
                interaction.guild, interaction.user,
                f"Auction Threshold Action (>= {AUCTION_CAP})",
                target=member,
                reason=f"Count: {count} • Roles applied: {applied}",
                category="auction"
            )
            try:
                await member.send(
                    f"⛔ You reached the auction warning threshold in {interaction.guild.name} ({count}/{AUCTION_CAP}).\n"
                    f"Moderation actions were applied. You can appeal to the staff."
                )
            except discord.Forbidden:
                pass

    @app_commands.command(name="warn-general", description="Issue a general warning")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def warn_general(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        if not await self.is_staff_or_admin(interaction.user):
            return await interaction.response.send_message("⛔ Unauthorized.", ephemeral=True)
        key = f"warns:general:{member.id}"
        count = await self.redis.incr(key)
        sanction = {
            "type": "warn-general",
            "reason": reason,
            "moderator": interaction.user.id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "count": count
        }
        await self.redis.rpush(f"sanctions:{member.id}", json.dumps(sanction))
        # DM
        try:
            await member.send(
                f"⚠️ You have received a General Warning in {interaction.guild.name}.\n"
                f"Reason: {reason}\nTotal General Warnings: {count}"
            )
        except discord.Forbidden:
            pass
        await self.log_action(interaction.guild, interaction.user, "Warn (General)", target=member, reason=f"{reason} • Count {count}", category="general")
        await interaction.response.send_message(f"⚠️ General warning issued to {member.mention} (now at {count})", ephemeral=True)

    # --------- Ban (category role) ---------
    @app_commands.choices(category=[
        app_commands.Choice(name="Auction", value="Auction"),
        app_commands.Choice(name="Market", value="Market"),
        app_commands.Choice(name="Crosstrade", value="Crosstrade"),
        app_commands.Choice(name="Spawn", value="Spawn"),
        app_commands.Choice(name="Pricing", value="Pricing")
    ])
    @app_commands.command(name="ban", description="Give a ban role to a member by category")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def ban(self, interaction: discord.Interaction, member: discord.Member, category: app_commands.Choice[str], reason: str, time: Optional[str] = None):
        if not await self.is_staff_or_admin(interaction.user):
            return await interaction.response.send_message("⛔ Unauthorized.", ephemeral=True)

        role_id = CATEGORY_ROLES.get(category.value)
        role = interaction.guild.get_role(role_id) if role_id else None
        if not role:
            return await interaction.response.send_message("❌ Role not found in guild.", ephemeral=True)

        try:
            await member.add_roles(role, reason=reason)
        except discord.Forbidden:
            return await interaction.response.send_message("❌ Missing permissions to add role.", ephemeral=True)

        sanction = {
            "type": "ban-role",
            "category": category.value,
            "reason": reason,
            "moderator": interaction.user.id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "duration": time
        }
        await self.redis.rpush(f"sanctions:{member.id}", json.dumps(sanction))

        # DM the user
        try:
            await member.send(
                f"🔨 You have been banned from **{category.value}** in **{interaction.guild.name}**.\n"
                f"Reason: {reason}\n"
                f"Duration: {time or 'Permanent'}"
            )
        except discord.Forbidden:
            pass

        await self.log_action(
            interaction.guild,
            interaction.user,
            f"Ban Role ({category.value})",
            target=member,
            reason=f"{reason} • Duration: {time or 'Permanent'}",
            category="ban"
        )

        await interaction.response.send_message(
            f"🔨 {member.mention} has been given the **{category.value}** ban role.\nReason: {reason}",
            ephemeral=True
        )

    # --------- Unban commands ---------
    @app_commands.choices(category=[
        app_commands.Choice(name="Auction", value="Auction"),
        app_commands.Choice(name="Market", value="Market"),
        app_commands.Choice(name="Crosstrade", value="Crosstrade"),
        app_commands.Choice(name="Spawn", value="Spawn"),
        app_commands.Choice(name="Pricing", value="Pricing")
    ])
    @app_commands.command(name="unban", description="Remove a category ban role from a member")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def unban(self, interaction: discord.Interaction, member: discord.Member, category: app_commands.Choice[str]):
        if not await self.is_staff_or_admin(interaction.user):
            return await interaction.response.send_message("⛔ Unauthorized.", ephemeral=True)

        role_id = CATEGORY_ROLES.get(category.value)
        role = interaction.guild.get_role(role_id) if role_id else None
        if role and role in member.roles:
            try:
                await member.remove_roles(role, reason="Unban command")
            except discord.Forbidden:
                return await interaction.response.send_message("❌ Missing permissions to remove role.", ephemeral=True)
            await self.log_action(interaction.guild, interaction.user, f"Unban ({category.value})", target=member, category="ban")
            await interaction.response.send_message(f"✅ {member.mention} unbanned from {category.value}", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Role not found or not applied.", ephemeral=True)

    # --------- Global ban ---------
    @app_commands.command(name="all-ban", description="Give a global ban role to a member")
    @app_commands.describe(reason="Reason for the ban", time="Optional duration (e.g. '2 days')")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def all_ban(self, interaction: discord.Interaction, member: discord.Member, reason: str, time: Optional[str] = None):
        if not await self.is_staff_or_admin(interaction.user):
            return await interaction.response.send_message("⛔ Unauthorized.", ephemeral=True)

        role = interaction.guild.get_role(ALL_BAN_ROLE_ID)
        if not role:
            return await interaction.response.send_message("❌ Global ban role not found.", ephemeral=True)

        try:
            await member.add_roles(role, reason=reason)
        except discord.Forbidden:
            return await interaction.response.send_message("❌ Missing permissions to add role.", ephemeral=True)

        sanction = {
            "type": "all-ban",
            "reason": reason,
            "moderator": interaction.user.id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "duration": time
        }
        await self.redis.rpush(f"sanctions:{member.id}", json.dumps(sanction))

        # DM the user
        try:
            await member.send(
                f"🚫 You have received a **Global Ban** in **{interaction.guild.name}**.\n"
                f"Reason: {reason}\n"
                f"Duration: {time or 'Permanent'}"
            )
        except discord.Forbidden:
            pass

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

    @app_commands.command(name="all-unban", description="Remove the global ban role from a member")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def all_unban(self, interaction: discord.Interaction, member: discord.Member):
        if not await self.is_staff_or_admin(interaction.user):
            return await interaction.response.send_message("⛔ Unauthorized.", ephemeral=True)

        role = interaction.guild.get_role(ALL_BAN_ROLE_ID)
        if role and role in member.roles:
            try:
                await member.remove_roles(role, reason="All-unban command")
            except discord.Forbidden:
                return await interaction.response.send_message("❌ Missing permissions to remove role.", ephemeral=True)
            await self.log_action(interaction.guild, interaction.user, "All-Unban", target=member, category="ban")
            await interaction.response.send_message(f"✅ {member.mention} global ban removed.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Global ban role not applied.", ephemeral=True)

    # --------- Timeout ---------
    @app_commands.command(name="timeout", description="Timeout a member")
    @app_commands.describe(reason="Reason for the timeout", time="Duration in minutes")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def timeout(self, interaction: discord.Interaction, member: discord.Member, reason: str, time: int):
        if not await self.is_staff_or_admin(interaction.user):
            return await interaction.response.send_message("⛔ Unauthorized.", ephemeral=True)

        until = datetime.now(timezone.utc) + timedelta(minutes=time)
        try:
            await member.timeout(until, reason=reason)
        except Exception as e:
            return await interaction.response.send_message(f"❌ Failed to timeout: {e}", ephemeral=True)

        sanction = {
            "type": "timeout",
            "reason": reason,
            "moderator": interaction.user.id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "duration": f"{time} minutes"
        }
        await self.redis.rpush(f"sanctions:{member.id}", json.dumps(sanction))

        # DM the user
        try:
            await member.send(
                f"⏳ You have been put in **timeout** in **{interaction.guild.name}**.\n"
                f"Reason: {reason}\n"
                f"Duration: {time} minutes"
            )
        except discord.Forbidden:
            pass

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

    # --------- Warnings view/clear ---------
    @app_commands.command(name="warnings", description="Check a user's warnings")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def warnings(self, interaction: discord.Interaction, member: discord.Member):
        if not await self.is_staff_or_admin(interaction.user):
            return await interaction.response.send_message("⛔ Unauthorized.", ephemeral=True)

        auction = int(await self.redis.get(f"warns:auction:{member.id}") or 0)
        general = int(await self.redis.get(f"warns:general:{member.id}") or 0)

        text = (
            f"📊 Warnings for {member.mention}:\n"
            f"- Auction: {auction}/{AUCTION_CAP}\n"
            f"- General: {general}"
        )
        await interaction.response.send_message(text, ephemeral=True)

        await self.log_action(
            interaction.guild,
            interaction.user,
            "Warnings View",
            target=member,
            reason=f"Auction={auction}, General={general}"
        )

    @app_commands.describe(category="Choose category to clear")
    @app_commands.choices(category=[
        app_commands.Choice(name="auction", value="auction"),
        app_commands.Choice(name="general", value="general"),
    ])
    @app_commands.command(name="clear-warnings", description="Clear a user's warnings")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def clear_warnings(self, interaction: discord.Interaction, member: discord.Member, category: app_commands.Choice[str]):
        if not await self.is_staff_or_admin(interaction.user):
            return await interaction.response.send_message("⛔ Unauthorized.", ephemeral=True)

        if category.value == "auction":
            await self.redis.delete(f"warns:auction:{member.id}")
        else:
            await self.redis.delete(f"warns:general:{member.id}")

        await interaction.response.send_message(f"✅ Cleared {category.value} warnings for {member.mention}", ephemeral=True)
        await self.log_action(interaction.guild, interaction.user, f"Clear Warnings ({category.value})", target=member)

    # --------- Context notes ---------
    @app_commands.describe(action="Select action", note="Only required when adding")
    @app_commands.choices(action=[
        app_commands.Choice(name="add", value="add"),
        app_commands.Choice(name="list", value="list"),
        app_commands.Choice(name="clear", value="clear"),
    ])
    @app_commands.command(name="context", description="Add, list, or clear context notes for a user")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def context(self, interaction: discord.Interaction, member: discord.Member, action: app_commands.Choice[str], note: Optional[str] = None):
        if not await self.is_staff_or_admin(interaction.user):
            return await interaction.response.send_message("⛔ Unauthorized.", ephemeral=True)

        key = f"context:{member.id}"

        if action.value == "add":
            if not note:
                return await interaction.response.send_message("❌ You must provide a note when adding.", ephemeral=True)
            if len(note) > 500:
                return await interaction.response.send_message("❌ Note too long (max 500 chars).", ephemeral=True)
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            entry = f"[{timestamp}] {interaction.user.display_name}: {note}"
            await self.redis.rpush(key, entry)
            await interaction.response.send_message(f"📝 Added context note for {member.mention}", ephemeral=True)
            await self.log_action(interaction.guild, interaction.user, "Context Add", target=member, reason=entry)

        elif action.value == "list":
            notes = await self.redis.lrange(key, 0, -1)
            if not notes:
                await interaction.response.send_message("📭 No context notes for this user.", ephemeral=True)
                await self.log_action(interaction.guild, interaction.user, "Context List", target=member, reason="No notes")
                return
            formatted = "\n".join(notes[:20])
            more = f"\n… and {len(notes)-20} more." if len(notes) > 20 else ""
            await interaction.response.send_message(f"📒 Context notes for {member.mention}:\n{formatted}{more}", ephemeral=True)
            await self.log_action(interaction.guild, interaction.user, "Context List", target=member, reason=f"Listed {len(notes)} notes")

        else:
            await self.redis.delete(key)
            await interaction.response.send_message(f"🗑️ Cleared all context notes for {member.mention}", ephemeral=True)
            await self.log_action(interaction.guild, interaction.user, "Context Clear", target=member, reason="Cleared notes")

    # --------- Staff management (admins only) ---------
    @app_commands.describe(action="Select action")
    @app_commands.choices(action=[
        app_commands.Choice(name="add", value="add"),
        app_commands.Choice(name="remove", value="remove"),
        app_commands.Choice(name="list", value="list"),
    ])
    @app_commands.command(name="staff", description="Manage staff list (admins only)")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def staff(self, interaction: discord.Interaction, action: app_commands.Choice[str], member: Optional[discord.Member] = None):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("⛔ Only administrators can manage staff.", ephemeral=True)

        if action.value == "add":
            if not member:
                return await interaction.response.send_message("❌ You must specify a user to add.", ephemeral=True)
            await self.redis.sadd(self.staff_key, str(member.id))
            await interaction.response.send_message(f"✅ {member.mention} added to staff list.", ephemeral=True)
            await self.log_action(interaction.guild, interaction.user, "Staff Add", target=member, reason="Added to internal staff list")

        elif action.value == "remove":
            if not member:
                return await interaction.response.send_message("❌ You must specify a user to remove.", ephemeral=True)
            await self.redis.srem(self.staff_key, str(member.id))
            await interaction.response.send_message(f"✅ {member.mention} removed from staff list.", ephemeral=True)
            await self.log_action(interaction.guild, interaction.user, "Staff Remove", target=member, reason="Removed from internal staff list")

        else:
            staff_ids = await self.redis.smembers(self.staff_key)
            if not staff_ids:
                await interaction.response.send_message("📭 No staff members registered.", ephemeral=True)
                await self.log_action(interaction.guild, interaction.user, "Staff List", reason="No staff in list")
                return
            mentions = []
            for uid in staff_ids:
                m = interaction.guild.get_member(int(uid))
                mentions.append(m.mention if m else f"<@{uid}>")
            await interaction.response.send_message(f"👥 Staff list ({len(mentions)}):\n" + ", ".join(mentions), ephemeral=True)
            await self.log_action(interaction.guild, interaction.user, "Staff List", reason=f"Listed {len(mentions)} staff members")

    # --------- Case retrieval ---------
    @app_commands.command(name="case", description="Retrieve details of a specific moderation case")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def case(self, interaction: discord.Interaction, case_id: int):
        if not await self.is_staff_or_admin(interaction.user):
            return await interaction.response.send_message("⛔ Unauthorized.", ephemeral=True)

        data = await self.redis.get(f"moderation:case:{case_id}")
        if not data:
            return await interaction.response.send_message(f"❌ Case ID #{case_id} not found.", ephemeral=True)

        case = json.loads(data)
        guild = interaction.guild

        moderator = guild.get_member(case["moderator_id"])
        target = guild.get_member(case["target_id"]) if case["target_id"] else None

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
        embed.add_field(name="Reason/Details", value=(case.get("reason") or "No reason provided"), inline=False)
        embed.add_field(name="Category", value=(case.get("category") or "—"), inline=True)
        embed.set_footer(text=f"Case ID #{case_id} • Guild: {guild.name}")

        await interaction.response.send_message(embed=embed, ephemeral=True)
        await self.log_action(interaction.guild, interaction.user, "Case Retrieve", reason=f"Retrieved Case #{case_id}")

    # --------- Sanctions list ---------
    @app_commands.command(name="sanctions", description="List all sanctions for a user")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def sanctions(self, interaction: discord.Interaction, member: discord.Member):
        if not await self.is_staff_or_admin(interaction.user):
            return await interaction.response.send_message("⛔ Unauthorized.", ephemeral=True)

        sanctions = await self.redis.lrange(f"sanctions:{member.id}", 0, -1)
        if not sanctions:
            return await interaction.response.send_message("📭 No sanctions.", ephemeral=True)

        lines = []
        for raw in sanctions:
            try:
                s = json.loads(raw)
            except Exception:
                continue
            t = s.get("type", "unknown")
            cat = s.get("category")
            rsn = s.get("reason") or "No reason"
            dur = s.get("duration")
            mod = s.get("moderator")
            ts = s.get("timestamp")
            line = f"- [{ts}] {t}{f' ({cat})' if cat else ''} • {rsn}{f' • Duration: {dur}' if dur else ''} • by <@{mod}>"
            lines.append(line)

        text = "📒 Sanctions:\n" + "\n".join(lines[:30])
        more = f"\n… and {len(lines)-30} more." if len(lines) > 30 else ""
        await interaction.response.send_message(text + more, ephemeral=True)

    # --------- User profile + Sanctions button ---------
    class SanctionsView(discord.ui.View):
        def __init__(self, cog: "Moderation", member_id: int, *, timeout: float = 180):
            super().__init__(timeout=timeout)
            self.cog = cog
            self.member_id = member_id

        @discord.ui.button(label="Sanctions", style=discord.ButtonStyle.red)
        async def show_sanctions(self, interaction: discord.Interaction, button: discord.ui.Button):
            if not await self.cog.is_staff_or_admin(interaction.user):
                return await interaction.response.send_message("⛔ Unauthorized.", ephemeral=True)

            sanctions = await self.cog.redis.lrange(f"sanctions:{self.member_id}", 0, -1)
            if not sanctions:
                return await interaction.response.send_message("📭 No sanctions found.", ephemeral=True)

            lines = []
            for raw in sanctions:
                try:
                    s = json.loads(raw)
                except Exception:
                    continue
                t = s.get("type", "unknown")
                cat = s.get("category")
                rsn = s.get("reason") or "No reason"
                dur = s.get("duration")
                mod = s.get("moderator")
                ts = s.get("timestamp")
                line = f"- [{ts}] {t}{f' ({cat})' if cat else ''} • {rsn}{f' • Duration: {dur}' if dur else ''} • by <@{mod}>"
                lines.append(line)

            text = "📒 Sanctions:\n" + "\n".join(lines[:25])
            more = f"\n… and {len(lines)-25} more." if len(lines) > 25 else ""
            await interaction.response.send_message(text + more, ephemeral=True)

    @app_commands.command(name="user", description="Show user profile with sanctions")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def user_profile(self, interaction: discord.Interaction, member: discord.Member):
        if not await self.is_staff_or_admin(interaction.user):
            return await interaction.response.send_message("⛔ Unauthorized.", ephemeral=True)

        sanctions_raw = await self.redis.lrange(f"sanctions:{member.id}", 0, -1)
        sanction_count = len(sanctions_raw)

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

        if sanctions_raw:
            latest_lines = []
            for raw in sanctions_raw[-3:]:
                try:
                    s = json.loads(raw)
                except Exception:
                    continue
                t = s.get("type", "unknown")
                cat = s.get("category")
                rsn = s.get("reason") or "No reason"
                dur = s.get("duration")
                ts = s.get("timestamp")
                latest_lines.append(f"[{ts}] {t}{f' ({cat})' if cat else ''} • {rsn}{f' • {dur}' if dur else ''}")
            if latest_lines:
                embed.add_field(name="Latest sanctions", value="\n".join(latest_lines), inline=False)

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
