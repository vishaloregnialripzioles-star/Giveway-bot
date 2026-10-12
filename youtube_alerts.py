import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks
from xml.etree import ElementTree as ET

DATA_FILE = Path("data") / "youtube_alerts.json"
CHECK_INTERVAL = 45
DEFAULT_COLOR = discord.Color.red()
YOUTUBE_FEED_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={}"


def ensure_data_folder() -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)


def default_guild_config() -> Dict[str, Any]:
    return {
        "enabled": True,
        "default_channel": None,
        "ping_role": None,
        "custom_message": "",
        "channels": {},
    }


def load_data() -> Dict[str, Any]:
    ensure_data_folder()
    if not DATA_FILE.exists():
        data = {"guilds": {}}
        save_data(data)
        return data

    try:
        with DATA_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {"guilds": {}}

    if not isinstance(data, dict):
        data = {"guilds": {}}

    data.setdefault("guilds", {})
    return data


def save_data(data: Dict[str, Any]) -> None:
    ensure_data_folder()
    temp = DATA_FILE.with_suffix(".json.tmp")
    with temp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    os.replace(temp, DATA_FILE)


DATA = load_data()


def guild_data(guild_id: int) -> Dict[str, Any]:
    gid = str(guild_id)
    if gid not in DATA["guilds"]:
        DATA["guilds"][gid] = default_guild_config()

    guild = DATA["guilds"][gid]
    guild.setdefault("enabled", True)
    guild.setdefault("default_channel", None)
    guild.setdefault("ping_role", None)
    guild.setdefault("custom_message", "")
    guild.setdefault("channels", {})
    return guild


def normalize_input(raw: str) -> str:
    value = (raw or "").strip()
    value = value.replace("<", "").replace(">", "")
    return value


def extract_channel_id(value: str) -> Optional[str]:
    """Extract channel ID from URL, @handle, or direct ID"""
    text = normalize_input(value)
    if not text:
        return None

    # Try to extract from URL format: youtube.com/channel/UCXXXX
    match = re.search(r"youtube\.com/channel/([A-Za-z0-9_-]{20,})", text)
    if match:
        return match.group(1)

    # Try direct UC format
    if re.match(r"^UC[A-Za-z0-9_-]{20,}$", text):
        return text

    return None


async def resolve_channel_handle(handle: str) -> Optional[str]:
    """
    Resolve YouTube @handle to channel ID using YouTube's channel page.
    This is a workaround since RSS doesn't resolve handles.
    """
    try:
        # Remove @ if present
        clean_handle = handle.lstrip("@")
        
        # Try the YouTube channel page
        url = f"https://www.youtube.com/{clean_handle}"
        
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; AirCommanderBot/1.0)"},
                allow_redirects=True
            ) as response:
                if response.status != 200:
                    return None
                
                text = await response.text()
                
                # Look for channel ID in the page HTML
                # Pattern: "externalId":"UCxxxxxx"
                match = re.search(r'"externalId":"(UC[A-Za-z0-9_-]{20,})"', text)
                if match:
                    return match.group(1)
                
                # Alternative pattern
                match = re.search(r'channel/([A-Za-z0-9_-]{20,})', text)
                if match:
                    return match.group(1)
                
                return None
    except Exception:
        return None


def make_embed(title: str, description: str = "", color: discord.Colour = DEFAULT_COLOR):
    embed = discord.Embed(title=title, description=description, color=color, timestamp=discord.utils.utcnow())
    embed.set_footer(text="Air Commander • YouTube Alerts")
    return embed


def youtube_url(video_id: str, kind: str = "video") -> str:
    if kind == "short":
        return f"https://www.youtube.com/shorts/{video_id}"
    return f"https://www.youtube.com/watch?v={video_id}"


def detect_kind(title: str, description: str) -> str:
    text = f"{title} {description}".lower()
    if "#short" in text or "shorts" in text:
        return "short"
    if "live" in text and "stream" in text:
        return "live"
    return "video"


def parse_rss(xml_text: str) -> List[Dict[str, str]]:
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return []

    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "yt": "http://www.youtube.com/xml/schemas/2015",
        "media": "http://search.yahoo.com/mrss/",
    }

    videos: List[Dict[str, str]] = []
    for entry in root.findall("atom:entry", ns):
        video_id = entry.findtext("yt:videoId", default="", namespaces=ns)
        title = entry.findtext("atom:title", default="YouTube Upload", namespaces=ns)
        author = entry.findtext("atom:author/atom:name", default="YouTube Channel", namespaces=ns)
        description = ""
        media_group = entry.find("media:group", ns)
        if media_group is not None:
            description = media_group.findtext("media:description", default="", namespaces=ns)

        if not video_id:
            continue

        videos.append(
            {
                "video_id": video_id,
                "title": title,
                "description": description,
                "author": author,
            }
        )

    return videos


async def fetch_rss(channel_id: str) -> Optional[str]:
    url = YOUTUBE_FEED_URL.format(channel_id)
    timeout = aiohttp.ClientTimeout(total=20)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers={"User-Agent": "Mozilla/5.0 AirCommander/1.0"}) as response:
                if response.status != 200:
                    return None
                return await response.text()
    except Exception:
        return None


async def get_channel_name(channel_id: str) -> str:
    rss = await fetch_rss(channel_id)
    if not rss:
        return "YouTube Channel"
    videos = parse_rss(rss)
    if not videos:
        return "YouTube Channel"
    return videos[0].get("author") or "YouTube Channel"


class YouTubeWatchView(discord.ui.View):
    def __init__(self, url: str):
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                label="Watch on YouTube",
                emoji="▶️",
                style=discord.ButtonStyle.link,
                url=url,
            )
        )


async def build_alert_embed(video: Dict[str, str], author: str, custom_message: str = "") -> discord.Embed:
    kind = detect_kind(video.get("title", ""), video.get("description", ""))
    url = youtube_url(video["video_id"], kind)
    description = (video.get("description") or "").strip()

    if kind == "short":
        label = "🎬 NEW SHORT"
        color = discord.Color.orange()
    elif kind == "live":
        label = "🔴 LIVE NOW"
        color = discord.Color.dark_red()
    else:
        label = "🔴 NEW YOUTUBE UPLOAD"
        color = discord.Color.red()

    embed = make_embed(label, color=color)
    embed.add_field(name="🎥 Video", value=f"**{video.get('title', 'Untitled video')}**", inline=False)
    embed.add_field(name="📺 Channel", value=author, inline=True)
    embed.add_field(name="🔗 Watch", value=f"[Open on YouTube]({url})", inline=True)

    if description:
        short_desc = description[:500] + ("..." if len(description) > 500 else "")
        embed.add_field(name="📝 Description", value=short_desc, inline=False)

    embed.set_thumbnail(url=f"https://i.ytimg.com/vi/{video['video_id']}/hqdefault.jpg")

    if custom_message:
        embed.add_field(name="📣 Message", value=custom_message[:1024], inline=False)

    return embed


async def send_alert(bot: commands.Bot, guild: discord.Guild, guild_cfg: Dict[str, Any], tracked: Dict[str, Any], video: Dict[str, str]) -> bool:
    target_channel_id = tracked.get("discord_channel_id") or guild_cfg.get("default_channel")
    target = guild.get_channel(int(target_channel_id)) if target_channel_id else None
    if target is None and guild_cfg.get("default_channel"):
        target = guild.get_channel(int(guild_cfg["default_channel"]))
    if target is None:
        return False

    ping_role_id = tracked.get("ping_role_id") or guild_cfg.get("ping_role")
    ping_content = None
    if ping_role_id:
        role = guild.get_role(int(ping_role_id))
        if role:
            ping_content = role.mention

    author = tracked.get("name") or video.get("author") or "YouTube Channel"
    custom_message = (guild_cfg.get("custom_message") or "").strip()
    embed = await build_alert_embed(video, author, custom_message)
    kind = detect_kind(video.get("title", ""), video.get("description", ""))
    url = youtube_url(video["video_id"], kind)

    allowed_mentions = discord.AllowedMentions(everyone=False, users=False, roles=True, replied_user=False)

    try:
        await target.send(
            content=ping_content,
            embed=embed,
            allowed_mentions=allowed_mentions,
            view=YouTubeWatchView(url),
        )
        return True
    except Exception:
        return False


class YouTubeAlerts(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.youtube_loop.start()

    def cog_unload(self):
        self.youtube_loop.cancel()

    @tasks.loop(seconds=CHECK_INTERVAL)
    async def youtube_loop(self):
        if not self.bot.is_ready():
            return

        for guild_id, guild_cfg in list(DATA.get("guilds", {}).items()):
            if not guild_cfg.get("enabled", True):
                continue

            guild = self.bot.get_guild(int(guild_id))
            if guild is None:
                continue

            channels = guild_cfg.get("channels", {})
            if not channels:
                continue

            for yt_id, tracked in list(channels.items()):
                try:
                    rss = await fetch_rss(yt_id)
                    if not rss:
                        continue

                    videos = parse_rss(rss)
                    if not videos:
                        continue

                    latest_id = videos[0]["video_id"]
                    old_id = tracked.get("last_video_id")

                    if not old_id:
                        tracked["last_video_id"] = latest_id
                        tracked["name"] = tracked.get("name") or await get_channel_name(yt_id)
                        save_data(DATA)
                        continue

                    if latest_id == old_id:
                        continue

                    new_videos = []
                    for video in reversed(videos):
                        if video["video_id"] == old_id:
                            break
                        new_videos.append(video)

                    for video in new_videos:
                        await send_alert(self.bot, guild, guild_cfg, tracked, video)

                    tracked["last_video_id"] = latest_id
                    tracked["name"] = tracked.get("name") or await get_channel_name(yt_id)
                    save_data(DATA)

                except Exception:
                    continue

    @youtube_loop.before_loop
    async def before_youtube_loop(self):
        await self.bot.wait_until_ready()


# ---------------------------
# Prefix commands
# ---------------------------

def setup_prefix_commands(bot: commands.Bot):
    @bot.group(name="youtube", invoke_without_command=True)
    @commands.guild_only()
    async def youtube(ctx):
        embed = make_embed(
            "📺 YouTube Alerts",
            "**Available commands:**\n\n"
            "`,youtube setup` - Set alert channel\n"
            "`,youtube add <URL/ID/@name>` - Add channel\n"
            "`,youtube remove <ID>` - Remove channel\n"
            "`,youtube list` - List tracked channels\n"
            "`,youtube config` - Show configuration\n"
            "`,youtube enable` - Enable alerts\n"
            "`,youtube disable` - Disable alerts\n"
            "`,youtube test` - Send test alert\n"
            "`,youtube role set @Role` - Set ping role\n"
            "`,youtube role remove` - Remove ping role\n"
            "`,youtube channel set #channel` - Set alert channel\n"
            "`,youtube channel clear` - Clear alert channel\n"
            "`,youtube message <text>` - Set custom message",
        )
        await ctx.send(embed=embed)

    @youtube.command(name="setup")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def youtube_setup(ctx):
        cfg = guild_data(ctx.guild.id)
        cfg["default_channel"] = ctx.channel.id
        save_data(DATA)
        await ctx.send(embed=make_embed("✅ YouTube Alerts Setup", f"Alerts will be sent in {ctx.channel.mention}.", discord.Color.green()))

    @youtube.command(name="add")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def youtube_add(ctx, *, channel: str = None):
        if not channel:
            await ctx.send("❌ Usage: `,youtube add <URL/ID/@name>`\n\nExamples:\n• `https://www.youtube.com/channel/UC...`\n• `UC...` (Channel ID)\n• `@channelname` (Channel handle)")
            return

        channel = normalize_input(channel)
        
        # Try to extract channel ID directly
        channel_id = extract_channel_id(channel)
        
        # If not a direct ID/URL, try to resolve as handle
        if not channel_id:
            await ctx.send("🔄 Resolving channel name... (This may take a moment)")
            channel_id = await resolve_channel_handle(channel)
            
            if not channel_id:
                await ctx.send(
                    "❌ Couldn't find that YouTube channel.\n\n"
                    "Please use one of these formats:\n"
                    "• Full URL: `https://www.youtube.com/channel/UC...`\n"
                    "• Channel ID: `UC...`\n"
                    "• Handle: `@channelname`"
                )
                return

        # Verify channel works with RSS
        rss = await fetch_rss(channel_id)
        if not rss:
            await ctx.send("❌ Couldn't access that YouTube channel's RSS feed.\n\nMake sure it's a valid YouTube channel.")
            return

        videos = parse_rss(rss)
        if not videos:
            await ctx.send("❌ No videos found for this channel.")
            return

        cfg = guild_data(ctx.guild.id)
        if channel_id in cfg["channels"]:
            await ctx.send("⚠️ This channel is already being tracked.")
            return

        channel_name = videos[0].get("author") or await get_channel_name(channel_id)
        cfg["channels"][channel_id] = {
            "name": channel_name,
            "channel_id": channel_id,
            "discord_channel_id": cfg.get("default_channel") or ctx.channel.id,
            "ping_role_id": cfg.get("ping_role"),
            "last_video_id": None,
        }
        save_data(DATA)

        await ctx.send(
            embed=make_embed(
                "✅ YouTube Channel Added",
                f"**Channel:** {channel_name}\n**ID:** `{channel_id}`\n**Alert Channel:** <#{cfg['channels'][channel_id]['discord_channel_id']}>\n\n✨ Latest video initialized. Next upload will be alerted.",
                discord.Color.green(),
            )
        )

    @youtube.command(name="remove")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def youtube_remove(ctx, *, channel_id: str = None):
        if not channel_id:
            await ctx.send("❌ Usage: `,youtube remove <channel-id>`")
            return

        clean = extract_channel_id(channel_id) or channel_id
        cfg = guild_data(ctx.guild.id)
        if clean not in cfg["channels"]:
            await ctx.send("❌ That channel is not being tracked.")
            return

        removed = cfg["channels"].pop(clean)
        save_data(DATA)
        await ctx.send(embed=make_embed("🗑️ YouTube Channel Removed", f"Removed **{removed.get('name', clean)}**.", discord.Color.orange()))

    @youtube.command(name="list")
    @commands.guild_only()
    async def youtube_list(ctx):
        cfg = guild_data(ctx.guild.id)
        channels = cfg.get("channels", {})
        if not channels:
            await ctx.send(embed=make_embed("📺 YouTube Channels", "No channels are being tracked."))
            return

        lines = []
        for yt_id, info in channels.items():
            line = f"**{info.get('name', 'Unknown')}**\n🆔 `{yt_id}`\n"
            if info.get("discord_channel_id"):
                line += f"📢 <#{info['discord_channel_id']}>\n"
            if info.get("ping_role_id"):
                line += f"🔔 <@&{info['ping_role_id']}>\n"
            lines.append(line)

        await ctx.send(embed=make_embed("📺 Tracked YouTube Channels", "\n".join(lines)))

    @youtube.command(name="config")
    @commands.guild_only()
    async def youtube_config(ctx):
        cfg = guild_data(ctx.guild.id)
        embed = make_embed(
            "⚙️ YouTube Alerts Configuration",
            f"**Status:** {'🟢 Enabled' if cfg.get('enabled', True) else '🔴 Disabled'}\n"
            f"**Tracked Channels:** {len(cfg.get('channels', {}))}\n"
            f"**Alert Channel:** {f'<#{cfg.get("default_channel")}>' if cfg.get('default_channel') else 'Not set'}\n"
            f"**Ping Role:** {f'<@&{cfg.get("ping_role")}>' if cfg.get('ping_role') else 'Not set'}\n"
            f"**Check Interval:** `{CHECK_INTERVAL}s`",
        )
        await ctx.send(embed=embed)

    @youtube.command(name="enable")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def youtube_enable(ctx):
        cfg = guild_data(ctx.guild.id)
        cfg["enabled"] = True
        save_data(DATA)
        await ctx.send(embed=make_embed("🟢 YouTube Alerts Enabled", "YouTube notifications are now enabled.", discord.Color.green()))

    @youtube.command(name="disable")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def youtube_disable(ctx):
        cfg = guild_data(ctx.guild.id)
        cfg["enabled"] = False
        save_data(DATA)
        await ctx.send(embed=make_embed("🔴 YouTube Alerts Disabled", "YouTube notifications are now disabled.", discord.Color.red()))

    @youtube.command(name="test")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def youtube_test(ctx):
        cfg = guild_data(ctx.guild.id)
        ping_content = None
        if cfg.get("ping_role"):
            role = ctx.guild.get_role(int(cfg["ping_role"]))
            if role:
                ping_content = role.mention

        embed = make_embed("🔴 NEW YOUTUBE UPLOAD", "**Test Video**\n\nThis is a test notification from Air Commander.\n\n🔗 [Watch on YouTube](https://www.youtube.com/)", discord.Color.red())
        embed.set_thumbnail(url="https://www.youtube.com/img/desktop/yt_1200.png")
        await ctx.send(
            content=ping_content,
            embed=embed,
            allowed_mentions=discord.AllowedMentions(everyone=False, users=False, roles=True),
            view=YouTubeWatchView("https://www.youtube.com/"),
        )

    @youtube.command(name="role")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def youtube_role(ctx, action: str = None, role: discord.Role = None):
        cfg = guild_data(ctx.guild.id)

        if action == "set":
            if role is None:
                await ctx.send("❌ Usage: `,youtube role set @Role`")
                return

            cfg["ping_role"] = role.id
            for info in cfg["channels"].values():
                if not info.get("ping_role_id"):
                    info["ping_role_id"] = role.id
            save_data(DATA)
            await ctx.send(embed=make_embed("🔔 YouTube Ping Role Set", f"Every new alert will ping {role.mention}.", discord.Color.green()))
            return

        if action == "remove":
            cfg["ping_role"] = None
            save_data(DATA)
            await ctx.send(embed=make_embed("🔕 YouTube Ping Role Removed", "New alerts will no longer use a default ping role.", discord.Color.orange()))
            return

        await ctx.send("❌ Use `,youtube role set @Role` or `,youtube role remove`.")

    @youtube.command(name="channel")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def youtube_channel(ctx, action: str = None, channel: discord.TextChannel = None):
        cfg = guild_data(ctx.guild.id)

        if action == "set":
            if channel is None:
                await ctx.send("❌ Usage: `,youtube channel set #alerts`")
                return
            cfg["default_channel"] = channel.id
            for info in cfg["channels"].values():
                if not info.get("discord_channel_id"):
                    info["discord_channel_id"] = channel.id
            save_data(DATA)
            await ctx.send(embed=make_embed("📢 Alert Channel Updated", f"All new YouTube alerts will go to {channel.mention}.", discord.Color.blue()))
            return

        if action == "clear":
            cfg["default_channel"] = None
            for info in cfg["channels"].values():
                info["discord_channel_id"] = None
            save_data(DATA)
            await ctx.send(embed=make_embed("📢 Alert Channel Cleared", "This guild will no longer have a default YouTube alert channel.", discord.Color.orange()))
            return

        await ctx.send("❌ Use `,youtube channel set #alerts` or `,youtube channel clear`.")

    @youtube.command(name="message")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def youtube_message(ctx, *, text: str = None):
        cfg = guild_data(ctx.guild.id)
        if text is None:
            cfg["custom_message"] = ""
            save_data(DATA)
            await ctx.send(embed=make_embed("📝 Custom Message Cleared", "YouTube alerts will now be sent without a custom message.", discord.Color.orange()))
            return

        cfg["custom_message"] = text[:1000]
        save_data(DATA)
        await ctx.send(embed=make_embed("📝 Custom Message Saved", f"New alerts will include this message:\n\n{cfg['custom_message'][:500]}", discord.Color.green()))


# ---------------------------
# Slash commands
# ---------------------------

def setup_slash_commands(bot: commands.Bot):
    tree = bot.tree
    existing = tree.get_command("youtube")
    if existing is not None:
        return

    youtube = app_commands.Group(name="youtube", description="YouTube alert controls")

    @youtube.command(name="setup", description="Set this channel as the default alert channel")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def slash_setup(interaction: discord.Interaction):
        cfg = guild_data(interaction.guild.id)
        cfg["default_channel"] = interaction.channel.id
        save_data(DATA)
        await interaction.response.send_message(
            embed=make_embed("✅ YouTube Alerts Setup", f"Alerts will be sent in {interaction.channel.mention}.", discord.Color.green()),
            ephemeral=True,
        )

    @youtube.command(name="add", description="Track a YouTube channel by URL, ID, or @handle")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def slash_add(interaction: discord.Interaction, channel: str):
        channel = normalize_input(channel)
        
        # Try to extract channel ID directly
        channel_id = extract_channel_id(channel)
        
        # If not a direct ID/URL, try to resolve as handle
        if not channel_id:
            await interaction.response.defer(ephemeral=True)
            await interaction.followup.send("🔄 Resolving channel name... (This may take a moment)", ephemeral=True)
            channel_id = await resolve_channel_handle(channel)
            
            if not channel_id:
                await interaction.followup.send(
                    "❌ Couldn't find that YouTube channel.\n\n"
                    "Please use one of these formats:\n"
                    "• Full URL: `https://www.youtube.com/channel/UC...`\n"
                    "• Channel ID: `UC...`\n"
                    "• Handle: `@channelname`",
                    ephemeral=True
                )
                return
        else:
            await interaction.response.defer(ephemeral=True)

        rss = await fetch_rss(channel_id)
        if not rss:
            await interaction.followup.send("❌ Couldn't access that YouTube channel's RSS feed.", ephemeral=True)
            return

        videos = parse_rss(rss)
        if not videos:
            await interaction.followup.send("❌ No videos found for this channel.", ephemeral=True)
            return

        cfg = guild_data(interaction.guild.id)
        if channel_id in cfg["channels"]:
            await interaction.followup.send("⚠️ This channel is already being tracked.", ephemeral=True)
            return

        channel_name = videos[0].get("author") or await get_channel_name(channel_id)
        cfg["channels"][channel_id] = {
            "name": channel_name,
            "channel_id": channel_id,
            "discord_channel_id": cfg.get("default_channel") or interaction.channel.id,
            "ping_role_id": cfg.get("ping_role"),
            "last_video_id": None,
        }
        save_data(DATA)

        await interaction.followup.send(
            embed=make_embed(
                "✅ YouTube Channel Added",
                f"**Channel:** {channel_name}\n**ID:** `{channel_id}`\n\n✨ Latest video initialized. Next upload will be alerted.",
                discord.Color.green(),
            ),
            ephemeral=True,
        )

    @youtube.command(name="remove", description="Stop tracking a YouTube channel")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def slash_remove(interaction: discord.Interaction, channel_id: str):
        cfg = guild_data(interaction.guild.id)
        clean = extract_channel_id(channel_id) or channel_id
        if clean not in cfg["channels"]:
            await interaction.response.send_message("❌ That channel is not being tracked.", ephemeral=True)
            return

        removed = cfg["channels"].pop(clean)
        save_data(DATA)
        await interaction.response.send_message(
            embed=make_embed("🗑️ YouTube Channel Removed", f"Removed **{removed.get('name', clean)}**.", discord.Color.orange()),
            ephemeral=True,
        )

    @youtube.command(name="list", description="Show tracked YouTube channels")
    async def slash_list(interaction: discord.Interaction):
        cfg = guild_data(interaction.guild.id)
        channels = cfg.get("channels", {})
        if not channels:
            await interaction.response.send_message(
                embed=make_embed("📺 YouTube Channels", "No channels are being tracked."),
                ephemeral=True,
            )
            return

        lines = []
        for yt_id, info in channels.items():
            line = f"**{info.get('name', 'Unknown')}**\n🆔 `{yt_id}`\n📢 <#{info.get('discord_channel_id')}>\n"
            if info.get("ping_role_id"):
                line += f"🔔 <@&{info['ping_role_id']}>\n"
            lines.append(line)

        await interaction.response.send_message(
            embed=make_embed("📺 Tracked YouTube Channels", "\n".join(lines)),
            ephemeral=True,
        )

    @youtube.command(name="config", description="Show YouTube alert configuration")
    async def slash_config(interaction: discord.Interaction):
        cfg = guild_data(interaction.guild.id)
        embed = make_embed(
            "⚙️ YouTube Alerts Configuration",
            f"**Status:** {'🟢 Enabled' if cfg.get('enabled', True) else '🔴 Disabled'}\n"
            f"**Tracked:** {len(cfg.get('channels', {}))}\n"
            f"**Alert Channel:** {f'<#{cfg.get("default_channel")}>' if cfg.get('default_channel') else 'Not set'}\n"
            f"**Ping Role:** {f'<@&{cfg.get("ping_role")}>' if cfg.get('ping_role') else 'Not set'}\n"
            f"**Check Interval:** `{CHECK_INTERVAL}s`",
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @youtube.command(name="enable", description="Enable YouTube alerts")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def slash_enable(interaction: discord.Interaction):
        cfg = guild_data(interaction.guild.id)
        cfg["enabled"] = True
        save_data(DATA)
        await interaction.response.send_message("🟢 YouTube Alerts enabled.", ephemeral=True)

    @youtube.command(name="disable", description="Disable YouTube alerts")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def slash_disable(interaction: discord.Interaction):
        cfg = guild_data(interaction.guild.id)
        cfg["enabled"] = False
        save_data(DATA)
        await interaction.response.send_message("🔴 YouTube Alerts disabled.", ephemeral=True)

    @youtube.command(name="test", description="Send a test YouTube alert")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def slash_test(interaction: discord.Interaction):
        cfg = guild_data(interaction.guild.id)
        ping_content = None
        if cfg.get("ping_role"):
            role = interaction.guild.get_role(int(cfg["ping_role"]))
            if role:
                ping_content = role.mention

        embed = make_embed("🔴 NEW YOUTUBE UPLOAD", "**Test Video**\n\nThis is a test notification from Air Commander.", discord.Color.red())
        await interaction.response.send_message(
            content=ping_content,
            embed=embed,
            allowed_mentions=discord.AllowedMentions(everyone=False, users=False, roles=True),
            view=YouTubeWatchView("https://www.youtube.com/"),
        )

    role_group = app_commands.Group(name="role", description="Manage YouTube ping role")

    @role_group.command(name="set", description="Set the default ping role")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def role_set(interaction: discord.Interaction, role: discord.Role):
        cfg = guild_data(interaction.guild.id)
        cfg["ping_role"] = role.id
        for info in cfg["channels"].values():
            if not info.get("ping_role_id"):
                info["ping_role_id"] = role.id
        save_data(DATA)
        await interaction.response.send_message(
            embed=make_embed("🔔 YouTube Ping Role Set", f"Alerts will ping {role.mention}.", discord.Color.green()),
            ephemeral=True,
        )

    @role_group.command(name="remove", description="Remove the default ping role")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def role_remove(interaction: discord.Interaction):
        cfg = guild_data(interaction.guild.id)
        cfg["ping_role"] = None
        save_data(DATA)
        await interaction.response.send_message("🔕 YouTube ping role removed.", ephemeral=True)

    channel_group = app_commands.Group(name="channel", description="Set default alert channel")

    @channel_group.command(name="set", description="Set default channel for YouTube alerts")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def channel_set(interaction: discord.Interaction, channel: discord.TextChannel):
        cfg = guild_data(interaction.guild.id)
        cfg["default_channel"] = channel.id
        for info in cfg["channels"].values():
            if not info.get("discord_channel_id"):
                info["discord_channel_id"] = channel.id
        save_data(DATA)
        await interaction.response.send_message(
            embed=make_embed("📢 Alert Channel Updated", f"All new YouTube alerts will go to {channel.mention}.", discord.Color.blue()),
            ephemeral=True,
        )

    @channel_group.command(name="clear", description="Clear the default alert channel")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def channel_clear(interaction: discord.Interaction):
        cfg = guild_data(interaction.guild.id)
        cfg["default_channel"] = None
        for info in cfg["channels"].values():
            info["discord_channel_id"] = None
        save_data(DATA)
        await interaction.response.send_message(
            embed=make_embed("📢 Alert Channel Cleared", "This guild will no longer have a default YouTube alert channel.", discord.Color.orange()),
            ephemeral=True,
        )

    message_group = app_commands.Group(name="message", description="Manage custom alert message")

    @message_group.command(name="set", description="Set a custom message added to each YouTube alert")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def message_set(interaction: discord.Interaction, text: str):
        cfg = guild_data(interaction.guild.id)
        cfg["custom_message"] = text[:1000]
        save_data(DATA)
        await interaction.response.send_message(
            embed=make_embed("📝 Custom Message Saved", f"New alerts will include this message:\n\n{cfg['custom_message'][:500]}", discord.Color.green()),
            ephemeral=True,
        )

    @message_group.command(name="clear", description="Clear the custom alert message")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def message_clear(interaction: discord.Interaction):
        cfg = guild_data(interaction.guild.id)
        cfg["custom_message"] = ""
        save_data(DATA)
        await interaction.response.send_message(
            embed=make_embed("📝 Custom Message Cleared", "YouTube alerts will now be sent without a custom message.", discord.Color.orange()),
            ephemeral=True,
        )

    youtube.add_command(role_group)
    youtube.add_command(channel_group)
    youtube.add_command(message_group)
    tree.add_command(youtube)


# ---------------------------
# Setup
# ---------------------------

def setup(bot: commands.Bot):
    if getattr(bot, "_air_youtube_alerts_loaded", False):
        return

    bot._air_youtube_alerts_loaded = True
    cog = YouTubeAlerts(bot)

    async def add_cog():
        await bot.add_cog(cog)

    bot.loop.create_task(add_cog())
    setup_prefix_commands(bot)
    setup_slash_commands(bot)

    print("📺 YouTube Alerts system initialized (RSS + advanced alert controls).")
