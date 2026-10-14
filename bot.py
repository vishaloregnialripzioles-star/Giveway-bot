import asyncio
import logging
import os
import threading
from datetime import timedelta

import discord
from discord import app_commands
from flask import Flask, jsonify
from giveaway_system import register_giveaway_commands

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("giveway-bot")
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")
PORT = int(os.getenv("PORT", "10000"))

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing. Set it in Render Environment.")
if GUILD_ID and not GUILD_ID.isdigit():
    raise RuntimeError("GUILD_ID must be a numeric Discord server ID.")

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)
giveaways = register_giveaway_commands(tree, client)
web = Flask(__name__)
synced = False


@web.get("/")
def home():
    return jsonify({
        "status": "ok",
        "bot": "Giveway-bot",
        "discord_connected": client.is_ready(),
        "commands": ["help", "ping", "giveaway start", "giveaway end", "giveaway reroll",
                     "giveaway cancel", "giveaway entrants", "kick", "ban", "timeout",
                     "untimeout", "purge", "warn", "slowmode", "lock", "unlock", "nickname"],
    })


@web.get("/health")
def health():
    return jsonify({"status": "ok", "discord_connected": client.is_ready()})


threading.Thread(
    target=lambda: web.run(host="0.0.0.0", port=PORT, use_reloader=False),
    daemon=True,
    name="health-server",
).start()


def has_permission(interaction: discord.Interaction, permission: str) -> bool:
    return (
        interaction.guild is not None
        and isinstance(interaction.user, discord.Member)
        and bool(getattr(interaction.user.guild_permissions, permission, False))
    )


async def require_permission(interaction: discord.Interaction, permission: str, label: str) -> bool:
    if not has_permission(interaction, permission):
        await interaction.response.send_message(
            f"❌ You need the {label} permission to use this command.", ephemeral=True
        )
        return False
    return True


def hierarchy_ok(interaction: discord.Interaction, target: discord.Member) -> bool:
    guild = interaction.guild
    if guild is None or not isinstance(interaction.user, discord.Member):
        return False
    bot_member = guild.me
    if target.id in {interaction.user.id, guild.owner_id}:
        return False
    if bot_member is None or target.id == bot_member.id:
        return False
    if interaction.user.id != guild.owner_id and target.top_role >= interaction.user.top_role:
        return False
    return target.top_role < bot_member.top_role


@tree.command(name="help", description="Show all Giveway-bot commands.")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="✨ Giveway-bot • Help",
        description="Giveaways plus useful server moderation tools.",
        color=discord.Color.blurple(),
    )
    embed.add_field(
        name="🧰 General",
        value="**/help** — Show this guide\n**/ping** — Check bot latency",
        inline=False,
    )
    embed.add_field(
        name="🛡️ Moderation",
        value=(
            "**/kick** — Kick a member\n**/ban** — Ban a member\n"
            "**/timeout** — Temporarily restrict a member\n**/untimeout** — Remove a timeout\n"
            "**/purge** — Delete recent messages\n**/warn** — Send a warning by DM"
        ),
        inline=False,
    )
    embed.add_field(
        name="🔧 Channel and member tools",
        value=(
            "**/slowmode** — Set channel slowmode\n**/lock** and **/unlock** — Change channel access\n"
            "**/nickname** — Change or reset a nickname"
        ),
        inline=False,
    )
    embed.set_footer(text="Moderation commands require the relevant server permissions.")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="ping", description="Check whether the bot is online.")
async def ping(interaction: discord.Interaction):
    latency = round(client.latency * 1000) if client.is_ready() else 0
    await interaction.response.send_message(f"🏓 Pong! Gateway latency: {latency} ms", ephemeral=True)


@tree.command(name="kick", description="Kick a member from this server.")
@app_commands.default_permissions(kick_members=True)
@app_commands.describe(member="Member to kick", reason="Reason for the kick")
async def kick(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    if not await require_permission(interaction, "kick_members", "Kick Members"):
        return
    if not hierarchy_ok(interaction, member):
        await interaction.response.send_message("❌ You cannot kick yourself, the server owner, the bot, or a member with an equal/higher role.", ephemeral=True)
        return
    try:
        await member.kick(reason=f"{reason} | Moderator: {interaction.user} ({interaction.user.id})")
        await interaction.response.send_message(f"👢 Kicked **{member}**. Reason: {reason}", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("❌ I cannot kick that member. Check my Kick Members permission and role position.", ephemeral=True)
    except discord.HTTPException:
        await interaction.response.send_message("❌ Discord could not complete the kick. Please try again later.", ephemeral=True)


@tree.command(name="ban", description="Ban a member from this server.")
@app_commands.default_permissions(ban_members=True)
@app_commands.describe(member="Member to ban", reason="Reason for the ban")
async def ban(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    if not await require_permission(interaction, "ban_members", "Ban Members"):
        return
    if not hierarchy_ok(interaction, member):
        await interaction.response.send_message("❌ You cannot ban yourself, the server owner, the bot, or a member with an equal/higher role.", ephemeral=True)
        return
    try:
        await member.ban(reason=f"{reason} | Moderator: {interaction.user} ({interaction.user.id})", delete_message_seconds=0)
        await interaction.response.send_message(f"🔨 Banned **{member}**. Reason: {reason}", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("❌ I cannot ban that member. Check my Ban Members permission and role position.", ephemeral=True)
    except discord.HTTPException:
        await interaction.response.send_message("❌ Discord could not complete the ban. Please try again later.", ephemeral=True)


@tree.command(name="timeout", description="Timeout a member for 1 to 40320 minutes.")
@app_commands.default_permissions(moderate_members=True)
@app_commands.describe(member="Member to timeout", minutes="Duration in minutes (1–40320)", reason="Reason for timeout")
async def timeout(interaction: discord.Interaction, member: discord.Member, minutes: app_commands.Range[int, 1, 40320], reason: str = "No reason provided"):
    if not await require_permission(interaction, "moderate_members", "Moderate Members"):
        return
    if not hierarchy_ok(interaction, member):
        await interaction.response.send_message("❌ You cannot timeout yourself, the server owner, the bot, or a member with an equal/higher role.", ephemeral=True)
        return
    try:
        await member.timeout(timedelta(minutes=minutes), reason=f"{reason} | Moderator: {interaction.user} ({interaction.user.id})")
        await interaction.response.send_message(f"⏳ Timed out **{member}** for {minutes} minute(s). Reason: {reason}", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("❌ I cannot timeout that member. Check Moderate Members permission and role position.", ephemeral=True)
    except discord.HTTPException:
        await interaction.response.send_message("❌ Discord could not complete the timeout. Please try again later.", ephemeral=True)


@tree.command(name="untimeout", description="Remove a member's timeout.")
@app_commands.default_permissions(moderate_members=True)
@app_commands.describe(member="Member whose timeout should be removed", reason="Reason for removing timeout")
async def untimeout(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    if not await require_permission(interaction, "moderate_members", "Moderate Members"):
        return
    if not hierarchy_ok(interaction, member):
        await interaction.response.send_message("❌ You cannot modify that member because of role hierarchy.", ephemeral=True)
        return
    try:
        await member.timeout(None, reason=f"{reason} | Moderator: {interaction.user} ({interaction.user.id})")
        await interaction.response.send_message(f"✅ Removed timeout for **{member}**. Reason: {reason}", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("❌ I cannot remove that timeout. Check permissions and role position.", ephemeral=True)
    except discord.HTTPException:
        await interaction.response.send_message("❌ Discord could not remove the timeout. Please try again later.", ephemeral=True)


@tree.command(name="purge", description="Delete 1 to 100 recent messages in this channel.")
@app_commands.default_permissions(manage_messages=True)
@app_commands.describe(amount="Number of messages to delete (1–100)")
async def purge(interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100]):
    if not await require_permission(interaction, "manage_messages", "Manage Messages"):
        return
    if not isinstance(interaction.channel, discord.TextChannel):
        await interaction.response.send_message("❌ Use this command in a server text channel.", ephemeral=True)
        return
    bot_member = interaction.guild.me if interaction.guild else None
    if bot_member is None or not bot_member.guild_permissions.manage_messages or not bot_member.guild_permissions.read_message_history:
        await interaction.response.send_message("❌ I need Manage Messages and Read Message History permissions.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(f"🧹 Deleted {len(deleted)} message(s).", ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send("❌ I cannot manage messages in this channel.", ephemeral=True)
    except discord.HTTPException:
        await interaction.followup.send("❌ Discord could not delete those messages. Please try again later.", ephemeral=True)


@tree.command(name="warn", description="Send a warning to a member by DM.")
@app_commands.default_permissions(moderate_members=True)
@app_commands.describe(member="Member to warn", reason="Reason for the warning")
async def warn(interaction: discord.Interaction, member: discord.Member, reason: str):
    if not await require_permission(interaction, "moderate_members", "Moderate Members"):
        return
    if member.id == interaction.user.id or member.id == interaction.guild.owner_id:
        await interaction.response.send_message("❌ You cannot warn yourself or the server owner.", ephemeral=True)
        return
    embed = discord.Embed(
        title="⚠️ Server Warning",
        description=f"You have received a warning in **{interaction.guild.name}**.",
        color=discord.Color.orange(),
    )
    embed.add_field(name="Reason", value=reason[:1024], inline=False)
    embed.set_footer(text=f"Moderator: {interaction.user}")
    try:
        await member.send(embed=embed)
        await interaction.response.send_message(f"⚠️ Warning DM sent to **{member}**. Reason: {reason}", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message(f"⚠️ Could not DM **{member}**; their DMs may be closed. No warning DM was delivered.", ephemeral=True)
    except discord.HTTPException:
        await interaction.response.send_message("❌ Discord could not deliver the warning. Please try again later.", ephemeral=True)


@tree.command(name="slowmode", description="Set slowmode for this text channel.")
@app_commands.default_permissions(manage_channels=True)
@app_commands.describe(seconds="Delay in seconds; 0 disables slowmode")
async def slowmode(interaction: discord.Interaction, seconds: app_commands.Range[int, 0, 21600]):
    if not await require_permission(interaction, "manage_channels", "Manage Channels"):
        return
    if not isinstance(interaction.channel, discord.TextChannel):
        await interaction.response.send_message("❌ Use this command in a server text channel.", ephemeral=True)
        return
    try:
        await interaction.channel.edit(slowmode_delay=seconds, reason=f"Slowmode set by {interaction.user} ({interaction.user.id})")
        message = "disabled" if seconds == 0 else f"set to {seconds} second(s)"
        await interaction.response.send_message(f"🐢 Slowmode {message}.", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("❌ I need Manage Channels permission in this channel.", ephemeral=True)
    except discord.HTTPException:
        await interaction.response.send_message("❌ Discord could not update slowmode. Please try again later.", ephemeral=True)


async def set_lock(interaction: discord.Interaction, locked: bool, channel: discord.TextChannel | None):
    if not await require_permission(interaction, "manage_channels", "Manage Channels"):
        return
    target = channel or interaction.channel
    if not isinstance(target, discord.TextChannel) or interaction.guild is None:
        await interaction.response.send_message("❌ Choose a server text channel.", ephemeral=True)
        return
    try:
        overwrite = target.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = False if locked else None
        await target.set_permissions(
            interaction.guild.default_role,
            overwrite=overwrite,
            reason=f"Channel {'locked' if locked else 'unlocked'} by {interaction.user} ({interaction.user.id})",
        )
        await interaction.response.send_message(f"✅ {target.mention} has been {'locked 🔒' if locked else 'unlocked 🔓'}.", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("❌ I need Manage Channels permission to change this channel.", ephemeral=True)
    except discord.HTTPException:
        await interaction.response.send_message("❌ Discord could not update channel permissions. Please try again later.", ephemeral=True)


@tree.command(name="lock", description="Prevent @everyone from sending messages in a text channel.")
@app_commands.default_permissions(manage_channels=True)
@app_commands.describe(channel="Channel to lock; defaults to this channel")
async def lock(interaction: discord.Interaction, channel: discord.TextChannel | None = None):
    await set_lock(interaction, True, channel)


@tree.command(name="unlock", description="Allow @everyone to send messages in a text channel.")
@app_commands.default_permissions(manage_channels=True)
@app_commands.describe(channel="Channel to unlock; defaults to this channel")
async def unlock(interaction: discord.Interaction, channel: discord.TextChannel | None = None):
    await set_lock(interaction, False, channel)


@tree.command(name="nickname", description="Change or reset a member's server nickname.")
@app_commands.default_permissions(manage_nicknames=True)
@app_commands.describe(member="Member whose nickname to change", nickname="New nickname; leave empty to reset")
async def nickname(interaction: discord.Interaction, member: discord.Member, nickname: str | None = None):
    if not await require_permission(interaction, "manage_nicknames", "Manage Nicknames"):
        return
    if not hierarchy_ok(interaction, member):
        await interaction.response.send_message("❌ You cannot change that member's nickname because of role hierarchy.", ephemeral=True)
        return
    try:
        await member.edit(nick=nickname, reason=f"Nickname changed by {interaction.user} ({interaction.user.id})")
        label = f"set to **{nickname}**" if nickname else "reset to the username"
        await interaction.response.send_message(f"✅ Nickname for **{member}** {label}.", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("❌ I cannot change that nickname. Check Manage Nicknames permission and role position.", ephemeral=True)
    except discord.HTTPException:
        await interaction.response.send_message("❌ Discord could not change the nickname. Please try again later.", ephemeral=True)


@client.event
async def on_ready():
    global synced
    log.info("Discord connected as %s (ID: %s)", client.user, client.user.id)
    if synced:
        return
    try:
        await giveaways.restore_views()
        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))
            tree.copy_global_to(guild=guild)
            commands = await tree.sync(guild=guild)
            log.info("Synced %d command(s) to guild %s: %s", len(commands), GUILD_ID, ", ".join(command.name for command in commands))
        else:
            commands = await tree.sync()
            log.info("Synced %d global command(s).", len(commands))
        synced = True
    except discord.HTTPException as exc:
        log.exception("Slash-command sync failed with HTTP %s. Check Discord API access before retrying.", exc.status)
    except Exception:
        log.exception("Unexpected slash-command sync failure.")


async def main():
    delay = 120
    while True:
        try:
            await client.start(TOKEN, reconnect=True)
            return
        except discord.HTTPException as exc:
            if exc.status != 429:
                log.exception("Discord login failed with HTTP %s.", exc.status)
                raise
            log.warning("Discord login returned HTTP 429; waiting %s seconds before retry.", delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 900)
        except Exception:
            log.exception("Discord client stopped unexpectedly.")
            raise


if __name__ == "__main__":
    asyncio.run(main())
