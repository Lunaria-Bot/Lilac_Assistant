# cogs/moderation.py
import os
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Union

import discord
from discord.ext import commands, tasks
from discord import app_commands
import redis.asyncio as redis

log = logging.getLogger("cog-moderation")

# --------- Config via environment ---------
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "0")) or None
REDIS_URL = os.getenv("REDIS_URL")

AUCTION_CAP = int(os.getenv("AUCTION_CAP", "5"))

CATEGORY_ROLES = {
    "Auction": int(os.getenv("ROLE_AUCTION", "0")) or None,
    "Crosstrade": int(os.getenv("ROLE_CROSSTRADE", "0")) or None,
    "Market": int(os.getenv("ROLE_MARKET", "0")) or None,
    "Pricing": int(os.getenv("ROLE_PRICING", "0")) or None,
    "Spawn": int(os.getenv("ROLE_SPAWN", "0")) or None,
}

# --------- Utils ---------
def parse_duration_to_timedelta(duration: Optional[str]) -> Optional[timedelta]:
    if not duration:
        return None
    s = duration.strip().lower()
    try:
        # minutes
        if s.endswith(("minutes", "minute", "mins", "min")) or "min" in s:
            n = int(s.split()[0]) if " " in s else int(
                s.replace("minutes", "").replace("minute", "").replace("mins", "").replace("min", "")
            )
            return timedelta(minutes=n)
        # hours
        if s.endswith(("hours", "hour", "h")) or s.endswith("h"):
            n = int(s.split()[0]) if " " in s else int(
                s.replace("h", "").replace("hours", "").replace("hour", "")
            )
            return timedelta(hours=n)
        # days
        if s.endswith(("days", "day", "d")) or s.endswith("d"):
            n = int(s.split()[0]) if " " in s else int(
                s.replace("d", "").replace("days", "").replace("day", "")
            )
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
        # Réutilise Redis du bot si disponible, sinon crée la connexion
        self.redis = getattr(self.bot, "redis", None)
        if not self.redis and REDIS_URL:
            self.redis = redis.from_url(REDIS_URL, decode_responses=True)
        log.info("Moderation cog ready (Redis=%s)", "shared" if getattr(self.bot, "redis", None) else "own")

    async def cog_unload(self):
        self.check_expired.cancel()
        log.info("Moderation cog unloaded")

    # --------- Background task: remove expired sanctions ---------
    @tasks.loop(minutes=1)
    async def check_expired(self):
        guild = self.bot.get_guild(GUILD_ID) if GUILD_ID else None
        if not guild or not self.redis:
            return

        keys = await self.redis.keys("sanctions:*")
        now = datetime.now(timezone.utc)

        for key in keys:
            try:
                member_id = int(key.split(":")[1])
            except Exception:
                continue

            member = guild.get_member(member_id)
            sanctions = await self.redis.lrange(key, 0, -1)
            keep: List[str] = []

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

                        # --- Expiration ban par rôle ---
                        if stype == "ban-role" and member:
                            cat = s.get("category")
                            role_id = CATEGORY_ROLES.get(cat)
                            role = guild.get_role(role_id) if role_id else None
                            if role and role in member.roles:
                                try:
                                    await member.remove_roles(role, reason="Ban expired")
                                except discord.Forbidden:
                                    pass

                        # --- Expiration timeout ---
                        elif stype == "timeout":
                            # Discord retire déjà le timeout automatiquement
                            pass

                        # --- Expiration all-ban (ban serveur) ---
                        elif stype == "all-ban":
                            try:
                                await guild.unban(discord.Object(id=member_id), reason="Tempban expired")

                                # LOG auto-unban
                                if LOG_CHANNEL_ID:
                                    log_channel = guild.get_channel(LOG_CHANNEL_ID)
                                    if log_channel:
                                        embed = discord.Embed(
                                            title="⏳ Tempban expired",
                                            description=f"User <@{member_id}> has been automatically unbanned after serving their tempban.",
                                            color=discord.Color.green(),
                                            timestamp=datetime.now(timezone.utc)
                                        )
                                        embed.set_footer(text="Auto-Unban • System Action")
                                        await log_channel.send(embed=embed)
                            except (discord.NotFound, discord.Forbidden):
                                pass

                        # Sanction expirée → on ne la garde pas
                        continue

                # Pas expirée → on la garde
                keep.append(raw)

            # Réécrit la liste
            await self.redis.delete(key)
            if keep:
                await self.redis.rpush(key, *keep)

    # --------- Access control ---------
    async def is_staff_or_admin(self, member: discord.Member) -> bool:
        if member.guild_permissions.administrator:
            return True
        return await self.redis.sismember(self.staff_key, str(member.id))

    # --------- Logging ---------
    async def log_action(
        self,
        guild: discord.Guild,
        moderator: Union[discord.Member, discord.User],
        action: str,
        target: Optional[discord.Member] = None,
        reason: Optional[str] = None,
        category: Optional[str] = None
    ):
        if not LOG_CHANNEL_ID or not self.redis:
            return
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
        embed.add_field(name="Moderator", value=(getattr(moderator, "mention", f"<@{moderator.id}>")), inline=True)
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

    # --------- Core logic helpers (used by slash + prefix) ---------
    async def send_dm_safe(self, member: discord.Member, text: str):
        try:
            await member.send(text)
        except discord.Forbidden:
            pass

    async def reply(self, ctx_or_inter, text: str, *, ephemeral: bool = True):
        if isinstance(ctx_or_inter, discord.Interaction):
            await ctx_or_inter.response.send_message(text, ephemeral=ephemeral)
        else:
            await ctx_or_inter.send(text)

    # Warn auction
    async def do_warn_auction(self, source, guild, moderator, member: discord.Member, reason: str):
        if not await self.is_staff_or_admin(moderator if isinstance(moderator, discord.Member) else guild.get_member(moderator.id)):
            return await self.reply(source, "⛔ Unauthorized.")
        key = f"warns:auction:{member.id}"
        count = await self.redis.incr(key)
        sanction = {
            "type": "warn-auction",
            "reason": reason,
            "moderator": moderator.id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "count": count
        }
        await self.redis.rpush(f"sanctions:{member.id}", json.dumps(sanction))
        await self.send_dm_safe(member, f"⚠️ Auction Warning in {guild.name}\nReason: {reason}\nTotal: {count}/{AUCTION_CAP}")
        await self.log_action(guild, moderator, "Warn (Auction)", target=member, reason=f"{reason} • Count {count}", category="auction")
        await self.reply(source, f"⚠️ Auction warning issued to {member.mention} ({count}/{AUCTION_CAP})")

    # Warn general
    async def do_warn_general(self, source, guild, moderator, member: discord.Member, reason: str):
        if not await self.is_staff_or_admin(moderator if isinstance(moderator, discord.Member) else guild.get_member(moderator.id)):
            return await self.reply(source, "⛔ Unauthorized.")
        key = f"warns:general:{member.id}"
        count = await self.redis.incr(key)
        sanction = {
            "type": "warn-general",
            "reason": reason,
            "moderator": moderator.id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "count": count
        }
        await self.redis.rpush(f"sanctions:{member.id}", json.dumps(sanction))
        await self.send_dm_safe(member, f"⚠️ General Warning in {guild.name}\nReason: {reason}\nTotal: {count}")
        await self.log_action(guild, moderator, "Warn (General)", target=member, reason=f"{reason} • Count {count}", category="general")
        await self.reply(source, f"⚠️ General warning issued to {member.mention} (now at {count})")

    # Ban role
    async def do_ban_role(self, source, guild, moderator, member: discord.Member, category: str, reason: str, time: Optional[str]):
        if not await self.is_staff_or_admin(moderator if isinstance(moderator, discord.Member) else guild.get_member(moderator.id)):
            return await self.reply(source, "⛔ Unauthorized.")
        role_id = CATEGORY_ROLES.get(category)
        role = guild.get_role(role_id) if role_id else None
        if not role:
            return await self.reply(source, "❌ Role not found in guild.")
        try:
            await member.add_roles(role, reason=reason)
        except discord.Forbidden:
            return await self.reply(source, "❌ Missing permissions to add role.")
        sanction = {
            "type": "ban-role",
            "category": category,
            "reason": reason,
            "moderator": moderator.id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "duration": time
        }
        await self.redis.rpush(f"sanctions:{member.id}", json.dumps(sanction))
        await self.send_dm_safe(member, f"🔨 Banned from {category} in {guild.name}\nReason: {reason}\nDuration: {time or 'Permanent'}")
        await self.log_action(guild, moderator, f"Ban Role ({category})", target=member, reason=f"{reason} • Duration: {time or 'Permanent'}", category="ban")
        await self.reply(source, f"🔨 {member.mention} has been given the **{category}** ban role.\nReason: {reason}")

    # Unban role
    async def do_unban_role(self, source, guild, moderator, member: discord.Member, category: str):
        if not await self.is_staff_or_admin(moderator if isinstance(moderator, discord.Member) else guild.get_member(moderator.id)):
            return await self.reply(source, "⛔ Unauthorized.")
        role_id = CATEGORY_ROLES.get(category)
        role = guild.get_role(role_id) if role_id else None
        if role and role in member.roles:
            try:
                await member.remove_roles(role, reason="Unban command")
            except discord.Forbidden:
                return await self.reply(source, "❌ Missing permissions to remove role.")
            await self.log_action(guild, moderator, f"Unban ({category})", target=member, category="ban")
            await self.reply(source, f"✅ {member.mention} unbanned from {category}")
        else:
            await self.reply(source, "❌ Role not found or not applied.")

    # All-ban server
    async def do_all_ban(self, source, guild, moderator, member: discord.Member, reason: str, time: Optional[str]):
        if not await self.is_staff_or_admin(moderator if isinstance(moderator, discord.Member) else guild.get_member(moderator.id)):
            return await self.reply(source, "⛔ Unauthorized.")
        await self.send_dm_safe(member, f"🚫 Banned from {guild.name}\nReason: {reason}\nDuration: {time or 'Permanent'}")
        try:
            await member.ban(reason=reason, delete_message_days=0)
        except discord.Forbidden:
            return await self.reply(source, "❌ Missing permissions to ban this member.")
        sanction = {
            "type": "all-ban",
            "reason": reason,
            "moderator": moderator.id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "duration": time
        }
        await self.redis.rpush(f"sanctions:{member.id}", json.dumps(sanction))
        await self.log_action(guild, moderator, "All-Ban", target=member, reason=f"{reason} • Duration: {time or 'Permanent'}", category="ban")
        await self.reply(source, f"🚫 {member.mention} has been banned from the server.\nReason: {reason}")

    # All-unban server
    async def do_all_unban(self, source, guild, moderator, user_id: int):
        if not await self.is_staff_or_admin(moderator if isinstance(moderator, discord.Member) else guild.get_member(moderator.id)):
            return await self.reply(source, "⛔ Unauthorized.")
        obj = discord.Object(id=user_id)
        try:
            await guild.unban(obj, reason="All-unban command")
        except discord.NotFound:
            return await self.reply(source, "ℹ️ User not found in ban list.")
        except discord.Forbidden:
            return await self.reply(source, "❌ Missing permissions to unban.")
        await self.log_action(guild, moderator, "All-Unban", category="ban")
        await self.reply(source, f"✅ User <@{user_id}> has been unbanned from the server.")

    # Timeout
    async def do_timeout(self, source, guild, moderator, member: discord.Member, reason: str, minutes: int):
        if not await self.is_staff_or_admin(moderator if isinstance(moderator, discord.Member) else guild.get_member(moderator.id)):
            return await self.reply(source, "⛔ Unauthorized.")
        until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        try:
            await member.timeout(until, reason=reason)
        except Exception as e:
            return await self.reply(source, f"❌ Failed to timeout: {e}")
        sanction = {
            "type": "timeout",
            "reason": reason,
            "moderator": moderator.id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "duration": f"{minutes} minutes"
        }
        await self.redis.rpush(f"sanctions:{member.id}", json.dumps(sanction))
        await self.send_dm_safe(member, f"⏳ Timeout in {guild.name}\nReason: {reason}\nDuration: {minutes} minutes")
        await self.log_action(guild, moderator, "Timeout", target=member, reason=f"{reason} • Duration: {minutes} minutes", category="timeout")
        await self.reply(source, f"⏳ {member.mention} timed out for {minutes} minutes.\nReason: {reason}")

    # Warnings view
    async def do_warnings(self, source, guild, moderator, member: discord.Member):
        if not await self.is_staff_or_admin(moderator if isinstance(moderator, discord.Member) else guild.get_member(moderator.id)):
            return await self.reply(source, "⛔ Unauthorized.")
        auction = int(await self.redis.get(f"warns:auction:{member.id}") or 0)
        general = int(await self.redis.get(f"warns:general:{member.id}") or 0)
        text = f"📊 Warnings for {member.mention}:\n- Auction: {auction}/{AUCTION_CAP}\n- General: {general}"
        await self.reply(source, text)
        await self.log_action(guild, moderator, "Warnings View", target=member, reason=f"Auction={auction}, General={general}")

    # Clear warnings
    async def do_clear_warnings(self, source, guild, moderator, member: discord.Member, category_key: str):
        if not await self.is_staff_or_admin(moderator if isinstance(moderator, discord.Member) else guild.get_member(moderator.id)):
            return await self.reply(source, "⛔ Unauthorized.")
        if category_key == "auction":
            await self.redis.delete(f"warns:auction:{member.id}")
        else:
            await self.redis.delete(f"warns:general:{member.id}")
        await self.reply(source, f"✅ Cleared {category_key} warnings for {member.mention}")
        await self.log_action(guild, moderator, f"Clear Warnings ({category_key})", target=member)

    # Context notes
    async def do_context(self, source, guild, moderator, member: discord.Member, action: str, note: Optional[str]):
        if not await self.is_staff_or_admin(moderator if isinstance(moderator, discord.Member) else guild.get_member(moderator.id)):
            return await self.reply(source, "⛔ Unauthorized.")
        key = f"context:{member.id}"
        if action == "add":
            if not note:
                return await self.reply(source, "❌ You must provide a note when adding.")
            if len(note) > 500:
                return await self.reply(source, "❌ Note too long (max 500 chars).")
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            entry = f"[{timestamp}] {getattr(moderator, 'display_name', 'Staff')}: {note}"
            await self.redis.rpush(key, entry)
            await self.reply(source, f"📝 Added context note for {member.mention}")
            await self.log_action(guild, moderator, "Context Add", target=member, reason=entry)
        elif action == "list":
            notes = await self.redis.lrange(key, 0, -1)
            if not notes:
                await self.reply(source, "📭 No context notes for this user.")
                await self.log_action(guild, moderator, "Context List", target=member, reason="No notes")
                return
            formatted = "\n".join(notes[:20])
            more = f"\n… and {len(notes)-20} more." if len(notes) > 20 else ""
            await self.reply(source, f"📒 Context notes for {member.mention}:\n{formatted}{more}")
            await self.log_action(guild, moderator, "Context List", target=member, reason=f"Listed {len(notes)} notes")
        elif action == "clear":
            await self.redis.delete(key)
            await self.reply(source, f"🗑️ Cleared all context notes for {member.mention}")
            await self.log_action(guild, moderator, "Context Clear", target=member, reason="Cleared notes")
        else:
            await self.reply(source, "❌ Invalid action (use add/list/clear).")

    # Staff management (admins only)
    async def do_staff(self, source, guild, moderator_member: discord.Member, action: str, target: Optional[discord.Member]):
        if not moderator_member.guild_permissions.administrator:
            return await self.reply(source, "⛔ Only administrators can manage staff.")
        if action == "add":
            if not target:
                return await self.reply(source, "❌ You must specify a user to add.")
            await self.redis.sadd(self.staff_key, str(target.id))
            await self.reply(source, f"✅ {target.mention} added to staff list.")
            await self.log_action(guild, moderator_member, "Staff Add", target=target, reason="Added to internal staff list")
        elif action == "remove":
            if not target:
                return await self.reply(source, "❌ You must specify a user to remove.")
            await self.redis.srem(self.staff_key, str(target.id))
            await self.reply(source, f"✅ {target.mention} removed from staff list.")
            await self.log_action(guild, moderator_member, "Staff Remove", target=target, reason="Removed from internal staff list")
        elif action == "list":
            staff_ids = await self.redis.smembers(self.staff_key)
            if not staff_ids:
                await self.reply(source, "📭 No staff members registered.")
                await self.log_action(guild, moderator_member, "Staff List", reason="No staff in list")
                return
            mentions = []
            for uid in staff_ids:
                m = guild.get_member(int(uid))
                mentions.append(m.mention if m else f"<@{uid}>")
            await self.reply(source, f"👥 Staff list ({len(mentions)}):\n" + ", ".join(mentions))
            await self.log_action(guild, moderator_member, "Staff List", reason=f"Listed {len(mentions)} staff members")
        else:
            await self.reply(source, "❌ Invalid action (use add/remove/list).")

    # Case retrieval
    async def do_case(self, source, guild, moderator, case_id: int):
        if not await self.is_staff_or_admin(moderator if isinstance(moderator, discord.Member) else guild.get_member(moderator.id)):
            return await self.reply(source, "⛔ Unauthorized.")
        data = await self.redis.get(f"moderation:case:{case_id}")
        if not data:
            return await self.reply(source, f"❌ Case ID #{case_id} not found.")
        case = json.loads(data)
        mod = guild.get_member(case["moderator_id"])
        tgt = guild.get_member(case["target_id"]) if case["target_id"] else None
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
        mod_val = mod.mention if mod else f"<@{case['moderator_id']}>"
        tgt_val = tgt.mention if tgt else (f"<@{case['target_id']}>" if case["target_id"] else "—")
        embed.add_field(name="Moderator", value=mod_val, inline=True)
        embed.add_field(name="Target", value=tgt_val, inline=True)
        embed.add_field(name="Reason/Details", value=(case.get("reason") or "No reason provided"), inline=False)
        embed.add_field(name="Category", value=(case.get("category") or "—"), inline=True)
        # reply embed
        if isinstance(source, discord.Interaction):
            await source.response.send_message(embed=embed, ephemeral=True)
        else:
            await source.send(embed=embed)
        await self.log_action(guild, moderator, "Case Retrieve", reason=f"Retrieved Case #{case_id}")

    # Sanctions list
    async def do_sanctions(self, source, guild, moderator, member: discord.Member):
        if not await self.is_staff_or_admin(moderator if isinstance(moderator, discord.Member) else guild.get_member(moderator.id)):
            return await self.reply(source, "⛔ Unauthorized.")
        sanctions = await self.redis.lrange(f"sanctions:{member.id}", 0, -1)
        if not sanctions:
            return await self.reply(source, "📭 No sanctions.")
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
        await self.reply(source, text + more)

    # User profile
    async def do_user(self, source, guild, moderator, member: discord.Member):
        if not await self.is_staff_or_admin(moderator if isinstance(moderator, discord.Member) else guild.get_member(moderator.id)):
            return await self.reply(source, "⛔ Unauthorized.")
        sanctions_raw = await self.redis.lrange(f"sanctions:{member.id}", 0, -1)
        sanction_count = len(sanctions_raw)
        joined = member.joined_at.strftime("%Y-%m-%d %H:%M UTC") if member.joined_at else "Unknown"
        roles = [r.mention for r in member.roles if r != guild.default_role]
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
        if isinstance(source, discord.Interaction):
            await source.response.send_message(embed=embed, ephemeral=True)
        else:
            await source.send(embed=embed)
        await self.log_action(guild, moderator, "User Profile View", target=member, reason=f"Sanctions count: {sanction_count}")

    # --------- Slash commands ---------
    @app_commands.command(name="warn-auction", description="Issue an auction warning")
    @app_commands.guilds(discord.Object(id=GUILD_ID)) if GUILD_ID else (lambda f: f)
    async def warn_auction_slash(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        await self.do_warn_auction(interaction, interaction.guild, interaction.user, member, reason)

    @app_commands.command(name="warn-general", description="Issue a general warning")
    @app_commands.guilds(discord.Object(id=GUILD_ID)) if GUILD_ID else (lambda f: f)
    async def warn_general_slash(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        await self.do_warn_general(interaction, interaction.guild, interaction.user, member, reason)

    @app_commands.choices(category=[
        app_commands.Choice(name="Auction", value="Auction"),
        app_commands.Choice(name="Market", value="Market"),
        app_commands.Choice(name="Crosstrade", value="Crosstrade"),
        app_commands.Choice(name="Spawn", value="Spawn"),
        app_commands.Choice(name="Pricing", value="Pricing")
    ])
    @app_commands.command(name="ban", description="Give a ban role to a member by category")
    @app_commands.guilds(discord.Object(id=GUILD_ID)) if GUILD_ID else (lambda f: f)
    async def ban_slash(self, interaction: discord.Interaction, member: discord.Member, category: app_commands.Choice[str], reason: str, time: Optional[str] = None):
        await self.do_ban_role(interaction, interaction.guild, interaction.user, member, category.value, reason, time)

    @app_commands.choices(category=[
        app_commands.Choice(name="Auction", value="Auction"),
        app_commands.Choice(name="Market", value="Market"),
        app_commands.Choice(name="Crosstrade", value="Crosstrade"),
        app_commands.Choice(name="Spawn", value="Spawn"),
        app_commands.Choice(name="Pricing", value="Pricing")
    ])
    @app_commands.command(name="unban", description="Remove a category ban role from a member")
    @app_commands.guilds(discord.Object(id=GUILD_ID)) if GUILD_ID else (lambda f: f)
    async def unban_slash(self, interaction: discord.Interaction, member: discord.Member, category: app_commands.Choice[str]):
        await self.do_unban_role(interaction, interaction.guild, interaction.user, member, category.value)

    @app_commands.command(name="all-ban", description="Ban a member from the server")
    @app_commands.describe(reason="Reason for the ban", time="Optional duration (e.g. '2 days')")
    @app_commands.guilds(discord.Object(id=GUILD_ID)) if GUILD_ID else (lambda f: f)
    async def all_ban_slash(self, interaction: discord.Interaction, member: discord.Member, reason: str, time: Optional[str] = None):
        await self.do_all_ban(interaction, interaction.guild, interaction.user, member, reason, time)

    @app_commands.command(name="all-unban", description="Unban a user from the server")
    @app_commands.guilds(discord.Object(id=GUILD_ID)) if GUILD_ID else (lambda f: f)
    async def all_unban_slash(self, interaction: discord.Interaction, user_id: int):
        await self.do_all_unban(interaction, interaction.guild, interaction.user, user_id)

    @app_commands.command(name="timeout", description="Timeout a member")
    @app_commands.describe(reason="Reason for the timeout", time="Duration in minutes")
    @app_commands.guilds(discord.Object(id=GUILD_ID)) if GUILD_ID else (lambda f: f)
    async def timeout_slash(self, interaction: discord.Interaction, member: discord.Member, reason: str, time: int):
        await self.do_timeout(interaction, interaction.guild, interaction.user, member, reason, time)

    @app_commands.command(name="warnings", description="Check a user's warnings")
    @app_commands.guilds(discord.Object(id=GUILD_ID)) if GUILD_ID else (lambda f: f)
    async def warnings_slash(self, interaction: discord.Interaction, member: discord.Member):
        await self.do_warnings(interaction, interaction.guild, interaction.user, member)

    @app_commands.choices(category=[
        app_commands.Choice(name="auction", value="auction"),
        app_commands.Choice(name="general", value="general"),
    ])
    @app_commands.command(name="clear-warnings", description="Clear a user's warnings")
    @app_commands.guilds(discord.Object(id=GUILD_ID)) if GUILD_ID else (lambda f: f)
    async def clear_warnings_slash(self, interaction: discord.Interaction, member: discord.Member, category: app_commands.Choice[str]):
        await self.do_clear_warnings(interaction, interaction.guild, interaction.user, member, category.value)

    @app_commands.choices(action=[
        app_commands.Choice(name="add", value="add"),
        app_commands.Choice(name="list", value="list"),
        app_commands.Choice(name="clear", value="clear"),
    ])
    @app_commands.command(name="context", description="Add, list, or clear context notes for a user")
    @app_commands.guilds(discord.Object(id=GUILD_ID)) if GUILD_ID else (lambda f: f)
    async def context_slash(self, interaction: discord.Interaction, member: discord.Member, action: app_commands.Choice[str], note: Optional[str] = None):
        await self.do_context(interaction, interaction.guild, interaction.user, member, action.value, note)

    @app_commands.choices(action=[
        app_commands.Choice(name="add", value="add"),
        app_commands.Choice(name="remove", value="remove"),
        app_commands.Choice(name="list", value="list"),
    ])
    @app_commands.command(name="staff", description="Manage staff list (admins only)")
    @app_commands.guilds(discord.Object(id=GUILD_ID)) if GUILD_ID else (lambda f: f)
    async def staff_slash(self, interaction: discord.Interaction, action: app_commands.Choice[str], member: Optional[discord.Member] = None):
        await self.do_staff(interaction, interaction.guild, interaction.user, action.value, member)

    @app_commands.command(name="case", description="Retrieve details of a specific moderation case")
    @app_commands.guilds(discord.Object(id=GUILD_ID)) if GUILD_ID else (lambda f: f)
    async def case_slash(self, interaction: discord.Interaction, case_id: int):
        await self.do_case(interaction, interaction.guild, interaction.user, case_id)

    @app_commands.command(name="sanctions", description="List all sanctions for a user")
    @app_commands.guilds(discord.Object(id=GUILD_ID)) if GUILD_ID else (lambda f: f)
    async def sanctions_slash(self, interaction: discord.Interaction, member: discord.Member):
        await self.do_sanctions(interaction, interaction.guild, interaction.user, member)

    @app_commands.command(name="user", description="Show user profile with sanctions")
    @app_commands.guilds(discord.Object(id=GUILD_ID)) if GUILD_ID else (lambda f: f)
    async def user_slash(self, interaction: discord.Interaction, member: discord.Member):
        await self.do_user(interaction, interaction.guild, interaction.user, member)

    # --------- Prefix commands (mirror) ---------
    @commands.command(name="warn-auction")
    async def warn_auction_prefix(self, ctx: commands.Context, member: discord.Member, *, reason: str):
        await self.do_warn_auction(ctx, ctx.guild, ctx.author, member, reason)

    @commands.command(name="warn-general")
    async def warn_general_prefix(self, ctx: commands.Context, member: discord.Member, *, reason: str):
        await self.do_warn_general(ctx, ctx.guild, ctx.author, member, reason)

    @commands.command(name="ban")
    async def ban_prefix(self, ctx: commands.Context, member: discord.Member, category: str, *, reason: str):
        # Optional duration: use "time:<value>" at end of reason, e.g., "spam time:1h"
        time = None
        if " time:" in reason:
            reason, time = reason.split(" time:", 1)
            reason = reason.strip()
            time = time.strip()
        await self.do_ban_role(ctx, ctx.guild, ctx.author, member, category, reason, time)

    @commands.command(name="unban")
    async def unban_prefix(self, ctx: commands.Context, member: discord.Member, category: str):
        await self.do_unban_role(ctx, ctx.guild, ctx.author, member, category)

    @commands.command(name="all-ban")
    async def all_ban_prefix(self, ctx: commands.Context, member: discord.Member, *, reason: str):
        # Optional duration: "time:<value>" at end
        time = None
        if " time:" in reason:
            reason, time = reason.split(" time:", 1)
            reason = reason.strip()
            time = time.strip()
        await self.do_all_ban(ctx, ctx.guild, ctx.author, member, reason, time)

    @commands.command(name="all-unban")
    async def all_unban_prefix(self, ctx: commands.Context, user_id: int):
        await self.do_all_unban(ctx, ctx.guild, ctx.author, user_id)

    @commands.command(name="timeout")
    async def timeout_prefix(self, ctx: commands.Context, member: discord.Member, minutes: int, *, reason: str):
        await self.do_timeout(ctx, ctx.guild, ctx.author, member, reason, minutes)

    @commands.command(name="warnings")
    async def warnings_prefix(self, ctx: commands.Context, member: discord.Member):
        await self.do_warnings(ctx, ctx.guild, ctx.author, member)

    @commands.command(name="clear-warnings")
    async def clear_warnings_prefix(self, ctx: commands.Context, member: discord.Member, category: str):
        await self.do_clear_warnings(ctx, ctx.guild, ctx.author, member, category.lower())

    @commands.command(name="context")
    async def context_prefix(self, ctx: commands.Context, member: discord.Member, action: str, *, note: Optional[str] = None):
        await self.do_context(ctx, ctx.guild, ctx.author, member, action.lower(), note)

    @commands.command(name="staff")
    async def staff_prefix(self, ctx: commands.Context, action: str, member: Optional[discord.Member] = None):
        await self.do_staff(ctx, ctx.guild, ctx.author, action.lower(), member)

    @commands.command(name="case")
    async def case_prefix(self, ctx: commands.Context, case_id: int):
        await self.do_case(ctx, ctx.guild, ctx.author, case_id)

    @commands.command(name="sanctions")
    async def sanctions_prefix(self, ctx: commands.Context, member: discord.Member):
        await self.do_sanctions(ctx, ctx.guild, ctx.author, member)

    @commands.command(name="user")
    async def user_prefix(self, ctx: commands.Context, member: discord.Member):
        await self.do_user(ctx, ctx.guild, ctx.author, member)


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
    log.info("⚙️ Moderation cog loaded (slash + prefix)")
