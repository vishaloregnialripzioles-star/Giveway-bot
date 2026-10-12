# ============================================================
# AIR COMMANDER — ADVANCED DATABASE-BACKED GIVEAWAYS
# ============================================================
# Requires:
#   - discord.py 2.5+
#   - existing db.py with init_db(), create_giveaway(),
#     join_giveaway(), get_giveaway_entries(), end_giveaway(),
#     db_fetch(), db_fetchrow(), db_execute()
#
# Prefix:
#   ,giveaway create "Nitro 1 Month" 24 1
#   ,giveaway list
#   ,giveaway end 12
#   ,giveaway reroll 12
#   ,giveaway cancel 12
#   ,giveaway entrants 12
#
# Slash:
#   /giveaway create
#   /giveaway list
#   /giveaway end
#   /giveaway reroll
#   /giveaway cancel
#   /giveaway entrants
#
# Important:
#   Giveaway state and entries are stored in PostgreSQL using the
#   existing db.py schema. No JSON files are used by this module.
# ============================================================

from __future__ import annotations

import json
import random
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

import db

log = logging.getLogger("aircommander.giveaways")

BRAND = "Air Commander • Giveaway System"
PURPLE = discord.Color.from_rgb(88, 101, 242)
GREEN = discord.Color.green()
RED = discord.Color.red()
GOLD = discord.Color.gold()


def _json_object(value: Any) -> dict:
    """Normalize asyncpg JSON/JSONB output to a dict."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
            return decoded if isinstance(decoded, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


def _json_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
            return decoded if isinstance(decoded, list) else []
        except (json.JSONDecodeError, TypeError):
            return []
    return []


def _row_value(row: Any, key: str, default=None):
    try:
        value = row[key]
        return default if value is None else value
    except (KeyError, TypeError, IndexError):
        return default


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(dt: Optional[datetime]) -> str:
    if not dt:
        return "Unknown"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return f"<t:{int(dt.timestamp())}:R>"


def _duration_text(ends_at: Optional[datetime]) -> str:
    if not ends_at:
        return "No end time"
    return _timestamp(ends_at)


def giveaway_embed(
    *,
    prize: str,
    host_id: int,
    winner_count: int,
    ends_at: Optional[datetime],
    entries: int = 0,
    requirements: Optional[dict] = None,
    status: str = "active",
    winners: Optional[list] = None,
    giveaway_id: Optional[int] = None,
) -> discord.Embed:
    requirements = requirements or {}
    winners = winners or []

    if status == "active":
        color = PURPLE
        title = "🎉 GIVEAWAY"
        state = "🟢 **Status:** Active"
    elif status == "cancelled":
        color = RED
        title = "🛑 GIVEAWAY CANCELLED"
        state = "🔴 **Status:** Cancelled"
    else:
        color = GOLD
        title = "🏆 GIVEAWAY ENDED"
        state = "⚫ **Status:** Ended"

    description = (
        f"## 🎁 {discord.utils.escape_markdown(str(prize))}\n"
        f"Hosted by <@{int(host_id)}>\n\n"
        f"🏆 **Winners:** {int(winner_count)}\n"
        f"👥 **Entries:** {int(entries)}\n"
        f"⏰ **Ends:** {_duration_text(ends_at)}\n"
        f"{state}"
    )

    if requirements.get("required_role_id"):
        description += (
            f"\n🔒 **Required role:** "
            f"<@&{int(requirements['required_role_id'])}>"
        )
    if requirements.get("bonus_role_id"):
        description += (
            f"\n✨ **Bonus role:** <@&{int(requirements['bonus_role_id'])}> "
            f"({int(requirements.get('bonus_entries', 1))} bonus entries)"
        )

    if winners:
        mentions = ", ".join(f"<@{int(uid)}>" for uid in winners)
        description += f"\n\n🎊 **Winner(s):** {mentions}"

    embed = discord.Embed(title=title, description=description, color=color)
    embed.set_footer(
        text=f"{BRAND} • ID: {giveaway_id if giveaway_id is not None else 'pending'}"
    )
    embed.timestamp = _utcnow()
    return embed


class GiveawayJoinButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="Enter Giveaway",
            emoji="🎉",
            style=discord.ButtonStyle.success,
            custom_id="aircommander:giveaway:enter:v1",
        )

    async def callback(self, interaction: discord.Interaction):
        cog: GiveawayCog = self.view.cog  # type: ignore[attr-defined]
        await cog.handle_entry(interaction)


class GiveawayView(discord.ui.View):
    """Persistent view: works for giveaway messages after bot restarts."""

    def __init__(self, cog: "GiveawayCog"):
        super().__init__(timeout=None)
        self.cog = cog
        self.add_item(GiveawayJoinButton())


class GiveawayCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._closing_ids: set[int] = set()
        self.expiry_worker.start()

    async def cog_load(self):
        # A persistent view has no per-message state; each click resolves
        # its giveaway from the message_id stored in PostgreSQL.
        self.bot.add_view(GiveawayView(self))

    def cog_unload(self):
        self.expiry_worker.cancel()

    async def _fetch_giveaway(self, giveaway_id: int):
        return await db.db_fetchrow(
            "SELECT * FROM giveaways WHERE id=$1",
            int(giveaway_id),
        )

    async def _fetch_by_message(self, message_id: int):
        return await db.db_fetchrow(
            "SELECT * FROM giveaways WHERE message_id=$1",
            int(message_id),
        )

    async def _fetch_active(self, guild_id: Optional[int] = None):
        if guild_id is None:
            return await db.db_fetch(
                "SELECT * FROM giveaways WHERE status='active' ORDER BY ends_at ASC NULLS LAST"
            )
        return await db.db_fetch(
            """SELECT * FROM giveaways
               WHERE guild_id=$1 AND status='active'
               ORDER BY ends_at ASC NULLS LAST""",
            int(guild_id),
        )

    async def _entry_count(self, giveaway_id: int) -> int:
        value = await db.db_fetchval(
            "SELECT COUNT(*) FROM giveaway_entries WHERE giveaway_id=$1",
            int(giveaway_id),
        )
        return int(value or 0)

    async def _edit_giveaway_message(self, row: Any, *, status: str, winners=None):
        channel_id = _row_value(row, "channel_id")
        message_id = _row_value(row, "message_id")
        if not channel_id or not message_id:
            return

        channel = self.bot.get_channel(int(channel_id))
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(int(channel_id))
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return

        try:
            message = await channel.fetch_message(int(message_id))
        except (AttributeError, discord.NotFound, discord.Forbidden, discord.HTTPException):
            return

        requirements = _json_object(_row_value(row, "requirements", {}))
        count = await self._entry_count(int(_row_value(row, "id", 0)))
        embed = giveaway_embed(
            prize=_row_value(row, "prize", "Giveaway"),
            host_id=int(_row_value(row, "host_id", self.bot.user.id if self.bot.user else 0)),
            winner_count=int(_row_value(row, "winner_count", 1)),
            ends_at=_row_value(row, "ends_at"),
            entries=count,
            requirements=requirements,
            status=status,
            winners=winners or [],
            giveaway_id=int(_row_value(row, "id", 0)),
        )
        view = GiveawayView(self) if status == "active" else None
        try:
            await message.edit(embed=embed, view=view)
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            log.warning("Could not update giveaway message id=%s", message_id)

    async def handle_entry(self, interaction: discord.Interaction):
        if not interaction.guild or not interaction.user:
            await interaction.response.send_message(
                "Giveaways can only be entered inside a server.", ephemeral=True
            )
            return

        if not interaction.message:
            await interaction.response.send_message(
                "I couldn't identify this giveaway message.", ephemeral=True
            )
            return

        try:
            row = await self._fetch_by_message(interaction.message.id)
        except Exception:
            log.exception("Database error while loading giveaway for entry")
            await interaction.response.send_message(
                "The giveaway database is temporarily unavailable. Please try again.",
                ephemeral=True,
            )
            return

        if not row:
            await interaction.response.send_message(
                "This giveaway isn't registered in the database.", ephemeral=True
            )
            return

        giveaway_id = int(_row_value(row, "id", 0))
        if _row_value(row, "status", "active") != "active":
            await interaction.response.send_message(
                "This giveaway has already ended or been cancelled.", ephemeral=True
            )
            return

        ends_at = _row_value(row, "ends_at")
        if ends_at and ends_at <= _utcnow():
            await interaction.response.send_message(
                "This giveaway has ended. The winner draw is being processed.",
                ephemeral=True,
            )
            await self.finish_giveaway(giveaway_id)
            return

        if interaction.user.bot:
            await interaction.response.send_message(
                "Bots cannot enter giveaways.", ephemeral=True
            )
            return

        requirements = _json_object(_row_value(row, "requirements", {}))
        required_role_id = requirements.get("required_role_id")
        if required_role_id:
            member = interaction.user
            if not isinstance(member, discord.Member):
                try:
                    member = await interaction.guild.fetch_member(interaction.user.id)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    await interaction.response.send_message(
                        "I couldn't verify your server roles. Please try again.",
                        ephemeral=True,
                    )
                    return
            if not any(role.id == int(required_role_id) for role in member.roles):
                await interaction.response.send_message(
                    f"You need the <@&{int(required_role_id)}> role to enter.",
                    ephemeral=True,
                )
                return

        try:
            existing = await db.db_fetchval(
                """SELECT EXISTS(
                       SELECT 1 FROM giveaway_entries
                       WHERE giveaway_id=$1 AND user_id=$2
                   )""",
                giveaway_id,
                interaction.user.id,
            )
            if existing:
                await interaction.response.send_message(
                    "You're already entered in this giveaway. Good luck! 🍀",
                    ephemeral=True,
                )
                return

            await db.join_giveaway(giveaway_id, interaction.user.id)
            count = await self._entry_count(giveaway_id)
            await interaction.response.send_message(
                f"🎉 You're entered in **{discord.utils.escape_markdown(str(_row_value(row, 'prize', 'this giveaway')))}**! "
                f"Current entries: **{count}**.",
                ephemeral=True,
            )
            await self._edit_giveaway_message(row, status="active")
        except Exception:
            log.exception("Database error while registering giveaway entry")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "I couldn't save your entry. Please try again in a moment.",
                    ephemeral=True,
                )

    @tasks.loop(seconds=20)
    async def expiry_worker(self):
        try:
            rows = await self._fetch_active()
            now = _utcnow()
            for row in rows or []:
                ends_at = _row_value(row, "ends_at")
                if ends_at and ends_at <= now:
                    giveaway_id = int(_row_value(row, "id", 0))
                    if giveaway_id:
                        await self.finish_giveaway(giveaway_id)
        except Exception:
            # Database may still be initializing when the bot first comes online.
            log.exception("Giveaway expiry worker encountered an error")

    @expiry_worker.before_loop
    async def before_expiry_worker(self):
        await self.bot.wait_until_ready()

    async def _pick_winners(self, row: Any, *, exclude_ids=None) -> list[int]:
        giveaway_id = int(_row_value(row, "id", 0))
        guild_id = int(_row_value(row, "guild_id", 0))
        requirements = _json_object(_row_value(row, "requirements", {}))
        required_role_id = requirements.get("required_role_id")
        bonus_role_id = requirements.get("bonus_role_id")
        bonus_entries = max(1, min(100, int(requirements.get("bonus_entries", 1))))
        excluded = {int(uid) for uid in (exclude_ids or [])}

        entries = await db.get_giveaway_entries(giveaway_id)
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            try:
                guild = await self.bot.fetch_guild(guild_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return []

        weighted_pool: list[int] = []
        for entry in entries or []:
            user_id = int(_row_value(entry, "user_id", 0))
            if not user_id or user_id in excluded:
                continue

            member = guild.get_member(user_id)
            if member is None:
                try:
                    member = await guild.fetch_member(user_id)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    # Do not pick users who have left the server.
                    continue

            role_ids = {role.id for role in member.roles}
            if required_role_id and int(required_role_id) not in role_ids:
                continue

            weight = bonus_entries if bonus_role_id and int(bonus_role_id) in role_ids else 1
            weighted_pool.extend([user_id] * weight)

        if not weighted_pool:
            return []

        winners: list[int] = []
        while weighted_pool and len(winners) < int(_row_value(row, "winner_count", 1)):
            winner_id = random.choice(weighted_pool)
            if winner_id not in winners:
                winners.append(winner_id)
                # Remove all tickets belonging to the selected winner so they
                # cannot win multiple slots in the same giveaway.
                weighted_pool = [uid for uid in weighted_pool if uid != winner_id]
        return winners

    async def finish_giveaway(self, giveaway_id: int, *, force: bool = False):
        giveaway_id = int(giveaway_id)
        if giveaway_id in self._closing_ids:
            return False
        self._closing_ids.add(giveaway_id)
        try:
            row = await self._fetch_giveaway(giveaway_id)
            if not row or _row_value(row, "status", "active") != "active":
                return False
            ends_at = _row_value(row, "ends_at")
            if not force and ends_at and ends_at > _utcnow():
                return False

            winners = await self._pick_winners(row)
            await db.end_giveaway(giveaway_id, winners)
            # Reload so the status/winner data is consistent with PostgreSQL.
            updated = await self._fetch_giveaway(giveaway_id) or row
            await self._edit_giveaway_message(updated, status="ended", winners=winners)

            channel_id = _row_value(updated, "channel_id")
            if channel_id:
                channel = self.bot.get_channel(int(channel_id))
                if channel is None:
                    try:
                        channel = await self.bot.fetch_channel(int(channel_id))
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                        channel = None
                if channel:
                    prize = _row_value(updated, "prize", "Giveaway prize")
                    if winners:
                        winner_text = ", ".join(f"<@{uid}>" for uid in winners)
                        message = (
                            f"🎊 **Giveaway ended!** Prize: **{discord.utils.escape_markdown(str(prize))}**\n"
                            f"🏆 Winner(s): {winner_text}\n"
                            f"🆔 Giveaway ID: `{giveaway_id}`"
                        )
                    else:
                        message = (
                            f"🎉 Giveaway for **{discord.utils.escape_markdown(str(prize))}** ended, "
                            "but no eligible entrants were found."
                        )
                    try:
                        await channel.send(message)
                    except (discord.Forbidden, discord.HTTPException):
                        log.warning("Could not announce winners for giveaway %s", giveaway_id)
            return True
        except Exception:
            log.exception("Failed to finish giveaway id=%s", giveaway_id)
            return False
        finally:
            self._closing_ids.discard(giveaway_id)

    async def _require_manager(self, ctx: commands.Context) -> bool:
        if not ctx.guild:
            await ctx.send("This command can only be used in a server.")
            return False
        if not isinstance(ctx.author, discord.Member):
            await ctx.send("I couldn't verify your server permissions.")
            return False
        if not (
            ctx.author.guild_permissions.manage_guild
            or ctx.author.guild_permissions.manage_messages
            or ctx.author.guild_permissions.administrator
        ):
            await ctx.send("❌ You need **Manage Server** or **Manage Messages** to manage giveaways.")
            return False
        return True

    @commands.hybrid_group(name="giveaway", aliases=["giveaways", "gaw"], invoke_without_command=True)
    async def giveaway(self, ctx: commands.Context):
        embed = discord.Embed(
            title="✈️ Air Commander Giveaway System",
            description=(
                "**Available commands**\n"
                "`/giveaway create` — create a giveaway\n"
                "`/giveaway list` — list active giveaways\n"
                "`/giveaway end` — end one now\n"
                "`/giveaway reroll` — choose new winner(s)\n"
                "`/giveaway cancel` — cancel one\n"
                "`/giveaway entrants` — show entry count/list\n\n"
                "Prefix examples: `,giveaway list`, `,giveaway end 12`"
            ),
            color=PURPLE,
        )
        embed.set_footer(text=BRAND)
        await ctx.send(embed=embed)

    @giveaway.command(name="create", description="Create a database-backed giveaway")
    @app_commands.describe(
        prize="Prize being given away",
        duration_hours="Duration in hours (1–720)",
        winners="Number of winners (1–20)",
        required_role="Optional role members must have to enter",
        bonus_role="Optional role that receives extra draw entries",
        bonus_entries="Ticket weight for the bonus role (1–100; 1 means no bonus)",
    )
    async def giveaway_create(
        self,
        ctx: commands.Context,
        prize: str,
        duration_hours: app_commands.Range[int, 1, 720],
        winners: app_commands.Range[int, 1, 20] = 1,
        required_role: Optional[discord.Role] = None,
        bonus_role: Optional[discord.Role] = None,
        bonus_entries: app_commands.Range[int, 1, 100] = 2,
    ):
        if not await self._require_manager(ctx):
            return
        prize = prize.strip()
        if not prize or len(prize) > 200:
            await ctx.send("Prize must be between 1 and 200 characters.")
            return
        if bonus_role and int(bonus_entries) < 2:
            await ctx.send("Set bonus entries to at least **2** to give that role a bonus.")
            return

        channel = ctx.channel
        if not isinstance(channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel, discord.StageChannel)):
            await ctx.send("Please run this command in a text channel.")
            return

        ends_at = _utcnow() + timedelta(hours=int(duration_hours))
        requirements = {
            "required_role_id": required_role.id if required_role else None,
            "bonus_role_id": bonus_role.id if bonus_role else None,
            "bonus_entries": int(bonus_entries),
        }

        # Send the visible message first to get its message_id, then persist
        # its identifiers and settings in PostgreSQL.
        preview = giveaway_embed(
            prize=prize,
            host_id=ctx.author.id,
            winner_count=int(winners),
            ends_at=ends_at,
            entries=0,
            requirements=requirements,
            status="active",
            giveaway_id=None,
        )
        message = await ctx.send(embed=preview, view=GiveawayView(self))
        try:
            row = await db.create_giveaway(
                guild_id=ctx.guild.id,
                channel_id=channel.id,
                message_id=message.id,
                host_id=ctx.author.id,
                prize=prize,
                winner_count=int(winners),
                ends_at=ends_at,
                requirements=requirements,
            )
            if not row:
                raise RuntimeError("db.create_giveaway did not return a row")
            giveaway_id = int(_row_value(row, "id", 0))
            embed = giveaway_embed(
                prize=prize,
                host_id=ctx.author.id,
                winner_count=int(winners),
                ends_at=ends_at,
                entries=0,
                requirements=requirements,
                giveaway_id=giveaway_id,
            )
            await message.edit(embed=embed, view=GiveawayView(self))
            await ctx.send(f"✅ Giveaway created! ID: `{giveaway_id}` • Ends {_timestamp(ends_at)}")
        except Exception:
            log.exception("Could not save new giveaway to PostgreSQL")
            try:
                await message.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
            await ctx.send(
                "❌ I couldn't save the giveaway in PostgreSQL, so I removed its panel. "
                "Check the database connection and `db.init_db()` logs."
            )

    @giveaway.command(name="list", description="List active giveaways in this server")
    async def giveaway_list(self, ctx: commands.Context):
        if not ctx.guild:
            await ctx.send("This command can only be used in a server.")
            return
        try:
            rows = await self._fetch_active(ctx.guild.id)
        except Exception:
            log.exception("Could not list giveaways")
            await ctx.send("❌ The giveaway database is unavailable right now.")
            return
        if not rows:
            await ctx.send("There are no active giveaways in this server.")
            return
        embed = discord.Embed(title="🎉 Active Giveaways", color=PURPLE)
        for row in rows[:20]:
            embed.add_field(
                name=f"ID {int(_row_value(row, 'id', 0))} • {_row_value(row, 'prize', 'Giveaway')}",
                value=(
                    f"Channel: <#{int(_row_value(row, 'channel_id', 0))}>\n"
                    f"Entries: **{await self._entry_count(int(_row_value(row, 'id', 0)))}**\n"
                    f"Ends: {_timestamp(_row_value(row, 'ends_at'))}"
                ),
                inline=False,
            )
        embed.set_footer(text=BRAND)
        await ctx.send(embed=embed)

    @giveaway.command(name="end", description="End a giveaway and draw winners now")
    @app_commands.describe(giveaway_id="ID shown in the giveaway embed")
    async def giveaway_end(self, ctx: commands.Context, giveaway_id: int):
        if not await self._require_manager(ctx):
            return
        row = await self._fetch_giveaway(giveaway_id)
        if not row or int(_row_value(row, "guild_id", 0)) != ctx.guild.id:
            await ctx.send("❌ I couldn't find that giveaway in this server.")
            return
        if _row_value(row, "status", "active") != "active":
            await ctx.send("That giveaway is not active.")
            return
        success = await self.finish_giveaway(giveaway_id, force=True)
        await ctx.send("🏁 Giveaway ended." if success else "❌ Couldn't end the giveaway. Check the logs.")

    @giveaway.command(name="reroll", description="Reroll winner(s) for an ended giveaway")
    @app_commands.describe(giveaway_id="ID shown in the giveaway embed", winners="Number of replacement winners")
    async def giveaway_reroll(
        self,
        ctx: commands.Context,
        giveaway_id: int,
        winners: app_commands.Range[int, 1, 20] = 1,
    ):
        if not await self._require_manager(ctx):
            return
        row = await self._fetch_giveaway(giveaway_id)
        if not row or int(_row_value(row, "guild_id", 0)) != ctx.guild.id:
            await ctx.send("❌ I couldn't find that giveaway in this server.")
            return
        if _row_value(row, "status", "active") != "ended":
            await ctx.send("You can only reroll an **ended** giveaway.")
            return
        old_winners = [int(uid) for uid in _json_list(_row_value(row, "winners", []))]
        original_count = int(_row_value(row, "winner_count", 1))
        # Respect requested reroll count, while never exceeding the original count.
        row_dict = dict(row)
        row_dict["winner_count"] = min(int(winners), original_count)
        new_winners = await self._pick_winners(row_dict, exclude_ids=old_winners)
        if not new_winners:
            await ctx.send("No additional eligible entrants are available for a reroll.")
            return
        all_winners = old_winners + new_winners
        await db.db_execute(
            "UPDATE giveaways SET winners=$2::jsonb WHERE id=$1",
            int(giveaway_id),
            json.dumps(all_winners),
        )
        updated = await self._fetch_giveaway(giveaway_id) or row
        await self._edit_giveaway_message(updated, status="ended", winners=all_winners)
        mentions = ", ".join(f"<@{uid}>" for uid in new_winners)
        await ctx.send(f"🎲 **Rerolled!** New winner(s): {mentions}")

    @giveaway.command(name="cancel", description="Cancel an active giveaway without drawing")
    @app_commands.describe(giveaway_id="ID shown in the giveaway embed")
    async def giveaway_cancel(self, ctx: commands.Context, giveaway_id: int):
        if not await self._require_manager(ctx):
            return
        row = await self._fetch_giveaway(giveaway_id)
        if not row or int(_row_value(row, "guild_id", 0)) != ctx.guild.id:
            await ctx.send("❌ I couldn't find that giveaway in this server.")
            return
        if _row_value(row, "status", "active") != "active":
            await ctx.send("That giveaway is not active.")
            return
        await db.db_execute(
            "UPDATE giveaways SET status='cancelled' WHERE id=$1 AND status='active'",
            int(giveaway_id),
        )
        updated = await self._fetch_giveaway(giveaway_id) or row
        await self._edit_giveaway_message(updated, status="cancelled")
        await ctx.send(f"🛑 Giveaway `{giveaway_id}` has been cancelled.")

    @giveaway.command(name="entrants", description="Show entrant count and optionally list entrants")
    @app_commands.describe(giveaway_id="ID shown in the giveaway embed")
    async def giveaway_entrants(self, ctx: commands.Context, giveaway_id: int):
        if not ctx.guild:
            await ctx.send("This command can only be used in a server.")
            return
        row = await self._fetch_giveaway(giveaway_id)
        if not row or int(_row_value(row, "guild_id", 0)) != ctx.guild.id:
            await ctx.send("❌ I couldn't find that giveaway in this server.")
            return
        entries = await db.get_giveaway_entries(giveaway_id)
        user_ids = [int(_row_value(entry, "user_id", 0)) for entry in (entries or [])]
        embed = discord.Embed(
            title=f"👥 Giveaway {giveaway_id} Entrants",
            description=f"**{len(user_ids)}** unique participant(s)",
            color=PURPLE,
        )
        if user_ids:
            # Keep the response below Discord's embed field limits.
            preview = user_ids[:50]
            embed.add_field(
                name="Participants (first 50)",
                value=", ".join(f"<@{uid}>" for uid in preview),
                inline=False,
            )
        embed.set_footer(text=BRAND)
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(GiveawayCog(bot))
