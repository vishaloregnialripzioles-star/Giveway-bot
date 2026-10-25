"""Persistent Discord giveaway system for Giveway-bot.

Giveaway records and entries are stored in Supabase PostgreSQL.
"""
import asyncio
import json
import logging
import os
import random
import re
import time
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from datetime import datetime, timezone

import discord
from discord import app_commands

log = logging.getLogger("giveway-bot.giveaways")
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is missing. Set your Supabase PostgreSQL connection URI in Render Environment.")
DURATION_RE = re.compile(r"^(\d{1,5})(s|m|h|d)$", re.IGNORECASE)
MAX_DURATION_SECONDS = 60 * 60 * 24 * 30


def _connect():
    return psycopg.connect(
        DATABASE_URL,
        sslmode="require",
        connect_timeout=10,
        row_factory=dict_row,
    )


def _init_db():
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS giveaways (
                message_id BIGINT PRIMARY KEY,
                guild_id BIGINT NOT NULL,
                channel_id BIGINT NOT NULL,
                host_id BIGINT NOT NULL,
                prize TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                winner_count INTEGER NOT NULL,
                ends_at DOUBLE PRECISION NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                entrants_json TEXT NOT NULL DEFAULT '[]',
                winners_json TEXT NOT NULL DEFAULT '[]',
                created_at DOUBLE PRECISION NOT NULL
            )
        """)


_init_db()


@contextmanager
def _db():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _get(message_id: int):
    with _db() as conn:
        row = conn.execute("SELECT * FROM giveaways WHERE message_id = %s", (message_id,)).fetchone()
        return dict(row) if row else None


def _update(message_id: int, **fields):
    if not fields:
        return
    allowed = {"status", "entrants_json", "winners_json", "ends_at"}
    if not set(fields).issubset(allowed):
        raise ValueError("Unsupported giveaway field")
    assignments = ", ".join(f"{key} = %s" for key in fields)
    with _db() as conn:
        conn.execute(
            f"UPDATE giveaways SET {assignments} WHERE message_id = %s",
            (*fields.values(), message_id),
        )


def _entrants(row):
    try:
        return [int(x) for x in json.loads(row["entrants_json"])]
    except (ValueError, TypeError, json.JSONDecodeError):
        return []


def _winners(row):
    try:
        return [int(x) for x in json.loads(row["winners_json"])]
    except (ValueError, TypeError, json.JSONDecodeError):
        return []


def parse_duration(value: str) -> int:
    match = DURATION_RE.fullmatch(value.strip())
    if not match:
        raise ValueError("Use a duration like `30s`, `10m`, `2h`, or `1d`.")
    amount = int(match.group(1))
    unit = match.group(2).lower()
    seconds = amount * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
    if seconds < 30 or seconds > MAX_DURATION_SECONDS:
        raise ValueError("Duration must be between 30 seconds and 30 days.")
    return seconds


def _duration_label(seconds: int) -> str:
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds % size == 0 and seconds >= size:
            return f"{seconds // size}{unit}"
    return f"{seconds}s"


def _embed(row):
    ends = datetime.fromtimestamp(row["ends_at"], timezone.utc)
    entrants = _entrants(row)
    status = row["status"]
    color = discord.Color.blurple() if status == "active" else discord.Color.dark_grey()
    title = "🎉 GIVEAWAY" if status == "active" else (
        "🎊 GIVEAWAY ENDED" if status == "ended" else "🛑 GIVEAWAY CANCELLED"
    )
    embed = discord.Embed(title=title, color=color, timestamp=datetime.now(timezone.utc))
    embed.description = f"## 🎁 {row['prize']}\n"
    if row.get("description"):
        embed.description += f"{row['description']}\n\n"
    embed.description += (
        f"**Hosted by:** <@{row['host_id']}>\n"
        f"**Winners:** {row['winner_count']}\n"
        f"**Entries:** {len(entrants)}\n"
    )
    if status == "active":
        embed.description += f"**Ends:** <t:{int(row['ends_at'])}:R> • <t:{int(row['ends_at'])}:f>\n\n"
        embed.description += "Click **Enter Giveaway** below to join. You can leave and re-enter before it ends."
    elif status == "ended":
        winners = _winners(row)
        embed.description += f"**Ended:** <t:{int(row['ends_at'])}:f>\n"
        embed.add_field(
            name="🏆 Winner(s)",
            value=", ".join(f"<@{uid}>" for uid in winners) if winners else "No valid entries; no winner was selected.",
            inline=False,
        )
    else:
        embed.description += "\nThis giveaway was cancelled by a moderator."
    embed.set_footer(text=f"Giveway-bot • ID: {row['message_id']}")
    return embed


class GiveawayView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Enter Giveaway", style=discord.ButtonStyle.success,
        emoji="🎉", custom_id="giveaway:enter"
    )
    async def enter(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._change_entry(interaction, enter=True)

    @discord.ui.button(
        label="Leave Giveaway", style=discord.ButtonStyle.secondary,
        emoji="↩️", custom_id="giveaway:leave"
    )
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._change_entry(interaction, enter=False)

    async def _change_entry(self, interaction: discord.Interaction, enter: bool):
        if interaction.message is None or interaction.guild is None:
            await interaction.response.send_message("This button only works in the server giveaway post.", ephemeral=True)
            return
        row = _get(interaction.message.id)
        if not row or row["status"] != "active":
            await interaction.response.send_message("This giveaway is no longer active.", ephemeral=True)
            return
        if row["ends_at"] <= time.time():
            await interaction.response.send_message("This giveaway is ending. Please wait for the result.", ephemeral=True)
            return
        if interaction.user.bot:
            await interaction.response.send_message("Bots cannot enter giveaways.", ephemeral=True)
            return
        entrants = _entrants(row)
        user_id = interaction.user.id
        if enter:
            if user_id in entrants:
                await interaction.response.send_message("You're already entered. Good luck! 🍀", ephemeral=True)
                return
            entrants.append(user_id)
            message = "🎉 You're in! Good luck!"
        else:
            if user_id not in entrants:
                await interaction.response.send_message("You're not entered in this giveaway.", ephemeral=True)
                return
            entrants.remove(user_id)
            message = "You've left the giveaway."
        _update(row["message_id"], entrants_json=json.dumps(entrants))
        latest = _get(row["message_id"])
        try:
            await interaction.message.edit(embed=_embed(latest), view=self)
        except discord.HTTPException:
            log.warning("Could not refresh giveaway message %s after entry change", row["message_id"])
        await interaction.response.send_message(message, ephemeral=True)


class GiveawayManager:
    def __init__(self, client: discord.Client):
        self.client = client
        self._restore_lock = asyncio.Lock()
        self._restored = False
        self._end_tasks = {}

    async def restore_views(self):
        async with self._restore_lock:
            if self._restored:
                return
            with _db() as conn:
                rows = conn.execute("SELECT message_id, ends_at FROM giveaways WHERE status = 'active'").fetchall()
            for row in rows:
                self.client.add_view(GiveawayView(), message_id=int(row["message_id"]))
                self._schedule_end(int(row["message_id"]), float(row["ends_at"]))
            self._restored = True
            log.info("Restored %d active giveaway view(s).", len(rows))

    def _schedule_end(self, message_id: int, ends_at: float):
        existing = self._end_tasks.get(message_id)
        if existing and not existing.done():
            return
        task = asyncio.create_task(self._end_when_due(message_id, ends_at))
        self._end_tasks[message_id] = task

    async def _end_when_due(self, message_id: int, ends_at: float):
        try:
            await asyncio.sleep(max(0, ends_at - time.time()))
            row = _get(message_id)
            if row and row["status"] == "active":
                await self.finish(message_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Automatic end failed for giveaway %s", message_id)
        finally:
            self._end_tasks.pop(message_id, None)

    async def finish(self, message_id: int, *, reroll: bool = False):
        row = _get(message_id)
        if not row:
            raise ValueError("I couldn't find a giveaway with that message ID.")
        if not reroll and row["status"] != "active":
            raise ValueError("That giveaway has already ended or been cancelled.")
        entrants = _entrants(row)
        previous = _winners(row) if reroll else []
        eligible = [uid for uid in entrants if uid not in previous]
        winners = random.sample(eligible, min(int(row["winner_count"]), len(eligible))) if eligible else []
        if not reroll:
            _update(message_id, status="ended", winners_json=json.dumps(winners))
        else:
            _update(message_id, winners_json=json.dumps(previous + winners))
        latest = _get(message_id)
        channel = self.client.get_channel(int(row["channel_id"]))
        if channel is None:
            try:
                channel = await self.client.fetch_channel(int(row["channel_id"]))
            except discord.HTTPException:
                channel = None
        if channel is None:
            raise ValueError("The giveaway channel is unavailable. The result was saved.")
        try:
            message = await channel.fetch_message(message_id)
            await message.edit(embed=_embed(latest), view=None if latest["status"] != "active" else GiveawayView())
        except (discord.NotFound, discord.Forbidden):
            log.warning("Could not edit giveaway post %s; it may have been deleted or permissions changed.", message_id)
        if winners:
            mentions = ", ".join(f"<@{uid}>" for uid in winners)
            await channel.send(f"🎊 Congratulations {mentions}! You won **{row['prize']}**! 🎁")
        elif not reroll:
            await channel.send(f"🎉 **{row['prize']}** giveaway ended, but there were no eligible entries.")
        return winners

    def register(self, tree: app_commands.CommandTree):
        group = app_commands.Group(name="giveaway", description="Create and manage server giveaways.")

        @group.command(name="start", description="Start a giveaway with a join button.")
        @app_commands.default_permissions(manage_guild=True)
        @app_commands.describe(
            prize="What people can win",
            duration="Length: 30s minimum, up to 30d (examples: 10m, 2h, 1d)",
            winners="Number of winners (1–20)",
            channel="Where the giveaway will be posted",
            description="Optional extra details or eligibility rules",
        )
        async def start(
            interaction: discord.Interaction,
            prize: app_commands.Range[str, 1, 200],
            duration: app_commands.Range[str, 2, 8],
            winners: app_commands.Range[int, 1, 20] = 1,
            channel: discord.TextChannel | None = None,
            description: app_commands.Range[str, 1, 500] | None = None,
        ):
            if interaction.guild is None:
                await interaction.response.send_message("Giveaways can only be created in a server.", ephemeral=True)
                return
            if not interaction.user.guild_permissions.manage_guild:
                await interaction.response.send_message("❌ You need Manage Server permission to start a giveaway.", ephemeral=True)
                return
            try:
                seconds = parse_duration(duration)
            except ValueError as exc:
                await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
                return
            target = channel or interaction.channel
            if not isinstance(target, discord.TextChannel):
                await interaction.response.send_message("Choose a server text channel.", ephemeral=True)
                return
            me = interaction.guild.me
            permissions = target.permissions_for(me) if me else None
            if not permissions or not permissions.send_messages or not permissions.embed_links or not permissions.read_message_history:
                await interaction.response.send_message(
                    "❌ I need View Channel, Send Messages, Embed Links, and Read Message History in that channel.",
                    ephemeral=True,
                )
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            ends_at = time.time() + seconds
            # Temporary payload; the final message ID becomes the durable primary key.
            draft = {
                "message_id": 0, "guild_id": interaction.guild.id, "channel_id": target.id,
                "host_id": interaction.user.id, "prize": prize, "description": description or "",
                "winner_count": int(winners), "ends_at": ends_at, "status": "active",
                "entrants_json": "[]", "winners_json": "[]", "created_at": time.time(),
            }
            embed = discord.Embed(
                title="🎉 GIVEAWAY",
                description=(
                    f"## 🎁 {discord.utils.escape_markdown(prize)}\n"
                    + ((description or "") + "\n\n" if description else "")
                    + f"**Hosted by:** {interaction.user.mention}\n"
                    + f"**Winners:** {winners}\n**Entries:** 0\n"
                    + f"**Ends:** <t:{int(ends_at)}:R> • <t:{int(ends_at)}:f>\n\n"
                    + "Click **Enter Giveaway** below to join. You can leave and re-enter before it ends."
                ),
                color=discord.Color.blurple(),
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_footer(text="Giveway-bot • Good luck everyone!")
            try:
                post = await target.send(embed=embed, view=GiveawayView())
                draft["message_id"] = post.id
                with _db() as conn:
                    conn.execute(
                        """INSERT INTO giveaways
                        (message_id, guild_id, channel_id, host_id, prize, description,
                         winner_count, ends_at, status, entrants_json, winners_json, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        (post.id, draft["guild_id"], draft["channel_id"], draft["host_id"],
                         draft["prize"], draft["description"], draft["winner_count"], draft["ends_at"],
                         draft["status"], draft["entrants_json"], draft["winners_json"], draft["created_at"]),
                    )
                self.client.add_view(GiveawayView(), message_id=post.id)
                self._schedule_end(post.id, ends_at)
                await interaction.followup.send(f"✅ Giveaway posted in {target.mention}! [Jump to giveaway]({post.jump_url})", ephemeral=True)
            except discord.Forbidden:
                await interaction.followup.send("❌ I couldn't post there. Check my channel permissions.", ephemeral=True)
            except discord.HTTPException:
                log.exception("Failed to create giveaway post")
                await interaction.followup.send("❌ Discord couldn't create the giveaway. Please try again.", ephemeral=True)

        @group.command(name="end", description="End a giveaway now and pick its winners.")
        @app_commands.default_permissions(manage_guild=True)
        @app_commands.describe(message_id="Message ID of the giveaway post")
        async def end(interaction: discord.Interaction, message_id: str):
            await self._manage(interaction)
            if interaction.response.is_done():
                return
            if not message_id.isdigit():
                await interaction.response.send_message("Enter the numeric message ID of the giveaway post.", ephemeral=True)
                return
            row = _get(int(message_id))
            if not row or interaction.guild_id != row["guild_id"]:
                await interaction.response.send_message("Giveaway not found in this server.", ephemeral=True)
                return
            try:
                await interaction.response.defer(ephemeral=True, thinking=True)
                winners = await self.finish(int(message_id))
                await interaction.followup.send(
                    f"✅ Giveaway ended. Winners: {', '.join(f'<@{uid}>' for uid in winners) if winners else 'No eligible entries.'}",
                    ephemeral=True,
                )
            except ValueError as exc:
                await interaction.followup.send(f"❌ {exc}", ephemeral=True)

        @group.command(name="reroll", description="Pick new winner(s) from the remaining entrants.")
        @app_commands.default_permissions(manage_guild=True)
        @app_commands.describe(message_id="Message ID of the ended giveaway post")
        async def reroll(interaction: discord.Interaction, message_id: str):
            if not await self._manage(interaction):
                return
            if not message_id.isdigit():
                await interaction.response.send_message("Enter the numeric message ID of the giveaway post.", ephemeral=True)
                return
            row = _get(int(message_id))
            if not row or row["guild_id"] != interaction.guild_id or row["status"] != "ended":
                await interaction.response.send_message("I couldn't find an ended giveaway in this server.", ephemeral=True)
                return
            try:
                await interaction.response.defer(ephemeral=True, thinking=True)
                winners = await self.finish(int(message_id), reroll=True)
                await interaction.followup.send(
                    f"🎲 Reroll result: {', '.join(f'<@{uid}>' for uid in winners) if winners else 'No remaining eligible entrants.'}",
                    ephemeral=True,
                )
            except ValueError as exc:
                await interaction.followup.send(f"❌ {exc}", ephemeral=True)

        @group.command(name="cancel", description="Cancel a giveaway without selecting winners.")
        @app_commands.default_permissions(manage_guild=True)
        @app_commands.describe(message_id="Message ID of the giveaway post")
        async def cancel(interaction: discord.Interaction, message_id: str):
            if not await self._manage(interaction):
                return
            if not message_id.isdigit():
                await interaction.response.send_message("Enter the numeric message ID of the giveaway post.", ephemeral=True)
                return
            row = _get(int(message_id))
            if not row or row["guild_id"] != interaction.guild_id or row["status"] != "active":
                await interaction.response.send_message("I couldn't find an active giveaway in this server.", ephemeral=True)
                return
            _update(int(message_id), status="cancelled")
            task = self._end_tasks.pop(int(message_id), None)
            if task and not task.done():
                task.cancel()
            latest = _get(int(message_id))
            channel = self.client.get_channel(int(row["channel_id"]))
            if channel:
                try:
                    message = await channel.fetch_message(int(message_id))
                    await message.edit(embed=_embed(latest), view=None)
                except discord.HTTPException:
                    pass
                await channel.send(f"🛑 The **{row['prize']}** giveaway has been cancelled.")
            await interaction.response.send_message("✅ Giveaway cancelled.", ephemeral=True)

        @group.command(name="entrants", description="Show the current entrants in a giveaway.")
        @app_commands.default_permissions(manage_guild=True)
        @app_commands.describe(message_id="Message ID of the giveaway post")
        async def entrants(interaction: discord.Interaction, message_id: str):
            if not await self._manage(interaction):
                return
            if not message_id.isdigit():
                await interaction.response.send_message("Enter the numeric message ID of the giveaway post.", ephemeral=True)
                return
            row = _get(int(message_id))
            if not row or row["guild_id"] != interaction.guild_id:
                await interaction.response.send_message("Giveaway not found in this server.", ephemeral=True)
                return
            ids = _entrants(row)
            preview = ", ".join(f"<@{uid}>" for uid in ids[:50]) or "No entries yet."
            if len(ids) > 50:
                preview += f"\n…and {len(ids) - 50} more."
            embed = discord.Embed(title=f"🎟️ Entrants • {row['prize']}", description=preview, color=discord.Color.blurple())
            embed.set_footer(text=f"{len(ids)} total entr(y/ies)")
            await interaction.response.send_message(embed=embed, ephemeral=True)

        tree.add_command(group)

    async def _manage(self, interaction: discord.Interaction) -> bool:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This command only works in a server.", ephemeral=True)
            return False
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ You need Manage Server permission to manage giveaways.", ephemeral=True)
            return False
        return True


def register_giveaway_commands(tree: app_commands.CommandTree, client: discord.Client):
    manager = GiveawayManager(client)
    manager.register(tree)
    return manager
