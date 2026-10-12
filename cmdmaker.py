import re
import random
import asyncio
import discord
from discord import app_commands
import db


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


def setup(bot):
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

    bot._air_load_custom_commands = load_custom_commands
