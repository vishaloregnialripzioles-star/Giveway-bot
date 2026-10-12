# ============================================================
# AIR COMMANDER - AUTOMATION
# AutoMode / Silent Protect + Anti-Nuke
# ============================================================

import os
import json
import time
import re
import copy
import asyncio

from pathlib import Path
from collections import defaultdict, deque
from datetime import timedelta

import discord
from discord.ext import commands
from discord import app_commands


# ============================================================
# FILES
# ============================================================

AUTOMODE_CONFIG_FILE = "automode_config.json"
ANTINUKE_CONFIG_FILE = "antinuke_config.json"
ANTILINK_CONFIG_FILE = "antilink_config.json"


# ============================================================
# DEFAULT AUTOMODE CONFIG
# ============================================================

AUTOMODE_DEFAULT = {
    "enabled": False,
    "log_channel_id": None,

    "spam_messages": 5,
    "spam_window": 7,

    "warn_enabled": True,
    "warn_after": 3,

    "timeout_enabled": True,
    "timeout_after": 5,
    "timeout_minutes": 10,

    "link_protection": True,

    "mention_protection": True,
    "mention_limit": 5,

    "duplicate_protection": True,
    "duplicate_limit": 3,

    "badword_protection": True,
    "badwords": [],

    "whitelist_users": [],
    "whitelist_roles": [],

    "warnings": {}
}


# ============================================================
# DEFAULT ANTINUKE CONFIG
# ============================================================

# ============================================================
# DEFAULT ANTI-LINK CONFIG
# ============================================================

ANTILINK_DEFAULT = {
    "enabled": False,
    "log_channel_id": None,
    "warning_enabled": True,
    "dm_enabled": True,
    "delete_enabled": True,
    "types": {
        "gif": True,
        "youtube": False,
        "discord": False,
        "website": False,
        "image": False,
        "other": False
    },
    "whitelist_users": {
        "gif": [],
        "youtube": [],
        "discord": [],
        "website": [],
        "image": [],
        "other": []
    },
    "whitelist_roles": {
        "gif": [],
        "youtube": [],
        "discord": [],
        "website": [],
        "image": [],
        "other": []
    },
    "warnings": {}
}


ANTINUKE_DEFAULT = {
    "enabled": False,

    "action": "ban",

    "log_channel_id": None,

    "whitelist_users": [],
    "whitelist_roles": [],

    "window": 10,

    "thresholds": {
        "ban": 3,
        "kick": 3,
        "channel_delete": 3,
        "channel_create": 5,
        "role_delete": 3,
        "role_create": 5,
        "webhook_delete": 3,
        "bot_add": 2,
        "guild_update": 2,
        "emoji_delete": 3,
        "emoji_create": 5,
        "sticker_delete": 3,
        "sticker_create": 5,
        "overwrite_update": 3
    },

    "modules": {
        "ban": True,
        "kick": True,
        "channel_delete": True,
        "channel_create": True,
        "role_delete": True,
        "role_create": True,
        "webhook_delete": True,
        "bot_add": True,
        "guild_update": True,
        "emoji_delete": True,
        "emoji_create": True,
        "sticker_delete": True,
        "sticker_create": True,
        "overwrite_update": True
    }
}


# ============================================================
# GENERIC JSON HELPERS
# ============================================================

def load_json_file(filename, default):
    path = Path(filename)

    try:
        if not path.exists():
            path.write_text(
                json.dumps(default, indent=4),
                encoding="utf-8"
            )
            return copy.deepcopy(default)

        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            return copy.deepcopy(default)

        return data

    except Exception as e:
        print(f"⚠️ Failed loading {filename}: {e}")
        return copy.deepcopy(default)


def save_json_file(filename, data):
    path = Path(filename)

    try:
        path.write_text(
            json.dumps(data, indent=4),
            encoding="utf-8"
        )
        return True
    except Exception as e:
        print(f"❌ Failed saving {filename}: {e}")
        return False


# ============================================================
# AUTOMODE STORAGE
# ============================================================

AUTOMODE_CONFIGS = load_json_file(
    AUTOMODE_CONFIG_FILE,
    {}
)


def automode_save_all():
    return save_json_file(
        AUTOMODE_CONFIG_FILE,
        AUTOMODE_CONFIGS
    )


def get_automode_config(guild_id):
    gid = str(guild_id)

    if gid not in AUTOMODE_CONFIGS:
        AUTOMODE_CONFIGS[gid] = copy.deepcopy(AUTOMODE_DEFAULT)
        automode_save_all()

    config = AUTOMODE_CONFIGS[gid]

    # Keep old config files compatible
    for key, value in AUTOMODE_DEFAULT.items():
        if key not in config:
            config[key] = copy.deepcopy(value)

    return config


# ============================================================
# ANTI-LINK STORAGE
# ============================================================

ANTILINK_CONFIGS = load_json_file(
    ANTILINK_CONFIG_FILE,
    {}
)


def antilink_save_all():
    return save_json_file(
        ANTILINK_CONFIG_FILE,
        ANTILINK_CONFIGS
    )


def get_antilink_config(guild_id):
    gid = str(guild_id)

    if gid not in ANTILINK_CONFIGS:
        ANTILINK_CONFIGS[gid] = copy.deepcopy(ANTILINK_DEFAULT)
        antilink_save_all()

    config = ANTILINK_CONFIGS[gid]

    for key, value in ANTILINK_DEFAULT.items():
        if key not in config:
            config[key] = copy.deepcopy(value)

    config.setdefault("types", {})
    for key, value in ANTILINK_DEFAULT["types"].items():
        config["types"].setdefault(key, value)

    config.setdefault("whitelist_users", {})
    config.setdefault("whitelist_roles", {})
    for link_type in ANTILINK_DEFAULT["types"]:
        config["whitelist_users"].setdefault(link_type, [])
        config["whitelist_roles"].setdefault(link_type, [])

    config.setdefault("warnings", {})
    return config


# ============================================================
# ANTINUKE STORAGE
# ============================================================

ANTINUKE_CONFIGS = load_json_file(
    ANTINUKE_CONFIG_FILE,
    {}
)


def antinuke_save_all():
    return save_json_file(
        ANTINUKE_CONFIG_FILE,
        ANTINUKE_CONFIGS
    )


def get_antinuke_config(guild_id):
    gid = str(guild_id)

    if gid not in ANTINUKE_CONFIGS:
        ANTINUKE_CONFIGS[gid] = copy.deepcopy(
            ANTINUKE_DEFAULT
        )
        antinuke_save_all()

    config = ANTINUKE_CONFIGS[gid]

    for key, value in ANTINUKE_DEFAULT.items():
        if key not in config:
            config[key] = copy.deepcopy(value)

    for key, value in ANTINUKE_DEFAULT["thresholds"].items():
        config.setdefault("thresholds", {})
        config["thresholds"].setdefault(
            key,
            value
        )

    for key, value in ANTINUKE_DEFAULT["modules"].items():
        config.setdefault("modules", {})
        config["modules"].setdefault(
            key,
            value
        )

    return config


# ============================================================
# AUTOMODE HELPERS
# ============================================================

def automode_is_whitelisted(member, config):
    if member is None:
        return False

    if member.id in config.get(
        "whitelist_users",
        []
    ):
        return True

    role_ids = {
        role.id
        for role in getattr(member, "roles", [])
    }

    return bool(
        role_ids.intersection(
            set(
                config.get(
                    "whitelist_roles",
                    []
                )
            )
        )
    )


def contains_link(content):
    if not content:
        return False

    pattern = (
        r"(https?://\S+)"
        r"|www\.\S+"
        r"|discord\.gg/\S+"
        r"|discord\.com/invite/\S+"
    )

    return bool(
        re.search(
            pattern,
            content,
            re.IGNORECASE
        )
    )


ANTILINK_TYPES = (
    "gif",
    "youtube",
    "discord",
    "website",
    "image",
    "other"
)

ANTILINK_TYPE_LABELS = {
    "gif": "🎞️ GIF",
    "youtube": "▶️ YouTube",
    "discord": "💬 Discord Invite",
    "website": "🌐 Website",
    "image": "🖼️ Image",
    "other": "🔗 Other Link"
}


def detect_link_type(content):
    if not content:
        return None

    urls = re.findall(
        r"(?:https?://|www\.)[^\s<>]+",
        content,
        re.IGNORECASE
    )

    if not urls:
        return None

    for raw in urls:
        url = raw.lower().rstrip(".,!?)]}>")

        if (
            "discord.gg/" in url
            or "discord.com/invite/" in url
            or "discordapp.com/invite/" in url
        ):
            return "discord"

        if (
            "youtube.com/" in url
            or "youtu.be/" in url
            or "music.youtube.com/" in url
        ):
            return "youtube"

        if (
            url.endswith(".gif")
            or "giphy.com/" in url
            or "tenor.com/" in url
            or "media.giphy.com/" in url
        ):
            return "gif"

        if re.search(
            r"\.(?:png|jpe?g|webp|bmp|svg)(?:[?#].*)?$",
            url,
            re.IGNORECASE
        ):
            return "image"

        if url.startswith("http://") or url.startswith("https://") or url.startswith("www."):
            return "website"

    return "other"


def antilink_is_whitelisted(member, config, link_type):
    if member is None or link_type not in ANTILINK_TYPES:
        return False

    if member.id == getattr(member.guild, "owner_id", None):
        return True

    user_ids = config.get("whitelist_users", {}).get(link_type, [])
    if member.id in user_ids:
        return True

    role_ids = {role.id for role in getattr(member, "roles", [])}
    allowed_roles = set(
        config.get("whitelist_roles", {}).get(link_type, [])
    )
    return bool(role_ids.intersection(allowed_roles))


def find_badword(content, badwords):
    if not content:
        return None

    lowered = content.lower()

    for word in badwords:
        if not word:
            continue

        if word.lower() in lowered:
            return word

    return None


def parse_word_list(value):
    if not value:
        return []

    return [
        x.strip()
        for x in value.split(",")
        if x.strip()
    ]


# ============================================================
# ANTINUKE HELPERS
# ============================================================

def status_text(value):
    return "🟢 ENABLED" if value else "🔴 DISABLED"


def action_text(action):
    mapping = {
        "ban": "🔨 Ban",
        "kick": "👢 Kick",
        "timeout": "⏱️ Timeout",
        "strip": "🧹 Strip Roles"
    }

    return mapping.get(
        action,
        action.title()
    )


def make_embed(
    title,
    description=None,
    color=discord.Color.blurple()
):
    embed = discord.Embed(
        title=title,
        description=description or "",
        color=color,
        timestamp=discord.utils.utcnow()
    )

    embed.set_footer(
        text="✈️ Air Commander • Automation"
    )

    return embed


async def public_send(
    interaction,
    *,
    content=None,
    embed=None,
    view=None,
    ephemeral=False
):
    try:
        if interaction.response.is_done():
            await interaction.followup.send(
                content=content,
                embed=embed,
                view=view,
                ephemeral=ephemeral
            )
        else:
            await interaction.response.send_message(
                content=content,
                embed=embed,
                view=view,
                ephemeral=ephemeral
            )
    except Exception as e:
        print(f"[Automation] Interaction send error: {e}")


def is_admin(member):
    return bool(
        member
        and hasattr(member, "guild_permissions")
        and member.guild_permissions.administrator
    )


def is_owner(member):
    if member is None:
        return False

    try:
        return member.guild.owner_id == member.id
    except Exception:
        return False


def antinuke_is_whitelisted(member, config):
    if member is None:
        return False

    if member.id == getattr(
        member.guild,
        "owner_id",
        None
    ):
        return True

    if member.id in config.get(
        "whitelist_users",
        []
    ):
        return True

    role_ids = {
        role.id
        for role in getattr(
            member,
            "roles",
            []
        )
    }

    return bool(
        role_ids.intersection(
            set(
                config.get(
                    "whitelist_roles",
                    []
                )
            )
        )
    )


# ============================================================
# AUTOMODE LOGGING
# ============================================================

class AutoMode(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        self.message_history = defaultdict(
            lambda: defaultdict(deque)
        )

        self.duplicate_history = defaultdict(
            lambda: defaultdict(deque)
        )

        self.mention_history = defaultdict(
            lambda: defaultdict(deque)
        )

    # ========================================================
    # AUTOMODE LOG CHANNEL
    # ========================================================

    async def get_log_channel(self, guild):
        config = get_automode_config(guild.id)

        channel_id = config.get(
            "log_channel_id"
        )

        if channel_id:
            channel = guild.get_channel(
                int(channel_id)
            )

            if channel:
                return channel

        return None

    async def send_log(
        self,
        guild,
        title,
        description,
        color=discord.Color.orange()
    ):
        channel = await self.get_log_channel(
            guild
        )

        if not channel:
            return

        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=discord.utils.utcnow()
        )

        embed.set_footer(
            text="✈️ Air Commander • AutoMode"
        )

        try:
            await channel.send(
                embed=embed
            )
        except Exception as e:
            print(
                f"[AutoMode] Log error: {e}"
            )

    async def send_dm(
        self,
        member,
        reason
    ):
        try:
            embed = discord.Embed(
                title="🛡️ AutoMode Action",
                description=(
                    f"An automated protection action "
                    f"was triggered in **{member.guild.name}**.\n\n"
                    f"**Reason:** {reason}"
                ),
                color=discord.Color.orange()
            )

            await member.send(
                embed=embed
            )

        except Exception:
            pass

    # ========================================================
    # AUTOMODE ENABLE / DISABLE
    # ========================================================

    async def enable_automode(self, guild):
        config = get_automode_config(
            guild.id
        )

        config["enabled"] = True

        # Create log channel automatically
        channel = guild.get_channel(
            config.get("log_channel_id")
        ) if config.get("log_channel_id") else None

        if channel is None:
            try:
                channel = await guild.create_text_channel(
                    "commander-logs",
                    reason="Air Commander AutoMode"
                )

                config["log_channel_id"] = channel.id

            except Exception as e:
                print(
                    f"[AutoMode] Could not create log channel: {e}"
                )

        automode_save_all()

        return config

    async def disable_automode(self, guild):
        config = get_automode_config(
            guild.id
        )

        config["enabled"] = False

        automode_save_all()

        return config

    # ========================================================
    # WARN
    # ========================================================

    async def warn_member(
        self,
        member,
        reason
    ):
        config = get_automode_config(
            member.guild.id
        )

        warnings = config.setdefault(
            "warnings",
            {}
        )

        user_id = str(member.id)

        warnings[user_id] = (
            warnings.get(user_id, 0) + 1
        )

        count = warnings[user_id]

        automode_save_all()

        try:
            await self.send_dm(
                member,
                reason
            )
        except Exception:
            pass

        await self.send_log(
            member.guild,
            "⚠️ AutoMode Warning",
            (
                f"**Member:** {member.mention}\n"
                f"**Reason:** {reason}\n"
                f"**Warnings:** `{count}`"
            ),
            discord.Color.yellow()
        )

        return count

    # ========================================================
    # TIMEOUT
    # ========================================================

    async def timeout_member(
        self,
        member,
        reason,
        minutes
    ):
        try:
            await member.timeout(
                timedelta(
                    minutes=minutes
                ),
                reason=reason
            )

            await self.send_dm(
                member,
                reason
            )

            await self.send_log(
                member.guild,
                "⏱️ AutoMode Timeout",
                (
                    f"**Member:** {member.mention}\n"
                    f"**Reason:** {reason}\n"
                    f"**Duration:** `{minutes} minutes`"
                ),
                discord.Color.red()
            )

            return True

        except Exception as e:
            print(
                f"[AutoMode] Timeout error: {e}"
            )
            return False

    # ========================================================
    # ESCALATION
    # ========================================================

    async def handle_escalation(
        self,
        member,
        reason
    ):
        config = get_automode_config(
            member.guild.id
        )

        count = await self.warn_member(
            member,
            reason
        )

        if (
            config.get("timeout_enabled", True)
            and count >= config.get(
                "timeout_after",
                5
            )
        ):
            await self.timeout_member(
                member,
                reason,
                config.get(
                    "timeout_minutes",
                    10
                )
            )

            # Reset after timeout
            config.setdefault(
                "warnings",
                {}
            )[str(member.id)] = 0

            automode_save_all()

    # ========================================================
    # ANTI-LINK
    # ========================================================

    async def get_antilink_log_channel(self, guild):
        config = get_antilink_config(guild.id)
        channel_id = config.get("log_channel_id")

        if channel_id:
            channel = guild.get_channel(int(channel_id))
            if channel:
                return channel

        return None

    async def ensure_antilink_log_channel(self, guild, config=None):
        config = config or get_antilink_config(guild.id)
        existing = await self.get_antilink_log_channel(guild)
        if existing:
            return existing

        try:
            channel = await guild.create_text_channel(
                "commander-antilink-logs",
                reason="Air Commander Anti-Link"
            )
            config["log_channel_id"] = channel.id
            antilink_save_all()
            return channel
        except Exception as e:
            print(f"[AntiLink] Could not create log channel: {e}")
            return None

    async def antilink_log(self, guild, member, channel, link_type, action, warning_count):
        config = get_antilink_config(guild.id)
        log_channel = await self.get_antilink_log_channel(guild)
        if not log_channel:
            return

        embed = discord.Embed(
            title="🔗 Anti-Link Detection",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="User", value=f"{member.mention} (`{member.id}`)", inline=False)
        embed.add_field(name="Type", value=ANTILINK_TYPE_LABELS.get(link_type, link_type), inline=True)
        embed.add_field(name="Channel", value=getattr(channel, "mention", "Unknown"), inline=True)
        embed.add_field(name="Action", value=action, inline=True)
        embed.add_field(name="Warning", value=f"+1 • Total `{warning_count}`", inline=True)
        embed.set_footer(text="✈️ Air Commander • Anti-Link")

        try:
            await log_channel.send(embed=embed)
        except Exception as e:
            print(f"[AntiLink] Log error: {e}")

    async def handle_antilink(self, message):
        if not message.guild:
            return False

        config = get_antilink_config(message.guild.id)
        if not config.get("enabled", False):
            return False

        member = message.author
        if is_admin(member):
            return True

        link_type = detect_link_type(message.content or "")
        if not link_type:
            return False

        # Anti-Link takes ownership of all links while enabled so that
        # AutoMode's older generic link protection cannot conflict with it.
        if (
            config.get("types", {}).get(link_type, False)
            or antilink_is_whitelisted(member, config, link_type)
        ):
            return True

        deleted = False
        if config.get("delete_enabled", True):
            try:
                await message.delete()
                deleted = True
            except Exception:
                pass

        warnings = config.setdefault("warnings", {})
        user_id = str(member.id)
        warnings[user_id] = warnings.get(user_id, 0) + 1
        warning_count = warnings[user_id]
        antilink_save_all()

        if config.get("warning_enabled", True):
            try:
                warning_embed = discord.Embed(
                    title="⚠️ Link Protection Warning",
                    description=(
                        f"{member.mention}\n\n"
                        f"You are not allowed to send **{ANTILINK_TYPE_LABELS.get(link_type, link_type)}** links in this server.\n\n"
                        f"Your message has been removed.\n"
                        f"Warning count: `{warning_count}`"
                    ),
                    color=discord.Color.orange()
                )
                await message.channel.send(embed=warning_embed)
            except Exception:
                pass

        if config.get("dm_enabled", True):
            try:
                dm_embed = discord.Embed(
                    title="🛡️ Air Commander • Anti-Link",
                    description=(
                        f"Your message was removed in **{message.guild.name}**.\n\n"
                        f"**Link Type:** {ANTILINK_TYPE_LABELS.get(link_type, link_type)}\n"
                        f"**Reason:** This link type is not allowed for you.\n"
                        f"**Warning count:** ⚠️ `{warning_count}`"
                    ),
                    color=discord.Color.red()
                )
                await member.send(embed=dm_embed)
            except Exception:
                pass

        action = "Message Deleted" if deleted else "Message Detected"
        await self.antilink_log(
            message.guild,
            member,
            message.channel,
            link_type,
            action,
            warning_count
        )
        return True

    # ========================================================
    # MESSAGE PROTECTION
    # ========================================================

    @commands.Cog.listener()
    async def on_message(self, message):

        if message.author.bot:
            return

        if not message.guild:
            return

        config = get_automode_config(
            message.guild.id
        )

        if not config.get(
            "enabled",
            False
        ):
            return

        member = message.author

        if automode_is_whitelisted(
            member,
            config
        ):
            return

        if is_admin(member):
            return

        content = (
            message.content or ""
        ).strip()

        # ----------------------------------------------------
        # BAD WORD
        # ----------------------------------------------------

        if config.get(
            "badword_protection",
            True
        ):
            badword = find_badword(
                content,
                config.get(
                    "badwords",
                    []
                )
            )

            if badword:
                try:
                    await message.delete()
                except Exception:
                    pass

                await self.handle_escalation(
                    member,
                    f"Bad word detected: `{badword}`"
                )

                return

        # ----------------------------------------------------
        # ANTI-LINK / LEGACY LINK PROTECTION
        # ----------------------------------------------------

        if contains_link(content):
            antilink_config = get_antilink_config(message.guild.id)

            if antilink_config.get("enabled", False):
                await self.handle_antilink(message)
                return

            if config.get("link_protection", True):
                try:
                    await message.delete()
                except Exception:
                    pass

                await self.handle_escalation(
                    member,
                    "Unauthorized link detected."
                )

                return

        # ----------------------------------------------------
        # MENTION PROTECTION
        # ----------------------------------------------------

        if config.get(
            "mention_protection",
            True
        ):
            mention_count = (
                len(message.mentions)
                + len(message.role_mentions)
            )

            limit = config.get(
                "mention_limit",
                5
            )

            if mention_count >= limit:

                try:
                    await message.delete()
                except Exception:
                    pass

                await self.handle_escalation(
                    member,
                    f"Mass mention detected ({mention_count} mentions)."
                )

                return

        # ----------------------------------------------------
        # DUPLICATE PROTECTION
        # ----------------------------------------------------

        if (
            config.get(
                "duplicate_protection",
                True
            )
            and content
        ):
            now = time.time()

            key = (
                message.guild.id,
                member.id
            )

            history = self.duplicate_history[
                message.guild.id
            ][member.id]

            history.append(
                (
                    now,
                    content.lower()
                )
            )

            while history and (
                now - history[0][0] > 10
            ):
                history.popleft()

            same_count = sum(
                1
                for _, msg in history
                if msg == content.lower()
            )

            limit = config.get(
                "duplicate_limit",
                3
            )

            if same_count >= limit:

                try:
                    await message.delete()
                except Exception:
                    pass

                await self.handle_escalation(
                    member,
                    "Duplicate message spam detected."
                )

                history.clear()

                return

        # ----------------------------------------------------
        # SPAM PROTECTION
        # ----------------------------------------------------

        now = time.time()

        history = self.message_history[
            message.guild.id
        ][member.id]

        history.append(now)

        window = config.get(
            "spam_window",
            7
        )

        while history and (
            now - history[0] > window
        ):
            history.popleft()

        spam_limit = config.get(
            "spam_messages",
            5
        )

        if len(history) >= spam_limit:

            try:
                await message.delete()
            except Exception:
                pass

            await self.handle_escalation(
                member,
                (
                    f"Message spam detected: "
                    f"{len(history)} messages "
                    f"in {window} seconds."
                )
            )

            history.clear()


# ============================================================
# AUTOMODE SLASH GROUP
# ============================================================

automode_group = app_commands.Group(
    name="automode",
    description="AutoMode / Silent Protect controls"
)


@automode_group.command(
    name="enable",
    description="Enable AutoMode"
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def automode_enable(
    interaction: discord.Interaction
):
    config = get_automode_config(
        interaction.guild.id
    )

    config["enabled"] = True

    automode_save_all()

    embed = make_embed(
        "🛡️ AutoMode Enabled",
        (
            "Air Commander AutoMode is now **enabled**.\n\n"
            "Protection systems are active."
        ),
        discord.Color.green()
    )

    await public_send(
        interaction,
        embed=embed
    )


@automode_group.command(
    name="disable",
    description="Disable AutoMode"
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def automode_disable(
    interaction: discord.Interaction
):
    config = get_automode_config(
        interaction.guild.id
    )

    config["enabled"] = False

    automode_save_all()

    embed = make_embed(
        "🛡️ AutoMode Disabled",
        "AutoMode protection has been disabled.",
        discord.Color.red()
    )

    await public_send(
        interaction,
        embed=embed
    )


@automode_group.command(
    name="status",
    description="View AutoMode status"
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def automode_status(
    interaction: discord.Interaction
):
    config = get_automode_config(
        interaction.guild.id
    )

    embed = make_embed(
        "🛡️ AutoMode Status"
    )

    embed.add_field(
        name="Status",
        value=status_text(
            config.get("enabled")
        ),
        inline=False
    )

    embed.add_field(
        name="Spam",
        value=(
            f"`{config.get('spam_messages')}` "
            f"messages / "
            f"`{config.get('spam_window')}` sec"
        ),
        inline=True
    )

    embed.add_field(
        name="Links",
        value=status_text(
            config.get("link_protection")
        ),
        inline=True
    )

    embed.add_field(
        name="Mentions",
        value=(
            f"{status_text(config.get('mention_protection'))}\n"
            f"Limit: `{config.get('mention_limit')}`"
        ),
        inline=True
    )

    embed.add_field(
        name="Duplicates",
        value=(
            f"{status_text(config.get('duplicate_protection'))}\n"
            f"Limit: `{config.get('duplicate_limit')}`"
        ),
        inline=True
    )

    embed.add_field(
        name="Bad Words",
        value=status_text(
            config.get("badword_protection")
        ),
        inline=True
    )

    embed.add_field(
        name="Timeout",
        value=(
            f"{status_text(config.get('timeout_enabled'))}\n"
            f"After `{config.get('timeout_after')}` warnings"
        ),
        inline=True
    )

    await public_send(
        interaction,
        embed=embed
    )


@automode_group.command(
    name="config",
    description="View AutoMode configuration"
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def automode_config(
    interaction: discord.Interaction
):
    config = get_automode_config(
        interaction.guild.id
    )

    embed = make_embed(
        "⚙️ AutoMode Configuration"
    )

    embed.add_field(
        name="Spam",
        value=(
            f"Messages: `{config['spam_messages']}`\n"
            f"Window: `{config['spam_window']}s`"
        ),
        inline=True
    )

    embed.add_field(
        name="Warning",
        value=(
            f"Enabled: {status_text(config['warn_enabled'])}\n"
            f"After: `{config['warn_after']}`"
        ),
        inline=True
    )

    embed.add_field(
        name="Timeout",
        value=(
            f"Enabled: {status_text(config['timeout_enabled'])}\n"
            f"After: `{config['timeout_after']}`\n"
            f"Duration: `{config['timeout_minutes']}m`"
        ),
        inline=True
    )

    embed.add_field(
        name="Protection",
        value=(
            f"Links: {status_text(config['link_protection'])}\n"
            f"Mentions: {status_text(config['mention_protection'])}\n"
            f"Duplicates: {status_text(config['duplicate_protection'])}\n"
            f"Bad Words: {status_text(config['badword_protection'])}"
        ),
        inline=False
    )

    await public_send(
        interaction,
        embed=embed
    )


# ============================================================
# AUTOMODE WHITELIST SLASH
# ============================================================

automode_whitelist_group = app_commands.Group(
    name="whitelist",
    description="Manage AutoMode whitelist",
    parent=automode_group
)


@automode_whitelist_group.command(
    name="user",
    description="Whitelist a user"
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def automode_whitelist_user(
    interaction: discord.Interaction,
    user: discord.Member
):
    config = get_automode_config(
        interaction.guild.id
    )

    if user.id not in config["whitelist_users"]:
        config["whitelist_users"].append(
            user.id
        )

    automode_save_all()

    await public_send(
        interaction,
        content=f"✅ {user.mention} added to AutoMode whitelist."
    )


@automode_whitelist_group.command(
    name="role",
    description="Whitelist a role"
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def automode_whitelist_role(
    interaction: discord.Interaction,
    role: discord.Role
):
    config = get_automode_config(
        interaction.guild.id
    )

    if role.id not in config["whitelist_roles"]:
        config["whitelist_roles"].append(
            role.id
        )

    automode_save_all()

    await public_send(
        interaction,
        content=f"✅ {role.mention} added to AutoMode whitelist."
    )


# ============================================================
# AUTOMODE BADWORD SLASH
# ============================================================

automode_badword_group = app_commands.Group(
    name="badword",
    description="Manage AutoMode bad words",
    parent=automode_group
)


@automode_badword_group.command(
    name="add",
    description="Add a bad word"
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def automode_badword_add(
    interaction: discord.Interaction,
    word: str
):
    config = get_automode_config(
        interaction.guild.id
    )

    word = word.strip()

    if not word:
        await public_send(
            interaction,
            content="❌ Word cannot be empty.",
            ephemeral=True
        )
        return

    if word.lower() not in [
        x.lower()
        for x in config["badwords"]
    ]:
        config["badwords"].append(word)

    automode_save_all()

    await public_send(
        interaction,
        content=f"✅ Added `{word}` to bad-word protection."
    )


@automode_badword_group.command(
    name="remove",
    description="Remove a bad word"
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def automode_badword_remove(
    interaction: discord.Interaction,
    word: str
):
    config = get_automode_config(
        interaction.guild.id
    )

    before = len(
        config["badwords"]
    )

    config["badwords"] = [
        x for x in config["badwords"]
        if x.lower() != word.lower()
    ]

    automode_save_all()

    if len(config["badwords"]) == before:
        await public_send(
            interaction,
            content=f"⚠️ `{word}` was not found.",
            ephemeral=True
        )
        return

    await public_send(
        interaction,
        content=f"✅ Removed `{word}`."
    )


# ============================================================
# AUTOMODE PREFIX
# ============================================================

@commands.group(
    name="automode",
    invoke_without_command=True
)
@commands.guild_only()
@commands.has_permissions(
    administrator=True
)
async def automode_prefix(
    ctx
):
    config = get_automode_config(
        ctx.guild.id
    )

    embed = make_embed(
        "🛡️ AutoMode",
        (
            f"Status: {status_text(config['enabled'])}\n\n"
            "Use:\n"
            "`,automode enable`\n"
            "`,automode disable`\n"
            "`,automode status`\n"
            "`,automode config`\n"
            "`,automode spam <messages> <seconds>`\n"
            "`,automode warn <number>`\n"
            "`,automode timeout <number> <minutes>`\n"
            "`,automode links on/off`\n"
            "`,automode mentions on/off`\n"
            "`,automode duplicates on/off`"
        )
    )

    await ctx.send(
        embed=embed
    )


@automode_prefix.command(
    name="enable"
)
@commands.has_permissions(
    administrator=True
)
async def automode_prefix_enable(ctx):
    config = get_automode_config(
        ctx.guild.id
    )

    config["enabled"] = True
    automode_save_all()

    await ctx.send(
        "🟢 **AutoMode enabled.**"
    )


@automode_prefix.command(
    name="disable"
)
@commands.has_permissions(
    administrator=True
)
async def automode_prefix_disable(ctx):
    config = get_automode_config(
        ctx.guild.id
    )

    config["enabled"] = False
    automode_save_all()

    await ctx.send(
        "🔴 **AutoMode disabled.**"
    )


@automode_prefix.command(
    name="status"
)
@commands.has_permissions(
    administrator=True
)
async def automode_prefix_status(ctx):
    config = get_automode_config(
        ctx.guild.id
    )

    await ctx.send(
        embed=make_embed(
            "🛡️ AutoMode Status",
            f"Status: {status_text(config['enabled'])}"
        )
    )


@automode_prefix.command(
    name="config"
)
@commands.has_permissions(
    administrator=True
)
async def automode_prefix_config(ctx):
    config = get_automode_config(
        ctx.guild.id
    )

    embed = make_embed(
        "⚙️ AutoMode Configuration"
    )

    embed.add_field(
        name="Spam",
        value=(
            f"{config['spam_messages']} msgs / "
            f"{config['spam_window']}s"
        ),
        inline=True
    )

    embed.add_field(
        name="Warnings",
        value=(
            f"{status_text(config['warn_enabled'])}\n"
            f"After: {config['warn_after']}"
        ),
        inline=True
    )

    embed.add_field(
        name="Timeout",
        value=(
            f"{status_text(config['timeout_enabled'])}\n"
            f"After: {config['timeout_after']}"
        ),
        inline=True
    )

    await ctx.send(
        embed=embed
    )


@automode_prefix.command(
    name="spam"
)
@commands.has_permissions(
    administrator=True
)
async def automode_prefix_spam(
    ctx,
    messages: int,
    seconds: int
):
    config = get_automode_config(
        ctx.guild.id
    )

    messages = max(
        2,
        min(messages, 50)
    )

    seconds = max(
        1,
        min(seconds, 60)
    )

    config["spam_messages"] = messages
    config["spam_window"] = seconds

    automode_save_all()

    await ctx.send(
        f"✅ Spam protection set to `{messages}` messages / `{seconds}` seconds."
    )


@automode_prefix.command(
    name="warn"
)
@commands.has_permissions(
    administrator=True
)
async def automode_prefix_warn(
    ctx,
    number: int
):
    config = get_automode_config(
        ctx.guild.id
    )

    config["warn_after"] = max(
        1,
        min(number, 20)
    )

    automode_save_all()

    await ctx.send(
        f"✅ Warning threshold set to `{config['warn_after']}`."
    )


@automode_prefix.command(
    name="timeout"
)
@commands.has_permissions(
    administrator=True
)
async def automode_prefix_timeout(
    ctx,
    number: int,
    minutes: int
):
    config = get_automode_config(
        ctx.guild.id
    )

    config["timeout_after"] = max(
        1,
        min(number, 20)
    )

    config["timeout_minutes"] = max(
        1,
        min(minutes, 40320)
    )

    automode_save_all()

    await ctx.send(
        f"✅ Timeout set to `{number}` warnings / `{minutes}` minutes."
    )


@automode_prefix.command(
    name="links"
)
@commands.has_permissions(
    administrator=True
)
async def automode_prefix_links(
    ctx,
    state: str
):
    config = get_automode_config(
        ctx.guild.id
    )

    state = state.lower()

    if state not in (
        "on",
        "off"
    ):
        await ctx.send(
            "❌ Use `on` or `off`."
        )
        return

    config["link_protection"] = (
        state == "on"
    )

    automode_save_all()

    await ctx.send(
        f"🔗 Link protection `{state}`."
    )


@automode_prefix.command(
    name="mentions"
)
@commands.has_permissions(
    administrator=True
)
async def automode_prefix_mentions(
    ctx,
    state: str
):
    config = get_automode_config(
        ctx.guild.id
    )

    state = state.lower()

    if state not in (
        "on",
        "off"
    ):
        await ctx.send(
            "❌ Use `on` or `off`."
        )
        return

    config["mention_protection"] = (
        state == "on"
    )

    automode_save_all()

    await ctx.send(
        f"📢 Mention protection `{state}`."
    )


@automode_prefix.command(
    name="duplicates"
)
@commands.has_permissions(
    administrator=True
)
async def automode_prefix_duplicates(
    ctx,
    state: str
):
    config = get_automode_config(
        ctx.guild.id
    )

    state = state.lower()

    if state not in (
        "on",
        "off"
    ):
        await ctx.send(
            "❌ Use `on` or `off`."
        )
        return

    config["duplicate_protection"] = (
        state == "on"
    )

    automode_save_all()

    await ctx.send(
        f"🔁 Duplicate protection `{state}`."
    )


# ============================================================
# AUTOMODE WHITELIST PREFIX
# ============================================================

@automode_prefix.group(
    name="whitelist",
    invoke_without_command=True
)
@commands.has_permissions(
    administrator=True
)
async def automode_prefix_whitelist(
    ctx
):
    config = get_automode_config(
        ctx.guild.id
    )

    users = config.get(
        "whitelist_users",
        []
    )

    roles = config.get(
        "whitelist_roles",
        []
    )

    await ctx.send(
        embed=make_embed(
            "🛡️ AutoMode Whitelist",
            (
                f"Users: `{len(users)}`\n"
                f"Roles: `{len(roles)}`"
            )
        )
    )


@automode_prefix_whitelist.command(
    name="user"
)
@commands.has_permissions(
    administrator=True
)
async def automode_prefix_whitelist_user(
    ctx,
    member: discord.Member
):
    config = get_automode_config(
        ctx.guild.id
    )

    if member.id not in config["whitelist_users"]:
        config["whitelist_users"].append(
            member.id
        )

    automode_save_all()

    await ctx.send(
        f"✅ {member.mention} added to AutoMode whitelist."
    )


@automode_prefix_whitelist.command(
    name="role"
)
@commands.has_permissions(
    administrator=True
)
async def automode_prefix_whitelist_role(
    ctx,
    role: discord.Role
):
    config = get_automode_config(
        ctx.guild.id
    )

    if role.id not in config["whitelist_roles"]:
        config["whitelist_roles"].append(
            role.id
        )

    automode_save_all()

    await ctx.send(
        f"✅ {role.mention} added to AutoMode whitelist."
    )


# ============================================================
# AUTOMODE BADWORD PREFIX
# ============================================================

@automode_prefix.group(
    name="badword",
    invoke_without_command=True
)
@commands.has_permissions(
    administrator=True
)
async def automode_prefix_badword(
    ctx
):
    config = get_automode_config(
        ctx.guild.id
    )

    words = config.get(
        "badwords",
        []
    )

    await ctx.send(
        embed=make_embed(
            "🚫 AutoMode Bad Words",
            (
                "\n".join(
                    f"• `{word}`"
                    for word in words
                )
                if words
                else "No bad words configured."
            )
        )
    )


@automode_prefix_badword.command(
    name="add"
)
@commands.has_permissions(
    administrator=True
)
async def automode_prefix_badword_add(
    ctx,
    *,
    word: str
):
    config = get_automode_config(
        ctx.guild.id
    )

    word = word.strip()

    if word.lower() not in [
        x.lower()
        for x in config["badwords"]
    ]:
        config["badwords"].append(
            word
        )

    automode_save_all()

    await ctx.send(
        f"✅ Added `{word}`."
    )


@automode_prefix_badword.command(
    name="remove"
)
@commands.has_permissions(
    administrator=True
)
async def automode_prefix_badword_remove(
    ctx,
    *,
    word: str
):
    config = get_automode_config(
        ctx.guild.id
    )

    config["badwords"] = [
        x for x in config["badwords"]
        if x.lower() != word.lower()
    ]

    automode_save_all()

    await ctx.send(
        f"✅ Removed `{word}`."
    )


# ============================================================
# ANTINUKE LOGGING
# ============================================================

async def ensure_antinuke_log_channel(
    guild,
    config
):
    channel_id = config.get(
        "log_channel_id"
    )

    if channel_id:
        channel = guild.get_channel(
            int(channel_id)
        )

        if channel:
            return channel

    try:
        channel = await guild.create_text_channel(
            "commander-antinuke-logs",
            reason="Air Commander Anti-Nuke"
        )

        config["log_channel_id"] = channel.id
        antinuke_save_all()

        return channel

    except Exception as e:
        print(
            f"[AntiNuke] Log channel error: {e}"
        )
        return None


async def send_antinuke_log(
    guild,
    title,
    description,
    color=discord.Color.red()
):
    config = get_antinuke_config(
        guild.id
    )

    channel = await ensure_antinuke_log_channel(
        guild,
        config
    )

    if not channel:
        return

    embed = make_embed(
        title,
        description,
        color
    )

    try:
        await channel.send(
            embed=embed
        )
    except Exception as e:
        print(
            f"[AntiNuke] Send log error: {e}"
        )


# ============================================================
# ANTINUKE ACTION HISTORY
# ============================================================

ANTI_NUKE_HISTORY = defaultdict(
    lambda: defaultdict(
        lambda: defaultdict(deque)
    )
)


def register_antinuke_action(
    guild_id,
    user_id,
    action,
    window
):
    now = time.time()

    history = ANTI_NUKE_HISTORY[
        guild_id
    ][user_id][action]

    history.append(now)

    while history and (
        now - history[0] > window
    ):
        history.popleft()

    return len(history)


def clear_antinuke_history(
    guild_id,
    user_id,
    action
):
    try:
        ANTI_NUKE_HISTORY[
            guild_id
        ][user_id][action].clear()
    except Exception:
        pass


# ============================================================
# ANTINUKE PUNISHMENT
# ============================================================

async def punish_antinuke_actor(
    guild,
    member,
    config,
    reason
):
    action = config.get(
        "action",
        "ban"
    )

    try:

        if member.id == guild.owner_id:
            return False

        if action == "ban":
            await guild.ban(
                member,
                reason=reason,
                delete_message_seconds=0
            )

        elif action == "kick":
            await guild.kick(
                member,
                reason=reason
            )

        elif action == "timeout":
            await member.timeout(
                timedelta(
                    minutes=10
                ),
                reason=reason
            )

        elif action == "strip":
            removable_roles = []

            for role in member.roles:
                if (
                    role.is_default()
                    or role.managed
                ):
                    continue

                removable_roles.append(
                    role
                )

            if removable_roles:
                await member.remove_roles(
                    *removable_roles,
                    reason=reason
                )

        else:
            await guild.ban(
                member,
                reason=reason,
                delete_message_seconds=0
            )

        return True

    except Exception as e:
        print(
            f"[AntiNuke] Punishment error: {e}"
        )

        return False


# ============================================================
# AUDIT ACTION MAP
# ============================================================

AUDIT_ACTION_MAP = {
    discord.AuditLogAction.ban: "ban",
    discord.AuditLogAction.kick: "kick",

    discord.AuditLogAction.channel_delete:
        "channel_delete",

    discord.AuditLogAction.channel_create:
        "channel_create",

    discord.AuditLogAction.role_delete:
        "role_delete",

    discord.AuditLogAction.role_create:
        "role_create",

    discord.AuditLogAction.webhook_delete:
        "webhook_delete",

    discord.AuditLogAction.bot_add:
        "bot_add",

    discord.AuditLogAction.guild_update:
        "guild_update",

    discord.AuditLogAction.emoji_delete:
        "emoji_delete",

    discord.AuditLogAction.emoji_create:
        "emoji_create",

    discord.AuditLogAction.sticker_delete:
        "sticker_delete",

    discord.AuditLogAction.sticker_create:
        "sticker_create",

    discord.AuditLogAction.overwrite_update:
        "overwrite_update"
}


# ============================================================
# PROCESS AUDIT ENTRY
# ============================================================

async def process_audit_entry(
    bot,
    entry
):
    try:
        guild = bot.get_guild(
            entry.guild.id
        )

        if guild is None:
            return

        config = get_antinuke_config(
            guild.id
        )

        if not config.get(
            "enabled",
            False
        ):
            return

        action_name = AUDIT_ACTION_MAP.get(
            entry.action
        )

        if not action_name:
            return

        if not config.get(
            "modules",
            {}
        ).get(
            action_name,
            True
        ):
            return

        actor = entry.user

        if actor is None:
            return

        if actor.bot:
            return

        if antinuke_is_whitelisted(
            actor,
            config
        ):
            return

        window = int(
            config.get(
                "window",
                10
            )
        )

        count = register_antinuke_action(
            guild.id,
            actor.id,
            action_name,
            window
        )

        threshold = int(
            config.get(
                "thresholds",
                {}
            ).get(
                action_name,
                3
            )
        )

        if count < threshold:
            await send_antinuke_log(
                guild,
                "⚠️ Anti-Nuke Detection",
                (
                    f"**User:** {actor.mention}\n"
                    f"**Action:** `{action_name}`\n"
                    f"**Count:** `{count}/{threshold}`\n"
                    f"**Window:** `{window}s`"
                ),
                discord.Color.orange()
            )
            return

        reason = (
            f"Air Commander Anti-Nuke: "
            f"{action_name} threshold exceeded "
            f"({count}/{threshold} in {window}s)"
        )

        punished = await punish_antinuke_actor(
            guild,
            actor,
            config,
            reason
        )

        await send_antinuke_log(
            guild,
            "🚨 Anti-Nuke Triggered",
            (
                f"**User:** {actor.mention}\n"
                f"**User ID:** `{actor.id}`\n"
                f"**Action:** `{action_name}`\n"
                f"**Threshold:** `{threshold}`\n"
                f"**Detected:** `{count}`\n"
                f"**Punishment:** {action_text(config.get('action'))}\n"
                f"**Successful:** `{punished}`"
            ),
            discord.Color.red()
        )

        clear_antinuke_history(
            guild.id,
            actor.id,
            action_name
        )

    except Exception as e:
        print(
            f"[AntiNuke] Audit processing error: {e}"
        )


# ============================================================
# ANTINUKE DASHBOARD
# ============================================================

def dashboard_embed(guild):
    config = get_antinuke_config(
        guild.id
    )

    enabled = config.get(
        "enabled",
        False
    )

    embed = make_embed(
        "🛡️ Air Commander Anti-Nuke",
        (
            "Advanced server protection dashboard.\n\n"
            "Use the buttons below to configure Anti-Nuke."
        ),
        (
            discord.Color.green()
            if enabled
            else discord.Color.red()
        )
    )

    embed.add_field(
        name="Status",
        value=status_text(
            enabled
        ),
        inline=True
    )

    embed.add_field(
        name="Action",
        value=action_text(
            config.get(
                "action",
                "ban"
            )
        ),
        inline=True
    )

    embed.add_field(
        name="Detection Window",
        value=f"`{config.get('window', 10)} seconds`",
        inline=True
    )

    modules = config.get(
        "modules",
        {}
    )

    active = sum(
        1
        for value in modules.values()
        if value
    )

    total = len(modules)

    embed.add_field(
        name="Protection Modules",
        value=f"`{active}/{total}` active",
        inline=True
    )

    embed.add_field(
        name="Whitelisted Users",
        value=str(
            len(
                config.get(
                    "whitelist_users",
                    []
                )
            )
        ),
        inline=True
    )

    embed.add_field(
        name="Whitelisted Roles",
        value=str(
            len(
                config.get(
                    "whitelist_roles",
                    []
                )
            )
        ),
        inline=True
    )

    return embed


# ============================================================
# ANTINUKE MAIN VIEW
# ============================================================

class AntiNukeMainView(
    discord.ui.View
):
    def __init__(
        self,
        bot
    ):
        super().__init__(
            timeout=300
        )
        self.bot = bot

    async def interaction_check(
        self,
        interaction
    ):
        if not is_admin(
            interaction.user
        ):
            await public_send(
                interaction,
                content="❌ Administrator permission required.",
                ephemeral=True
            )
            return False

        return True

    @discord.ui.select(
        placeholder="Select Anti-Nuke option...",
        options=[
            discord.SelectOption(
                label="Enable / Disable",
                value="toggle",
                emoji="🛡️"
            ),
            discord.SelectOption(
                label="Modify Protection",
                value="modify",
                emoji="⚙️"
            ),
            discord.SelectOption(
                label="View Configuration",
                value="view",
                emoji="📋"
            ),
            discord.SelectOption(
                label="Whitelist",
                value="whitelist",
                emoji="👤"
            ),
            discord.SelectOption(
                label="Thresholds",
                value="thresholds",
                emoji="📊"
            ),
            discord.SelectOption(
                label="Logs",
                value="logs",
                emoji="📜"
            )
        ]
    )
    async def menu(
        self,
        interaction,
        select
    ):
        choice = select.values[0]

        if choice == "toggle":
            await interaction.response.edit_message(
                embed=dashboard_embed(
                    interaction.guild
                ),
                view=AntiNukeToggleView(
                    self.bot
                )
            )

        elif choice == "modify":
            await interaction.response.edit_message(
                embed=make_embed(
                    "⚙️ Modify Protection",
                    "Select the protection module you want to configure."
                ),
                view=AntiNukeModifyView(
                    self.bot
                )
            )

        elif choice == "view":
            await interaction.response.edit_message(
                embed=view_config_embed(
                    interaction.guild
                ),
                view=AntiNukeBackView(
                    self.bot
                )
            )

        elif choice == "whitelist":
            await interaction.response.edit_message(
                embed=make_embed(
                    "👤 Anti-Nuke Whitelist",
                    "Manage trusted users and roles."
                ),
                view=AntiNukeWhitelistView(
                    self.bot
                )
            )

        elif choice == "thresholds":
            await interaction.response.edit_message(
                embed=make_embed(
                    "📊 Anti-Nuke Thresholds",
                    "Choose the detection window."
                ),
                view=AntiNukeThresholdView(
                    self.bot
                )
            )

        elif choice == "logs":
            await interaction.response.edit_message(
                embed=make_embed(
                    "📜 Anti-Nuke Logs",
                    "Anti-Nuke logs are automatically sent to the configured log channel."
                ),
                view=AntiNukeLogsView(
                    self.bot
                )
            )


# ============================================================
# TOGGLE VIEW
# ============================================================

class AntiNukeToggleView(
    discord.ui.View
):
    def __init__(
        self,
        bot
    ):
        super().__init__(
            timeout=300
        )
        self.bot = bot

    async def interaction_check(
        self,
        interaction
    ):
        return is_admin(
            interaction.user
        )

    @discord.ui.button(
        label="Enable",
        emoji="🟢",
        style=discord.ButtonStyle.success
    )
    async def enable(
        self,
        interaction,
        button
    ):
        config = get_antinuke_config(
            interaction.guild.id
        )

        config["enabled"] = True

        antinuke_save_all()

        await interaction.response.edit_message(
            embed=dashboard_embed(
                interaction.guild
            ),
            view=AntiNukeMainView(
                self.bot
            )
        )

    @discord.ui.button(
        label="Disable",
        emoji="🔴",
        style=discord.ButtonStyle.danger
    )
    async def disable(
        self,
        interaction,
        button
    ):
        config = get_antinuke_config(
            interaction.guild.id
        )

        config["enabled"] = False

        antinuke_save_all()

        await interaction.response.edit_message(
            embed=dashboard_embed(
                interaction.guild
            ),
            view=AntiNukeMainView(
                self.bot
            )
        )

    @discord.ui.button(
        label="Back",
        emoji="↩️",
        style=discord.ButtonStyle.secondary
    )
    async def back(
        self,
        interaction,
        button
    ):
        await interaction.response.edit_message(
            embed=dashboard_embed(
                interaction.guild
            ),
            view=AntiNukeMainView(
                self.bot
            )
        )


# ============================================================
# MODIFY VIEW
# ============================================================

class AntiNukeModifyView(
    discord.ui.View
):
    def __init__(
        self,
        bot
    ):
        super().__init__(
            timeout=300
        )
        self.bot = bot

    @discord.ui.select(
        placeholder="Select protection module...",
        options=[
            discord.SelectOption(
                label="Ban Protection",
                value="ban",
                emoji="🔨"
            ),
            discord.SelectOption(
                label="Kick Protection",
                value="kick",
                emoji="👢"
            ),
            discord.SelectOption(
                label="Channel Delete",
                value="channel_delete",
                emoji="🗑️"
            ),
            discord.SelectOption(
                label="Channel Create",
                value="channel_create",
                emoji="📁"
            ),
            discord.SelectOption(
                label="Role Delete",
                value="role_delete",
                emoji="🗑️"
            ),
            discord.SelectOption(
                label="Role Create",
                value="role_create",
                emoji="🎭"
            ),
            discord.SelectOption(
                label="Webhook Delete",
                value="webhook_delete",
                emoji="🔗"
            ),
            discord.SelectOption(
                label="Bot Add",
                value="bot_add",
                emoji="🤖"
            ),
            discord.SelectOption(
                label="Guild Update",
                value="guild_update",
                emoji="🏠"
            ),
            discord.SelectOption(
                label="Emoji Delete",
                value="emoji_delete",
                emoji="😀"
            ),
            discord.SelectOption(
                label="Emoji Create",
                value="emoji_create",
                emoji="😀"
            ),
            discord.SelectOption(
                label="Sticker Delete",
                value="sticker_delete",
                emoji="🏷️"
            ),
            discord.SelectOption(
                label="Sticker Create",
                value="sticker_create",
                emoji="🏷️"
            ),
            discord.SelectOption(
                label="Overwrite Update",
                value="overwrite_update",
                emoji="🔐"
            )
        ]
    )
    async def select_module(
        self,
        interaction,
        select
    ):
        module = select.values[0]

        await interaction.response.edit_message(
            embed=make_embed(
                "⚙️ Module Control",
                f"Configure `{module}` protection."
            ),
            view=AntiNukeModuleControlView(
                self.bot,
                module
            )
        )

    @discord.ui.button(
        label="Back",
        emoji="↩️",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def back(
        self,
        interaction,
        button
    ):
        await interaction.response.edit_message(
            embed=dashboard_embed(
                interaction.guild
            ),
            view=AntiNukeMainView(
                self.bot
            )
        )


# ============================================================
# MODULE CONTROL VIEW
# ============================================================

class AntiNukeModuleControlView(
    discord.ui.View
):
    def __init__(
        self,
        bot,
        module
    ):
        super().__init__(
            timeout=300
        )
        self.bot = bot
        self.module = module

    @discord.ui.button(
        label="Enable",
        emoji="🟢",
        style=discord.ButtonStyle.success
    )
    async def enable(
        self,
        interaction,
        button
    ):
        config = get_antinuke_config(
            interaction.guild.id
        )

        config["modules"][
            self.module
        ] = True

        antinuke_save_all()

        await interaction.response.edit_message(
            embed=make_embed(
                "🟢 Protection Enabled",
                f"`{self.module}` protection is enabled."
            ),
            view=AntiNukeModifyView(
                self.bot
            )
        )

    @discord.ui.button(
        label="Disable",
        emoji="🔴",
        style=discord.ButtonStyle.danger
    )
    async def disable(
        self,
        interaction,
        button
    ):
        config = get_antinuke_config(
            interaction.guild.id
        )

        config["modules"][
            self.module
        ] = False

        antinuke_save_all()

        await interaction.response.edit_message(
            embed=make_embed(
                "🔴 Protection Disabled",
                f"`{self.module}` protection is disabled."
            ),
            view=AntiNukeModifyView(
                self.bot
            )
        )

    @discord.ui.button(
        label="Back",
        emoji="↩️",
        style=discord.ButtonStyle.secondary
    )
    async def back(
        self,
        interaction,
        button
    ):
        await interaction.response.edit_message(
            embed=make_embed(
                "⚙️ Modify Protection",
                "Select the protection module you want to configure."
            ),
            view=AntiNukeModifyView(
                self.bot
            )
        )


# ============================================================
# CONFIG VIEW
# ============================================================

def view_config_embed(guild):
    config = get_antinuke_config(
        guild.id
    )

    embed = make_embed(
        "📋 Anti-Nuke Configuration"
    )

    embed.add_field(
        name="Status",
        value=status_text(
            config["enabled"]
        ),
        inline=True
    )

    embed.add_field(
        name="Action",
        value=action_text(
            config["action"]
        ),
        inline=True
    )

    embed.add_field(
        name="Window",
        value=f"`{config['window']} seconds`",
        inline=True
    )

    modules_text = []

    for name, enabled in config[
        "modules"
    ].items():
        modules_text.append(
            f"{'🟢' if enabled else '🔴'} `{name}`"
        )

    embed.add_field(
        name="Modules",
        value="\n".join(
            modules_text
        ),
        inline=False
    )

    return embed


class AntiNukeBackView(
    discord.ui.View
):
    def __init__(
        self,
        bot
    ):
        super().__init__(
            timeout=300
        )
        self.bot = bot

    @discord.ui.button(
        label="Back",
        emoji="↩️",
        style=discord.ButtonStyle.secondary
    )
    async def back(
        self,
        interaction,
        button
    ):
        await interaction.response.edit_message(
            embed=dashboard_embed(
                interaction.guild
            ),
            view=AntiNukeMainView(
                self.bot
            )
        )


# ============================================================
# WHITELIST VIEW
# ============================================================

class AntiNukeWhitelistView(
    discord.ui.View
):
    def __init__(
        self,
        bot
    ):
        super().__init__(
            timeout=300
        )
        self.bot = bot

    @discord.ui.button(
        label="Add User",
        emoji="👤",
        style=discord.ButtonStyle.success
    )
    async def add_user(
        self,
        interaction,
        button
    ):
        await interaction.response.send_message(
            "Use `/antinuke whitelist @user` to add a user.",
            ephemeral=True
        )

    @discord.ui.button(
        label="Add Role",
        emoji="🎭",
        style=discord.ButtonStyle.success
    )
    async def add_role(
        self,
        interaction,
        button
    ):
        await interaction.response.send_message(
            "Use `/antinuke whitelist` with a role.",
            ephemeral=True
        )

    @discord.ui.button(
        label="Back",
        emoji="↩️",
        style=discord.ButtonStyle.secondary
    )
    async def back(
        self,
        interaction,
        button
    ):
        await interaction.response.edit_message(
            embed=dashboard_embed(
                interaction.guild
            ),
            view=AntiNukeMainView(
                self.bot
            )
        )


# ============================================================
# THRESHOLD VIEW
# ============================================================

class AntiNukeThresholdView(
    discord.ui.View
):
    def __init__(
        self,
        bot
    ):
        super().__init__(
            timeout=300
        )
        self.bot = bot

    @discord.ui.button(
        label="5 Seconds",
        emoji="⚡",
        style=discord.ButtonStyle.primary
    )
    async def five(
        self,
        interaction,
        button
    ):
        config = get_antinuke_config(
            interaction.guild.id
        )

        config["window"] = 5

        antinuke_save_all()

        await interaction.response.edit_message(
            embed=dashboard_embed(
                interaction.guild
            ),
            view=AntiNukeMainView(
                self.bot
            )
        )

    @discord.ui.button(
        label="10 Seconds",
        emoji="⏱️",
        style=discord.ButtonStyle.primary
    )
    async def ten(
        self,
        interaction,
        button
    ):
        config = get_antinuke_config(
            interaction.guild.id
        )

        config["window"] = 10

        antinuke_save_all()

        await interaction.response.edit_message(
            embed=dashboard_embed(
                interaction.guild
            ),
            view=AntiNukeMainView(
                self.bot
            )
        )

    @discord.ui.button(
        label="Back",
        emoji="↩️",
        style=discord.ButtonStyle.secondary
    )
    async def back(
        self,
        interaction,
        button
    ):
        await interaction.response.edit_message(
            embed=dashboard_embed(
                interaction.guild
            ),
            view=AntiNukeMainView(
                self.bot
            )
        )


# ============================================================
# LOG VIEW
# ============================================================

class AntiNukeLogsView(
    discord.ui.View
):
    def __init__(
        self,
        bot
    ):
        super().__init__(
            timeout=300
        )
        self.bot = bot

    @discord.ui.button(
        label="Create / Repair Logs",
        emoji="📜",
        style=discord.ButtonStyle.primary
    )
    async def repair(
        self,
        interaction,
        button
    ):
        config = get_antinuke_config(
            interaction.guild.id
        )

        channel = await ensure_antinuke_log_channel(
            interaction.guild,
            config
        )

        if channel:
            await interaction.response.send_message(
                f"✅ Anti-Nuke logs channel: {channel.mention}",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "❌ Could not create the log channel.",
                ephemeral=True
            )

    @discord.ui.button(
        label="Back",
        emoji="↩️",
        style=discord.ButtonStyle.secondary
    )
    async def back(
        self,
        interaction,
        button
    ):
        await interaction.response.edit_message(
            embed=dashboard_embed(
                interaction.guild
            ),
            view=AntiNukeMainView(
                self.bot
            )
        )


# ============================================================
# ANTI-LINK SLASH GROUP
# ============================================================

antilink_group = app_commands.Group(
    name="antilink",
    description="Type-specific link protection"
)


def _antilink_type_choice(value):
    return app_commands.Choice(name=ANTILINK_TYPE_LABELS.get(value, value), value=value)


@antilink_group.command(name="enable", description="Enable Anti-Link")
@app_commands.checks.has_permissions(administrator=True)
async def antilink_enable(interaction: discord.Interaction):
    config = get_antilink_config(interaction.guild.id)
    config["enabled"] = True
    antilink_save_all()
    await public_send(interaction, embed=make_embed(
        "🔗 Anti-Link Enabled",
        "Type-specific link protection is now **enabled**.",
        discord.Color.green()
    ))


@antilink_group.command(name="disable", description="Disable Anti-Link")
@app_commands.checks.has_permissions(administrator=True)
async def antilink_disable(interaction: discord.Interaction):
    config = get_antilink_config(interaction.guild.id)
    config["enabled"] = False
    antilink_save_all()
    await public_send(interaction, embed=make_embed(
        "🔗 Anti-Link Disabled",
        "Type-specific link protection is now **disabled**.",
        discord.Color.red()
    ))


@antilink_group.command(name="status", description="View Anti-Link status")
@app_commands.checks.has_permissions(administrator=True)
async def antilink_status(interaction: discord.Interaction):
    config = get_antilink_config(interaction.guild.id)
    embed = make_embed("🔗 Air Commander Anti-Link")
    embed.add_field(name="Status", value=status_text(config.get("enabled")), inline=False)
    for link_type in ANTILINK_TYPES:
        state = config.get("types", {}).get(link_type, False)
        embed.add_field(
            name=ANTILINK_TYPE_LABELS[link_type],
            value=status_text(state),
            inline=True
        )
    embed.add_field(
        name="Whitelists",
        value=(
            f"👤 Users: `{sum(len(v) for v in config.get('whitelist_users', {}).values())}`\n"
            f"🎭 Roles: `{sum(len(v) for v in config.get('whitelist_roles', {}).values())}`"
        ),
        inline=False
    )
    await public_send(interaction, embed=embed)


@antilink_group.command(name="config", description="View Anti-Link configuration")
@app_commands.checks.has_permissions(administrator=True)
async def antilink_config_command(interaction: discord.Interaction):
    config = get_antilink_config(interaction.guild.id)
    embed = make_embed("⚙️ Anti-Link Configuration")
    embed.add_field(
        name="Protection",
        value="\n".join(
            f"{ANTILINK_TYPE_LABELS[t]}: {status_text(config['types'].get(t, False))}"
            for t in ANTILINK_TYPES
        ),
        inline=False
    )
    embed.add_field(
        name="Actions",
        value=(
            f"🗑️ Delete: {status_text(config.get('delete_enabled', True))}\n"
            f"⚠️ Warning: {status_text(config.get('warning_enabled', True))}\n"
            f"📩 DM: {status_text(config.get('dm_enabled', True))}"
        ),
        inline=True
    )
    await public_send(interaction, embed=embed)


@antilink_group.command(name="type", description="Allow or block a link type")
@app_commands.describe(link_type="Link type", state="on = allow, off = block")
@app_commands.choices(
    link_type=[app_commands.Choice(name=ANTILINK_TYPE_LABELS[t], value=t) for t in ANTILINK_TYPES],
    state=[app_commands.Choice(name="Allowed", value="on"), app_commands.Choice(name="Blocked", value="off")]
)
@app_commands.checks.has_permissions(administrator=True)
async def antilink_type(interaction: discord.Interaction, link_type: app_commands.Choice[str], state: app_commands.Choice[str]):
    config = get_antilink_config(interaction.guild.id)
    config["types"][link_type.value] = state.value == "on"
    antilink_save_all()
    await public_send(
        interaction,
        content=f"✅ {ANTILINK_TYPE_LABELS[link_type.value]} is now **{'allowed' if state.value == 'on' else 'blocked'}**."
    )


@antilink_group.command(name="whitelist_user", description="Whitelist a user for one link type")
@app_commands.describe(user="User", link_type="Link type")
@app_commands.choices(
    link_type=[app_commands.Choice(name=ANTILINK_TYPE_LABELS[t], value=t) for t in ANTILINK_TYPES]
)
@app_commands.checks.has_permissions(administrator=True)
async def antilink_whitelist_user(interaction: discord.Interaction, user: discord.Member, link_type: app_commands.Choice[str]):
    config = get_antilink_config(interaction.guild.id)
    ids = config["whitelist_users"].setdefault(link_type.value, [])
    if user.id not in ids:
        ids.append(user.id)
    antilink_save_all()
    await public_send(interaction, content=f"✅ {user.mention} can now send {ANTILINK_TYPE_LABELS[link_type.value]} links.")


@antilink_group.command(name="whitelist_role", description="Whitelist a role for one link type")
@app_commands.describe(role="Role", link_type="Link type")
@app_commands.choices(
    link_type=[app_commands.Choice(name=ANTILINK_TYPE_LABELS[t], value=t) for t in ANTILINK_TYPES]
)
@app_commands.checks.has_permissions(administrator=True)
async def antilink_whitelist_role(interaction: discord.Interaction, role: discord.Role, link_type: app_commands.Choice[str]):
    config = get_antilink_config(interaction.guild.id)
    ids = config["whitelist_roles"].setdefault(link_type.value, [])
    if role.id not in ids:
        ids.append(role.id)
    antilink_save_all()
    await public_send(interaction, content=f"✅ {role.mention} can now send {ANTILINK_TYPE_LABELS[link_type.value]} links.")


@antilink_group.command(name="unwhitelist_user", description="Remove a user link-type whitelist")
@app_commands.describe(user="User", link_type="Link type")
@app_commands.choices(
    link_type=[app_commands.Choice(name=ANTILINK_TYPE_LABELS[t], value=t) for t in ANTILINK_TYPES]
)
@app_commands.checks.has_permissions(administrator=True)
async def antilink_unwhitelist_user(interaction: discord.Interaction, user: discord.Member, link_type: app_commands.Choice[str]):
    config = get_antilink_config(interaction.guild.id)
    ids = config["whitelist_users"].setdefault(link_type.value, [])
    if user.id in ids:
        ids.remove(user.id)
    antilink_save_all()
    await public_send(interaction, content=f"✅ {user.mention} is no longer whitelisted for {ANTILINK_TYPE_LABELS[link_type.value]} links.")


@antilink_group.command(name="unwhitelist_role", description="Remove a role link-type whitelist")
@app_commands.describe(role="Role", link_type="Link type")
@app_commands.choices(
    link_type=[app_commands.Choice(name=ANTILINK_TYPE_LABELS[t], value=t) for t in ANTILINK_TYPES]
)
@app_commands.checks.has_permissions(administrator=True)
async def antilink_unwhitelist_role(interaction: discord.Interaction, role: discord.Role, link_type: app_commands.Choice[str]):
    config = get_antilink_config(interaction.guild.id)
    ids = config["whitelist_roles"].setdefault(link_type.value, [])
    if role.id in ids:
        ids.remove(role.id)
    antilink_save_all()
    await public_send(interaction, content=f"✅ {role.mention} is no longer whitelisted for {ANTILINK_TYPE_LABELS[link_type.value]} links.")


# ============================================================
# ANTI-LINK PREFIX COMMANDS
# ============================================================

@commands.group(name="antilink", invoke_without_command=True)
@commands.guild_only()
@commands.has_permissions(administrator=True)
async def antilink_prefix(ctx):
    config = get_antilink_config(ctx.guild.id)
    embed = make_embed(
        "🔗 Air Commander Anti-Link",
        (
            f"Status: {status_text(config['enabled'])}\n\n"
            "`,antilink enable`\n"
            "`,antilink disable`\n"
            "`,antilink status`\n"
            "`,antilink config`\n"
            "`,antilink type <gif/youtube/discord/website/image/other> <on/off>`\n"
            "`,antilink whitelist user @User <type>`\n"
            "`,antilink whitelist role @Role <type>`\n"
            "`,antilink unwhitelist user @User <type>`\n"
            "`,antilink unwhitelist role @Role <type>`"
        )
    )
    await ctx.send(embed=embed)


@antilink_prefix.command(name="enable")
@commands.has_permissions(administrator=True)
async def antilink_prefix_enable(ctx):
    config = get_antilink_config(ctx.guild.id)
    config["enabled"] = True
    antilink_save_all()
    await ctx.send("🟢 **Anti-Link enabled.**")


@antilink_prefix.command(name="disable")
@commands.has_permissions(administrator=True)
async def antilink_prefix_disable(ctx):
    config = get_antilink_config(ctx.guild.id)
    config["enabled"] = False
    antilink_save_all()
    await ctx.send("🔴 **Anti-Link disabled.**")


@antilink_prefix.command(name="status")
@commands.has_permissions(administrator=True)
async def antilink_prefix_status(ctx):
    config = get_antilink_config(ctx.guild.id)
    embed = make_embed("🔗 Anti-Link Status")
    embed.add_field(name="Status", value=status_text(config["enabled"]), inline=False)
    for link_type in ANTILINK_TYPES:
        embed.add_field(name=ANTILINK_TYPE_LABELS[link_type], value=status_text(config["types"].get(link_type, False)), inline=True)
    await ctx.send(embed=embed)


@antilink_prefix.command(name="config")
@commands.has_permissions(administrator=True)
async def antilink_prefix_config(ctx):
    config = get_antilink_config(ctx.guild.id)
    embed = make_embed("⚙️ Anti-Link Configuration")
    embed.add_field(
        name="Protection",
        value="\n".join(f"{ANTILINK_TYPE_LABELS[t]}: {status_text(config['types'].get(t, False))}" for t in ANTILINK_TYPES),
        inline=False
    )
    await ctx.send(embed=embed)


@antilink_prefix.command(name="type")
@commands.has_permissions(administrator=True)
async def antilink_prefix_type(ctx, link_type: str, state: str):
    link_type = link_type.lower()
    state = state.lower()
    if link_type not in ANTILINK_TYPES:
        await ctx.send("❌ Invalid link type. Use `gif`, `youtube`, `discord`, `website`, `image`, or `other`.")
        return
    if state not in ("on", "off"):
        await ctx.send("❌ Use `on` or `off`.")
        return
    config = get_antilink_config(ctx.guild.id)
    config["types"][link_type] = state == "on"
    antilink_save_all()
    await ctx.send(f"✅ {ANTILINK_TYPE_LABELS[link_type]} is now **{'allowed' if state == 'on' else 'blocked'}**.")


@antilink_prefix.group(name="whitelist", invoke_without_command=True)
@commands.has_permissions(administrator=True)
async def antilink_prefix_whitelist(ctx):
    config = get_antilink_config(ctx.guild.id)
    users = sum(len(v) for v in config.get("whitelist_users", {}).values())
    roles = sum(len(v) for v in config.get("whitelist_roles", {}).values())
    await ctx.send(embed=make_embed("🛡️ Anti-Link Whitelist", f"Users: `{users}`\nRoles: `{roles}`"))


@antilink_prefix_whitelist.command(name="user")
@commands.has_permissions(administrator=True)
async def antilink_prefix_whitelist_user(ctx, member: discord.Member, link_type: str):
    link_type = link_type.lower()
    if link_type not in ANTILINK_TYPES:
        await ctx.send("❌ Invalid link type.")
        return
    config = get_antilink_config(ctx.guild.id)
    ids = config["whitelist_users"].setdefault(link_type, [])
    if member.id not in ids:
        ids.append(member.id)
    antilink_save_all()
    await ctx.send(f"✅ {member.mention} can now send {ANTILINK_TYPE_LABELS[link_type]} links.")


@antilink_prefix_whitelist.command(name="role")
@commands.has_permissions(administrator=True)
async def antilink_prefix_whitelist_role(ctx, role: discord.Role, link_type: str):
    link_type = link_type.lower()
    if link_type not in ANTILINK_TYPES:
        await ctx.send("❌ Invalid link type.")
        return
    config = get_antilink_config(ctx.guild.id)
    ids = config["whitelist_roles"].setdefault(link_type, [])
    if role.id not in ids:
        ids.append(role.id)
    antilink_save_all()
    await ctx.send(f"✅ {role.mention} can now send {ANTILINK_TYPE_LABELS[link_type]} links.")


@antilink_prefix.group(name="unwhitelist", invoke_without_command=True)
@commands.has_permissions(administrator=True)
async def antilink_prefix_unwhitelist(ctx):
    await ctx.send("Use `,antilink unwhitelist user @User <type>` or `,antilink unwhitelist role @Role <type>`.")


@antilink_prefix_unwhitelist.command(name="user")
@commands.has_permissions(administrator=True)
async def antilink_prefix_unwhitelist_user(ctx, member: discord.Member, link_type: str):
    link_type = link_type.lower()
    if link_type not in ANTILINK_TYPES:
        await ctx.send("❌ Invalid link type.")
        return
    config = get_antilink_config(ctx.guild.id)
    ids = config["whitelist_users"].setdefault(link_type, [])
    if member.id in ids:
        ids.remove(member.id)
    antilink_save_all()
    await ctx.send(f"✅ {member.mention} is no longer whitelisted for {ANTILINK_TYPE_LABELS[link_type]} links.")


@antilink_prefix_unwhitelist.command(name="role")
@commands.has_permissions(administrator=True)
async def antilink_prefix_unwhitelist_role(ctx, role: discord.Role, link_type: str):
    link_type = link_type.lower()
    if link_type not in ANTILINK_TYPES:
        await ctx.send("❌ Invalid link type.")
        return
    config = get_antilink_config(ctx.guild.id)
    ids = config["whitelist_roles"].setdefault(link_type, [])
    if role.id in ids:
        ids.remove(role.id)
    antilink_save_all()
    await ctx.send(f"✅ {role.mention} is no longer whitelisted for {ANTILINK_TYPE_LABELS[link_type]} links.")


# ============================================================
# ANTINUKE PREFIX COMMAND
# ============================================================

@commands.command(
    name="antinuke"
)
@commands.guild_only()
@commands.has_permissions(
    administrator=True
)
async def antinuke_prefix_command(
    ctx
):
    await ctx.send(
        embed=dashboard_embed(
            ctx.guild
        ),
        view=AntiNukeMainView(
            ctx.bot
        )
    )


# ============================================================
# ANTINUKE SLASH GROUP
# ============================================================

class AntiNukeGroup(
    app_commands.Group
):
    def __init__(self):
        super().__init__(
            name="antinuke",
            description="Anti-Nuke server protection"
        )

    @app_commands.command(
        name="config",
        description="Open Anti-Nuke configuration"
    )
    @app_commands.checks.has_permissions(
        administrator=True
    )
    async def config(
        self,
        interaction: discord.Interaction
    ):
        await public_send(
            interaction,
            embed=dashboard_embed(
                interaction.guild
            ),
            view=AntiNukeMainView(
                interaction.client
            )
        )

    @app_commands.command(
        name="whitelist",
        description="Whitelist a user or role"
    )
    @app_commands.describe(
        user="User to whitelist",
        role="Role to whitelist"
    )
    @app_commands.checks.has_permissions(
        administrator=True
    )
    async def whitelist(
        self,
        interaction: discord.Interaction,
        user: discord.Member = None,
        role: discord.Role = None
    ):
        config = get_antinuke_config(
            interaction.guild.id
        )

        if user is None and role is None:
            await public_send(
                interaction,
                content="❌ Mention a user or role.",
                ephemeral=True
            )
            return

        if user:
            if user.id not in config[
                "whitelist_users"
            ]:
                config[
                    "whitelist_users"
                ].append(user.id)

            antinuke_save_all()

            await public_send(
                interaction,
                content=(
                    f"✅ {user.mention} added "
                    f"to Anti-Nuke whitelist."
                )
            )
            return

        if role:
            if role.id not in config[
                "whitelist_roles"
            ]:
                config[
                    "whitelist_roles"
                ].append(role.id)

            antinuke_save_all()

            await public_send(
                interaction,
                content=(
                    f"✅ {role.mention} added "
                    f"to Anti-Nuke whitelist."
                )
            )

    @app_commands.command(
        name="unwhitelist",
        description="Remove a user or role from whitelist"
    )
    @app_commands.describe(
        user="User to remove",
        role="Role to remove"
    )
    @app_commands.checks.has_permissions(
        administrator=True
    )
    async def unwhitelist(
        self,
        interaction: discord.Interaction,
        user: discord.Member = None,
        role: discord.Role = None
    ):
        config = get_antinuke_config(
            interaction.guild.id
        )

        if user is None and role is None:
            await public_send(
                interaction,
                content="❌ Mention a user or role.",
                ephemeral=True
            )
            return

        if user:
            if user.id in config[
                "whitelist_users"
            ]:
                config[
                    "whitelist_users"
                ].remove(user.id)

            antinuke_save_all()

            await public_send(
                interaction,
                content=(
                    f"✅ {user.mention} removed "
                    f"from Anti-Nuke whitelist."
                )
            )
            return

        if role:
            if role.id in config[
                "whitelist_roles"
            ]:
                config[
                    "whitelist_roles"
                ].remove(role.id)

            antinuke_save_all()

            await public_send(
                interaction,
                content=(
                    f"✅ {role.mention} removed "
                    f"from Anti-Nuke whitelist."
                )
            )


# ============================================================
# ERROR HANDLERS
# ============================================================

async def antinuke_error(
    interaction,
    error
):
    if isinstance(
        error,
        app_commands.errors.MissingPermissions
    ):
        await public_send(
            interaction,
            content="❌ Administrator permission required.",
            ephemeral=True
        )
        return

    print(
        f"[AntiNuke] Slash error: {error}"
    )

    if not interaction.response.is_done():
        await public_send(
            interaction,
            content="❌ An Anti-Nuke error occurred.",
            ephemeral=True
        )


# ============================================================
# SETUP
# ============================================================

async def setup(bot):

    # --------------------------------------------------------
    # GLOBAL DUPLICATE GUARD
    # --------------------------------------------------------

    if getattr(
        bot,
        "_air_automation_setup",
        False
    ):
        print(
            "⚠️ Air Commander Automation already initialized."
        )
        return

    bot._air_automation_setup = True

    # --------------------------------------------------------
    # AUTOMODE COG
    # --------------------------------------------------------

    try:
        existing_automode = bot.get_cog(
            "AutoMode"
        )

        if existing_automode is None:
            await bot.add_cog(
                AutoMode(bot)
            )

            print(
                "🛡️ Air Commander AutoMode loaded."
            )
        else:
            print(
                "⚠️ AutoMode Cog already loaded."
            )

    except Exception as e:
        print(
            f"❌ AutoMode setup error: {e}"
        )

    # --------------------------------------------------------
    # ANTINUKE SLASH GROUP
    # --------------------------------------------------------

    try:
        existing_group = bot.tree.get_command(
            "antinuke"
        )

        if existing_group is None:
            bot.tree.add_command(
                AntiNukeGroup()
            )

            print(
                "🛡️ Air Commander Anti-Nuke slash group loaded."
            )

        else:
            print(
                "⚠️ Anti-Nuke slash group already registered."
            )

    except app_commands.errors.CommandAlreadyRegistered:
        print(
            "⚠️ Anti-Nuke slash group already registered."
        )

    except Exception as e:
        print(
            f"❌ Anti-Nuke slash setup error: {e}"
        )

    # --------------------------------------------------------
    # ANTINUKE PREFIX COMMAND
    # --------------------------------------------------------

    try:
        existing_prefix = bot.get_command(
            "antinuke"
        )

        if existing_prefix is None:
            bot.add_command(
                antinuke_prefix_command
            )

            print(
                "🛡️ Air Commander Anti-Nuke prefix command loaded."
            )

        else:
            print(
                "⚠️ Anti-Nuke prefix command already registered."
            )

    except Exception as e:
        print(
            f"❌ Anti-Nuke prefix setup error: {e}"
        )

    # --------------------------------------------------------
    # ANTINUKE AUDIT LOG LISTENER
    # --------------------------------------------------------

    if not getattr(
        bot,
        "_air_antinuke_audit_registered",
        False
    ):

        async def _air_antinuke_audit_handler(
            entry
        ):
            try:
                await process_audit_entry(
                    bot,
                    entry
                )
            except Exception as e:
                print(
                    f"[AntiNuke] Audit error: {e}"
                )

        try:
            bot.add_listener(
                _air_antinuke_audit_handler,
                "on_audit_log_entry_create"
            )

            bot._air_antinuke_audit_registered = True

            print(
                "🛡️ Air Commander Anti-Nuke audit listener loaded."
            )

        except Exception as e:
            print(
                f"❌ Anti-Nuke audit listener setup error: {e}"
            )

    else:
        print(
            "⚠️ Anti-Nuke audit listener already registered."
        )

    # --------------------------------------------------------
    # PREFIX COMMAND GROUPS
    # --------------------------------------------------------

    try:
        if bot.get_command(
            "automode"
        ) is None:
            bot.add_command(
                automode_prefix
            )
            print(
                "⌨️ AutoMode prefix commands loaded."
            )
        else:
            print(
                "⚠️ AutoMode prefix group already registered."
            )

    except Exception as e:
        print(
            f"❌ AutoMode prefix setup error: {e}"
        )

    # --------------------------------------------------------
    # SLASH AUTOMODE GROUP
    # --------------------------------------------------------

    try:
        existing = bot.tree.get_command(
            "automode"
        )

        if existing is None:
            bot.tree.add_command(
                automode_group
            )
            print(
                "⚡ AutoMode slash group loaded."
            )
        else:
            print(
                "⚠️ AutoMode slash group already registered."
            )

    except app_commands.errors.CommandAlreadyRegistered:
        print(
            "⚠️ AutoMode slash group already registered."
        )

    except Exception as e:
        print(
            f"❌ AutoMode slash setup error: {e}"
        )

    # --------------------------------------------------------
    # ANTI-LINK PREFIX GROUP
    # --------------------------------------------------------

    try:
        if bot.get_command("antilink") is None:
            bot.add_command(antilink_prefix)
            print("🔗 Anti-Link prefix commands loaded.")
        else:
            print("⚠️ Anti-Link prefix group already registered.")
    except Exception as e:
        print(f"❌ Anti-Link prefix setup error: {e}")

    # --------------------------------------------------------
    # ANTI-LINK SLASH GROUP
    # --------------------------------------------------------

    try:
        existing = bot.tree.get_command("antilink")
        if existing is None:
            bot.tree.add_command(antilink_group)
            print("🔗 Anti-Link slash group loaded.")
        else:
            print("⚠️ Anti-Link slash group already registered.")
    except app_commands.errors.CommandAlreadyRegistered:
        print("⚠️ Anti-Link slash group already registered.")
    except Exception as e:
        print(f"❌ Anti-Link slash setup error: {e}")

    # --------------------------------------------------------
    # FINAL
    # --------------------------------------------------------

    print(
        "🚀 Air Commander Automation loaded "
        "(AutoMode + Anti-Nuke + Anti-Link)."
    )
