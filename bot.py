import os
import time
import threading
import asyncio
import io
import re
import random
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import defaultdict, deque

import asyncpg
import discord
from discord import app_commands
from discord.ext import commands
from flask import Flask

import db
import games
import basic_commands
from owner_prefix import setup_owner_prefixless

# Current repository modules (all present on main)
import autorolesetup
import automation
import cmdmaker
import command_permissions
import embed_builder
import giveaways
import leveling
import snipe
import welcome_autorole
import youtube_alerts

# CONFIGURATION
# =========================================================

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN environment variable is required")


# =========================================================
# WEB / HEALTH SERVER
# =========================================================

app = Flask(__name__)


@app.get("/")
def home():
    return "✈️ Air Commander is online!", 200


@app.get("/health")
def health():
    return {
        "status": "ok",
        "discord": bot.is_ready() if "bot" in globals() else False
    }, 200


def run_web():
    port = int(os.getenv("PORT", "10000"))
    app.run(
        host="0.0.0.0",
        port=port,
        threaded=True,
        use_reloader=False
    )


# =========================================================
# BOT CONFIGURATION
# =========================================================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

class AirCommanderBot(commands.Bot):
    async def setup_hook(self):
        # discord.py calls this automatically before connecting to Gateway.
        # Use a uniquely named module-level loader to avoid setup_hook name
        # shadowing/ambiguity in this large single-file bot.
        print("🔄 Air Commander setup_hook method called...", flush=True)
        await _air_startup_loader(self)


bot = AirCommanderBot(
    command_prefix=",",
    intents=intents,
    help_command=None
)

setup_owner_prefixless(bot)

start_time = time.time()
bot._air_start_time = start_time

games.setup(bot)
basic_commands.setup(bot)


# =========================================================
# PURGE / AFK / STEAL
# =========================================================

# AFK is kept in memory so no database changes are required.
# Global AFK applies across every server the bot is in.
# Guild AFK applies only to the current server.
global_afk = {}
guild_afk = {}


# ---------------------------------------------------------
# PURGE
# ---------------------------------------------------------

@bot.tree.command(name="purge", description="Delete messages from the current channel.")
@app_commands.describe(amount="Number of messages to delete (1-100)")
@app_commands.checks.has_permissions(manage_messages=True)
@app_commands.checks.bot_has_permissions(manage_messages=True)
async def slash_purge(interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100]):
    if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
        return await interaction.response.send_message(
            "❌ This command can only be used in a text channel.", ephemeral=True
        )

    await interaction.response.defer(ephemeral=True)

    try:
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(
            f"🧹 Deleted **{len(deleted)}** message(s).", ephemeral=True
        )
    except discord.Forbidden:
        await interaction.followup.send(
            "❌ I need **Manage Messages** permission in this channel.", ephemeral=True
        )
    except discord.HTTPException as e:
        await interaction.followup.send(
            f"❌ Discord rejected the purge: `{e}`", ephemeral=True
        )


@bot.command(name="purge")
@commands.has_permissions(manage_messages=True)
@commands.bot_has_permissions(manage_messages=True)
async def prefix_purge(ctx, amount: int):
    """Delete 1-100 messages from the current channel."""
    if not isinstance(ctx.channel, discord.TextChannel):
        return await ctx.send("❌ This command can only be used in a text channel.")

    if amount < 1 or amount > 100:
        return await ctx.send("❌ Amount must be between **1 and 100**.")

    try:
        deleted = await ctx.channel.purge(limit=amount + 1)
        msg = await ctx.send(f"🧹 Deleted **{max(len(deleted) - 1, 0)}** message(s).")
        await asyncio.sleep(3)
        try:
            await msg.delete()
        except discord.HTTPException:
            pass
    except discord.Forbidden:
        await ctx.send("❌ I need **Manage Messages** permission in this channel.")
    except discord.HTTPException as e:
        await ctx.send(f"❌ Discord rejected the purge: `{e}`")


# ---------------------------------------------------------
# PREFIX WARNING COMMANDS
# Prefix: ,
# ---------------------------------------------------------

@bot.command(name="warn")
@commands.has_guild_permissions(moderate_members=True)
async def prefix_warn(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    """Warn a member and save a persistent moderation record.
    Usage: ,warn @user reason
    """
    if not ctx.guild:
        return await ctx.send("❌ This command can only be used inside a server.")
    if member == ctx.author or member.bot:
        return await ctx.send("❌ That member cannot be warned.")
    if member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
        return await ctx.send("❌ You cannot warn a member with an equal or higher role.")
    if ctx.guild.me and member.top_role >= ctx.guild.me.top_role:
        return await ctx.send("❌ I cannot manage that member because of role hierarchy.")

    try:
        case_code, warning_count = await db.create_warning(
            ctx.guild.id,
            member.id,
            ctx.author.id,
            reason[:1024],
            "Not provided"
        )
        e = air_embed(
            "Warning Issued",
            f"{member.mention} has received a moderation warning.",
            discord.Color.orange()
        )
        e.add_field(name="Member", value=f"{member.mention}\n`{member.id}`", inline=True)
        e.add_field(name="Total Warnings", value=f"**{warning_count}**", inline=True)
        e.add_field(name="Case", value=f"`{case_code}`", inline=True)
        e.add_field(name="Moderator", value=ctx.author.mention, inline=True)
        e.add_field(name="Reason", value=reason[:1024], inline=False)
        await ctx.send(embed=e)
    except Exception as exc:
        print(f"Prefix warn error: {type(exc).__name__}: {exc}")
        await ctx.send("❌ Warning could not be saved. Check the database/Render logs.")


@bot.command(name="warnings", aliases=["warning"])
@commands.has_guild_permissions(moderate_members=True)
async def prefix_warnings(ctx, member: discord.Member):
    """View a member's warning history.
    Usage: ,warnings @user
    """
    if not ctx.guild:
        return await ctx.send("❌ This command can only be used inside a server.")

    try:
        rows = await db.get_warnings(ctx.guild.id, member.id)
        e = air_embed(
            "Warning History",
            f"Moderation history for {member.mention}.",
            discord.Color.orange()
        )
        e.add_field(name="Total", value=f"**{len(rows)}** warning(s)", inline=True)

        if not rows:
            e.add_field(name="History", value="No warnings recorded.", inline=False)
        else:
            history = []
            for row in rows[:10]:
                history.append(
                    f"`{row['case_code']}` • {discord.utils.format_dt(row['created_at'], 'R')}\n"
                    f"**Reason:** {str(row['reason'])[:300]}\n"
                    f"**Moderator:** <@{row['moderator_id']}>"
                )
            e.add_field(name="Recent Warnings", value="\n\n".join(history)[:1024], inline=False)

        await ctx.send(embed=e)
    except Exception as exc:
        print(f"Prefix warnings error: {type(exc).__name__}: {exc}")
        await ctx.send("❌ Warning history could not be loaded.")


@bot.command(name="unwarn")
@commands.has_guild_permissions(moderate_members=True)
async def prefix_unwarn(ctx, case_code: str):
    """Remove a warning by case code.
    Usage: ,unwarn AC-W0001
    """
    if not ctx.guild:
        return await ctx.send("❌ This command can only be used inside a server.")

    match = re.fullmatch(r"AC-W(\d+)", case_code.strip().upper())
    if not match:
        return await ctx.send("❌ Invalid case code. Example: `,unwarn AC-W0001`.")

    warning_id = int(match.group(1))
    try:
        if not db._pool:
            return await ctx.send("❌ Database is unavailable.")

        result = await db._pool.execute(
            "DELETE FROM warnings WHERE guild_id=$1 AND id=$2",
            ctx.guild.id,
            warning_id
        )
        if result != "DELETE 1":
            return await ctx.send(f"❌ Warning `{case_code.upper()}` was not found in this server.")

        e = air_embed(
            "Warning Removed",
            f"Warning `{case_code.upper()}` has been removed.",
            discord.Color.green()
        )
        e.add_field(name="Moderator", value=ctx.author.mention, inline=True)
        e.add_field(name="Case", value=f"`{case_code.upper()}`", inline=True)
        await ctx.send(embed=e)
    except Exception as exc:
        print(f"Prefix unwarn error: {type(exc).__name__}: {exc}")
        await ctx.send("❌ Warning could not be removed. Check the database/Render logs.")


# ---------------------------------------------------------
# AFK HELPERS
# ---------------------------------------------------------

def _afk_reason(value):
    value = (value or "").strip()
    return value[:250] if value else "AFK"


def _set_guild_afk(guild_id, user_id, reason):
    guild_afk[(guild_id, user_id)] = {
        "reason": _afk_reason(reason),
        "since": discord.utils.utcnow(),
    }


def _set_global_afk(user_id, reason):
    global_afk[user_id] = {
        "reason": _afk_reason(reason),
        "since": discord.utils.utcnow(),
    }


def _remove_afk(guild_id, user_id):
    removed_guild = guild_afk.pop((guild_id, user_id), None)
    removed_global = global_afk.pop(user_id, None)
    return removed_guild, removed_global


def _afk_text(data):
    if not data:
        return "AFK"
    return data.get("reason", "AFK")


# ---------------------------------------------------------
# /afk
# ---------------------------------------------------------

@bot.tree.command(name="afk", description="Set a guild or global AFK status.")
@app_commands.describe(
    scope="Choose whether your AFK is guild-only or global",
    reason="Optional AFK reason"
)
@app_commands.choices(scope=[
    app_commands.Choice(name="Guild", value="guild"),
    app_commands.Choice(name="Global", value="global"),
])
async def slash_afk(interaction: discord.Interaction, scope: app_commands.Choice[str], reason: str | None = None):
    if not interaction.guild:
        return await interaction.response.send_message(
            "❌ This command can only be used inside a server.", ephemeral=True
        )

    reason = _afk_reason(reason)

    if scope.value == "global":
        _set_global_afk(interaction.user.id, reason)
        text = "🌐 **Global AFK enabled.** Your AFK will be shown across servers."
    else:
        _set_guild_afk(interaction.guild.id, interaction.user.id, reason)
        text = f"🏠 **Guild AFK enabled** in **{interaction.guild.name}**."

    e = discord.Embed(
        title="💤 AFK Status",
        description=f"{text}\n\n📝 **Reason:** {reason}",
        color=discord.Color.orange(),
        timestamp=discord.utils.utcnow(),
    )
    e.set_footer(text="✈️ Air Commander • AFK System")
    await interaction.response.send_message(embed=e)


@bot.command(name="afk")
async def prefix_afk(ctx, scope: str = "guild", *, reason: str = "AFK"):
    """Set guild or global AFK. Usage: ,afk guild reason / ,afk global reason"""
    if not ctx.guild:
        return await ctx.send("❌ This command can only be used inside a server.")

    scope = scope.lower().strip()
    if scope not in {"guild", "global"}:
        reason = f"{scope} {reason}".strip()
        scope = "guild"

    reason = _afk_reason(reason)

    if scope == "global":
        _set_global_afk(ctx.author.id, reason)
        text = "🌐 **Global AFK enabled.** Your AFK will be shown across servers."
    else:
        _set_guild_afk(ctx.guild.id, ctx.author.id, reason)
        text = f"🏠 **Guild AFK enabled** in **{ctx.guild.name}**."

    e = discord.Embed(
        title="💤 AFK Status",
        description=f"{text}\n\n📝 **Reason:** {reason}",
        color=discord.Color.orange(),
        timestamp=discord.utils.utcnow(),
    )
    e.set_footer(text="✈️ Air Commander • AFK System")
    await ctx.send(embed=e)


# ---------------------------------------------------------
# STEAL HELPERS
# ---------------------------------------------------------

EMOJI_RE = re.compile(r"<(?P<animated>a?):(?P<name>[A-Za-z0-9_]{1,32}):(?P<id>\d+)>")


def _extract_emoji_tokens(text: str):
    found = []
    seen = set()
    for match in EMOJI_RE.finditer(text or ""):
        emoji_id = int(match.group("id"))
        if emoji_id in seen:
            continue
        seen.add(emoji_id)
        found.append({
            "name": match.group("name"),
            "id": emoji_id,
            "animated": bool(match.group("animated")),
            "url": f"https://cdn.discordapp.com/emojis/{emoji_id}.{'gif' if match.group('animated') else 'png'}?size=160&quality=lossless",
        })
    return found


async def _read_url(url: str):
    try:
        async with bot.http._HTTPClient__session.get(url) as response:
            if response.status != 200:
                return None
            return await response.read()
    except Exception:
        # Fallback through discord.py's asset reader where available.
        return None


async def _fetch_bytes(url: str):
    # discord.py exposes its aiohttp session internally. Using it avoids
    # adding another dependency to requirements.txt.
    data = await _read_url(url)
    if data:
        return data
    return None


async def _create_stolen_emoji(guild: discord.Guild, item):
    data = await _fetch_bytes(item["url"])
    if not data:
        return False, "download failed"

    try:
        await guild.create_custom_emoji(
            name=item["name"][:32],
            image=data,
            reason="Air Commander steal command",
        )
        return True, "ok"
    except discord.HTTPException as e:
        return False, str(e)


async def _steal_from_message(guild: discord.Guild, message: discord.Message):
    emoji_items = _extract_emoji_tokens(message.content)
    emoji_items = emoji_items[:50]

    emoji_ok = 0
    emoji_failed = 0

    for item in emoji_items:
        ok, _ = await _create_stolen_emoji(guild, item)
        if ok:
            emoji_ok += 1
        else:
            emoji_failed += 1

    # Discord message stickers are represented by StickerItem objects.
    # We process at most 5, as requested. Sticker creation can fail when
    # the source sticker type/file is not supported by Discord's API.
    sticker_ok = 0
    sticker_failed = 0
    sticker_items = list(message.stickers)[:5]

    for sticker_item in sticker_items:
        try:
            sticker = await sticker_item.fetch()
            if not sticker.url:
                sticker_failed += 1
                continue

            data = await _fetch_bytes(str(sticker.url))
            if not data:
                sticker_failed += 1
                continue

            # Discord custom stickers require a supported image file.
            file = discord.File(io.BytesIO(data), filename="sticker.png")
            await guild.create_sticker(
                name=re.sub(r"[^a-zA-Z0-9_-]", "-", sticker.name)[:30] or "stolen-sticker",
                description=(sticker.description or "Stolen by Air Commander")[:100],
                emoji=sticker.emoji or "🙂",
                file=file,
                reason="Air Commander steal command",
            )
            sticker_ok += 1
        except Exception:
            sticker_failed += 1

    return emoji_ok, emoji_failed, sticker_ok, sticker_failed


async def _resolve_steal_message(ctx, message_id: str | None):
    if message_id:
        try:
            return await ctx.channel.fetch_message(int(message_id))
        except (ValueError, discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None

    reference = ctx.message.reference
    if reference and reference.message_id:
        try:
            return await ctx.channel.fetch_message(reference.message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None

    return ctx.message


# ---------------------------------------------------------
# ,steal
# ---------------------------------------------------------

@bot.command(name="steal")
@commands.has_permissions(manage_emojis_and_stickers=True)
@commands.bot_has_permissions(manage_emojis_and_stickers=True)
async def prefix_steal(ctx, message_id: str | None = None):
    """Steal up to 50 emojis and 5 stickers from a message."""
    if not ctx.guild:
        return await ctx.send("❌ This command can only be used inside a server.")

    message = await _resolve_steal_message(ctx, message_id)
    if not message:
        return await ctx.send("❌ Message not found.")

    # For best results, reply to the message containing the emojis/stickers:
    # ,steal  (while replying), or use ,steal MESSAGE_ID.
    if not message.content and not message.stickers:
        return await ctx.send("❌ No custom emojis or stickers found in that message.")

    e = discord.Embed(
        title="📥 Stealing Expressions...",
        description="Please wait while I import the selected emojis/stickers.",
        color=discord.Color.blurple(),
    )
    status = await ctx.send(embed=e)

    emoji_ok, emoji_failed, sticker_ok, sticker_failed = await _steal_from_message(ctx.guild, message)

    e = discord.Embed(
        title="📥 Steal Complete",
        description="Expression import finished.",
        color=discord.Color.green() if (emoji_ok or sticker_ok) else discord.Color.red(),
        timestamp=discord.utils.utcnow(),
    )
    e.add_field(name="😀 Emojis", value=f"✅ {emoji_ok} added\n❌ {emoji_failed} failed", inline=True)
    e.add_field(name="🏷️ Stickers", value=f"✅ {sticker_ok} added\n❌ {sticker_failed} failed", inline=True)
    e.set_footer(text="✈️ Air Commander • Limits: 50 emojis / 5 stickers")
    await status.edit(embed=e)


# ---------------------------------------------------------
# /steal
# ---------------------------------------------------------

@bot.tree.command(name="steal", description="Steal up to 50 emojis and 5 stickers from a message.")
@app_commands.describe(message_id="Optional message ID containing the emojis/stickers")
@app_commands.checks.has_permissions(manage_emojis_and_stickers=True)
@app_commands.checks.bot_has_permissions(manage_emojis_and_stickers=True)
async def slash_steal(interaction: discord.Interaction, message_id: str | None = None):
    if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
        return await interaction.response.send_message(
            "❌ This command can only be used in a server text channel.", ephemeral=True
        )

    message = None
    if message_id:
        try:
            message = await interaction.channel.fetch_message(int(message_id))
        except (ValueError, discord.NotFound, discord.Forbidden, discord.HTTPException):
            return await interaction.response.send_message("❌ Message not found.", ephemeral=True)

    if not message:
        return await interaction.response.send_message(
            "ℹ️ Give me a **message ID** containing the emojis/stickers.\n"
            "Example: `/steal message_id:123456789012345678`",
            ephemeral=True,
        )

    if not message.content and not message.stickers:
        return await interaction.response.send_message(
            "❌ No custom emojis or stickers found in that message.", ephemeral=True
        )

    await interaction.response.defer()
    emoji_ok, emoji_failed, sticker_ok, sticker_failed = await _steal_from_message(interaction.guild, message)

    e = discord.Embed(
        title="📥 Steal Complete",
        description="Expression import finished.",
        color=discord.Color.green() if (emoji_ok or sticker_ok) else discord.Color.red(),
        timestamp=discord.utils.utcnow(),
    )
    e.add_field(name="😀 Emojis", value=f"✅ {emoji_ok} added\n❌ {emoji_failed} failed", inline=True)
    e.add_field(name="🏷️ Stickers", value=f"✅ {sticker_ok} added\n❌ {sticker_failed} failed", inline=True)
    e.set_footer(text="✈️ Air Commander • Limits: 50 emojis / 5 stickers")
    await interaction.followup.send(embed=e)



# =========================================================
# EMBEDDED COMMAND MODULES
# =========================================================


MAX_PROMPT = 1800


def clean_name(value: str) -> str:
    value = value.strip().lower().replace(" ", "-")
    value = re.sub(r"[^a-z0-9_-]", "", value)
    return value[:32]


def render_text(text: str, interaction: discord.Interaction) -> str:
    user = interaction.user
    guild = interaction.guild
    replacements = {
        "{user}": user.mention,
        "{username}": user.display_name,
        "{userid}": str(user.id),
        "{server}": guild.name if guild else "DM",
        "{membercount}": str(guild.member_count) if guild else "0",
        "{channel}": interaction.channel.mention if hasattr(interaction.channel, "mention") else "this channel",
    }
    for key, value in replacements.items():
        text = text.replace(key, value)
    return text[:4000]


def execute_prompt(prompt: str, interaction: discord.Interaction):
    """Safe mini-interpreter; prompts are never executed as Python or shell code."""
    raw = prompt.strip()
    low = raw.lower()

    if low.startswith("random:"):
        choices = [x.strip() for x in raw.split(":", 1)[1].split("|") if x.strip()]
        if choices:
            return render_text(random.choice(choices), interaction), None

    match = re.search(r"roll\s+(?:a\s+)?d(\d+)", low)
    if match:
        sides = max(2, min(int(match.group(1)), 1000000))
        return f"🎲 **{random.randint(1, sides)}** (d{sides})", None
    match = re.search(r"roll\s+(\d+)\s*[-–]\s*(\d+)", low)
    if match:
        a, b = sorted((int(match.group(1)), int(match.group(2))))
        return f"🎲 **{random.randint(a, b)}**", None

    if low.startswith("embed"):
        parts = [x.strip() for x in raw.split("|", 2)]
        if len(parts) >= 3:
            e = discord.Embed(title=render_text(parts[1], interaction), description=render_text(parts[2], interaction), color=discord.Color.blurple(), timestamp=discord.utils.utcnow())
            e.set_footer(text="Air Commander • Custom Command")
            return None, e

    if "member count" in low or "how many members" in low:
        if interaction.guild:
            return f"👥 **{interaction.guild.member_count:,}** members are in **{interaction.guild.name}**.", None
    if "server name" in low:
        return f"🛰️ Server: **{interaction.guild.name if interaction.guild else 'DM'}**", None
    if "user id" in low:
        return f"🪪 Your user ID is `{interaction.user.id}`.", None
    if "avatar" in low:
        e = discord.Embed(title=f"✈️ {interaction.user.display_name} • Avatar", color=discord.Color.blurple())
        e.set_image(url=interaction.user.display_avatar.replace(size=1024).url)
        return None, e

    for prefix in ("reply:", "respond:", "say:", "send:", "message:"):
        if low.startswith(prefix):
            return render_text(raw[len(prefix):].strip(), interaction), None

    return render_text(raw, interaction), None


async def _ensure_table():
    if not db._pool:
        return
    await db._pool.execute("""CREATE TABLE IF NOT EXISTS custom_commands(
        guild_id BIGINT NOT NULL,
        command_name TEXT NOT NULL,
        usage TEXT NOT NULL,
        prompt TEXT NOT NULL,
        creator_id BIGINT NOT NULL,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        PRIMARY KEY(guild_id, command_name)
    )""")


async def _save(guild_id, name, usage, prompt, creator_id):
    if not db._pool:
        return False
    await db._pool.execute("""INSERT INTO custom_commands(guild_id,command_name,usage,prompt,creator_id)
        VALUES($1,$2,$3,$4,$5)
        ON CONFLICT(guild_id,command_name) DO UPDATE SET usage=EXCLUDED.usage,prompt=EXCLUDED.prompt,creator_id=EXCLUDED.creator_id""",
        guild_id, name, usage, prompt, creator_id)
    return True


async def _all(guild_id=None):
    if not db._pool:
        return []
    if guild_id is None:
        return await db._pool.fetch("SELECT guild_id,command_name,usage,prompt,creator_id FROM custom_commands ORDER BY created_at")
    return await db._pool.fetch("SELECT guild_id,command_name,usage,prompt,creator_id FROM custom_commands WHERE guild_id=$1 ORDER BY created_at", guild_id)


async def _delete(guild_id, name):
    if not db._pool:
        return False
    result = await db._pool.execute("DELETE FROM custom_commands WHERE guild_id=$1 AND command_name=$2", guild_id, name)
    return result.endswith("1")


def _make_command(bot, guild_id: int, name: str, usage: str, prompt: str):
    async def callback(interaction: discord.Interaction):
        try:
            text, custom_embed = execute_prompt(prompt, interaction)
            if custom_embed:
                await interaction.response.send_message(embed=custom_embed)
            else:
                e = discord.Embed(title=f"✈️ /{name}", description=text or "Done.", color=discord.Color.blurple(), timestamp=discord.utils.utcnow())
                e.add_field(name="Usage", value=usage[:1024], inline=False)
                e.set_footer(text="Air Commander • Custom Command")
                await interaction.response.send_message(embed=e)
        except Exception as exc:
            print(f"Custom command /{name} error: {type(exc).__name__}: {exc}")
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ This custom command could not be completed.", ephemeral=True)

    command = app_commands.Command(name=name, description=usage[:100] or "Custom Air Commander command", callback=callback)
    command.extras["air_custom"] = True
    command.extras["air_guild_id"] = guild_id
    return command


def _remove_existing(bot, guild_id, name):
    guild = discord.Object(id=guild_id)
    existing = bot.tree.get_command(name, guild=guild)
    if existing and existing.extras.get("air_custom"):
        bot.tree.remove_command(name, guild=guild)


async def load_custom_commands(bot):
    for _ in range(60):
        if db._pool:
            break
        await asyncio.sleep(0.5)
    if not db._pool:
        print("⚠️ Custom command loader skipped: database unavailable.")
        return
    await _ensure_table()
    rows = await _all()
    loaded = 0
    for row in rows:
        guild_id, name, usage, prompt, _creator = row
        if not bot.get_guild(guild_id):
            continue
        try:
            _remove_existing(bot, guild_id, name)
            bot.tree.add_command(_make_command(bot, guild_id, name, usage, prompt), guild=discord.Object(id=guild_id), override=True)
            loaded += 1
        except Exception as exc:
            print(f"Custom command load error /{name}: {type(exc).__name__}: {exc}")
    for guild in bot.guilds:
        try:
            await bot.tree.sync(guild=guild)
        except Exception as exc:
            print(f"Custom command sync error for {guild.id}: {type(exc).__name__}: {exc}")
    print(f"🧩 Loaded {loaded} custom Air Commander command(s).")


def setup_cmdmaker(bot):
    @bot.tree.command(name="cmdmaker", description="Create a custom slash command")
    @app_commands.describe(cmdname="New command name", usage="How the command should be used", prompt="How the command works and what it should do")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cmdmaker(interaction: discord.Interaction, cmdname: str, usage: str, prompt: str):
        if not interaction.guild:
            return await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
        name = clean_name(cmdname)
        if not name:
            return await interaction.response.send_message("❌ Command name must contain letters or numbers.", ephemeral=True)
        if name in {"cmdmaker", "cmdlist", "cmddelete", "help", "ping"}:
            return await interaction.response.send_message("❌ That command name is reserved.", ephemeral=True)
        if len(name) > 32:
            return await interaction.response.send_message("❌ Command name must be 1–32 characters.", ephemeral=True)
        if not usage.strip() or len(usage) > 100:
            return await interaction.response.send_message("❌ Usage must be 1–100 characters.", ephemeral=True)
        if not prompt.strip() or len(prompt) > MAX_PROMPT:
            return await interaction.response.send_message(f"❌ Prompt must be 1–{MAX_PROMPT} characters.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        await _ensure_table()
        if not await _save(interaction.guild.id, name, usage.strip(), prompt.strip(), interaction.user.id):
            return await interaction.followup.send("❌ Database is unavailable, so the command could not be saved.", ephemeral=True)
        _remove_existing(bot, interaction.guild.id, name)
        bot.tree.add_command(_make_command(bot, interaction.guild.id, name, usage.strip(), prompt.strip()), guild=interaction.guild, override=True)
        try:
            await bot.tree.sync(guild=interaction.guild)
        except Exception as exc:
            print(f"Custom command sync error: {type(exc).__name__}: {exc}")
            return await interaction.followup.send("⚠️ Saved, but Discord could not sync the new command yet. It will retry on the next startup.", ephemeral=True)

        e = discord.Embed(title="🧩 Air Commander • Command Created", description=f"Your custom command **/{name}** is ready.", color=discord.Color.green(), timestamp=discord.utils.utcnow())
        e.add_field(name="Command", value=f"`/{name}`", inline=True)
        e.add_field(name="Usage", value=usage.strip(), inline=True)
        e.add_field(name="How it works", value=prompt.strip()[:1024], inline=False)
        e.add_field(name="Supported placeholders", value="`{user}` `{username}` `{userid}` `{server}` `{membercount}` `{channel}`", inline=False)
        e.set_footer(text="Air Commander • Custom command saved to the database")
        await interaction.followup.send(embed=e, ephemeral=True)

    @bot.tree.command(name="cmdlist", description="List custom commands in this server")
    async def cmdlist(interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("❌ Server only.", ephemeral=True)
        rows = await _all(interaction.guild.id)
        e = discord.Embed(title="🧩 Air Commander • Custom Commands", description="Commands created with /cmdmaker.", color=discord.Color.blurple())
        if rows:
            e.add_field(name="Available", value="\n".join(f"• `/{r['command_name']}` — {r['usage']}" for r in rows[:25]), inline=False)
        else:
            e.description = "No custom commands have been created yet."
        await interaction.response.send_message(embed=e)

    @bot.tree.command(name="cmddelete", description="Delete a custom command")
    @app_commands.describe(cmdname="Custom command to delete")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def cmddelete(interaction: discord.Interaction, cmdname: str):
        if not interaction.guild:
            return await interaction.response.send_message("❌ Server only.", ephemeral=True)
        name = clean_name(cmdname)
        if not await _delete(interaction.guild.id, name):
            return await interaction.response.send_message("❌ Custom command not found.", ephemeral=True)
        _remove_existing(bot, interaction.guild.id, name)
        try:
            await bot.tree.sync(guild=interaction.guild)
        except Exception:
            pass
        e = discord.Embed(title="🗑️ Custom Command Deleted", description=f"`/{name}` has been removed from this server.", color=discord.Color.red())
        await interaction.response.send_message(embed=e, ephemeral=True)

    setup_autosetup(bot)
    bot._air_load_custom_commands = load_custom_commands


# =========================================================
# =========================================================

HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")


def _embed(title, description, color):
    e = discord.Embed(
        title=f"✈️ {title}",
        description=description,
        color=color,
        timestamp=discord.utils.utcnow(),
    )
    e.set_footer(text="Air Commander • Auto Role Setup")
    return e


def _parse_layout(layout: str):
    roles = []
    seen = set()
    for raw in layout.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if " - " not in line:
            raise ValueError(f"Invalid line: **{line}**\nUse `Role Name - #RRGGBB`.")
        name, hexcode = line.rsplit(" - ", 1)
        name = name.strip()
        hexcode = hexcode.strip()
        match = HEX_RE.fullmatch(hexcode)
        if not name:
            raise ValueError("A role name cannot be empty.")
        if not match:
            raise ValueError(f"Invalid hex code for **{name}**. Use a 6-digit code such as `#5865F2`.")
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        roles.append((name[:100], int(match.group(1), 16)))
    if not roles:
        raise ValueError("No roles found. Add lines like `Admin - #5865F2`.")
    return roles


async def _apply_roles(guild: discord.Guild, layout: str):
    specs = _parse_layout(layout)
    me = guild.me
    if me is None:
        raise RuntimeError("I could not determine my member record in this server.")
    if not me.guild_permissions.manage_roles:
        raise PermissionError("I need **Manage Roles** to create roles.")
    bot_top = me.top_role
    created = 0
    existing = 0
    skipped = []

    for name, colour_value in specs:
        role = discord.utils.find(lambda r: r.name.casefold() == name.casefold(), guild.roles)
        if role:
            existing += 1
            if role >= bot_top and role != guild.default_role:
                skipped.append(f"{role.name} (higher than my role)")
            continue
        if bot_top <= guild.default_role:
            raise PermissionError("My bot role must be above @everyone and have **Manage Roles**.")
        role = await guild.create_role(
            name=name,
            colour=discord.Colour(colour_value),
            reason="Air Commander auto role setup",
        )
        created += 1

    return created, existing, skipped


def setup_autorolesetup(bot: commands.Bot):
    @bot.tree.command(name="autorolesetup", description="Create roles from Role Name - #RRGGBB lines")
    @app_commands.describe(layout="Example: Admin - #5865F2\nOwner - #FF0000")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def autorolesetup(interaction: discord.Interaction, layout: str):
        if not interaction.guild:
            return await interaction.response.send_message(
                embed=_embed("Server Only", "This command can only be used inside a server.", discord.Color.red()),
                ephemeral=True,
            )
        await interaction.response.defer(ephemeral=True)
        try:
            created, existing, skipped = await _apply_roles(interaction.guild, layout)
        except ValueError as exc:
            return await interaction.followup.send(embed=_embed("Invalid Layout", str(exc), discord.Color.red()), ephemeral=True)
        except PermissionError as exc:
            return await interaction.followup.send(embed=_embed("Missing Permission", str(exc), discord.Color.red()), ephemeral=True)
        except discord.Forbidden:
            return await interaction.followup.send(
                embed=_embed("Discord Permission Error", "Discord denied role creation. Give Air Commander **Manage Roles** and move its bot role above the roles it needs to manage.", discord.Color.red()),
                ephemeral=True,
            )
        except Exception as exc:
            print(f"[AutoRoleSetup] Error in {interaction.guild.id}: {type(exc).__name__}: {exc}")
            return await interaction.followup.send(embed=_embed("Setup Failed", "The roles could not be created. Check the bot permissions and Render logs.", discord.Color.red()), ephemeral=True)

        text = f"🎨 Roles created: **{created}**\n↪️ Roles already present: **{existing}**"
        if skipped:
            text += "\n\n⚠️ Not manageable because they are at/above my role:\n" + "\n".join(f"• {x}" for x in skipped)
        await interaction.followup.send(embed=_embed("Auto Role Setup Complete", text, discord.Color.green()), ephemeral=True)

    @bot.command(name="autorolesetup")
    @commands.has_guild_permissions(manage_roles=True)
    async def prefix_autorolesetup(ctx: commands.Context, *, layout: str):
        if not ctx.guild:
            return await ctx.send(embed=_embed("Server Only", "This command can only be used inside a server.", discord.Color.red()))
        try:
            created, existing, skipped = await _apply_roles(ctx.guild, layout)
        except ValueError as exc:
            return await ctx.send(embed=_embed("Invalid Layout", str(exc), discord.Color.red()))
        except PermissionError as exc:
            return await ctx.send(embed=_embed("Missing Permission", str(exc), discord.Color.red()))
        except discord.Forbidden:
            return await ctx.send(embed=_embed("Discord Permission Error", "Give Air Commander **Manage Roles** and move its bot role above the roles it needs to manage.", discord.Color.red()))
        except Exception as exc:
            print(f"[AutoRoleSetup] Prefix error in {ctx.guild.id}: {type(exc).__name__}: {exc}")
            return await ctx.send(embed=_embed("Setup Failed", "The roles could not be created.", discord.Color.red()))
        text = f"🎨 Roles created: **{created}**\n↪️ Roles already present: **{existing}**"
        if skipped:
            text += "\n\n⚠️ Not manageable because they are at/above my role:\n" + "\n".join(f"• {x}" for x in skipped)
        await ctx.send(embed=_embed("Auto Role Setup Complete", text, discord.Color.green()))



# =========================================================
# =========================================================

def _embed(title, description, color):
    e = discord.Embed(
        title=f"✈️ {title}",
        description=description,
        color=color,
        timestamp=discord.utils.utcnow(),
    )
    e.set_footer(text="Air Commander • Auto Channel Setup")
    return e


def _parse_layout(layout: str):
    """Parse a simple layout:

    Category Name - category
    text-channel
    voice-channel -vc

    A category header becomes the active category. Normal lines create text
    channels inside that category; lines ending in -vc create voice channels.
    """
    categories = []
    current = None

    for raw in layout.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        match = re.match(r"^(.+?)\s*-\s*category\s*$", line, re.I)
        if match:
            name = match.group(1).strip()
            if name:
                current = {"name": name[:100], "channels": []}
                categories.append(current)
            continue

        voice = bool(re.search(r"\s*-\s*vc\s*$", line, re.I))
        if voice:
            name = re.sub(r"\s*-\s*vc\s*$", "", line, flags=re.I).strip()
        else:
            name = line
        if not name:
            continue

        # A channel before the first category is invalid instead of silently
        # creating it outside the requested layout.
        if current is None:
            raise ValueError(
                f"Channel **{name}** appears before a category. Add a `- category` line first."
            )

        current["channels"].append({"name": name[:100], "voice": voice})

    if not categories:
        raise ValueError("No categories found. Use lines ending with `- category`.")
    return categories


def _find_category(guild: discord.Guild, name: str):
    wanted = name.casefold()
    return discord.utils.find(
        lambda c: c.name.casefold() == wanted,
        guild.categories,
    )


def _find_channel(category: discord.CategoryChannel, name: str, voice: bool):
    wanted = name.casefold()
    for channel in category.channels:
        if channel.name.casefold() == wanted:
            if voice and isinstance(channel, discord.VoiceChannel):
                return channel
            if not voice and isinstance(channel, discord.TextChannel):
                return channel
    return None


async def _apply_layout(guild: discord.Guild, layout: str):
    parsed = _parse_layout(layout)
    created_categories = 0
    existing_categories = 0
    created_channels = 0
    existing_channels = 0

    for spec in parsed:
        category = _find_category(guild, spec["name"])
        if category is None:
            category = await guild.create_category(
                spec["name"],
                reason="Air Commander auto channel setup",
            )
            created_categories += 1
        else:
            existing_categories += 1

        for channel_spec in spec["channels"]:
            name = channel_spec["name"]
            voice = channel_spec["voice"]
            if _find_channel(category, name, voice):
                existing_channels += 1
                continue

            if voice:
                await guild.create_voice_channel(
                    name,
                    category=category,
                    reason="Air Commander auto channel setup",
                )
            else:
                await guild.create_text_channel(
                    name,
                    category=category,
                    reason="Air Commander auto channel setup",
                )
            created_channels += 1

    return created_categories, existing_categories, created_channels, existing_channels


def setup_autosetup(bot: commands.Bot):
    @bot.tree.command(
        name="autosetup",
        description="Create categories and channels from a simple layout",
    )
    @app_commands.describe(
        layout="Layout using `Name - category`, channel names, and `Name -vc` for voice",
    )
    @app_commands.checks.has_permissions(manage_channels=True)
    async def autosetup(interaction: discord.Interaction, layout: str):
        if interaction.guild is None:
            return await interaction.response.send_message(
                embed=_embed("Server Only", "This command can only be used inside a server.", discord.Color.red()),
                ephemeral=True,
            )

        if not interaction.guild.me.guild_permissions.manage_channels:
            return await interaction.response.send_message(
                embed=_embed(
                    "Missing Permission",
                    "I need **Manage Channels** to create the requested layout.",
                    discord.Color.red(),
                ),
                ephemeral=True,
            )

        if len(layout) > 4000:
            return await interaction.response.send_message(
                embed=_embed("Layout Too Long", "Keep the layout under **4000 characters**.", discord.Color.red()),
                ephemeral=True,
            )

        try:
            await interaction.response.defer(ephemeral=True)
            result = await _apply_layout(interaction.guild, layout)
        except ValueError as exc:
            if interaction.response.is_done():
                return await interaction.followup.send(
                    embed=_embed("Invalid Layout", str(exc), discord.Color.red()),
                    ephemeral=True,
                )
            return await interaction.response.send_message(
                embed=_embed("Invalid Layout", str(exc), discord.Color.red()),
                ephemeral=True,
            )
        except discord.Forbidden:
            return await interaction.followup.send(
                embed=_embed(
                    "Permission Error",
                    "Discord denied channel creation. Make sure my role has **Manage Channels** and is high enough to manage the server configuration.",
                    discord.Color.red(),
                ),
                ephemeral=True,
            )
        except Exception as exc:
            print(f"[AutoSetup] Error in {interaction.guild.id}: {type(exc).__name__}: {exc}")
            return await interaction.followup.send(
                embed=_embed(
                    "Auto Setup Failed",
                    "The layout could not be completed. Check the bot permissions and Render logs.",
                    discord.Color.red(),
                ),
                ephemeral=True,
            )

        cc, ec, ch, eh = result
        description = (
            "The requested server layout has been processed.\n\n"
            f"📁 Categories created: **{cc}**\n"
            f"📁 Categories already present: **{ec}**\n"
            f"💬 Channels created: **{ch}**\n"
            f"↪️ Channels already present: **{eh}**"
        )
        await interaction.followup.send(
            embed=_embed("Auto Setup Complete", description, discord.Color.green()),
            ephemeral=True,
        )

    @bot.command(name="autosetup")
    @commands.has_guild_permissions(manage_channels=True)
    async def prefix_autosetup(ctx: commands.Context, *, layout: str):
        if ctx.guild is None:
            return await ctx.send(
                embed=_embed("Server Only", "This command can only be used inside a server.", discord.Color.red())
            )
        if not ctx.guild.me.guild_permissions.manage_channels:
            return await ctx.send(
                embed=_embed("Missing Permission", "I need **Manage Channels** to create channels.", discord.Color.red())
            )
        try:
            result = await _apply_layout(ctx.guild, layout)
        except ValueError as exc:
            return await ctx.send(embed=_embed("Invalid Layout", str(exc), discord.Color.red()))
        except discord.Forbidden:
            return await ctx.send(
                embed=_embed(
                    "Permission Error",
                    "Discord denied channel creation. Give Air Commander **Manage Channels**.",
                    discord.Color.red(),
                )
            )
        except Exception as exc:
            print(f"[AutoSetup] Prefix error in {ctx.guild.id}: {type(exc).__name__}: {exc}")
            return await ctx.send(
                embed=_embed("Auto Setup Failed", "The layout could not be completed.", discord.Color.red())
            )

        cc, ec, ch, eh = result
        await ctx.send(
            embed=_embed(
                "Auto Setup Complete",
                f"📁 Categories created: **{cc}**\n"
                f"📁 Categories already present: **{ec}**\n"
                f"💬 Channels created: **{ch}**\n"
                f"↪️ Channels already present: **{eh}**",
                discord.Color.green(),
            )
        )



# =========================================================
# =========================================================

def clean_embed(title, description="", color=None):
    e = discord.Embed(title=f"✈️ {title}", description=description, color=color or discord.Color.blurple(), timestamp=discord.utils.utcnow())
    e.set_footer(text="Air Commander • Moderation Control")
    return e


def setup_moderation_extra(bot: commands.Bot):
    if not hasattr(bot, "_air_prefixes"):
        bot._air_prefixes = {}

    async def load_prefixes():
        try:
            bot._air_prefixes.update(await db.all_prefixes())
        except Exception as exc:
            print(f"Prefix load error: {exc}")

    async def dynamic_prefix(_bot, message):
        return bot._air_prefixes.get(message.guild.id, ",") if message.guild else ","

    bot.command_prefix = dynamic_prefix
    bot._air_load_prefixes = load_prefixes

    prefix_group = app_commands.Group(name="prefix", description="Configure the server's text command prefix")
    @prefix_group.command(name="set", description="Set the server prefix")
    @app_commands.describe(prefix="New prefix, 1-5 characters")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def prefix_set(i: discord.Interaction, prefix: str):
        if not i.guild: return await i.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
        prefix = prefix.strip()
        if not 1 <= len(prefix) <= 5 or prefix.isspace() or "@everyone" in prefix or "@here" in prefix: return await i.response.send_message("❌ That prefix cannot be used.", ephemeral=True)
        await db.set_prefix(i.guild.id, prefix); bot._air_prefixes[i.guild.id] = prefix
        e = clean_embed("Prefix Updated", f"Text commands in **{i.guild.name}** now use **`{prefix}`**.", discord.Color.green()); e.add_field(name="New Prefix", value=f"`{prefix}`", inline=True); e.add_field(name="Example", value=f"`{prefix}help`", inline=True); e.add_field(name="Changed By", value=i.user.mention, inline=True); await i.response.send_message(embed=e)

    @prefix_group.command(name="view", description="Show the current server prefix")
    async def prefix_view(i: discord.Interaction):
        if not i.guild: return await i.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
        prefix = bot._air_prefixes.get(i.guild.id, ","); e = clean_embed("Server Prefix", f"The current text command prefix is **`{prefix}`**."); e.add_field(name="Example", value=f"`{prefix}help`", inline=False); await i.response.send_message(embed=e)

    #bot.tree.add_command(prefix_group)
    #setup_cmdmaker(bot)
    #.setup_autorolesetup(bot)




# =========================================================
# =========================================================

OWNER_ID = 1504354088538869892
DB_URL = os.getenv("DATABASE_URL")
_pool = None

LINK_RE = re.compile(r"(?:https?://|www\.)\S+", re.I)
SPAM = defaultdict(lambda: deque(maxlen=20))
CONFIG_CACHE = {}


def clean_color(value: str) -> discord.Colour:
    value = value.strip().lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", value):
        raise ValueError("Use a 6-digit hex color such as #5865F2.")
    return discord.Colour(int(value, 16))


async def init_security_db():
    global _pool
    if _pool or not DB_URL:
        return
    try:
        _pool = await asyncpg.create_pool(DB_URL, min_size=1, max_size=4, command_timeout=15)
        async with _pool.acquire() as c:
            await c.execute("""
                CREATE TABLE IF NOT EXISTS security_config(
                    guild_id BIGINT PRIMARY KEY,
                    automod_enabled BOOLEAN DEFAULT FALSE,
                    automod_spam_limit INT DEFAULT 5,
                    automod_spam_seconds INT DEFAULT 3,
                    automod_action TEXT DEFAULT 'warn',
                    automod_mention_limit INT DEFAULT 5,
                    automod_emoji_limit INT DEFAULT 10,
                    automod_lines_limit INT DEFAULT 12,
                    automod_chars_limit INT DEFAULT 2000,
                    antilink_enabled BOOLEAN DEFAULT FALSE,
                    antilink_action TEXT DEFAULT 'delete',
                    antinuke_enabled BOOLEAN DEFAULT FALSE,
                    antinuke_action TEXT DEFAULT 'ban'
                );
                CREATE TABLE IF NOT EXISTS security_whitelist(
                    guild_id BIGINT,
                    user_id BIGINT,
                    kind TEXT DEFAULT 'user',
                    PRIMARY KEY(guild_id,user_id)
                );
                CREATE TABLE IF NOT EXISTS security_warnings(
                    id BIGSERIAL PRIMARY KEY,
                    guild_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    moderator_id BIGINT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)
        print("🛡️ Security database ready")
    except Exception as e:
        _pool = None
        print(f"⚠️ Security database unavailable: {type(e).__name__}: {e}")


async def cfg(guild_id):
    if guild_id in CONFIG_CACHE:
        return CONFIG_CACHE[guild_id]
    defaults = {
        "automod_enabled": False, "automod_spam_limit": 5, "automod_spam_seconds": 3,
        "automod_action": "warn", "automod_mention_limit": 5, "automod_emoji_limit": 10,
        "automod_lines_limit": 12, "automod_chars_limit": 2000,
        "antilink_enabled": False, "antilink_action": "delete",
        "antinuke_enabled": False, "antinuke_action": "ban"
    }
    if not _pool:
        return defaults.copy()
    row = await _pool.fetchrow("SELECT * FROM security_config WHERE guild_id=$1", guild_id)
    if not row:
        await _pool.execute("INSERT INTO security_config(guild_id) VALUES($1) ON CONFLICT DO NOTHING", guild_id)
        CONFIG_CACHE[guild_id] = defaults.copy()
        return CONFIG_CACHE[guild_id]
    data = dict(row)
    CONFIG_CACHE[guild_id] = data
    return data


async def set_cfg(guild_id, **values):
    data = await cfg(guild_id)
    data.update(values)
    CONFIG_CACHE[guild_id] = data
    if _pool:
        cols = [k for k in values if k in data and k != "guild_id"]
        if cols:
            sets = ",".join(f"{k}=${i+2}" for i,k in enumerate(cols))
            await _pool.execute(
                f"INSERT INTO security_config(guild_id,{','.join(cols)}) VALUES($1,{','.join(f'${i+2}' for i in range(len(cols)))}) ON CONFLICT(guild_id) DO UPDATE SET {sets}",
                guild_id, *[values[k] for k in cols]
            )


async def is_whitelisted(guild_id, user_id):
    if user_id == OWNER_ID:
        return True
    if not _pool:
        return False
    return bool(await _pool.fetchval("SELECT 1 FROM security_whitelist WHERE guild_id=$1 AND user_id=$2", guild_id, user_id))


async def whitelist_user(guild_id, user_id):
    if _pool:
        await _pool.execute("INSERT INTO security_whitelist(guild_id,user_id) VALUES($1,$2) ON CONFLICT DO NOTHING", guild_id, user_id)


async def unwhitelist_user(guild_id, user_id):
    if _pool:
        await _pool.execute("DELETE FROM security_whitelist WHERE guild_id=$1 AND user_id=$2", guild_id, user_id)


async def add_warning(guild_id, user_id, moderator_id, reason):
    if not _pool:
        return 0
    return await _pool.fetchval(
        "INSERT INTO security_warnings(guild_id,user_id,moderator_id,reason) VALUES($1,$2,$3,$4) RETURNING id",
        guild_id, user_id, moderator_id, reason
    )


async def remove_warning(guild_id, case_id):
    if not _pool:
        return False
    return bool(await _pool.execute("DELETE FROM security_warnings WHERE guild_id=$1 AND id=$2", guild_id, case_id) == "DELETE 1")


async def warning_count(guild_id, user_id):
    if not _pool:
        return 0
    return int(await _pool.fetchval("SELECT COUNT(*) FROM security_warnings WHERE guild_id=$1 AND user_id=$2", guild_id, user_id))


async def punish(member: discord.Member, action: str, reason: str, duration: int = 10):
    try:
        if action == "warn":
            await add_warning(member.guild.id, member.id, member.guild.me.id, reason)
        elif action == "mute":
            await member.timeout(timedelta(minutes=duration), reason=reason)
        elif action == "kick":
            await member.kick(reason=reason)
        elif action == "ban":
            await member.ban(reason=reason, delete_message_seconds=0)
    except (discord.Forbidden, discord.HTTPException) as e:
        print(f"⚠️ Security punishment failed for {member.id}: {e}")


def admin_check(interaction: discord.Interaction) -> bool:
    return bool(interaction.guild and (interaction.user.id == OWNER_ID or interaction.user.guild_permissions.manage_guild))


def embed(title, description, success=True):
    e = discord.Embed(title=("✅ " if success else "⚠️ ") + title, description=description, colour=discord.Colour.blurple() if success else discord.Colour.orange())
    e.set_footer(text="Air Commander • Security")
    return e


class Security(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._audit_seen = set()

    async def security_action(self, guild: discord.Guild, actor_id: int, reason: str):
        if actor_id == guild.me.id or await is_whitelisted(guild.id, actor_id):
            return False
        member = guild.get_member(actor_id)
        if not member:
            try:
                member = await guild.fetch_member(actor_id)
            except discord.HTTPException:
                return False
        if not member or not member.bannable:
            owner = guild.owner
            if owner:
                try: await owner.send(f"🚨 Anti-nuke detected `{actor_id}` in **{guild.name}**, but I could not ban them. Move my role above their role and ensure I have Ban Members.")
                except discord.HTTPException: pass
            return False
        await member.ban(reason=f"Anti-nuke: {reason}", delete_message_seconds=0)
        try:
            await guild.owner.send(f"🚨 Anti-nuke triggered in **{guild.name}**. Banned <@{actor_id}> for: {reason}")
        except discord.HTTPException: pass
        return True

    async def audit_trigger(self, guild, action, reason):
        if not (await cfg(guild.id)).get("antinuke_enabled"):
            return
        await asyncio.sleep(0.8)
        try:
            async for entry in guild.audit_logs(limit=8, action=action):
                if entry.id in self._audit_seen:
                    continue
                self._audit_seen.add(entry.id)
                await self.security_action(guild, entry.user.id, reason)
                return
        except (discord.Forbidden, discord.HTTPException):
            pass

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        await self.audit_trigger(channel.guild, discord.AuditLogAction.channel_create, "created a channel")

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        await self.audit_trigger(channel.guild, discord.AuditLogAction.channel_delete, "deleted a channel")

    @commands.Cog.listener()
    async def on_guild_role_create(self, role):
        await self.audit_trigger(role.guild, discord.AuditLogAction.role_create, "created a role")

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        await self.audit_trigger(role.guild, discord.AuditLogAction.role_delete, "deleted a role")

    @commands.Cog.listener()
    async def on_guild_role_update(self, before, after):
        await self.audit_trigger(after.guild, discord.AuditLogAction.role_update, "changed a role")

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        await self.audit_trigger(guild, discord.AuditLogAction.ban, "banned a member")

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        if member.bot:
            await self.audit_trigger(member.guild, discord.AuditLogAction.bot_add, "removed a bot/member")

    @commands.Cog.listener()
    async def on_member_join(self, member):
        if member.bot and (await cfg(member.guild.id)).get("antinuke_enabled"):
            await asyncio.sleep(1)
            try:
                async for entry in member.guild.audit_logs(limit=5, action=discord.AuditLogAction.bot_add):
                    if entry.target and entry.target.id == member.id:
                        await self.security_action(member.guild, entry.user.id, "added an unauthorized bot")
                        return
            except (discord.Forbidden, discord.HTTPException):
                pass

    @commands.Cog.listener()
    async def on_message(self, message):
        if not message.guild or message.author.bot:
            return
        c = await cfg(message.guild.id)
        if c.get("antilink_enabled") and LINK_RE.search(message.content) and not await is_whitelisted(message.guild.id, message.author.id):
            try: await message.delete()
            except discord.HTTPException: pass
            if c.get("antilink_action") in {"warn", "mute", "kick", "ban"} and isinstance(message.author, discord.Member):
                await punish(message.author, c["antilink_action"], "Anti-link: unauthorized link")
            return
        if not c.get("automod_enabled") or await is_whitelisted(message.guild.id, message.author.id):
            return
        now = message.created_at.timestamp()
        key = (message.guild.id, message.author.id)
        q = SPAM[key]
        q.append(now)
        while q and now - q[0] > c.get("automod_spam_seconds", 3): q.popleft()
        reasons = []
        if len(q) >= c.get("automod_spam_limit", 5): reasons.append("spam")
        if len(message.mentions) >= c.get("automod_mention_limit", 5): reasons.append("mention spam")
        emoji_count = len(re.findall(r"<a?:\w+:\d+>|[\U0001F300-\U0001FAFF]", message.content))
        if emoji_count >= c.get("automod_emoji_limit", 10): reasons.append("emoji spam")
        if message.mention_everyone: reasons.append("@everyone/@here spam")
        if len(message.content.splitlines()) > c.get("automod_lines_limit", 12) or len(message.content) > c.get("automod_chars_limit", 2000): reasons.append("line/character spam")
        if reasons:
            try: await message.delete()
            except discord.HTTPException: pass
            if isinstance(message.author, discord.Member):
                await punish(message.author, c.get("automod_action", "warn"), "Automod: " + ", ".join(reasons))


async def setup_security(bot):
    await bot.add_cog(Security(bot))
    #bot.tree.add_command(WarningGroup())
    #bot.tree.add_command(AutoModGroup())
    #bot.tree.add_command(AntiNukeGroup())
    #bot.tree.add_command(AntiLinkGroup())


class WarningGroup(app_commands.Group):
    def __init__(self): super().__init__(name="warning", description="Manage member warnings")

    @app_commands.command(name="warn", description="Warn a member")
    @app_commands.check(admin_check)
    async def warn(self, interaction, member: discord.Member, reason: str = "No reason provided"):
        case = await add_warning(interaction.guild.id, member.id, interaction.user.id, reason)
        count = await warning_count(interaction.guild.id, member.id)
        await interaction.response.send_message(embed=embed("Warning issued", f"**Member:** {member.mention}\n**Case:** `AC-W{case:04d}`\n**Warnings:** `{count}`\n**Reason:** {reason}"))

    @app_commands.command(name="unwarn", description="Remove a warning by case ID")
    @app_commands.check(admin_check)
    async def unwarn(self, interaction, case: str):
        try: case_id = int(case.upper().replace("AC-W", ""))
        except ValueError:
            await interaction.response.send_message(embed=embed("Invalid case", "Use a case such as `AC-W0001`.", False), ephemeral=True); return
        ok = await remove_warning(interaction.guild.id, case_id)
        await interaction.response.send_message(embed=embed("Warning removed" if ok else "Warning not found", f"Case `AC-W{case_id:04d}` was {'removed' if ok else 'not found'}. ", ok))

    @app_commands.command(name="warnings", description="Show a member's warnings")
    @app_commands.check(admin_check)
    async def warnings(self, interaction, member: discord.Member):
        if not _pool:
            await interaction.response.send_message(embed=embed("Warnings", "Database is unavailable.", False), ephemeral=True); return
        rows = await _pool.fetch("SELECT id,moderator_id,reason,created_at FROM security_warnings WHERE guild_id=$1 AND user_id=$2 ORDER BY id DESC LIMIT 10", interaction.guild.id, member.id)
        desc = "\n".join(f"`AC-W{r['id']:04d}` • <@{r['moderator_id']}> • {r['reason']}" for r in rows) or "No warnings."
        await interaction.response.send_message(embed=embed(f"Warnings • {member}", desc))


class AutoModGroup(app_commands.Group):
    def __init__(self): super().__init__(name="automod", description="Configure message protection")

    @app_commands.command(name="enable", description="Enable automod")
    @app_commands.check(admin_check)
    @app_commands.describe(action="warn, mute, kick or ban")
    async def enable(self, interaction, action: str = "warn", spam_limit: int = 5, seconds: int = 3):
        action = action.lower()
        if action not in {"warn","mute","kick","ban"}:
            await interaction.response.send_message("Action must be warn, mute, kick or ban.", ephemeral=True); return
        await set_cfg(interaction.guild.id, automod_enabled=True, automod_action=action, automod_spam_limit=max(2,spam_limit), automod_spam_seconds=max(1,seconds))
        await interaction.response.send_message(embed=embed("Automod enabled", f"Spam: **{spam_limit} messages / {seconds}s**\nPunishment: **{action}**\nMention/emoji/@everyone/line checks are active."))

    @app_commands.command(name="disable", description="Disable automod")
    @app_commands.check(admin_check)
    async def disable(self, interaction):
        await set_cfg(interaction.guild.id, automod_enabled=False)
        await interaction.response.send_message(embed=embed("Automod disabled", "Message automod is now off."))



# =========================================================
# =========================================================
# security is embedded above


class AntiNukeRollback(commands.Cog):
    """Reverts identifiable destructive changes made by non-whitelisted users."""

    def __init__(self, bot):
        self.bot = bot
        self._handled = set()

    async def _actor(self, guild, action, target_id=None):
        try:
            async for entry in guild.audit_logs(limit=10, action=action):
                if entry.id in self._handled:
                    continue
                if target_id is not None and getattr(entry.target, "id", None) != target_id:
                    continue
                self._handled.add(entry.id)
                return entry
        except (discord.Forbidden, discord.HTTPException):
            return None
        return None

    async def _enabled_and_unauthorized(self, guild, entry):
        if not (await security.cfg(guild.id)).get("antinuke_enabled"):
            return False
        return not await security.is_whitelisted(guild.id, entry.user.id)

    @commands.Cog.listener()
    async def on_guild_role_create(self, role):
        await asyncio.sleep(0.8)
        entry = await self._actor(role.guild, discord.AuditLogAction.role_create, role.id)
        if not entry or not await self._enabled_and_unauthorized(role.guild, entry):
            return
        try:
            await role.delete(reason="Anti-nuke rollback: unauthorized role creation")
        except (discord.Forbidden, discord.HTTPException):
            pass

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        await asyncio.sleep(0.8)
        entry = await self._actor(channel.guild, discord.AuditLogAction.channel_create, channel.id)
        if not entry or not await self._enabled_and_unauthorized(channel.guild, entry):
            return
        try:
            await channel.delete(reason="Anti-nuke rollback: unauthorized channel creation")
        except (discord.Forbidden, discord.HTTPException):
            pass

    @commands.Cog.listener()
    async def on_guild_role_update(self, before, after):
        await asyncio.sleep(0.8)
        entry = await self._actor(after.guild, discord.AuditLogAction.role_update, after.id)
        if not entry or not await self._enabled_and_unauthorized(after.guild, entry):
            return
        try:
            # Restore the properties Discord exposes safely through Role.edit.
            kwargs = {
                "name": before.name,
                "permissions": before.permissions,
                "colour": before.colour,
                "hoist": before.hoist,
                "mentionable": before.mentionable,
            }
            await after.edit(reason="Anti-nuke rollback: unauthorized role change", **kwargs)
        except (discord.Forbidden, discord.HTTPException):
            pass

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        if before.roles == after.roles:
            return
        await asyncio.sleep(0.8)
        entry = await self._actor(after.guild, discord.AuditLogAction.member_role_update, after.id)
        if not entry or not await self._enabled_and_unauthorized(after.guild, entry):
            return

        before_ids = {r.id for r in before.roles}
        after_ids = {r.id for r in after.roles}
        added = after_ids - before_ids
        removed = before_ids - after_ids

        # Undo only the roles implicated by the unauthorized audit-log change.
        # Discord may report multiple role changes in one audit entry, so restoring
        # the complete previous role set is the most reliable rollback.
        try:
            await after.edit(roles=before.roles, reason="Anti-nuke rollback: unauthorized member role change")
        except (discord.Forbidden, discord.HTTPException):
            # Fallback: remove newly-added roles when full role restoration is not allowed.
            for role in after.roles:
                if role.id in added and role.is_assignable():
                    try:
                        await after.remove_roles(role, reason="Anti-nuke rollback: unauthorized role addition")
                    except (discord.Forbidden, discord.HTTPException):
                        pass

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        # If a non-whitelisted actor deletes a role, we cannot recreate it perfectly
        # from the audit event alone. The existing anti-nuke handler still bans the
        # actor; this cog intentionally avoids a lossy reconstruction.
        return


async def setup_antinuke_rollback(bot):
    await bot.add_cog(AntiNukeRollback(bot))


# Register all synchronous embedded command systems.
if not getattr(bot, "_air_moderation_extra_loaded", False):
    setup_moderation_extra(bot)
    bot._air_moderation_extra_loaded = True


# =========================================================
# AIR COMMANDER • SPECIAL INTELLIGENCE SYSTEM
# =========================================================

SPECIAL_SNAPSHOT_CACHE = defaultdict(list)
SPECIAL_LAST_ACTIVITY = {}
SPECIAL_QUEST_CACHE = {}
SPECIAL_SEASON_CACHE = defaultdict(lambda: {"season": 1, "xp": 0, "started": discord.utils.utcnow()})
SPECIAL_DB_READY = False

async def _special_db_init():
    global SPECIAL_DB_READY
    if SPECIAL_DB_READY:
        return
    pool = getattr(db, "_pool", None)
    if not pool:
        return
    try:
        await pool.execute("""
            CREATE TABLE IF NOT EXISTS air_member_activity(
                guild_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY(guild_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS air_server_snapshots(
                id BIGSERIAL PRIMARY KEY,
                guild_id BIGINT NOT NULL,
                captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                member_count INT NOT NULL DEFAULT 0,
                message_count BIGINT NOT NULL DEFAULT 0,
                channel_count INT NOT NULL DEFAULT 0,
                role_count INT NOT NULL DEFAULT 0,
                quest_xp BIGINT NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS air_server_seasons(
                guild_id BIGINT PRIMARY KEY,
                season INT NOT NULL DEFAULT 1,
                xp BIGINT NOT NULL DEFAULT 0,
                started_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)
        SPECIAL_DB_READY = True
    except Exception as exc:
        print(f"⚠️ Special intelligence DB setup error: {type(exc).__name__}: {exc}")

async def _special_activity_rows(guild_id):
    try:
        return await db.activity_counts(guild_id) or []
    except Exception:
        return []

async def _special_activity_total(guild_id):
    rows = await _special_activity_rows(guild_id)
    total = 0
    for row in rows:
        try:
            total += int(row["messages"])
        except Exception:
            try:
                total += int(row[1])
            except Exception:
                pass
    return total

async def _special_snapshot(guild):
    total_messages = await _special_activity_total(guild.id)
    data = {
        "captured_at": discord.utils.utcnow(),
        "member_count": guild.member_count or len(guild.members),
        "message_count": total_messages,
        "channel_count": len(guild.channels),
        "role_count": len(guild.roles),
    }
    SPECIAL_SNAPSHOT_CACHE[guild.id].append(data)
    SPECIAL_SNAPSHOT_CACHE[guild.id] = SPECIAL_SNAPSHOT_CACHE[guild.id][-30:]
    pool = getattr(db, "_pool", None)
    if pool:
        try:
            await pool.execute(
                """INSERT INTO air_server_snapshots
                   (guild_id,member_count,message_count,channel_count,role_count)
                   VALUES($1,$2,$3,$4,$5)""",
                guild.id, data["member_count"], data["message_count"],
                data["channel_count"], data["role_count"]
            )
        except Exception:
            pass
    return data

async def _special_first_snapshot(guild_id):
    pool = getattr(db, "_pool", None)
    if pool:
        try:
            return await pool.fetchrow(
                """SELECT captured_at,member_count,message_count,channel_count,role_count
                   FROM air_server_snapshots WHERE guild_id=$1
                   ORDER BY captured_at ASC LIMIT 1""", guild_id)
        except Exception:
            pass
    history = SPECIAL_SNAPSHOT_CACHE.get(guild_id, [])
    return history[0] if history else None

def _special_delta(old, new):
    if old in (None, 0):
        return "—"
    diff = new - old
    pct = (diff / old) * 100
    sign = "+" if diff >= 0 else ""
    return f"{sign}{diff:,} ({sign}{pct:.1f}%)"

def _special_bar(value, maximum=100, width=12):
    if maximum <= 0:
        return "░" * width
    filled = max(0, min(width, round((value / maximum) * width)))
    return "█" * filled + "░" * (width - filled)

async def _special_get_season(guild_id):
    pool = getattr(db, "_pool", None)
    if pool:
        try:
            row = await pool.fetchrow(
                "SELECT season,xp,started_at FROM air_server_seasons WHERE guild_id=$1", guild_id)
            if row:
                return dict(row)
            await pool.execute(
                "INSERT INTO air_server_seasons(guild_id) VALUES($1) ON CONFLICT DO NOTHING", guild_id)
            row = await pool.fetchrow(
                "SELECT season,xp,started_at FROM air_server_seasons WHERE guild_id=$1", guild_id)
            return dict(row)
        except Exception:
            pass
    return SPECIAL_SEASON_CACHE[guild_id]

async def _special_add_xp(guild_id, amount):
    season = await _special_get_season(guild_id)
    new_xp = int(season.get("xp", 0)) + amount
    pool = getattr(db, "_pool", None)
    if pool:
        try:
            await pool.execute(
                "UPDATE air_server_seasons SET xp=$2 WHERE guild_id=$1", guild_id, new_xp)
        except Exception:
            pass
    SPECIAL_SEASON_CACHE[guild_id]["xp"] = new_xp
    return new_xp

def _special_level(xp):
    return max(1, (xp // 1000) + 1)

async def _special_update_activity(guild_id, user_id):
    now = discord.utils.utcnow()
    SPECIAL_LAST_ACTIVITY[(guild_id, user_id)] = now
    pool = getattr(db, "_pool", None)
    if pool:
        try:
            await pool.execute(
                """INSERT INTO air_member_activity(guild_id,user_id,last_seen)
                   VALUES($1,$2,$3)
                   ON CONFLICT(guild_id,user_id)
                   DO UPDATE SET last_seen=EXCLUDED.last_seen""",
                guild_id, user_id, now)
        except Exception:
            pass

async def _special_silent_members(guild, days):
    cutoff = discord.utils.utcnow() - timedelta(days=days)
    results = []
    pool = getattr(db, "_pool", None)
    if pool:
        try:
            rows = await pool.fetch(
                """SELECT user_id,last_seen FROM air_member_activity
                   WHERE guild_id=$1 AND last_seen < $2
                   ORDER BY last_seen ASC LIMIT 100""", guild.id, cutoff)
            for row in rows:
                member = guild.get_member(row["user_id"])
                if member and not member.bot:
                    results.append((member, row["last_seen"]))
            return results
        except Exception:
            pass
    for member in guild.members:
        if member.bot:
            continue
        seen = SPECIAL_LAST_ACTIVITY.get((guild.id, member.id))
        if seen and seen < cutoff:
            results.append((member, seen))
    return sorted(results, key=lambda x: x[1])

async def _serverpulse_data(guild):
    rows = await _special_activity_rows(guild.id)
    ranked = []
    for row in rows:
        channel = guild.get_channel(row["channel_id"])
        if channel:
            ranked.append((channel, int(row["messages"])))
    ranked.sort(key=lambda x: x[1], reverse=True)
    total = sum(x[1] for x in ranked)
    online = sum(1 for m in guild.members if m.status != discord.Status.offline)
    activity_pct = min(100, round((total / max(1, (guild.member_count or 1) * 5)) * 100))
    return ranked, total, online, activity_pct

async def _send_serverpulse(send, guild):
    ranked, total, online, activity_pct = await _serverpulse_data(guild)
    hot = ranked[0] if ranked else None
    quiet = ranked[-1] if ranked else None
    e = discord.Embed(title="📡 Air Commander • Server Pulse",
        description=f"Live activity snapshot for **{guild.name}**.",
        color=discord.Color.teal(), timestamp=discord.utils.utcnow())
    e.add_field(name="👥 Members", value=f"**{guild.member_count:,}**", inline=True)
    e.add_field(name="🟢 Online", value=f"**{online:,}**", inline=True)
    e.add_field(name="💬 Recorded Messages", value=f"**{total:,}**", inline=True)
    e.add_field(name="🔥 Hottest Channel",
        value=f"{hot[0].mention} • **{hot[1]:,}** messages" if hot else "No activity recorded yet.", inline=True)
    e.add_field(name="💤 Quietest Recorded Channel",
        value=f"{quiet[0].mention} • **{quiet[1]:,}** messages" if quiet else "No activity recorded yet.", inline=True)
    e.add_field(name="📈 Activity Pulse",
        value=f"`{_special_bar(activity_pct)}` **{activity_pct}%**", inline=False)
    e.add_field(name="🧭 Status",
        value="🔥 HIGH ACTIVITY" if activity_pct >= 70 else ("🟡 ACTIVE" if activity_pct >= 30 else "🌙 QUIET"),
        inline=False)
    e.set_footer(text="✈️ Air Commander • Server Intelligence")
    await send(embed=e)

@bot.tree.command(name="serverpulse", description="Show a live health and activity pulse for the server")
async def slash_serverpulse(interaction: discord.Interaction):
    if not interaction.guild:
        return await interaction.response.send_message("❌ Server only.", ephemeral=True)
    await _special_db_init()
    await _special_snapshot(interaction.guild)
    await _send_serverpulse(interaction.response.send_message, interaction.guild)

@bot.command(name="serverpulse")
async def prefix_serverpulse(ctx):
    if not ctx.guild:
        return await ctx.send("❌ Server only.")
    await _special_db_init()
    await _special_snapshot(ctx.guild)
    await _send_serverpulse(ctx.send, ctx.guild)

async def _serverstory_text(guild):
    current = await _special_snapshot(guild)
    first = await _special_first_snapshot(guild.id)
    rows = await _special_activity_rows(guild.id)
    ranked = []
    for row in rows:
        ch = guild.get_channel(row["channel_id"])
        if ch:
            ranked.append((ch, int(row["messages"])))
    ranked.sort(key=lambda x: x[1], reverse=True)
    top = ranked[0] if ranked else None
    old_members = int(first["member_count"]) if first else current["member_count"]
    old_messages = int(first["message_count"]) if first else current["message_count"]
    member_change = current["member_count"] - old_members
    message_change = current["message_count"] - old_messages
    lines = []
    if member_change > 0:
        lines.append(f"👥 The community gained **{member_change:,}** member(s) since the earliest saved snapshot.")
    elif member_change < 0:
        lines.append(f"👥 The member count changed by **{member_change:,}** since the earliest saved snapshot.")
    else:
        lines.append("👥 The member count is currently stable against the earliest saved snapshot.")
    lines.append(f"💬 Recorded activity changed by **{message_change:+,}** messages.")
    if top:
        lines.append(f"🔥 **{top[0].name}** is currently the activity hotspot with **{top[1]:,}** recorded messages.")
    hour = discord.utils.utcnow().hour
    lines.append("🌆 The current snapshot was captured during the evening activity window." if 17 <= hour <= 22
                 else ("🌙 The current snapshot was captured during the late-night window." if 0 <= hour < 6
                       else "☀️ The current snapshot was captured during the daytime window."))
    return "\n".join(lines), current

async def _send_serverstory(send, guild):
    story, current = await _serverstory_text(guild)
    e = discord.Embed(title="📖 Air Commander • Server Story",
        description=f"**{guild.name} Chronicle**\n\n{story}",
        color=discord.Color.blurple(), timestamp=discord.utils.utcnow())
    e.add_field(name="📊 Current Snapshot",
        value=f"Members: **{current['member_count']:,}**\nRecorded messages: **{current['message_count']:,}**\nChannels: **{current['channel_count']:,}**",
        inline=False)
    e.set_footer(text="✈️ Air Commander • Community Chronicle")
    await send(embed=e)

@bot.tree.command(name="serverstory", description="Generate a data-based story of your server")
async def slash_serverstory(interaction: discord.Interaction):
    if not interaction.guild:
        return await interaction.response.send_message("❌ Server only.", ephemeral=True)
    await _special_db_init()
    await _send_serverstory(interaction.response.send_message, interaction.guild)

@bot.command(name="serverstory")
async def prefix_serverstory(ctx):
    if not ctx.guild:
        return await ctx.send("❌ Server only.")
    await _special_db_init()
    await _send_serverstory(ctx.send, ctx.guild)

async def _get_quest(guild_id):
    if guild_id not in SPECIAL_QUEST_CACHE:
        SPECIAL_QUEST_CACHE[guild_id] = {
            "title": "THE CHAT STORM", "description": "Collectively send 500 recorded messages.",
            "target": 500, "reward": 500, "started": discord.utils.utcnow(),
            "start_messages": await _special_activity_total(guild_id), "rewarded": False
        }
    return SPECIAL_QUEST_CACHE[guild_id]

async def _send_serverquest(send, guild):
    quest = await _get_quest(guild.id)
    total = await _special_activity_total(guild.id)
    progress = max(0, total - quest["start_messages"])
    done = min(progress, quest["target"])
    pct = round(done / quest["target"] * 100)
    if done >= quest["target"] and not quest["rewarded"]:
        await _special_add_xp(guild.id, quest["reward"])
        quest["rewarded"] = True
    e = discord.Embed(title="⚔️ Air Commander • Server Quest",
        description=f"**{quest['title']}**\n{quest['description']}",
        color=discord.Color.orange() if done < quest["target"] else discord.Color.green(),
        timestamp=discord.utils.utcnow())
    e.add_field(name="🎯 Progress", value=f"`{_special_bar(pct)}` **{done:,} / {quest['target']:,}**", inline=False)
    e.add_field(name="🎁 Reward", value=f"**+{quest['reward']} Server XP**", inline=True)
    e.add_field(name="📌 Status", value="🏆 COMPLETED" if done >= quest["target"] else "⚔️ IN PROGRESS", inline=True)
    e.set_footer(text="✈️ Air Commander • Community Quest")
    await send(embed=e)

@bot.tree.command(name="serverquest", description="View the current community server quest")
async def slash_serverquest(interaction: discord.Interaction):
    if not interaction.guild:
        return await interaction.response.send_message("❌ Server only.", ephemeral=True)
    await _special_db_init()
    await _send_serverquest(interaction.response.send_message, interaction.guild)

@bot.command(name="serverquest")
async def prefix_serverquest(ctx):
    if not ctx.guild:
        return await ctx.send("❌ Server only.")
    await _special_db_init()
    await _send_serverquest(ctx.send, ctx.guild)

async def _send_silentwatch(send, guild, days):
    members = await _special_silent_members(guild, days)
    e = discord.Embed(title="🤫 Air Commander • Silent Watch",
        description=f"Members with no recorded activity for **{days}+ days**.",
        color=discord.Color.dark_grey(), timestamp=discord.utils.utcnow())
    if members:
        e.add_field(name="👻 Candidates",
            value="\n".join(f"• {member.mention} — last seen {discord.utils.format_dt(seen, 'R')}" for member, seen in members[:20])[:1024],
            inline=False)
    else:
        e.add_field(name="👻 Candidates",
            value="No matching inactive members were found in the saved activity data.", inline=False)
    e.add_field(name="📊 Summary",
        value=f"**{len(members)}** member(s) matched the **{days}+ day** threshold.", inline=False)
    e.set_footer(text="✈️ Air Commander • Activity analytics only")
    await send(embed=e)

@bot.tree.command(name="silentwatch", description="Find members with no recorded activity for a selected number of days")
@app_commands.describe(days="Inactivity threshold in days")
async def slash_silentwatch(interaction: discord.Interaction, days: app_commands.Range[int, 1, 365]):
    if not interaction.guild:
        return await interaction.response.send_message("❌ Server only.", ephemeral=True)
    await _special_db_init()
    await _send_silentwatch(interaction.response.send_message, interaction.guild, days)

@bot.command(name="silentwatch")
async def prefix_silentwatch(ctx, days: int = 30):
    if not ctx.guild:
        return await ctx.send("❌ Server only.")
    if not 1 <= days <= 365:
        return await ctx.send("❌ Days must be between **1 and 365**.")
    await _special_db_init()
    await _send_silentwatch(ctx.send, ctx.guild, days)

async def _send_serverseason(send, guild):
    await _special_db_init()
    season = await _special_get_season(guild.id)
    xp = int(season.get("xp", 0))
    level = _special_level(xp)
    progress = xp - ((level - 1) * 1000)
    remaining = max(0, level * 1000 - xp)
    e = discord.Embed(title=f"🏆 Air Commander • Season {season.get('season', 1)}",
        description=f"**{guild.name}** community progression",
        color=discord.Color.gold(), timestamp=discord.utils.utcnow())
    e.add_field(name="🏆 Server Level",
        value=f"**LEVEL {level}**\n`{_special_bar(progress, 1000)}` **{progress:,} / 1,000 XP**\n{remaining:,} XP to next level",
        inline=False)
    e.add_field(name="⚔️ Quest XP", value=f"**{xp:,}**", inline=True)
    e.add_field(name="📅 Started", value=discord.utils.format_dt(season["started_at"], "D"), inline=True)
    e.add_field(name="🎖️ Season", value=f"**#{season.get('season', 1)}**", inline=True)
    e.set_footer(text="✈️ Air Commander • Community Progression")
    await send(embed=e)

@bot.tree.command(name="serverseason", description="Show the server's current season and progression")
async def slash_serverseason(interaction: discord.Interaction):
    if not interaction.guild:
        return await interaction.response.send_message("❌ Server only.", ephemeral=True)
    await _send_serverseason(interaction.response.send_message, interaction.guild)

@bot.command(name="serverseason")
async def prefix_serverseason(ctx):
    if not ctx.guild:
        return await ctx.send("❌ Server only.")
    await _send_serverseason(ctx.send, ctx.guild)

async def _send_serverevolution(send, guild, days=30):
    await _special_db_init()
    current = await _special_snapshot(guild)
    pool = getattr(db, "_pool", None)
    old = None
    if pool:
        try:
            old = await pool.fetchrow(
                """SELECT captured_at,member_count,message_count,channel_count,role_count
                   FROM air_server_snapshots
                   WHERE guild_id=$1 AND captured_at <= NOW() - ($2 * INTERVAL '1 day')
                   ORDER BY captured_at DESC LIMIT 1""", guild.id, days)
        except Exception:
            old = None
    if old is None:
        old = await _special_first_snapshot(guild.id)
    if old:
        old_members, old_messages = int(old["member_count"]), int(old["message_count"])
        old_channels, old_roles = int(old["channel_count"]), int(old["role_count"])
        period_label = f"saved baseline / {days} day target"
    else:
        old_members, old_messages = current["member_count"], current["message_count"]
        old_channels, old_roles = current["channel_count"], current["role_count"]
        period_label = "first available snapshot"
    e = discord.Embed(title="🧬 Air Commander • Server Evolution",
        description=f"**{guild.name}** • {period_label}",
        color=discord.Color.purple(), timestamp=discord.utils.utcnow())
    e.add_field(name="👥 Member Growth", value=f"`{old_members:,}` → `{current['member_count']:,}`\n**{_special_delta(old_members, current['member_count'])}**", inline=True)
    e.add_field(name="💬 Activity", value=f"`{old_messages:,}` → `{current['message_count']:,}`\n**{_special_delta(old_messages, current['message_count'])}**", inline=True)
    e.add_field(name="📚 Channels", value=f"`{old_channels:,}` → `{current['channel_count']:,}`\n**{_special_delta(old_channels, current['channel_count'])}**", inline=True)
    e.add_field(name="🎭 Roles", value=f"`{old_roles:,}` → `{current['role_count']:,}`\n**{_special_delta(old_roles, current['role_count'])}**", inline=True)
    e.add_field(name="🧠 Evolution Summary",
        value="This compares the current server snapshot with saved historical data. Run it regularly to build a useful timeline.",
        inline=False)
    e.set_footer(text="✈️ Air Commander • Server Evolution")
    await send(embed=e)

@bot.tree.command(name="serverevolution", description="Compare the server with a saved historical snapshot")
@app_commands.describe(days="Preferred historical window in days")
async def slash_serverevolution(interaction: discord.Interaction, days: app_commands.Range[int, 1, 365]):
    if not interaction.guild:
        return await interaction.response.send_message("❌ Server only.", ephemeral=True)
    await _send_serverevolution(interaction.response.send_message, interaction.guild, days)

@bot.command(name="serverevolution")
async def prefix_serverevolution(ctx, days: int = 30):
    if not ctx.guild:
        return await ctx.send("❌ Server only.")
    if not 1 <= days <= 365:
        return await ctx.send("❌ Days must be between **1 and 365**.")
    await _send_serverevolution(ctx.send, ctx.guild, days)

@bot.listen("on_message")
async def _air_special_activity_listener(message):
    if message.author.bot or not message.guild:
        return
    try:
        await _special_update_activity(message.guild.id, message.author.id)
    except Exception:
        pass
@bot.event
async def on_ready():
    print(f"✈️ Logged in as {bot.user} (ID: {bot.user.id})")

    # =========================
    # DATABASE
    # =========================
    if not getattr(bot, "_air_db_initialized", False):
        try:
            await db.init_db()
            bot._air_db_initialized = True
            print("🗄️ Database initialized.")
        except Exception as exc:
            print(f"⚠️ Database error: {type(exc).__name__}: {exc}")
    else:
        print("ℹ️ Database already initialized.")

    # =========================
    # PREFIX SETTINGS
    # =========================
    if not getattr(bot, "_air_prefixes_loaded_once", False):
        try:
            if hasattr(bot, "_air_load_prefixes"):
                await bot._air_load_prefixes()
            print("🔤 Prefix settings loaded.")
        except Exception as exc:
            print(f"⚠️ Prefix settings error: {type(exc).__name__}: {exc}")

        bot._air_prefixes_loaded_once = True

    # =========================
    # SECURITY
    # =========================
    if not getattr(bot, "_air_security_initialized", False):
        try:
            await init_security_db()
            await setup_security(bot)
            await setup_antinuke_rollback(bot)

            bot._air_security_initialized = True
            print("🛡️ Security systems initialized.")
        except Exception as exc:
            print(f"⚠️ Security initialization error: {type(exc).__name__}: {exc}")

    # =========================
    # CUSTOM COMMANDS
    # =========================
    if not getattr(bot, "_air_custom_commands_loaded_once", False):
        try:
            if hasattr(bot, "_air_load_custom_commands"):
                await bot._air_load_custom_commands(bot)

            print("🧩 Custom commands loaded.")
        except Exception as exc:
            print(f"⚠️ Custom command loader error: {type(exc).__name__}: {exc}")

        bot._air_custom_commands_loaded_once = True

    # =====================================================
    # SPECIAL INTELLIGENCE DB
    # =====================================================
    if not getattr(bot, "_air_special_db_ready_once", False):
        try:
            await _special_db_init()
            bot._air_special_db_ready_once = True
            print("🧠 Special intelligence DB initialized.")
        except Exception as exc:
            print(
                f"⚠️ Special intelligence DB error: "
                f"{type(exc).__name__}: {exc}"
            )

    # =====================================================
    # FINAL SLASH SYNC
    # Some systems register commands during on_ready.
    # Sync once more after those systems are initialized.
    # =====================================================
    if not getattr(bot, "_air_final_sync_done", False):
        try:
            if GUILD_ID:
                guild_id = int(GUILD_ID)
                guild = discord.Object(id=guild_id)
                guild_synced = await bot.tree.sync(guild=guild)
                print(
                    f"⚡ Final guild slash sync: "
                    f"{len(guild_synced)} commands "
                    f"(Guild ID: {guild_id})"
                )

            global_synced = await bot.tree.sync()
            print(
                f"🌍 Final global slash sync: "
                f"{len(global_synced)} commands"
            )

            print("\n📋 FINAL REGISTERED SLASH COMMANDS:")
            for command in sorted(
                bot.tree.get_commands(),
                key=lambda command: command.name
            ):
                print(f"   └─ /{command.name}")

            print(
                f"✅ Final slash command count: "
                f"{len(bot.tree.get_commands())}"
            )
            bot._air_final_sync_done = True

        except Exception as exc:
            print(
                f"⚠️ Final slash sync failed: "
                f"{type(exc).__name__}: {exc}"
            )

async def _air_startup_loader(bot):
    """Main startup loader called only from AirCommanderBot.setup_hook."""

    print("\n" + "=" * 60)
    print("🚀 AIR COMMANDER STARTUP")
    print("=" * 60)

    # =================================================
    # 0. DATABASE
    # Initialize the main database before feature setup.
    # =================================================
    if not getattr(bot, "_air_db_initialized", False):
        try:
            await db.init_db()
            bot._air_db_initialized = True
            print("🗄️ Database initialized.")
        except Exception as exc:
            print(
                f"⚠️ Database initialization error: "
                f"{type(exc).__name__}: {exc}"
            )
    else:
        print("ℹ️ Database already initialized.")

    # =================================================
    # 1. LOAD ALL FEATURE MODULES
    # =================================================

    feature_modules = [
        ("autorolesetup", autorolesetup),
        ("automation", automation),
        ("cmdmaker", cmdmaker),
        ("command_permissions", command_permissions),
        ("embed_builder", embed_builder),
        ("giveaways", giveaways),
        ("leveling", leveling),
        ("snipe", snipe),
        ("welcome_autorole", welcome_autorole),
        ("youtube_alerts", youtube_alerts),
    ]

    # Track modules individually: one failed setup must not mark every module loaded.
    loaded_modules = getattr(bot, "_air_loaded_feature_modules", set())
    failed = 0
    loaded_now = 0

    print("🧩 Loading current feature modules...")

    for module_name, module in feature_modules:
        if module_name in loaded_modules:
            print(f"ℹ️ {module_name} already loaded; skipping duplicate setup.")
            continue

        try:
            setup = getattr(module, "setup", None)
            if not callable(setup):
                raise AttributeError(f"{module_name}.setup(bot) is missing")

            # The repository has both sync setup(bot) and async setup(bot)
            # functions, so call them directly instead of bot.load_extension().
            result = setup(bot)
            if asyncio.iscoroutine(result):
                await result

            loaded_modules.add(module_name)
            loaded_now += 1
            print(f"✅ {module_name} loaded.")

        except Exception as exc:
            failed += 1
            print(
                f"❌ {module_name} failed: "
                f"{type(exc).__name__}: {exc}"
            )

    bot._air_loaded_feature_modules = loaded_modules
    bot._air_feature_modules_loaded = (
        len(loaded_modules) == len(feature_modules)
    )

    print(
        f"🧩 Feature loading finished: "
        f"{len(loaded_modules)}/{len(feature_modules)} loaded, "
        f"{failed} failed this pass ({loaded_now} newly loaded)."
    )

    # =================================================
    # 2. MODERATION / EMBEDDED SYSTEMS
    # =================================================

    try:
        if not getattr(bot, "_air_moderation_extra_loaded", False):
            setup_moderation_extra(bot)
            bot._air_moderation_extra_loaded = True
            print("✅ Moderation systems loaded.")
        else:
            print("ℹ️ Moderation systems already loaded.")
    except Exception as exc:
        print(
            f"❌ Moderation systems failed: "
            f"{type(exc).__name__}: {exc}"
        )

    # =================================================
    # 3. SYNC ALL REGISTERED SLASH COMMANDS
    # =================================================

    print("\n" + "=" * 60)
    print("🔄 AIR COMMANDER — SLASH COMMAND SYNC")
    print("=" * 60)

    try:

        if GUILD_ID:

            guild_id = int(GUILD_ID)
            guild = discord.Object(id=guild_id)

            # Copy all registered commands to the test guild
            bot.tree.copy_global_to(guild=guild)

            synced = await bot.tree.sync(guild=guild)

            print(
                f"⚡ Guild slash sync complete: "
                f"{len(synced)} commands"
            )

            print(f"🏠 Guild ID: {guild_id}")

        else:

            synced = await bot.tree.sync()

            print(
                f"🌐 Global slash sync complete: "
                f"{len(synced)} commands"
            )

        # -------------------------------------------------
        # PRINT COMMAND LIST
        # -------------------------------------------------

        if synced:

            print("\n📋 REGISTERED SLASH COMMANDS:")

            for command in sorted(
                synced,
                key=lambda command: command.name
            ):
                print(f"   └─ /{command.name}")

        else:

            print(
                "⚠️ Discord received 0 slash commands."
            )

    except Exception as exc:

        print("\n❌ COMMAND SYNC FAILED")

        print(
            f"Reason: {type(exc).__name__}: {exc}"
        )

    print("=" * 60)
    print("✅ AIR COMMANDER STARTUP COMPLETE")
    print("=" * 60)
    



# =========================================================
# setup_hook is implemented by AirCommanderBot above.
# Do NOT assign bot.setup_hook = setup_hook here.
# =========================================================


# =========================================================
# PREFIX COMMANDS — MISSING COMMANDS
# Prefix: ,
# =========================================================



def prefix_embed(title, description="", color=discord.Color.blurple()):
    return discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=datetime.now(timezone.utc)
    )


# =========================================================
# ,about
# =========================================================

@bot.command(name="about")
async def prefix_about(ctx):

    e = prefix_embed(
        "✈️ About Air Commander",
        "Advanced Discord security, moderation and utility system."
    )

    e.add_field(
        name="🤖 Bot",
        value="Air Commander",
        inline=True
    )

    e.add_field(
        name="⚡ Prefix",
        value="`,`",
        inline=True
    )

    e.add_field(
        name="🌐 Servers",
        value=str(len(bot.guilds)),
        inline=True
    )

    e.add_field(
        name="👥 Users",
        value=str(len(bot.users)),
        inline=True
    )

    e.set_thumbnail(url=bot.user.display_avatar.url)

    e.set_footer(
        text=f"Requested by {ctx.author}"
    )

    await ctx.send(embed=e)


# =========================================================
# ,serverinfo
# =========================================================

@bot.command(name="serverinfo")
async def prefix_serverinfo(ctx):

    if ctx.guild is None:
        return await ctx.send(
            embed=prefix_embed(
                "❌ Server Only",
                "This command can only be used inside a server.",
                discord.Color.red()
            )
        )

    guild = ctx.guild

    e = prefix_embed(
        f"🏰 {guild.name}",
        "Complete information about this server."
    )

    e.add_field(
        name="👑 Owner",
        value=f"<@{guild.owner_id}>" if guild.owner_id else "Unknown",
        inline=True
    )

    e.add_field(
        name="👥 Members",
        value=str(guild.member_count),
        inline=True
    )

    e.add_field(
        name="💬 Channels",
        value=str(len(guild.channels)),
        inline=True
    )

    e.add_field(
        name="🎭 Roles",
        value=str(len(guild.roles)),
        inline=True
    )

    e.add_field(
        name="😀 Emojis",
        value=str(len(guild.emojis)),
        inline=True
    )

    e.add_field(
        name="🆔 Server ID",
        value=str(guild.id),
        inline=True
    )

    e.add_field(
        name="📅 Created",
        value=discord.utils.format_dt(guild.created_at, "F"),
        inline=False
    )

    if guild.icon:
        e.set_thumbnail(url=guild.icon.url)

    e.set_footer(
        text=f"Requested by {ctx.author}"
    )

    await ctx.send(embed=e)


# =========================================================
# ,userinfo
# =========================================================

@bot.command(name="userinfo")
async def prefix_userinfo(
    ctx,
    member: discord.Member = None
):

    member = member or ctx.author

    e = prefix_embed(
        f"👤 User Information",
        f"Information about {member.mention}"
    )

    e.add_field(
        name="🏷️ Username",
        value=str(member),
        inline=True
    )

    e.add_field(
        name="🆔 User ID",
        value=str(member.id),
        inline=True
    )

    e.add_field(
        name="🤖 Bot",
        value="Yes" if member.bot else "No",
        inline=True
    )

    e.add_field(
        name="🎭 Highest Role",
        value=member.top_role.mention,
        inline=True
    )

    e.add_field(
        name="📅 Account Created",
        value=discord.utils.format_dt(
            member.created_at,
            "F"
        ),
        inline=False
    )

    if member.joined_at:
        e.add_field(
            name="📥 Joined Server",
            value=discord.utils.format_dt(
                member.joined_at,
                "F"
            ),
            inline=False
        )

    e.set_thumbnail(
        url=member.display_avatar.url
    )

    e.set_footer(
        text=f"Requested by {ctx.author}"
    )

    await ctx.send(embed=e)


# =========================================================
# ,avatar
# =========================================================

@bot.command(name="avatar")
async def prefix_avatar(
    ctx,
    member: discord.Member = None
):

    member = member or ctx.author

    e = prefix_embed(
        f"🖼️ {member.display_name}'s Avatar",
        f"[🔗 Open Full Resolution]({member.display_avatar.url})"
    )

    e.set_image(
        url=member.display_avatar.url
    )

    e.set_footer(
        text=f"Requested by {ctx.author}"
    )

    await ctx.send(embed=e)


# =========================================================
# ,uptime
# =========================================================

@bot.command(name="uptime")
async def prefix_uptime(ctx):

    if not hasattr(bot, "start_time"):
        return await ctx.send(
            embed=prefix_embed(
                "⏱️ Uptime",
                "Bot start time is not available.",
                discord.Color.orange()
            )
        )

    delta = datetime.now(
        timezone.utc
    ) - bot.start_time

    days = delta.days

    hours, remainder = divmod(
        delta.seconds,
        3600
    )

    minutes, seconds = divmod(
        remainder,
        60
    )

    e = prefix_embed(
        "⏱️ Air Commander Uptime",
        f"🟢 **{days}d {hours}h {minutes}m {seconds}s**"
    )

    e.set_footer(
        text=f"Requested by {ctx.author}"
    )

    await ctx.send(embed=e)


# =========================================================
# ,ghostscan
# =========================================================

@bot.command(name="ghostscan")
async def prefix_ghostscan(
    ctx,
    days: int = 30
):

    if ctx.guild is None:
        return await ctx.send(
            embed=prefix_embed(
                "❌ Server Only",
                "This command can only be used inside a server.",
                discord.Color.red()
            )
        )

    if days < 1 or days > 365:
        return await ctx.send(
            embed=prefix_embed(
                "❌ Invalid Days",
                "Days must be between **1 and 365**.",
                discord.Color.red()
            )
        )

    cutoff = (
        datetime.now(timezone.utc).timestamp()
        - (days * 86400)
    )

    inactive = []

    for member in ctx.guild.members:

        if member.bot:
            continue

        if (
            member.joined_at
            and member.joined_at.timestamp() < cutoff
        ):
            inactive.append(member)

    e = prefix_embed(
        "👻 Ghost Scan",
        f"Members checked against **{days} days** inactivity."
    )

    e.add_field(
        name="👻 Possible Ghost Members",
        value=str(len(inactive)),
        inline=True
    )

    e.add_field(
        name="👥 Total Members",
        value=str(ctx.guild.member_count),
        inline=True
    )

    e.set_footer(
        text=f"Requested by {ctx.author}"
    )

    await ctx.send(embed=e)


# =========================================================
# ,activitymap
# =========================================================

@bot.command(name="activitymap")
async def prefix_activitymap(ctx):

    if ctx.guild is None:
        return await ctx.send(
            embed=prefix_embed(
                "❌ Server Only",
                "This command can only be used inside a server.",
                discord.Color.red()
            )
        )

    try:

        counts = await db.activity_counts(
            ctx.guild.id
        )

        if not counts:

            description = (
                "📭 No activity data is available yet."
            )

        else:

            lines = []

            for name, count in counts[:10]:

                lines.append(
                    f"👤 **{name}** — `{count}` activities"
                )

            description = "\n".join(lines)

        e = prefix_embed(
            "📊 Activity Map",
            description
        )

        e.set_footer(
            text=f"Requested by {ctx.author}"
        )

        await ctx.send(embed=e)

    except Exception as ex:

        await ctx.send(
            embed=prefix_embed(
                "❌ Activity Map Error",
                f"Could not load activity data.\n```{ex}```",
                discord.Color.red()
            )
        )


# =========================================================
# ,membercard
# =========================================================

@bot.command(name="membercard")
async def prefix_membercard(
    ctx,
    member: discord.Member = None
):

    member = member or ctx.author

    e = prefix_embed(
        f"🪪 Member Card",
        f"### {member.mention}"
    )

    e.add_field(
        name="🏷️ Username",
        value=str(member),
        inline=True
    )

    e.add_field(
        name="🆔 ID",
        value=str(member.id),
        inline=True
    )

    e.add_field(
        name="🤖 Bot",
        value="Yes" if member.bot else "No",
        inline=True
    )

    e.add_field(
        name="🎭 Highest Role",
        value=member.top_role.mention,
        inline=True
    )

    e.add_field(
        name="📅 Account",
        value=discord.utils.format_dt(
            member.created_at,
            "R"
        ),
        inline=True
    )

    e.add_field(
        name="📥 Joined",
        value=(
            discord.utils.format_dt(
                member.joined_at,
                "R"
            )
            if member.joined_at
            else "Unknown"
        ),
        inline=True
    )

    e.set_thumbnail(
        url=member.display_avatar.url
    )

    e.set_footer(
        text=f"Requested by {ctx.author}"
    )

    await ctx.send(embed=e)


# =========================================================
# ,modcase
# =========================================================

@bot.command(name="modcase")
async def prefix_modcase(
    ctx,
    action: str,
    target: discord.Member,
    *,
    details: str = None
):

    if ctx.guild is None:
        return await ctx.send(
            embed=prefix_embed(
                "❌ Server Only",
                "This command can only be used inside a server.",
                discord.Color.red()
            )
        )

    if not (
        ctx.author.guild_permissions.moderate_members
        or ctx.author.guild_permissions.manage_guild
    ):
        return await ctx.send(
            embed=prefix_embed(
                "🚫 Permission Denied",
                "You need **Moderate Members** or **Manage Server**.",
                discord.Color.red()
            )
        )

    allowed = {
        "warn",
        "timeout",
        "kick",
        "ban",
        "note"
    }

    action = action.lower()

    if action not in allowed:
        return await ctx.send(
            embed=prefix_embed(
                "❌ Invalid Action",
                "`warn` • `timeout` • `kick` • `ban` • `note`",
                discord.Color.red()
            )
        )

    if not details:
        return await ctx.send(
            embed=prefix_embed(
                "❌ Reason Required",
                "Example:\n"
                "`,modcase warn @User Spamming | evidence`",
                discord.Color.red()
            )
        )

    parts = details.split("|", 1)

    reason = parts[0].strip()

    evidence = (
        parts[1].strip()
        if len(parts) > 1
        else "Not provided"
    )

    try:

        case_id = await db.create_mod_case(
            ctx.guild.id,
            target.id,
            ctx.author.id,
            action,
            reason,
            evidence
        )

        e = prefix_embed(
            "🛡️ Moderation Case Created",
            f"Case **#{case_id}** created successfully.",
            discord.Color.green()
        )

        e.add_field(
            name="🎯 Target",
            value=target.mention,
            inline=True
        )

        e.add_field(
            name="⚔️ Action",
            value=action.title(),
            inline=True
        )

        e.add_field(
            name="📝 Reason",
            value=reason,
            inline=False
        )

        e.add_field(
            name="🔎 Evidence",
            value=evidence,
            inline=False
        )

        await ctx.send(embed=e)

    except Exception as ex:

        await ctx.send(
            embed=prefix_embed(
                "❌ Modcase Error",
                f"```{ex}```",
                discord.Color.red()
            )
        )


# =========================================================
# ,suggestionlab
# =========================================================

@bot.command(name="suggestionlab")
async def prefix_suggestionlab(
    ctx,
    action: str,
    *,
    text: str = None
):

    if ctx.guild is None:
        return await ctx.send(
            embed=prefix_embed(
                "❌ Server Only",
                "This command can only be used inside a server.",
                discord.Color.red()
            )
        )

    action = action.lower()

    # =====================================================
    # CREATE
    # =====================================================

    if action == "create":

        if not text:
            return await ctx.send(
                embed=prefix_embed(
                    "❌ Missing Suggestion",
                    "Example:\n"
                    "`,suggestionlab create Add a music system`",
                    discord.Color.red()
                )
            )

        suggestion_id = await db.create_suggestion(
            ctx.guild.id,
            ctx.author.id,
            text
        )

        e = prefix_embed(
            "💡 Suggestion Created",
            f"Suggestion **#{suggestion_id}** submitted successfully.",
            discord.Color.green()
        )

        e.add_field(
            name="💭 Suggestion",
            value=text,
            inline=False
        )

        await ctx.send(embed=e)

        return

    # =====================================================
    # STAFF CHECK
    # =====================================================

    if not ctx.author.guild_permissions.manage_guild:

        return await ctx.send(
            embed=prefix_embed(
                "🚫 Permission Denied",
                "You need **Manage Server** permission.",
                discord.Color.red()
            )
        )

    if not text:

        return await ctx.send(
            embed=prefix_embed(
                "❌ Missing Arguments",
                "Use:\n"
                "`,suggestionlab status <id> <status>`\n"
                "`,suggestionlab response <id> <response>`",
                discord.Color.red()
            )
        )

    parts = text.split(maxsplit=1)

    try:

        suggestion_id = int(parts[0])

    except ValueError:

        return await ctx.send(
            embed=prefix_embed(
                "❌ Invalid ID",
                "Suggestion ID must be a number.",
                discord.Color.red()
            )
        )

    # =====================================================
    # STATUS
    # =====================================================

    if action == "status":

        if len(parts) < 2:

            return await ctx.send(
                embed=prefix_embed(
                    "❌ Missing Status",
                    "Example:\n"
                    "`,suggestionlab status 12 Approved`",
                    discord.Color.red()
                )
            )

        raw_status = parts[1].strip().lower()

        statuses = {
            "pending": "Pending",
            "under review": "Under Review",
            "approved": "Approved",
            "rejected": "Rejected",
            "implemented": "Implemented"
        }

        status = statuses.get(raw_status)

        if not status:

            return await ctx.send(
                embed=prefix_embed(
                    "❌ Invalid Status",
                    "Available:\n"
                    "`Pending` • `Under Review` • "
                    "`Approved` • `Rejected` • `Implemented`",
                    discord.Color.red()
                )
            )

        await db.update_suggestion(
            ctx.guild.id,
            suggestion_id,
            status=status
        )

        await ctx.send(
            embed=prefix_embed(
                "📌 Suggestion Updated",
                f"Suggestion **#{suggestion_id}** → **{status}**",
                discord.Color.green()
            )
        )

        return

    # =====================================================
    # RESPONSE
    # =====================================================

    if action == "response":

        if len(parts) < 2:

            return await ctx.send(
                embed=prefix_embed(
                    "❌ Missing Response",
                    "Example:\n"
                    "`,suggestionlab response 12 Thanks for the idea!`",
                    discord.Color.red()
                )
            )

        response = parts[1].strip()

        await db.update_suggestion(
            ctx.guild.id,
            suggestion_id,
            staff_response=response
        )

        await ctx.send(
            embed=prefix_embed(
                "💬 Staff Response Added",
                f"Response added to suggestion **#{suggestion_id}**.",
                discord.Color.green()
            )
        )

        return

    await ctx.send(
        embed=prefix_embed(
            "❌ Unknown Action",
            "Available: `create` • `status` • `response`",
            discord.Color.red()
        )
    )


# =========================================================
# ,airscan
# =========================================================

@bot.command(name="airscan")
async def prefix_airscan(ctx):

    if ctx.guild is None:
        return await ctx.send(
            embed=prefix_embed(
                "❌ Server Only",
                "This command can only be used inside a server.",
                discord.Color.red()
            )
        )

    if not ctx.author.guild_permissions.manage_guild:

        return await ctx.send(
            embed=prefix_embed(
                "🚫 Permission Denied",
                "You need **Manage Server** permission.",
                discord.Color.red()
            )
        )

    guild = ctx.guild

    bots = sum(
        1
        for member in guild.members
        if member.bot
    )

    humans = sum(
        1
        for member in guild.members
        if not member.bot
    )

    e = prefix_embed(
        "🛰️ Air Scan",
        f"Security overview for **{guild.name}**."
    )

    e.add_field(
        name="👥 Humans",
        value=str(humans),
        inline=True
    )

    e.add_field(
        name="🤖 Bots",
        value=str(bots),
        inline=True
    )

    e.add_field(
        name="💬 Channels",
        value=str(len(guild.channels)),
        inline=True
    )

    e.add_field(
        name="🎭 Roles",
        value=str(len(guild.roles)),
        inline=True
    )

    e.add_field(
        name="😀 Emojis",
        value=str(len(guild.emojis)),
        inline=True
    )

    e.add_field(
        name="🚀 Boost Level",
        value=str(guild.premium_tier),
        inline=True
    )

    e.set_thumbnail(
        url=guild.icon.url
    ) if guild.icon else None

    e.set_footer(
        text=f"Air Commander • Requested by {ctx.author}"
    )

    await ctx.send(embed=e)


# =========================================================
# /ping
# =========================================================

@bot.tree.command(
    name="ping",
    description="Check the bot's latency."
)
async def ping(interaction: discord.Interaction):

    latency = round(bot.latency * 1000)

    e = discord.Embed(
        title="✈️ Air Commander • Ping Check",
        description=(
            "╭────────────────────╮\n"
            "     **Gateway Status**\n"
            "╰────────────────────╯\n\n"
            "📡 Air Commander is connected "
            "and responding normally."
        ),
        color=discord.Color.blurple(),
        timestamp=discord.utils.utcnow()
    )

    e.add_field(
        name="📡 Latency",
        value=f"**{latency} ms**",
        inline=True
    )

    e.add_field(
        name="🟢 Status",
        value="**Operational**",
        inline=True
    )

    e.set_footer(
        text="✈️ Air Commander • Systems Operational"
    )

    await interaction.response.send_message(embed=e)



# =========================================================
# /about
# =========================================================

@bot.tree.command(
    name="about",
    description="Show information about Air Commander."
)
async def about(interaction: discord.Interaction):

    e = discord.Embed(
        title="✈️ Air Commander • About",
        description=(
            "╭────────────────────────╮\n"
            "     **Air Commander System**\n"
            "╰────────────────────────╯\n\n"
            "⚙️ Moderation • Utility • Intelligence • Games"
        ),
        color=discord.Color.blurple(),
        timestamp=discord.utils.utcnow()
    )

    e.add_field(
        name="👨‍💻 Developer",
        value="**Prithvi**",
        inline=True
    )

    e.add_field(
        name="🌐 Servers",
        value=f"**{len(bot.guilds)}**",
        inline=True
    )

    e.add_field(
        name="⚙️ Library",
        value="**discord.py**",
        inline=True
    )

    e.add_field(
        name="🟢 Status",
        value="**Online**",
        inline=True
    )

    e.add_field(
        name="⚡ Slash Commands",
        value=f"**{len(bot.tree.get_commands())}**",
        inline=True
    )

    e.set_footer(
        text="✈️ Air Commander • Built for clean server management"
    )

    await interaction.response.send_message(embed=e)


# =========================================================
# /serverinfo
# =========================================================

@bot.tree.command(
    name="serverinfo",
    description="Show detailed server information."
)
async def serverinfo(interaction: discord.Interaction):

    guild = interaction.guild

    if not guild:
        return await interaction.response.send_message(
            "❌ **This command can only be used inside a server.**",
            ephemeral=True
        )

    bots = sum(
        1 for m in guild.members if m.bot
    )

    e = discord.Embed(
        title=f"✈️ {guild.name} • Server Overview",
        description=(
            "📊 **Server Intelligence Snapshot**\n"
            "A quick overview of this Discord server."
        ),
        color=discord.Color.blurple(),
        timestamp=discord.utils.utcnow()
    )

    if guild.icon:
        e.set_thumbnail(url=guild.icon.url)

    e.add_field(
        name="👥 Members",
        value=(
            f"Total • **{guild.member_count}**\n"
            f"Humans • **{guild.member_count - bots}**\n"
            f"Bots • **{bots}**"
        ),
        inline=True
    )

    e.add_field(
        name="🗂️ Structure",
        value=(
            f"Channels • **{len(guild.channels)}**\n"
            f"Roles • **{len(guild.roles)}**\n"
            f"Categories • **{len(guild.categories)}**"
        ),
        inline=True
    )

    e.add_field(
        name="🔐 Security",
        value=(
            f"Verification • **{guild.verification_level.name}**\n"
            f"2FA Moderation • "
            f"**{'Enabled' if guild.mfa_level else 'Disabled'}**"
        ),
        inline=True
    )

    e.add_field(
        name="📅 Created",
        value=discord.utils.format_dt(
            guild.created_at,
            "F"
        ),
        inline=False
    )

    e.set_footer(
        text=f"✈️ Air Commander • Server ID • {guild.id}"
    )

    await interaction.response.send_message(embed=e)


# =========================================================
# /userinfo
# =========================================================

@bot.tree.command(
    name="userinfo",
    description="Show detailed information about a user."
)
@app_commands.describe(
    user="The user to inspect"
)
async def userinfo(
    interaction: discord.Interaction,
    user: discord.Member | None = None
):

    user = user or interaction.user

    e = discord.Embed(
        title=f"✈️ User Profile • {user.display_name}",
        description=(
            f"🔎 Detailed profile information for {user.mention}"
        ),
        color=discord.Color.blurple(),
        timestamp=discord.utils.utcnow()
    )

    e.set_thumbnail(
        url=user.display_avatar.url
    )

    e.add_field(
        name="🪪 Identity",
        value=(
            f"Username • **{user}**\n"
            f"ID • `{user.id}`\n"
            f"Bot • **{'Yes' if user.bot else 'No'}**"
        ),
        inline=True
    )

    e.add_field(
        name="📅 Dates",
        value=(
            f"Created • "
            f"{discord.utils.format_dt(user.created_at, 'R')}\n"
            f"Joined • "
            f"{discord.utils.format_dt(user.joined_at, 'R') if user.joined_at else 'Unknown'}"
        ),
        inline=True
    )

    e.add_field(
        name="👑 Top Role",
        value=user.top_role.mention,
        inline=True
    )

    e.set_footer(
        text=f"✈️ Air Commander • User ID • {user.id}"
    )

    await interaction.response.send_message(
        embed=e
    )


# =========================================================
# /avatar
# =========================================================

@bot.tree.command(
    name="avatar",
    description="Show a user's avatar."
)
@app_commands.describe(
    user="The user whose avatar you want to see"
)
async def avatar(
    interaction: discord.Interaction,
    user: discord.User | None = None
):

    user = user or interaction.user

    e = discord.Embed(
        title=f"🖼️ {user.display_name} • Avatar",
        description="✨ High-resolution profile avatar.",
        color=discord.Color.blurple(),
        timestamp=discord.utils.utcnow()
    )

    e.set_image(
        url=user.display_avatar.replace(
            size=1024
        ).url
    )

    e.set_footer(
        text=f"✈️ Air Commander • User ID • {user.id}"
    )

    await interaction.response.send_message(
        embed=e
    )


# =========================================================
# /uptime
# =========================================================

@bot.tree.command(
    name="uptime",
    description="Show how long Air Commander has been online."
)
async def uptime(interaction: discord.Interaction):

    seconds = int(
        time.time() - start_time
    )

    days, seconds = divmod(
        seconds,
        86400
    )

    hours, seconds = divmod(
        seconds,
        3600
    )

    minutes, seconds = divmod(
        seconds,
        60
    )

    e = discord.Embed(
        title="✈️ Air Commander • Uptime",
        description=(
            "🟢 **System availability report**\n"
            "Air Commander has remained operational for:"
        ),
        color=discord.Color.green(),
        timestamp=discord.utils.utcnow()
    )

    e.add_field(
        name="⏱️ Online For",
        value=(
            f"**{days}d {hours}h "
            f"{minutes}m {seconds}s**"
        ),
        inline=False
    )

    e.set_footer(
        text="🟢 Air Commander • System continuously monitored"
    )

    await interaction.response.send_message(
        embed=e
    )


# =========================================================
# PREFIX COMMAND ERROR HANDLER
# =========================================================

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingPermissions):
        return await ctx.send("❌ You don't have the required permission.")
    if isinstance(error, commands.BotMissingPermissions):
        return await ctx.send("❌ I don't have the required Discord permission.")
    if isinstance(error, commands.MissingRequiredArgument):
        return await ctx.send(f"❌ Missing argument: `{error.param.name}`.")
    if isinstance(error, commands.BadArgument):
        return await ctx.send("❌ Invalid argument. Check the command format and mention the member.")
    if isinstance(error, commands.CheckFailure):
        return await ctx.send("❌ You don't have permission to use this command.")
    print(f"Prefix command error: {type(error).__name__}: {error}")


# =========================================================
# MESSAGE ACTIVITY LOGGER
# =========================================================

@bot.event
async def on_message(message):

    if message.author.bot or not message.guild:
        return

    # -----------------------------------------------------
    # AFK: remove the sender's own AFK when they speak.
    # -----------------------------------------------------
    removed_guild, removed_global = _remove_afk(
        message.guild.id,
        message.author.id
    )

    if removed_guild or removed_global:
        try:
            await message.channel.send(
                f"👋 Welcome back {message.author.mention}! Your AFK has been removed.",
                delete_after=5
            )
        except discord.HTTPException:
            pass

    # -----------------------------------------------------
    # AFK: notify when someone mentions an AFK user.
    # -----------------------------------------------------
    mentioned = set(message.mentions)
    notices = []

    for member in mentioned:
        guild_data = guild_afk.get((message.guild.id, member.id))
        global_data = global_afk.get(member.id)

        if guild_data:
            notices.append(
                f"💤 {member.mention} is **AFK**: {_afk_text(guild_data)}"
            )
        elif global_data:
            notices.append(
                f"🌐 {member.mention} is **globally AFK**: {_afk_text(global_data)}"
            )

    if notices:
        try:
            await message.channel.send(
                "\n".join(notices[:10]),
                delete_after=8
            )
        except discord.HTTPException:
            pass

    try:
        await db.log_activity(
            message.guild.id,
            message.channel.id,
            message.author.id
        )

    except Exception as e:
        print(
            f"⚠️ Activity log error: {e}"
        )

    await bot.process_commands(message)


# =========================================================
# EMBED HELPER
# =========================================================

def air_embed(
    title,
    description="",
    color=None
):

    e = discord.Embed(
        title=f"✈️ {title}",
        description=description,
        color=(
            color
            or discord.Color.blurple()
        ),
        timestamp=discord.utils.utcnow()
    )

    e.set_footer(
        text="✈️ Air Commander • Intelligence System"
    )

    return e


# =========================================================
# /ghostscan
# =========================================================

@bot.tree.command(
    name="ghostscan",
    description="Scan inactive/ghost members"
)
@app_commands.describe(
    days="Joined before this many days ago"
)
async def ghostscan(
    i,
    days: app_commands.Range[int, 1, 365] = 30
):

    if not i.guild:
        return await i.response.send_message(
            "❌ **This command can only be used in a server.**",
            ephemeral=True
        )

    await i.response.defer()

    cutoff = (
        discord.utils.utcnow().timestamp()
        - days * 86400
    )

    ghosts = [
        m
        for m in i.guild.members
        if not m.bot
        and m.joined_at
        and m.joined_at.timestamp() < cutoff
    ]

    e = air_embed(
        "GhostScan • Member Intelligence",
        (
            "🔎 Scanning for members who joined "
            f"before the **{days}-day** threshold.\n\n"
            "⚠️ These are candidates only, "
            "not confirmed inactive users."
        ),
        discord.Color.orange()
    )

    e.add_field(
        name="👥 Members Scanned",
        value=f"**{len(i.guild.members)}**",
        inline=True
    )

    e.add_field(
        name="👻 Candidates",
        value=f"**{len(ghosts)}**",
        inline=True
    )

    e.add_field(
        name="🧠 Method",
        value=(
            "Older joins are treated as candidates. "
            "Activity history is based on messages collected "
            "while Air Commander is online."
        ),
        inline=False
    )

    if ghosts:
        e.add_field(
            name="👻 Candidate Members",
            value="\n".join(
                f"• {m.mention} — joined "
                f"{discord.utils.format_dt(m.joined_at, 'R')}"
                for m in ghosts[:20]
            ),
            inline=False
        )

    await i.followup.send(
        embed=e
    )


# =========================================================
# /activitymap
# =========================================================

@bot.tree.command(
    name="activitymap",
    description="Show channel/category activity intelligence"
)
async def activitymap(i):

    if not i.guild:
        return await i.response.send_message(
            "❌ **This command can only be used in a server.**",
            ephemeral=True
        )

    rows = await db.activity_counts(
        i.guild.id
    )

    e = air_embed(
        "ActivityMap • Server Activity",
        (
            "📊 Live activity collected while "
            "**Air Commander** is online."
        ),
        discord.Color.teal()
    )

    lines = []

    for row in rows or []:

        ch = i.guild.get_channel(
            row["channel_id"]
        )

        if ch:
            lines.append(
                f"• {ch.mention} — "
                f"**{row['messages']}** messages"
            )

    e.add_field(
        name="🔥 Most Active Channels",
        value=(
            "\n".join(lines)
            or "📭 No recorded activity yet."
        ),
        inline=False
    )

    cats = {}

    for ch in i.guild.text_channels:

        key = (
            ch.category.name
            if ch.category
            else "No Category"
        )

        cats[key] = cats.get(key, 0) + 1

    e.add_field(
        name="🗂️ Channel Distribution",
        value=(
            "\n".join(
                f"• {k}: **{v}** channels"
                for k, v in sorted(
                    cats.items(),
                    key=lambda x: x[1],
                    reverse=True
                )[:10]
            )
            or "📭 None"
        ),
        inline=False
    )

    await i.response.send_message(
        embed=e
    )


# =========================================================
# /membercard
# =========================================================

@bot.tree.command(
    name="membercard",
    description="Detailed Discord profile and server card"
)
@app_commands.describe(
    member="Member to inspect"
)
async def membercard(
    i,
    member: discord.Member = None
):

    if not i.guild:
        return await i.response.send_message(
            "❌ **This command can only be used in a server.**",
            ephemeral=True
        )

    member = member or i.user

    e = air_embed(
        f"MemberCard • {member.display_name}",
        "🪪 Detailed member profile.",
        discord.Color.blurple()
    )

    e.set_thumbnail(
        url=member.display_avatar.url
    )

    e.add_field(
        name="🪪 Identity",
        value=(
            f"{member.mention}\n"
            f"`{member.id}`\n"
            f"Bot: **{'Yes' if member.bot else 'No'}**"
        ),
        inline=True
    )

    e.add_field(
        name="📅 Dates",
        value=(
            f"Created • "
            f"{discord.utils.format_dt(member.created_at, 'R')}\n"
            f"Joined • "
            f"{discord.utils.format_dt(member.joined_at, 'R') if member.joined_at else 'Unknown'}"
        ),
        inline=True
    )

    e.add_field(
        name="🎭 Roles",
        value=(
            ", ".join(
                r.mention
                for r in member.roles[1:]
            )[:1024]
            or "None"
        ),
        inline=False
    )

    e.set_footer(
        text=f"✈️ Air Commander • Member ID • {member.id}"
    )

    await i.response.send_message(
        embed=e
    )


# =========================================================
# /modcase
# =========================================================

@bot.tree.command(
    name="modcase",
    description="Create a persistent moderation case"
)
@app_commands.describe(
    action="Action",
    target="Target member",
    reason="Reason",
    evidence="Evidence/reference"
)
@app_commands.choices(
    action=[
        app_commands.Choice(
            name=x.title(),
            value=x
        )
        for x in (
            "warn",
            "kick",
            "ban",
            "timeout",
            "unban",
            "other"
        )
    ]
)
async def modcase(
    i,
    action: app_commands.Choice[str],
    target: discord.Member,
    reason: str,
    evidence: str = "Not provided"
):

    if not i.guild:
        return await i.response.send_message(
            "❌ **This command can only be used in a server.**",
            ephemeral=True
        )

    if (
        not i.user.guild_permissions.moderate_members
        and not i.user.guild_permissions.manage_guild
    ):
        return await i.response.send_message(
            "🚫 **Moderation permission required.**",
            ephemeral=True
        )

    code = await db.next_case(
        i.guild.id,
        target.id,
        i.user.id,
        action.value,
        reason,
        evidence
    )

    e = air_embed(
        f"ModCase • {code}",
        (
            "🛡️ Persistent Air Commander "
            "moderation record."
        ),
        discord.Color.red()
    )

    e.add_field(
        name="⚔️ Action",
        value=action.name.upper(),
        inline=True
    )

    e.add_field(
        name="🎯 Target",
        value=f"{target.mention}\n`{target.id}`",
        inline=True
    )

    e.add_field(
        name="👮 Moderator",
        value=i.user.mention,
        inline=True
    )

    e.add_field(
        name="📝 Reason",
        value=reason[:1024],
        inline=False
    )

    e.add_field(
        name="📎 Evidence",
        value=evidence[:1024],
        inline=False
    )

    e.set_footer(
        text=f"✈️ Air Commander • Case • {code}"
    )

    await i.response.send_message(
        embed=e
    )


# =========================================================
# /suggestionlab
# =========================================================

@bot.tree.command(
    name="suggestionlab",
    description="Create or manage a suggestion"
)
@app_commands.describe(
    action="Create, update status, or add staff response",
    suggestion="Suggestion text for create",
    suggestion_id="Suggestion number for staff actions",
    status="New status",
    staff_response="Staff response"
)
@app_commands.choices(
    action=[
        app_commands.Choice(
            name="Create",
            value="create"
        ),
        app_commands.Choice(
            name="Set Status",
            value="status"
        ),
        app_commands.Choice(
            name="Staff Response",
            value="response"
        )
    ]
)
@app_commands.choices(
    status=[
        app_commands.Choice(
            name=x,
            value=x
        )
        for x in (
            "Pending",
            "Under Review",
            "Approved",
            "Rejected",
            "Implemented"
        )
    ]
)
async def suggestionlab(
    i,
    action: app_commands.Choice[str],
    suggestion: str = None,
    suggestion_id: int = None,
    status: app_commands.Choice[str] = None,
    staff_response: str = None
):

    if not i.guild:
        return await i.response.send_message(
            "❌ **This command can only be used in a server.**",
            ephemeral=True
        )

    # -----------------------------------------------------
    # CREATE SUGGESTION
    # -----------------------------------------------------

    if action.value == "create":

        if not suggestion:
            return await i.response.send_message(
                "📝 **Please provide suggestion text.**",
                ephemeral=True
            )

        sid = await db.save_suggestion(
            i.guild.id,
            i.user.id,
            suggestion
        )

        e = air_embed(
            "SuggestionLab • New Suggestion",
            (
                f"💡 **Suggestion submitted by {i.user.mention}**\n\n"
                f"{suggestion}"
            ),
            discord.Color.gold()
        )

        e.add_field(
            name="📌 Status",
            value="🟡 **Pending**",
            inline=True
        )

        e.add_field(
            name="👤 Author",
            value=i.user.mention,
            inline=True
        )

        e.add_field(
            name="🗳️ Voting",
            value="👍 Approve    👎 Reject",
            inline=False
        )

        if sid:
            e.set_footer(
                text=f"✈️ Air Commander • Suggestion #{sid} • Staff Review"
            )

        await i.response.send_message(
            embed=e
        )

        msg = await i.original_response()

        await msg.add_reaction("👍")
        await msg.add_reaction("👎")

        return

    # -----------------------------------------------------
    # STAFF PERMISSION
    # -----------------------------------------------------

    if not i.user.guild_permissions.manage_guild:
        return await i.response.send_message(
            "🚫 **Manage Server permission required for staff actions.**",
            ephemeral=True
        )

    if not suggestion_id:
        return await i.response.send_message(
            "🔢 **Please provide `suggestion_id`.**",
            ephemeral=True
        )

    if action.value == "status" and not status:
        return await i.response.send_message(
            "📌 **Please choose a status.**",
            ephemeral=True
        )

    if action.value == "response" and not staff_response:
        return await i.response.send_message(
            "💬 **Please provide a staff response.**",
            ephemeral=True
        )

    ok = await db.update_suggestion(
        suggestion_id,
        i.guild.id,
        status.value if status else None,
        staff_response
        if action.value == "response"
        else None
    )

    if not ok:
        return await i.response.send_message(
            "❌ **Suggestion not found.**",
            ephemeral=True
        )

    e = air_embed(
        f"SuggestionLab • #{suggestion_id}",
        "✨ Suggestion workflow updated successfully.",
        discord.Color.green()
    )

    e.add_field(
        name="⚙️ Action",
        value=action.name,
        inline=True
    )

    if status:
        e.add_field(
            name="📌 Status",
            value=status.name,
            inline=True
        )

    if staff_response:
        e.add_field(
            name="💬 Staff Response",
            value=staff_response[:1024],
            inline=False
        )

    e.set_footer(
        text=f"✈️ Air Commander • Suggestion #{suggestion_id}"
    )

    await i.response.send_message(
        embed=e
    )


# =========================================================
# /airscan
# =========================================================

@bot.tree.command(
    name="airscan",
    description="Generate a full AirCommander intelligence report"
)
async def airscan(i):

    if not i.guild:
        return await i.response.send_message(
            "❌ **This command can only be used in a server.**",
            ephemeral=True
        )

    if not i.user.guild_permissions.manage_guild:
        return await i.response.send_message(
            "🚫 **Manage Server permission required.**",
            ephemeral=True
        )

    await i.response.defer()

    g = i.guild

    bots = sum(
        1
        for m in g.members
        if m.bot
    )

    admin = [
        r
        for r in g.roles
        if r != g.default_role
        and r.permissions.administrator
    ]

    uncategorized = [
        ch
        for ch in g.channels
        if isinstance(
            ch,
            (
                discord.TextChannel,
                discord.VoiceChannel
            )
        )
        and ch.category is None
    ]

    e = air_embed(
        "AirScan • Intelligence Report",
        (
            f"🛰️ Security, moderation, activity and "
            f"configuration snapshot for **{g.name}**."
        ),
        discord.Color.blurple()
    )

    if g.icon:
        e.set_thumbnail(
            url=g.icon.url
        )

    e.add_field(
        name="👥 MEMBERS",
        value=(
            f"Total • **{g.member_count}**\n"
            f"Humans • **{g.member_count - bots}**\n"
            f"Bots • **{bots}**"
        ),
        inline=True
    )

    e.add_field(
        name="📚 CHANNELS",
        value=(
            f"Total • **{len(g.channels)}**\n"
            f"Text • **{len(g.text_channels)}**\n"
            f"Voice • **{len(g.voice_channels)}**\n"
            f"Categories • **{len(g.categories)}**"
        ),
        inline=True
    )

    e.add_field(
        name="🎭 ROLES",
        value=(
            f"Total • **{len(g.roles)}**\n"
            f"Admin Roles • **{len(admin)}**"
        ),
        inline=True
    )

    e.add_field(
        name="🔐 SECURITY",
        value=(
            (
                "⚠️ " +
                ", ".join(
                    r.mention
                    for r in admin[:8]
                )
            )
            if admin
            else "🟢 No extra Administrator roles detected"
        ),
        inline=False
    )

    e.add_field(
        name="⚙️ CONFIGURATION",
        value=(
            f"Verification • **{g.verification_level.name}**\n"
            f"2FA Moderation • "
            f"**{'Enabled' if g.mfa_level else 'Disabled'}**\n"
            f"System Channel • "
            f"**{g.system_channel.mention if g.system_channel else 'None'}**"
        ),
        inline=False
    )

    e.add_field(
        name="🗂️ STRUCTURE",
        value=(
            f"Uncategorized channels: "
            f"**{len(uncategorized)}**"
        ),
        inline=False
    )

    e.set_footer(
        text="🛰️ Air Commander • Intelligence Scan Complete"
    )

    await i.followup.send(
        embed=e
    )

# =========================================================
# BOT STARTUP
# =========================================================

def main():

    threading.Thread(
        target=run_web,
        daemon=True,
        name="render-health"
    ).start()

    print(
        f"🌐 Health server starting on "
        f"0.0.0.0:{os.getenv('PORT', '10000')}"
    )

    bot.run(TOKEN)


# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":
    main()

