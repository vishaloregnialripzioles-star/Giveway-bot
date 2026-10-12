# ============================================================
# AIR COMMANDER — ADVANCED AIR LEVELING
# ============================================================
#
# USER SLASH:
#   /airlevel rank
#   /airlevel profile
#   /airlevel leaderboard
#   /airlevel streak
#   /airlevel daily
#   /airlevel badges
#   /airlevel season
#   /airlevel quest
#   /airlevel battlepass
#   /airlevel rewards
#   /airlevel boost
#   /airlevel help
#
# ADMIN SLASH:
#   /airlevel enable
#   /airlevel disable
#   /airlevel settings
#   /airlevel channel
#   /airlevel announce
#   /airlevel xp
#   /airlevel cooldown
#   /airlevel ignorechannel
#   /airlevel ignorerole
#   /airlevel reward
#   /airlevel roleboost
#   /airlevel channelboost
#
# RESET:
#   /airlevel reset user
#   /airlevel reset server
#
# MESSAGE:
#   /message
#   ,m
#   ,message
#   ,messages
#
# PREFIX:
#   ,airlevel
#   ,airlevel rank
#   ,airlevel profile
#   ,airlevel leaderboard
#   ,airlevel streak
#   ,airlevel daily
#   ,airlevel quest
#   ,airlevel help
#   ,airrank
#   ,airleaderboard
#   ,airlb
#   ,airstreak
#   ,airdaily
#
# ============================================================

import json
import os
import time
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands


# ============================================================
# CONFIG
# ============================================================

DATA_FILE = "airleveling_data.json"

DEFAULT_XP_PER_MESSAGE = 15
DEFAULT_COOLDOWN = 60

# Hard cap for the Air Leveling system.
MAX_LEVEL = 200

DAILY_XP = 250

WEEKLY_QUEST_TARGET = 500
WEEKLY_QUEST_REWARD = 1000

MAX_LEADERBOARD = 10

# Keep enough history for month statistics.
MESSAGE_HISTORY_DAYS = 90

EMBED_COLOR = discord.Color.blurple()
SUCCESS_COLOR = discord.Color.green()
ERROR_COLOR = discord.Color.red()
GOLD_COLOR = discord.Color.gold()
ORANGE_COLOR = discord.Color.orange()
PURPLE_COLOR = discord.Color.purple()


# ============================================================
# DATA
# ============================================================

def load_data():
    if not os.path.exists(DATA_FILE):
        return {}

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            return {}

        return data

    except (json.JSONDecodeError, OSError):
        return {}


def save_data(data):
    """
    Atomic JSON save.
    """

    directory = os.path.dirname(DATA_FILE)

    if directory:
        os.makedirs(directory, exist_ok=True)

    temp_file = DATA_FILE + ".tmp"

    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(
                data,
                f,
                indent=4,
                ensure_ascii=False
            )

        os.replace(temp_file, DATA_FILE)

    except OSError:
        try:
            if os.path.exists(temp_file):
                os.remove(temp_file)
        except OSError:
            pass


DATA = load_data()


# ============================================================
# DEFAULT GUILD CONFIG
# ============================================================

def default_config():
    return {
        "enabled": True,

        "xp_per_message": DEFAULT_XP_PER_MESSAGE,
        "cooldown": DEFAULT_COOLDOWN,

        # Level-up announcement
        "announce": True,

        # None = current channel automatically
        "announce_channel": None,

        # Ignored locations
        "ignored_channels": [],
        "ignored_roles": [],

        # Level role rewards
        "role_rewards": {},

        # XP boosters
        "role_boosters": {},
        "channel_boosters": {},

        # Users
        "users": {},

        # Season
        "season": {
            "number": 1,
            "xp": 0,
            "started": time.time()
        },

        # Weekly quest
        "quests": {
            "name": "Chat Storm",
            "description": "Send 500 messages this week",
            "target": WEEKLY_QUEST_TARGET,
            "reward": WEEKLY_QUEST_REWARD,
            "progress": {},
            "started": time.time(),
            "claimed": {}
        }
    }


def guild_config(guild_id: int):
    gid = str(guild_id)

    if gid not in DATA:
        DATA[gid] = default_config()
        save_data(DATA)

    config = DATA[gid]

    defaults = default_config()

    for key, value in defaults.items():
        if key not in config:
            config[key] = value

    # --------------------------------------------------------
    # Nested season defaults
    # --------------------------------------------------------

    if not isinstance(config.get("season"), dict):
        config["season"] = defaults["season"]

    for key, value in defaults["season"].items():
        config["season"].setdefault(key, value)

    # --------------------------------------------------------
    # Nested quest defaults
    # --------------------------------------------------------

    if not isinstance(config.get("quests"), dict):
        config["quests"] = defaults["quests"]

    for key, value in defaults["quests"].items():
        config["quests"].setdefault(key, value)

    # --------------------------------------------------------
    # Type safety
    # --------------------------------------------------------

    for key in (
        "ignored_channels",
        "ignored_roles"
    ):
        if not isinstance(config.get(key), list):
            config[key] = []

    for key in (
        "role_rewards",
        "role_boosters",
        "channel_boosters",
        "users"
    ):
        if not isinstance(config.get(key), dict):
            config[key] = {}

    return config


# ============================================================
# USER DATA
# ============================================================

def user_data(config, user_id: int):
    uid = str(user_id)

    if uid not in config["users"]:
        config["users"][uid] = {
            "xp": 0,
            "messages": 0,

            "last_xp": 0,

            # Streak
            "streak": 0,
            "best_streak": 0,
            "last_chat_day": None,

            # Daily
            "daily_claim": 0,

            # Badges
            "badges": [],

            # Quest
            "quest_progress": 0,
            "quest_claimed": False,

            # Message statistics
            "message_history": []
        }

    user = config["users"][uid]

    defaults = {
        "xp": 0,
        "messages": 0,
        "last_xp": 0,
        "streak": 0,
        "best_streak": 0,
        "last_chat_day": None,
        "daily_claim": 0,
        "badges": [],
        "quest_progress": 0,
        "quest_claimed": False,
        "message_history": []
    }

    for key, value in defaults.items():
        user.setdefault(key, value)

    if not isinstance(user.get("message_history"), list):
        user["message_history"] = []

    if not isinstance(user.get("badges"), list):
        user["badges"] = []

    return user


# ============================================================
# XP SYSTEM
# ============================================================

def xp_required(level: int) -> int:
    level = max(0, int(level))

    return (
        100
        + (level * 55)
        + int((level ** 2) * 5)
    )


def calculate_level(total_xp: int):
    """
    Convert total XP into a level, capped at MAX_LEVEL.

    Existing total XP is preserved. At level 200 there is no next-level
    progress, so this returns (MAX_LEVEL, 0, 0).
    """
    level = 0
    remaining = max(0, int(total_xp))

    while level < MAX_LEVEL:
        required = xp_required(level)
        if remaining < required:
            return level, remaining, required
        remaining -= required
        level += 1

    return MAX_LEVEL, 0, 0


def progress_bar(
    current: int,
    required: int,
    length: int = 14
):
    if required <= 0:
        return "▰" * length

    ratio = max(
        0,
        min(
            1,
            current / required
        )
    )

    filled = int(
        ratio * length
    )

    return (
        "▰" * filled
        + "▱" * (length - filled)
    )


# ============================================================
# EMBEDS
# ============================================================

def success_embed(title, description):
    embed = discord.Embed(
        title=f"✅ {title}",
        description=description,
        color=SUCCESS_COLOR
    )

    embed.set_footer(
        text="Air Commander • Air Leveling"
    )

    return embed


def error_embed(description):
    embed = discord.Embed(
        title="❌ Air Leveling",
        description=description,
        color=ERROR_COLOR
    )

    embed.set_footer(
        text="Air Commander"
    )

    return embed


def info_embed(title, description):
    embed = discord.Embed(
        title=title,
        description=description,
        color=EMBED_COLOR
    )

    embed.set_footer(
        text="Air Commander • Air Leveling"
    )

    return embed


# ============================================================
# STREAK
# ============================================================

def utc_day():
    return datetime.now(
        timezone.utc
    ).date()


def update_streak(user):
    today = utc_day().isoformat()

    last_day = user.get(
        "last_chat_day"
    )

    if last_day == today:
        return False

    if last_day:
        try:
            previous = datetime.fromisoformat(
                last_day
            ).date()

            difference = (
                utc_day() - previous
            ).days

            if difference == 1:
                user["streak"] = (
                    int(user.get("streak", 0))
                    + 1
                )

            elif difference > 1:
                user["streak"] = 1

        except ValueError:
            user["streak"] = 1

    else:
        user["streak"] = 1

    user["best_streak"] = max(
        int(user.get("best_streak", 0)),
        int(user.get("streak", 0))
    )

    user["last_chat_day"] = today

    return True


# ============================================================
# BADGES
# ============================================================

def check_badges(user):
    badges = set(
        user.get(
            "badges",
            []
        )
    )

    messages = int(
        user.get(
            "messages",
            0
        )
    )

    streak = int(
        user.get(
            "best_streak",
            0
        )
    )

    if messages >= 100:
        badges.add(
            "💬 Chat Starter"
        )

    if messages >= 1000:
        badges.add(
            "🔥 Chat Veteran"
        )

    if messages >= 5000:
        badges.add(
            "👑 Chat Legend"
        )

    if streak >= 7:
        badges.add(
            "🔥 7 Day Streak"
        )

    if streak >= 30:
        badges.add(
            "⚡ 30 Day Streak"
        )

    user["badges"] = sorted(
        badges
    )


# ============================================================
# MESSAGE HISTORY
# ============================================================

def record_message(user, timestamp=None):
    """
    Store message timestamp for Today/Week/Month statistics.
    """

    now = (
        float(timestamp)
        if timestamp is not None
        else time.time()
    )

    history = user.setdefault(
        "message_history",
        []
    )

    if not isinstance(history, list):
        history = []
        user["message_history"] = history

    history.append(now)

    cutoff = (
        now
        - (
            MESSAGE_HISTORY_DAYS
            * 86400
        )
    )

    user["message_history"] = [
        value
        for value in history
        if isinstance(value, (int, float))
        and value >= cutoff
    ]


def get_message_stats(user):
    """
    Rolling statistics:

    Today = last 24 hours
    Week = last 7 days
    Month = last 30 days
    All Time = permanent total
    """

    history = user.get(
        "message_history",
        []
    )

    now = time.time()

    today_start = now - 86400
    week_start = now - (
        7 * 86400
    )
    month_start = now - (
        30 * 86400
    )

    today = 0
    week = 0
    month = 0

    for timestamp in history:

        if not isinstance(
            timestamp,
            (int, float)
        ):
            continue

        if timestamp >= today_start:
            today += 1

        if timestamp >= week_start:
            week += 1

        if timestamp >= month_start:
            month += 1

    return {
        "today": today,
        "week": week,
        "month": month,
        "all": int(
            user.get(
                "messages",
                0
            )
        )
    }


# ============================================================
# BOOSTERS
# ============================================================

def calculate_multiplier(
    config,
    member,
    channel
):
    multiplier = 1.0

    for role in getattr(
        member,
        "roles",
        []
    ):

        boost = config.get(
            "role_boosters",
            {}
        ).get(
            str(role.id)
        )

        if boost is not None:
            try:
                multiplier = max(
                    multiplier,
                    float(boost)
                )
            except (
                TypeError,
                ValueError
            ):
                pass

    channel_boost = config.get(
        "channel_boosters",
        {}
    ).get(
        str(channel.id)
    )

    if channel_boost is not None:
        try:
            multiplier = max(
                multiplier,
                float(channel_boost)
            )
        except (
            TypeError,
            ValueError
        ):
            pass

    return max(
        1.0,
        multiplier
    )


# ============================================================
# ANNOUNCEMENT CHANNEL
# ============================================================

def get_announcement_channel(
    guild: discord.Guild,
    fallback_channel=None
):
    """
    Priority:

    1. Configured leveling channel
    2. Current message channel
    3. System channel
    """

    config = guild_config(
        guild.id
    )

    configured_id = config.get(
        "announce_channel"
    )

    if configured_id:

        try:
            channel = guild.get_channel(
                int(configured_id)
            )

            if channel:
                return channel

        except (
            TypeError,
            ValueError
        ):
            pass

    if fallback_channel is not None:
        return fallback_channel

    return guild.system_channel


# ============================================================
# WEEKLY QUEST
# ============================================================

def reset_weekly_quest_if_needed(config):
    quests = config["quests"]

    try:
        started = float(
            quests.get(
                "started",
                time.time()
            )
        )
    except (
        TypeError,
        ValueError
    ):
        started = time.time()

    now = time.time()

    if now - started >= 604800:

        quests["started"] = now
        quests["progress"] = {}
        quests["claimed"] = {}

        for uid in config["users"]:

            config["users"][uid][
                "quest_progress"
            ] = 0

            config["users"][uid][
                "quest_claimed"
            ] = False

        save_data(DATA)


def update_quest(
    config,
    user_id
):
    reset_weekly_quest_if_needed(
        config
    )

    uid = str(user_id)

    quests = config["quests"]

    progress = quests.setdefault(
        "progress",
        {}
    )

    progress[uid] = (
        int(
            progress.get(
                uid,
                0
            )
        )
        + 1
    )

    user = user_data(
        config,
        user_id
    )

    user["quest_progress"] = (
        progress[uid]
    )

    target = int(
        quests.get(
            "target",
            WEEKLY_QUEST_TARGET
        )
    )

    reward = int(
        quests.get(
            "reward",
            WEEKLY_QUEST_REWARD
        )
    )

    if (
        progress[uid] >= target
        and not user.get(
            "quest_claimed",
            False
        )
    ):

        user["xp"] = (
            int(user.get("xp", 0))
            + reward
        )

        user["quest_claimed"] = True

        quests.setdefault(
            "claimed",
            {}
        )[uid] = time.time()

        return reward

    return 0


# ============================================================
# SEASON
# ============================================================

def add_season_xp(
    config,
    amount
):
    season = config["season"]

    season["xp"] = (
        int(
            season.get(
                "xp",
                0
            )
        )
        + max(
            0,
            int(amount)
        )
    )


# ============================================================
# COG
# ============================================================

class AirLeveling(commands.Cog):

    # --------------------------------------------------------
    # Main /airlevel group
    # --------------------------------------------------------

    airlevel = app_commands.Group(
        name="airlevel",
        description="Air Commander level system"
    )

    # --------------------------------------------------------
    # IMPORTANT:
    #
    # Reset is a subgroup.
    #
    # This keeps the direct child count under Discord.py's
    # application-command limit.
    #
    # /airlevel reset user
    # /airlevel reset server
    # --------------------------------------------------------

    reset = app_commands.Group(
        name="reset",
        description="Reset Air Leveling data"
    )

    def __init__(
        self,
        bot
    ):
        self.bot = bot

        # Runtime XP cooldown.
        self.cooldowns = {}

    # ========================================================
    # MESSAGE XP
    # ========================================================

    @commands.Cog.listener()
    async def on_message(
        self,
        message
    ):

        if message.author.bot:
            return

        if not message.guild:
            return

        config = guild_config(
            message.guild.id
        )

        if not config.get(
            "enabled",
            True
        ):
            return

        # ----------------------------------------------------
        # Ignored channel
        # ----------------------------------------------------

        if message.channel.id in config.get(
            "ignored_channels",
            []
        ):
            return

        # ----------------------------------------------------
        # Ignored roles
        # ----------------------------------------------------

        member_role_ids = {
            role.id
            for role in getattr(
                message.author,
                "roles",
                []
            )
        }

        ignored_roles = set()

        for role_id in config.get(
            "ignored_roles",
            []
        ):

            try:
                ignored_roles.add(
                    int(role_id)
                )
            except (
                TypeError,
                ValueError
            ):
                continue

        if member_role_ids.intersection(
            ignored_roles
        ):
            return

        # ----------------------------------------------------
        # User data
        # ----------------------------------------------------

        user = user_data(
            config,
            message.author.id
        )

        # ----------------------------------------------------
        # MESSAGE COUNT
        # ----------------------------------------------------

        user["messages"] = (
            int(
                user.get(
                    "messages",
                    0
                )
            )
            + 1
        )

        record_message(
            user
        )

        # ----------------------------------------------------
        # STREAK
        # ----------------------------------------------------

        update_streak(
            user
        )

        # ----------------------------------------------------
        # BADGES
        # ----------------------------------------------------

        check_badges(
            user
        )

        # ----------------------------------------------------
        # QUEST
        # ----------------------------------------------------

        old_xp_before_quest = int(
            user.get(
                "xp",
                0
            )
        )

        quest_reward = update_quest(
            config,
            message.author.id
        )

        if quest_reward:
            add_season_xp(
                config,
                quest_reward
            )

        now = time.time()

        # ----------------------------------------------------
        # XP COOLDOWN
        # ----------------------------------------------------

        cooldown_key = (
            message.guild.id,
            message.author.id
        )

        last_xp = self.cooldowns.get(
            cooldown_key,
            0
        )

        cooldown = max(
            0,
            int(
                config.get(
                    "cooldown",
                    DEFAULT_COOLDOWN
                )
            )
        )

        # ----------------------------------------------------
        # If cooldown active:
        #
        # Message statistics still save.
        # Quest reward still works.
        # ----------------------------------------------------

        if now - last_xp < cooldown:

            # If quest reward caused a level-up,
            # announce it even though normal XP is cooldowned.
            if quest_reward:

                old_level, _, _ = calculate_level(
                    old_xp_before_quest
                )

                new_level, _, _ = calculate_level(
                    user["xp"]
                )

                if new_level > old_level:

                    for level in range(
                        old_level + 1,
                        new_level + 1
                    ):
                        await self.handle_level_up(
                            message.guild,
                            message.author,
                            level,
                            message.channel
                        )

            save_data(DATA)
            return

        self.cooldowns[
            cooldown_key
        ] = now

        # ----------------------------------------------------
        # NORMAL XP
        # ----------------------------------------------------

        old_xp = int(
            user.get(
                "xp",
                0
            )
        )

        old_level, _, _ = calculate_level(
            old_xp
        )

        base_xp = max(
            1,
            int(
                config.get(
                    "xp_per_message",
                    DEFAULT_XP_PER_MESSAGE
                )
            )
        )

        multiplier = calculate_multiplier(
            config,
            message.author,
            message.channel
        )

        gained = max(
            1,
            int(
                base_xp * multiplier
            )
        )

        user["xp"] = (
            old_xp + gained
        )

        user["last_xp"] = now

        add_season_xp(
            config,
            gained
        )

        check_badges(
            user
        )

        save_data(DATA)

        # ----------------------------------------------------
        # LEVEL UP
        # ----------------------------------------------------

        new_level, _, _ = calculate_level(
            user["xp"]
        )

        if new_level > old_level:

            for level in range(
                old_level + 1,
                new_level + 1
            ):

                await self.handle_level_up(
                    message.guild,
                    message.author,
                    level,
                    message.channel
                )

    # ========================================================
    # LEVEL UP
    # ========================================================

    async def handle_level_up(
        self,
        guild,
        member,
        level,
        source_channel=None
    ):

        config = guild_config(
            guild.id
        )

        # ----------------------------------------------------
        # Role reward
        # ----------------------------------------------------

        reward_role_id = config.get(
            "role_rewards",
            {}
        ).get(
            str(level)
        )

        reward_role = None

        if reward_role_id:

            try:
                reward_role = guild.get_role(
                    int(reward_role_id)
                )
            except (
                TypeError,
                ValueError
            ):
                reward_role = None

            if (
                reward_role
                and reward_role not in member.roles
            ):

                try:
                    await member.add_roles(
                        reward_role,
                        reason=(
                            f"Air Leveling "
                            f"level {level} reward"
                        )
                    )

                except (
                    discord.Forbidden,
                    discord.HTTPException
                ):
                    reward_role = None

        # ----------------------------------------------------
        # Announcement disabled
        # ----------------------------------------------------

        if not config.get(
            "announce",
            True
        ):
            return

        # ----------------------------------------------------
        # Channel priority
        #
        # Configured channel
        #       ↓
        # Current chat channel
        #       ↓
        # System channel
        # ----------------------------------------------------

        channel = get_announcement_channel(
            guild,
            source_channel
        )

        if channel is None:
            return

        # ----------------------------------------------------
        # Embed
        # ----------------------------------------------------

        embed = discord.Embed(
            title="✦ LEVEL UP!",
            description=(
                f"## 🎉 Congratulations "
                f"{member.mention}!\n\n"
                f"You reached **Level {level}**!\n\n"
                f"**✨ New Level:** `{level}`"
            ),
            color=discord.Color.from_rgb(
                88,
                101,
                242
            )
        )

        embed.set_thumbnail(
            url=member.display_avatar.url
        )

        embed.add_field(
            name="📈 Progress",
            value=(
                f"**Level {level} unlocked**\n"
                f"`{progress_bar(1, 1)}`"
            ),
            inline=True
        )

        if reward_role:

            embed.add_field(
                name="🎖️ Reward",
                value=reward_role.mention,
                inline=True
            )

        user = user_data(
            config,
            member.id
        )

        embed.add_field(
            name="⭐ Total XP",
            value=(
                f"**{user['xp']:,} XP**"
            ),
            inline=True
        )

        embed.set_footer(
            text=(
                f"{guild.name} • "
                f"Air Commander Leveling"
            )
        )

        try:
            await channel.send(
                embed=embed
            )

        except (
            discord.Forbidden,
            discord.HTTPException
        ):
            pass

    # ========================================================
    # RANK EMBED
    # ========================================================

    def build_rank_embed(
        self,
        guild,
        member
    ):

        config = guild_config(
            guild.id
        )

        user = user_data(
            config,
            member.id
        )

        total_xp = int(
            user.get(
                "xp",
                0
            )
        )

        level, current_xp, needed = calculate_level(
            total_xp
        )

        ranking = sorted(
            config["users"].items(),
            key=lambda item: int(
                item[1].get(
                    "xp",
                    0
                )
            ),
            reverse=True
        )

        position = 1

        for index, (
            uid,
            _
        ) in enumerate(
            ranking,
            start=1
        ):

            if uid == str(
                member.id
            ):
                position = index
                break

        percentage = (
            current_xp / needed * 100
            if needed
            else 0
        )

        embed = discord.Embed(
            title=(
                f"✦ {member.display_name}'s "
                f"Profile"
            ),
            description=(
                f"{member.mention}\n"
                f"**Keep chatting and climb "
                f"the ranks!**"
            ),
            color=EMBED_COLOR
        )

        embed.set_thumbnail(
            url=member.display_avatar.url
        )

        embed.add_field(
            name="⭐ LEVEL",
            value=f"**{level}**",
            inline=True
        )

        embed.add_field(
            name="🏆 SERVER RANK",
            value=f"**#{position}**",
            inline=True
        )

        embed.add_field(
            name="💬 MESSAGES",
            value=(
                f"**{user['messages']:,}**"
            ),
            inline=True
        )

        xp_progress_text = (
            f"**{current_xp:,} / {needed:,} XP**\\n"
            f"`{progress_bar(current_xp, needed)}`\\n"
            f"**{percentage:.1f}%**"
            if level < MAX_LEVEL
            else f"🏆 **MAX LEVEL {MAX_LEVEL} REACHED**"
        )

        embed.add_field(
            name="✨ XP",
            value=xp_progress_text,
            inline=False
        )

        embed.add_field(
            name="📊 TOTAL XP",
            value=f"**{total_xp:,}**",
            inline=True
        )

        embed.add_field(
            name="🚀 NEXT LEVEL",
            value=(
                f"**Level {level + 1}**"
                if level < MAX_LEVEL
                else f"**MAX LEVEL {MAX_LEVEL}**"
            ),
            inline=True
        )

        embed.add_field(
            name="🔥 STREAK",
            value=(
                f"**{user.get('streak', 0)} days**"
            ),
            inline=True
        )

        embed.add_field(
            name="🎖️ BADGES",
            value=str(
                len(
                    user.get(
                        "badges",
                        []
                    )
                )
            ),
            inline=True
        )

        embed.set_footer(
            text="Air Commander • Air Leveling"
        )

        return embed

    # ========================================================
    # LEADERBOARD
    # ========================================================

    def build_leaderboard_embed(
        self,
        guild
    ):

        config = guild_config(
            guild.id
        )

        ranking = sorted(
            config["users"].items(),
            key=lambda item: int(
                item[1].get(
                    "xp",
                    0
                )
            ),
            reverse=True
        )

        if not ranking:
            return None

        lines = []

        medals = [
            "🥇",
            "🥈",
            "🥉"
        ]

        for index, (
            uid,
            data
        ) in enumerate(
            ranking[
                :MAX_LEADERBOARD
            ],
            start=1
        ):

            try:
                member = guild.get_member(
                    int(uid)
                )
            except (
                TypeError,
                ValueError
            ):
                member = None

            name = (
                member.display_name
                if member
                else f"User {uid}"
            )

            level, _, _ = calculate_level(
                data.get(
                    "xp",
                    0
                )
            )

            prefix = (
                medals[index - 1]
                if index <= 3
                else f"**#{index}**"
            )

            lines.append(
                f"{prefix}  **{name}**\n"
                f"      └─ Level `{level}` • "
                f"`{data.get('xp', 0):,} XP`"
            )

        embed = discord.Embed(
            title="🏆 AIR XP LEADERBOARD",
            description=(
                "```ansi\n"
                "     AIR COMMANDER • TOP 10\n"
                "```\n"
                + "\n\n".join(lines)
            ),
            color=GOLD_COLOR
        )

        embed.set_footer(
            text=(
                f"{guild.name} • "
                f"Air Leveling Leaderboard"
            )
        )

        return embed

    # ========================================================
    # USER — RANK
    # ========================================================

    @airlevel.command(
        name="rank",
        description="View your or another member's rank"
    )
    @app_commands.describe(
        member="Member whose rank you want to see"
    )
    async def airlevel_rank(
        self,
        interaction: discord.Interaction,
        member: Optional[discord.Member] = None
    ):

        if not interaction.guild:

            await interaction.response.send_message(
                embed=error_embed(
                    "This command can only be used inside a server."
                ),
                ephemeral=True
            )
            return

        member = (
            member
            or interaction.user
        )

        await interaction.response.send_message(
            embed=self.build_rank_embed(
                interaction.guild,
                member
            )
        )

    # ========================================================
    # USER — PROFILE
    # ========================================================

    @airlevel.command(
        name="profile",
        description="Show your full leveling profile"
    )
    @app_commands.describe(
        member="Member to inspect"
    )
    async def airlevel_profile(
        self,
        interaction: discord.Interaction,
        member: Optional[discord.Member] = None
    ):

        if not interaction.guild:

            await interaction.response.send_message(
                embed=error_embed(
                    "This command can only be used inside a server."
                ),
                ephemeral=True
            )
            return

        member = (
            member
            or interaction.user
        )

        await interaction.response.send_message(
            embed=self.build_rank_embed(
                interaction.guild,
                member
            )
        )

    # ========================================================
    # USER — LEADERBOARD
    # ========================================================

    @airlevel.command(
        name="leaderboard",
        description="Show the server XP leaderboard"
    )
    async def airlevel_leaderboard(
        self,
        interaction: discord.Interaction
    ):

        if not interaction.guild:

            await interaction.response.send_message(
                embed=error_embed(
                    "This command can only be used inside a server."
                ),
                ephemeral=True
            )
            return

        embed = self.build_leaderboard_embed(
            interaction.guild
        )

        if embed is None:

            await interaction.response.send_message(
                embed=info_embed(
                    "📊 No XP Data",
                    "No XP data exists in this server yet."
                )
            )
            return

        await interaction.response.send_message(
            embed=embed
        )

    # ========================================================
    # USER — STREAK
    # ========================================================

    @airlevel.command(
        name="streak",
        description="View your or another member's streak"
    )
    @app_commands.describe(
        member="Member to inspect"
    )
    async def airlevel_streak(
        self,
        interaction: discord.Interaction,
        member: Optional[discord.Member] = None
    ):

        if not interaction.guild:

            await interaction.response.send_message(
                embed=error_embed(
                    "This command can only be used inside a server."
                ),
                ephemeral=True
            )
            return

        member = (
            member
            or interaction.user
        )

        config = guild_config(
            interaction.guild.id
        )

        user = user_data(
            config,
            member.id
        )

        embed = discord.Embed(
            title=(
                f"🔥 {member.display_name}'s Streak"
            ),
            description=(
                f"Current streak: "
                f"**{user.get('streak', 0)}** days\n"
                f"Best streak: "
                f"**{user.get('best_streak', 0)}** days"
            ),
            color=ORANGE_COLOR
        )

        embed.set_thumbnail(
            url=member.display_avatar.url
        )

        await interaction.response.send_message(
            embed=embed
        )

    # ========================================================
    # DAILY HELPER
    # ========================================================

    async def claim_daily(
        self,
        guild,
        member,
        send_func
    ):

        config = guild_config(
            guild.id
        )

        user = user_data(
            config,
            member.id
        )

        now = time.time()

        last_claim = float(
            user.get(
                "daily_claim",
                0
            )
        )

        if now - last_claim < 86400:

            remain = max(
                0,
                int(
                    86400
                    - (
                        now - last_claim
                    )
                )
            )

            hours = remain // 3600

            minutes = (
                remain % 3600
            ) // 60

            await send_func(
                embed=info_embed(
                    "⏳ Daily Reward",
                    (
                        "You already claimed today.\n"
                        f"Come back in **{hours}h "
                        f"{minutes}m**."
                    )
                )
            )

            return

        old_xp = int(
            user.get(
                "xp",
                0
            )
        )

        user["daily_claim"] = now

        user["xp"] = (
            old_xp + DAILY_XP
        )

        add_season_xp(
            config,
            DAILY_XP
        )

        save_data(DATA)

        old_level, _, _ = calculate_level(
            old_xp
        )

        new_level, _, _ = calculate_level(
            user["xp"]
        )

        if new_level > old_level:

            for level in range(
                old_level + 1,
                new_level + 1
            ):

                await self.handle_level_up(
                    guild,
                    member,
                    level
                )

        await send_func(
            embed=success_embed(
                "🎁 Daily Reward Claimed",
                (
                    f"You received "
                    f"**{DAILY_XP} XP**."
                )
            )
        )

    # ========================================================
    # USER — DAILY
    # ========================================================

    @airlevel.command(
        name="daily",
        description="Claim your daily XP reward"
    )
    async def airlevel_daily(
        self,
        interaction: discord.Interaction
    ):

        if not interaction.guild:

            await interaction.response.send_message(
                embed=error_embed(
                    "This command can only be used inside a server."
                ),
                ephemeral=True
            )
            return

        await self.claim_daily(
            interaction.guild,
            interaction.user,
            interaction.response.send_message
        )

    # ========================================================
    # USER — BADGES
    # ========================================================

    @airlevel.command(
        name="badges",
        description="Show earned badges"
    )
    @app_commands.describe(
        member="Member to inspect"
    )
    async def airlevel_badges(
        self,
        interaction: discord.Interaction,
        member: Optional[discord.Member] = None
    ):

        if not interaction.guild:

            await interaction.response.send_message(
                embed=error_embed(
                    "This command can only be used inside a server."
                ),
                ephemeral=True
            )
            return

        member = (
            member
            or interaction.user
        )

        config = guild_config(
            interaction.guild.id
        )

        user = user_data(
            config,
            member.id
        )

        badges = user.get(
            "badges",
            []
        )

        if not badges:

            await interaction.response.send_message(
                embed=info_embed(
                    f"🎖️ {member.display_name}'s Badges",
                    "No badges earned yet."
                )
            )
            return

        label = "\n".join(
            f"• {badge}"
            for badge in badges
        )

        await interaction.response.send_message(
            embed=discord.Embed(
                title=(
                    f"🎖️ {member.display_name}'s Badges"
                ),
                description=label,
                color=GOLD_COLOR
            )
        )

    # ========================================================
    # USER — SEASON
    # ========================================================

    @airlevel.command(
        name="season",
        description="Show current season progress"
    )
    async def airlevel_season(
        self,
        interaction: discord.Interaction
    ):

        if not interaction.guild:

            await interaction.response.send_message(
                embed=error_embed(
                    "This command can only be used inside a server."
                ),
                ephemeral=True
            )
            return

        config = guild_config(
            interaction.guild.id
        )

        season = config["season"]

        started = float(
            season.get(
                "started",
                time.time()
            )
        )

        days = max(
            0,
            int(
                (
                    time.time()
                    - started
                )
                / 86400
            )
        )

        embed = discord.Embed(
            title=(
                f"🏆 Season "
                f"{season.get('number', 1)}"
            ),
            description=(
                f"Season XP: "
                f"**{season.get('xp', 0):,} XP**\n"
                f"Season age: **{days} days**"
            ),
            color=PURPLE_COLOR
        )

        await interaction.response.send_message(
            embed=embed
        )

    # ========================================================
    # USER — QUEST
    # ========================================================

    def build_quest_embed(
        self,
        config,
        user_id
    ):

        reset_weekly_quest_if_needed(
            config
        )

        quest = config["quests"]

        progress = int(
            quest.get(
                "progress",
                {}
            ).get(
                str(user_id),
                0
            )
        )

        target = int(
            quest.get(
                "target",
                WEEKLY_QUEST_TARGET
            )
        )

        reward = int(
            quest.get(
                "reward",
                WEEKLY_QUEST_REWARD
            )
        )

        percent = (
            min(
                100,
                progress / target * 100
            )
            if target
            else 100
        )

        user = user_data(
            config,
            user_id
        )

        claimed = user.get(
            "quest_claimed",
            False
        )

        if claimed:
            status = "🎁 Reward Claimed"

        elif progress >= target:
            status = "✅ Completed"

        else:
            status = "🔥 In Progress"

        return discord.Embed(
            title=(
                f"⚔️ {quest.get('name', 'Weekly Quest')}"
            ),
            description=(
                f"{quest.get('description', '')}\n\n"
                f"**Progress:** "
                f"`{progress}/{target}`\n"
                f"`{progress_bar(progress, target)}`\n"
                f"**{percent:.1f}%**\n\n"
                f"**Reward:** `{reward} XP`\n"
                f"**Status:** {status}"
            ),
            color=ORANGE_COLOR
        )

    @airlevel.command(
        name="quest",
        description="Show the current weekly quest"
    )
    async def airlevel_quest(
        self,
        interaction: discord.Interaction
    ):

        if not interaction.guild:

            await interaction.response.send_message(
                embed=error_embed(
                    "This command can only be used inside a server."
                ),
                ephemeral=True
            )
            return

        config = guild_config(
            interaction.guild.id
        )

        await interaction.response.send_message(
            embed=self.build_quest_embed(
                config,
                interaction.user.id
            )
        )

    # ========================================================
    # USER — BATTLE PASS
    # ========================================================

    @airlevel.command(
        name="battlepass",
        description="Show the Air Battle Pass"
    )
    async def airlevel_battlepass(
        self,
        interaction: discord.Interaction
    ):

        embed = discord.Embed(
            title="🎮 Air Battle Pass",
            description=(
                "**Tier 1** → 100 XP\n"
                "**Tier 2** → Level 5\n"
                "**Tier 3** → 500 XP\n"
                "**Tier 4** → Special Role Reward\n"
                "**Tier 5** → Elite Air Badge"
            ),
            color=discord.Color.dark_magenta()
        )

        embed.set_footer(
            text="Air Commander • Air Battle Pass"
        )

        await interaction.response.send_message(
            embed=embed
        )

    # ========================================================
    # USER — REWARDS
    # ========================================================

    @airlevel.command(
        name="rewards",
        description="Show level reward milestones"
    )
    async def airlevel_rewards(
        self,
        interaction: discord.Interaction
    ):

        if not interaction.guild:

            await interaction.response.send_message(
                embed=error_embed(
                    "This command can only be used inside a server."
                ),
                ephemeral=True
            )
            return

        config = guild_config(
            interaction.guild.id
        )

        rewards = config.get(
            "role_rewards",
            {}
        )

        if not rewards:

            await interaction.response.send_message(
                embed=info_embed(
                    "🎖️ Reward Milestones",
                    "No reward roles are configured yet."
                )
            )
            return

        sorted_rewards = sorted(
            rewards.items(),
            key=lambda item: int(
                item[0]
            )
        )

        lines = []

        for level, role_id in sorted_rewards:

            lines.append(
                f"**Level {level}** → "
                f"<@&{role_id}>"
            )

        await interaction.response.send_message(
            embed=discord.Embed(
                title="🎖️ Reward Milestones",
                description="\n".join(lines),
                color=GOLD_COLOR
            )
        )

    # ========================================================
    # USER — BOOST
    # ========================================================

    @airlevel.command(
        name="boost",
        description="View active XP boosters"
    )
    async def airlevel_boost(
        self,
        interaction: discord.Interaction
    ):

        if not interaction.guild:

            await interaction.response.send_message(
                embed=error_embed(
                    "This command can only be used inside a server."
                ),
                ephemeral=True
            )
            return

        config = guild_config(
            interaction.guild.id
        )

        roles = config.get(
            "role_boosters",
            {}
        )

        channels = config.get(
            "channel_boosters",
            {}
        )

        lines = []

        for role_id, boost in roles.items():

            lines.append(
                f"<@&{role_id}> → "
                f"**{boost}x XP**"
            )

        for channel_id, boost in channels.items():

            lines.append(
                f"<#{channel_id}> → "
                f"**{boost}x XP**"
            )

        text = (
            "\n".join(lines)
            if lines
            else "No XP boosters enabled."
        )

        await interaction.response.send_message(
            embed=discord.Embed(
                title="⚡ XP Boosts",
                description=text,
                color=discord.Color.from_rgb(
                    255,
                    153,
                    51
                )
            )
        )

    # ========================================================
    # USER — HELP
    # ========================================================

    @airlevel.command(
        name="help",
        description="Show Air Leveling commands"
    )
    async def airlevel_help(
        self,
        interaction: discord.Interaction
    ):

        text = (
            "```text\n"
            "USER\n"
            "/airlevel rank\n"
            "/airlevel profile\n"
            "/airlevel leaderboard\n"
            "/airlevel streak\n"
            "/airlevel daily\n"
            "/airlevel badges\n"
            "/airlevel season\n"
            "/airlevel quest\n"
            "/airlevel battlepass\n"
            "/airlevel rewards\n"
            "/airlevel boost\n"
            "\n"
            "ADMIN\n"
            "/airlevel settings\n"
            "/airlevel enable\n"
            "/airlevel disable\n"
            "/airlevel channel\n"
            "/airlevel announce\n"
            "/airlevel xp\n"
            "/airlevel cooldown\n"
            "/airlevel ignorechannel\n"
            "/airlevel ignorerole\n"
            "/airlevel reward\n"
            "/airlevel roleboost\n"
            "/airlevel channelboost\n"
            "/airlevel reset user\n"
            "/airlevel reset server\n"
            "\n"
            "MESSAGE STATS\n"
            "/message\n"
            ",m\n"
            ",message\n"
            "```"
        )

        await interaction.response.send_message(
            embed=info_embed(
                "📖 Air Leveling Help",
                text
            )
        )

    # ========================================================
    # ADMIN CHECK
    # ========================================================

    def is_admin(
        self,
        interaction
    ):
        return (
            interaction.user.guild_permissions.administrator
            or interaction.user.guild_permissions.manage_guild
        )

    async def require_admin(
        self,
        interaction
    ):

        if self.is_admin(
            interaction
        ):
            return True

        await interaction.response.send_message(
            embed=error_embed(
                "You need **Administrator** or "
                "**Manage Server** permission."
            ),
            ephemeral=True
        )

        return False

    # ========================================================
    # ADMIN — ENABLE
    # ========================================================

    @airlevel.command(
        name="enable",
        description="Enable Air Leveling"
    )
    async def airlevel_enable(
        self,
        interaction: discord.Interaction
    ):

        if not await self.require_admin(
            interaction
        ):
            return

        config = guild_config(
            interaction.guild.id
        )

        config["enabled"] = True

        save_data(DATA)

        await interaction.response.send_message(
            embed=success_embed(
                "Air Leveling Enabled",
                "XP leveling is now enabled."
            )
        )

    # ========================================================
    # ADMIN — DISABLE
    # ========================================================

    @airlevel.command(
        name="disable",
        description="Disable Air Leveling"
    )
    async def airlevel_disable(
        self,
        interaction: discord.Interaction
    ):

        if not await self.require_admin(
            interaction
        ):
            return

        config = guild_config(
            interaction.guild.id
        )

        config["enabled"] = False

        save_data(DATA)

        await interaction.response.send_message(
            embed=success_embed(
                "Air Leveling Disabled",
                "XP gain and leveling are now disabled."
            )
        )

    # ========================================================
    # ADMIN — SETTINGS
    # ========================================================

    @airlevel.command(
        name="settings",
        description="View Air Leveling configuration"
    )
    async def airlevel_settings(
        self,
        interaction: discord.Interaction
    ):

        if not await self.require_admin(
            interaction
        ):
            return

        config = guild_config(
            interaction.guild.id
        )

        channel_id = config.get(
            "announce_channel"
        )

        channel_text = (
            f"<#{channel_id}>"
            if channel_id
            else "Automatic — current chat channel"
        )

        embed = discord.Embed(
            title="⚙️ Air Leveling Settings",
            color=EMBED_COLOR
        )

        embed.add_field(
            name="Status",
            value=(
                "🟢 Enabled"
                if config["enabled"]
                else "🔴 Disabled"
            ),
            inline=True
        )

        embed.add_field(
            name="XP / Message",
            value=(
                f"`{config['xp_per_message']}`"
            ),
            inline=True
        )

        embed.add_field(
            name="Cooldown",
            value=(
                f"`{config['cooldown']}s`"
            ),
            inline=True
        )

        embed.add_field(
            name="Announcement",
            value=(
                "🟢 Enabled"
                if config["announce"]
                else "🔴 Disabled"
            ),
            inline=True
        )

        embed.add_field(
            name="Level-Up Channel",
            value=channel_text,
            inline=True
        )

        embed.add_field(
            name="Ignored Channels",
            value=(
                f"`{len(config.get('ignored_channels', []))}`"
            ),
            inline=True
        )

        embed.add_field(
            name="Ignored Roles",
            value=(
                f"`{len(config.get('ignored_roles', []))}`"
            ),
            inline=True
        )

        embed.add_field(
            name="Role Rewards",
            value=(
                f"`{len(config.get('role_rewards', {}))}`"
            ),
            inline=True
        )

        embed.add_field(
            name="Role Boosters",
            value=(
                f"`{len(config.get('role_boosters', {}))}`"
            ),
            inline=True
        )

        embed.add_field(
            name="Channel Boosters",
            value=(
                f"`{len(config.get('channel_boosters', {}))}`"
            ),
            inline=True
        )

        embed.set_footer(
            text="Air Commander • Leveling Configuration"
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )

    # ========================================================
    # ADMIN — CHANNEL
    # ========================================================

    @airlevel.command(
        name="channel",
        description="Set or clear the level-up announcement channel"
    )
    @app_commands.describe(
        action="Set or clear",
        channel="Channel for level-up announcements"
    )
    @app_commands.choices(
        action=[
            app_commands.Choice(
                name="set",
                value="set"
            ),
            app_commands.Choice(
                name="clear",
                value="clear"
            )
        ]
    )
    async def airlevel_channel(
        self,
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        channel: Optional[discord.TextChannel] = None
    ):

        if not await self.require_admin(
            interaction
        ):
            return

        config = guild_config(
            interaction.guild.id
        )

        if action.value == "set":

            if channel is None:

                await interaction.response.send_message(
                    embed=error_embed(
                        "Please select a channel when using `set`."
                    ),
                    ephemeral=True
                )
                return

            config["announce_channel"] = (
                channel.id
            )

            save_data(DATA)

            await interaction.response.send_message(
                embed=success_embed(
                    "Level-Up Channel Set",
                    (
                        f"All level-up announcements "
                        f"will now go to "
                        f"{channel.mention}."
                    )
                )
            )

            return

        config["announce_channel"] = None

        save_data(DATA)

        await interaction.response.send_message(
            embed=success_embed(
                "Level-Up Channel Cleared",
                (
                    "No fixed leveling channel is configured.\n\n"
                    "Level-up messages will now appear in the "
                    "**same channel where the user earned the level**."
                )
            )
        )

    # ========================================================
    # ADMIN — ANNOUNCE
    # ========================================================

    @airlevel.command(
        name="announce",
        description="Enable or disable level-up announcements"
    )
    @app_commands.describe(
        action="Enable or disable announcements"
    )
    @app_commands.choices(
        action=[
            app_commands.Choice(
                name="enable",
                value="enable"
            ),
            app_commands.Choice(
                name="disable",
                value="disable"
            )
        ]
    )
    async def airlevel_announce(
        self,
        interaction: discord.Interaction,
        action: app_commands.Choice[str]
    ):

        if not await self.require_admin(
            interaction
        ):
            return

        config = guild_config(
            interaction.guild.id
        )

        config["announce"] = (
            action.value == "enable"
        )

        save_data(DATA)

        await interaction.response.send_message(
            embed=success_embed(
                "Announcement Settings Updated",
                (
                    "Level-up announcements are now "
                    f"**{action.value}**."
                )
            )
        )

    # ========================================================
    # ADMIN — XP
    # ========================================================

    @airlevel.command(
        name="xp",
        description="Set XP earned per message"
    )
    @app_commands.describe(
        amount="XP amount per eligible message"
    )
    async def airlevel_xp(
        self,
        interaction: discord.Interaction,
        amount: app_commands.Range[
            int,
            1,
            10000
        ]
    ):

        if not await self.require_admin(
            interaction
        ):
            return

        config = guild_config(
            interaction.guild.id
        )

        config["xp_per_message"] = int(
            amount
        )

        save_data(DATA)

        await interaction.response.send_message(
            embed=success_embed(
                "XP Updated",
                (
                    f"Users will now receive "
                    f"**{amount} XP** per eligible message."
                )
            )
        )

    # ========================================================
    # ADMIN — COOLDOWN
    # ========================================================

    @airlevel.command(
        name="cooldown",
        description="Set XP cooldown in seconds"
    )
    @app_commands.describe(
        seconds="XP cooldown between messages"
    )
    async def airlevel_cooldown(
        self,
        interaction: discord.Interaction,
        seconds: app_commands.Range[
            int,
            0,
            3600
        ]
    ):

        if not await self.require_admin(
            interaction
        ):
            return

        config = guild_config(
            interaction.guild.id
        )

        config["cooldown"] = int(
            seconds
        )

        save_data(DATA)

        await interaction.response.send_message(
            embed=success_embed(
                "Cooldown Updated",
                (
                    f"XP cooldown is now "
                    f"**{seconds} seconds**."
                )
            )
        )

    # ========================================================
    # ADMIN — IGNORE CHANNEL
    # ========================================================

    @airlevel.command(
        name="ignorechannel",
        description="Toggle XP for a channel"
    )
    @app_commands.describe(
        channel="Channel to ignore or unignore"
    )
    async def airlevel_ignorechannel(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel
    ):

        if not await self.require_admin(
            interaction
        ):
            return

        config = guild_config(
            interaction.guild.id
        )

        ignored = config.setdefault(
            "ignored_channels",
            []
        )

        if channel.id in ignored:

            ignored.remove(
                channel.id
            )

            action = "enabled"

        else:

            ignored.append(
                channel.id
            )

            action = "ignored"

        save_data(DATA)

        await interaction.response.send_message(
            embed=success_embed(
                "Channel Updated",
                (
                    f"{channel.mention} XP is now "
                    f"**{action}**."
                )
            )
        )

    # ========================================================
    # ADMIN — IGNORE ROLE
    # ========================================================

    @airlevel.command(
        name="ignorerole",
        description="Toggle XP for members with a role"
    )
    @app_commands.describe(
        role="Role to ignore or unignore"
    )
    async def airlevel_ignorerole(
        self,
        interaction: discord.Interaction,
        role: discord.Role
    ):

        if not await self.require_admin(
            interaction
        ):
            return

        config = guild_config(
            interaction.guild.id
        )

        ignored = config.setdefault(
            "ignored_roles",
            []
        )

        if role.id in ignored:

            ignored.remove(
                role.id
            )

            action = "enabled"

        else:

            ignored.append(
                role.id
            )

            action = "ignored"

        save_data(DATA)

        await interaction.response.send_message(
            embed=success_embed(
                "Role Updated",
                (
                    f"{role.mention} XP is now "
                    f"**{action}**."
                )
            )
        )

    # ========================================================
    # ADMIN — REWARD
    # ========================================================

    @airlevel.command(
        name="reward",
        description="Set or remove a level reward role"
    )
    @app_commands.describe(
        action="Set or remove",
        level="Level number",
        role="Reward role"
    )
    @app_commands.choices(
        action=[
            app_commands.Choice(
                name="set",
                value="set"
            ),
            app_commands.Choice(
                name="remove",
                value="remove"
            )
        ]
    )
    async def airlevel_reward(
        self,
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        level: app_commands.Range[
            int,
            1,
            10000
        ],
        role: Optional[discord.Role] = None
    ):

        if not await self.require_admin(
            interaction
        ):
            return

        config = guild_config(
            interaction.guild.id
        )

        rewards = config.setdefault(
            "role_rewards",
            {}
        )

        if action.value == "set":

            if role is None:

                await interaction.response.send_message(
                    embed=error_embed(
                        "Select a role when using `set`."
                    ),
                    ephemeral=True
                )
                return

            rewards[str(level)] = role.id

            save_data(DATA)

            await interaction.response.send_message(
                embed=success_embed(
                    "Level Reward Set",
                    (
                        f"Level **{level}** → "
                        f"{role.mention}"
                    )
                )
            )

            return

        rewards.pop(
            str(level),
            None
        )

        save_data(DATA)

        await interaction.response.send_message(
            embed=success_embed(
                "Level Reward Removed",
                (
                    f"Reward for level "
                    f"**{level}** was removed."
                )
            )
        )

    # ========================================================
    # ADMIN — ROLE BOOST
    # ========================================================

    @airlevel.command(
        name="roleboost",
        description="Set a role XP multiplier"
    )
    @app_commands.describe(
        role="Role that receives the booster",
        multiplier="XP multiplier, e.g. 1.5 or 2.0"
    )
    async def airlevel_roleboost(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
        multiplier: app_commands.Range[
            float,
            1.0,
            10.0
        ]
    ):

        if not await self.require_admin(
            interaction
        ):
            return

        config = guild_config(
            interaction.guild.id
        )

        config.setdefault(
            "role_boosters",
            {}
        )[str(role.id)] = float(
            multiplier
        )

        save_data(DATA)

        await interaction.response.send_message(
            embed=success_embed(
                "Role XP Booster Set",
                (
                    f"{role.mention} now receives "
                    f"**{multiplier}x XP**."
                )
            )
        )

    # ========================================================
    # ADMIN — CHANNEL BOOST
    # ========================================================

    @airlevel.command(
        name="channelboost",
        description="Set a channel XP multiplier"
    )
    @app_commands.describe(
        channel="Channel that receives the booster",
        multiplier="XP multiplier, e.g. 1.5 or 2.0"
    )
    async def airlevel_channelboost(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        multiplier: app_commands.Range[
            float,
            1.0,
            10.0
        ]
    ):

        if not await self.require_admin(
            interaction
        ):
            return

        config = guild_config(
            interaction.guild.id
        )

        config.setdefault(
            "channel_boosters",
            {}
        )[str(channel.id)] = float(
            multiplier
        )

        save_data(DATA)

        await interaction.response.send_message(
            embed=success_embed(
                "Channel XP Booster Set",
                (
                    f"{channel.mention} now gives "
                    f"**{multiplier}x XP**."
                )
            )
        )

    # ========================================================
    # RESET USER
    # /airlevel reset user
    # ========================================================

    @reset.command(
        name="user",
        description="Reset a member's leveling data"
    )
    @app_commands.describe(
        member="Member whose XP should be reset"
    )
    async def airlevel_resetuser(
        self,
        interaction: discord.Interaction,
        member: discord.Member
    ):

        if not await self.require_admin(
            interaction
        ):
            return

        config = guild_config(
            interaction.guild.id
        )

        uid = str(
            member.id
        )

        config["users"].pop(
            uid,
            None
        )

        config["quests"].get(
            "progress",
            {}
        ).pop(
            uid,
            None
        )

        config["quests"].get(
            "claimed",
            {}
        ).pop(
            uid,
            None
        )

        # Also clear runtime cooldown.
        self.cooldowns.pop(
            (
                interaction.guild.id,
                member.id
            ),
            None
        )

        save_data(DATA)

        await interaction.response.send_message(
            embed=success_embed(
                "User Reset",
                (
                    f"{member.mention}'s "
                    f"Air Leveling data was reset."
                )
            )
        )

    # ========================================================
    # RESET SERVER
    # /airlevel reset server
    # ========================================================

    @reset.command(
        name="server",
        description="Reset all server leveling data"
    )
    async def airlevel_resetserver(
        self,
        interaction: discord.Interaction
    ):

        if not await self.require_admin(
            interaction
        ):
            return

        guild_id = str(
            interaction.guild.id
        )

        DATA[guild_id] = default_config()

        # Clear runtime cooldowns for this guild.
        keys_to_remove = [
            key
            for key in self.cooldowns
            if key[0] == interaction.guild.id
        ]

        for key in keys_to_remove:
            self.cooldowns.pop(
                key,
                None
            )

        save_data(DATA)

        await interaction.response.send_message(
            embed=success_embed(
                "Server Leveling Reset",
                (
                    "All Air Leveling XP, ranks, "
                    "streaks and reward data "
                    "for this server has been reset."
                )
            )
        )

    # ========================================================
    # PREFIX GROUP
    # ========================================================

    @commands.group(
        name="airlevel",
        invoke_without_command=True
    )
    async def prefix_airlevel(
        self,
        ctx
    ):

        if not ctx.guild:
            return

        await ctx.send(
            embed=info_embed(
                "📖 Air Leveling Help",
                (
                    "Use:\n"
                    "`,airlevel rank`\n"
                    "`,airlevel profile`\n"
                    "`,airlevel leaderboard`\n"
                    "`,airlevel streak`\n"
                    "`,airlevel daily`\n"
                    "`,airlevel quest`\n"
                    "`,airlevel settings`"
                )
            )
        )

    # ========================================================
    # PREFIX RANK
    # ========================================================

    @prefix_airlevel.command(
        name="rank"
    )
    async def prefix_airlevel_rank(
        self,
        ctx,
        member: Optional[discord.Member] = None
    ):

        member = (
            member
            or ctx.author
        )

        await ctx.send(
            embed=self.build_rank_embed(
                ctx.guild,
                member
            )
        )

    # ========================================================
    # PREFIX PROFILE
    # ========================================================

    @prefix_airlevel.command(
        name="profile"
    )
    async def prefix_airlevel_profile(
        self,
        ctx,
        member: Optional[discord.Member] = None
    ):

        member = (
            member
            or ctx.author
        )

        await ctx.send(
            embed=self.build_rank_embed(
                ctx.guild,
                member
            )
        )

    # ========================================================
    # PREFIX LEADERBOARD
    # ========================================================

    @prefix_airlevel.command(
        name="leaderboard"
    )
    async def prefix_airlevel_leaderboard(
        self,
        ctx
    ):

        embed = self.build_leaderboard_embed(
            ctx.guild
        )

        if embed is None:

            await ctx.send(
                embed=info_embed(
                    "📊 No XP Data",
                    "No XP data exists in this server yet."
                )
            )
            return

        await ctx.send(
            embed=embed
        )

    # ========================================================
    # PREFIX DAILY
    # ========================================================

    @prefix_airlevel.command(
        name="daily"
    )
    async def prefix_airlevel_daily(
        self,
        ctx
    ):

        await self.claim_daily(
            ctx.guild,
            ctx.author,
            ctx.send
        )

    # ========================================================
    # PREFIX STREAK
    # ========================================================

    @prefix_airlevel.command(
        name="streak"
    )
    async def prefix_airlevel_streak(
        self,
        ctx,
        member: Optional[discord.Member] = None
    ):

        member = (
            member
            or ctx.author
        )

        config = guild_config(
            ctx.guild.id
        )

        user = user_data(
            config,
            member.id
        )

        embed = discord.Embed(
            title=(
                f"🔥 {member.display_name}'s Streak"
            ),
            description=(
                f"Current streak: "
                f"**{user['streak']} days**\n"
                f"Best streak: "
                f"**{user['best_streak']} days**"
            ),
            color=ORANGE_COLOR
        )

        embed.set_thumbnail(
            url=member.display_avatar.url
        )

        await ctx.send(
            embed=embed
        )

    # ========================================================
    # PREFIX QUEST
    # ========================================================

    @prefix_airlevel.command(
        name="quest"
    )
    async def prefix_airlevel_quest(
        self,
        ctx
    ):

        config = guild_config(
            ctx.guild.id
        )

        await ctx.send(
            embed=self.build_quest_embed(
                config,
                ctx.author.id
            )
        )

    # ========================================================
    # PREFIX HELP
    # ========================================================

    @prefix_airlevel.command(
        name="help"
    )
    async def prefix_airlevel_help(
        self,
        ctx
    ):

        await ctx.send(
            embed=info_embed(
                "📖 Air Leveling Help",
                (
                    "`,airlevel rank`\n"
                    "`,airlevel profile`\n"
                    "`,airlevel leaderboard`\n"
                    "`,airlevel streak`\n"
                    "`,airlevel daily`\n"
                    "`,airlevel quest`\n"
                    "`,airlevel settings`\n"
                    "\n"
                    "Message Stats:\n"
                    "`,m`\n"
                    "`,message`\n"
                    "`,messages`"
                )
            )
        )

    # ========================================================
    # SHORTCUT — AIRRANK
    # ========================================================

    @commands.command(
        name="airrank",
        aliases=[
            "airlevelrank"
        ]
    )
    async def prefix_airrank(
        self,
        ctx,
        member: Optional[discord.Member] = None
    ):

        member = (
            member
            or ctx.author
        )

        await ctx.send(
            embed=self.build_rank_embed(
                ctx.guild,
                member
            )
        )

    # ========================================================
    # SHORTCUT — AIRLEADERBOARD
    # ========================================================

    @commands.command(
        name="airleaderboard",
        aliases=[
            "airlb"
        ]
    )
    async def prefix_airleaderboard(
        self,
        ctx
    ):

        embed = self.build_leaderboard_embed(
            ctx.guild
        )

        if embed is None:

            await ctx.send(
                embed=info_embed(
                    "📊 No XP Data",
                    "No XP data exists in this server yet."
                )
            )
            return

        await ctx.send(
            embed=embed
        )

    # ========================================================
    # SHORTCUT — AIRSTREAK
    # ========================================================

    @commands.command(
        name="airstreak"
    )
    async def prefix_airstreak(
        self,
        ctx,
        member: Optional[discord.Member] = None
    ):

        member = (
            member
            or ctx.author
        )

        config = guild_config(
            ctx.guild.id
        )

        user = user_data(
            config,
            member.id
        )

        embed = discord.Embed(
            title=(
                f"🔥 {member.display_name}'s Streak"
            ),
            description=(
                f"Current streak: "
                f"**{user['streak']} days**\n"
                f"Best streak: "
                f"**{user['best_streak']} days**"
            ),
            color=ORANGE_COLOR
        )

        await ctx.send(
            embed=embed
        )

    # ========================================================
    # SHORTCUT — AIRDAILY
    # ========================================================

    @commands.command(
        name="airdaily"
    )
    async def prefix_airdaily(
        self,
        ctx
    ):

        await self.claim_daily(
            ctx.guild,
            ctx.author,
            ctx.send
        )

    # ========================================================
    # MESSAGE COUNT — PREFIX
    #
    # ,m
    # ,message
    # ,messages
    # ========================================================

    @commands.command(
        name="m",
        aliases=[
            "message",
            "messages"
        ]
    )
    async def message_count(
        self,
        ctx,
        member: Optional[discord.Member] = None
    ):

        if not ctx.guild:
            return

        member = (
            member
            or ctx.author
        )

        config = guild_config(
            ctx.guild.id
        )

        user = user_data(
            config,
            member.id
        )

        stats = get_message_stats(
            user
        )

        embed = discord.Embed(
            title=(
                f"💬 {member.display_name}'s "
                f"Message Stats"
            ),
            description=(
                f"{member.mention}\n\n"
                f"📅 **Today**\n"
                f"`{stats['today']:,}` messages\n\n"
                f"📆 **Week**\n"
                f"`{stats['week']:,}` messages\n\n"
                f"🗓️ **Month**\n"
                f"`{stats['month']:,}` messages\n\n"
                f"💬 **All Time**\n"
                f"`{stats['all']:,}` messages"
            ),
            color=discord.Color.blurple()
        )

        embed.set_thumbnail(
            url=member.display_avatar.url
        )

        embed.set_footer(
            text="Air Commander • Message Statistics"
        )

        await ctx.send(
            embed=embed
        )

    # ========================================================
    # MESSAGE COUNT — SLASH
    #
    # /message
    # ========================================================

    @app_commands.command(
        name="message",
        description="View message statistics"
    )
    @app_commands.describe(
        member="Member whose message statistics you want to see"
    )
    async def slash_message(
        self,
        interaction: discord.Interaction,
        member: Optional[discord.Member] = None
    ):

        if not interaction.guild:

            await interaction.response.send_message(
                "This command can only be used inside a server.",
                ephemeral=True
            )
            return

        member = (
            member
            or interaction.user
        )

        config = guild_config(
            interaction.guild.id
        )

        user = user_data(
            config,
            member.id
        )

        stats = get_message_stats(
            user
        )

        embed = discord.Embed(
            title=(
                f"💬 {member.display_name}'s "
                f"Message Stats"
            ),
            description=(
                f"{member.mention}\n\n"
                f"📅 **Today** — "
                f"`{stats['today']:,}`\n"
                f"📆 **Week** — "
                f"`{stats['week']:,}`\n"
                f"🗓️ **Month** — "
                f"`{stats['month']:,}`\n"
                f"💬 **All Time** — "
                f"`{stats['all']:,}`"
            ),
            color=discord.Color.blurple()
        )

        embed.set_thumbnail(
            url=member.display_avatar.url
        )

        embed.set_footer(
            text="Air Commander • Message Statistics"
        )

        await interaction.response.send_message(
            embed=embed
        )


# ============================================================
# SETUP
# ============================================================

async def setup(bot):

    await bot.add_cog(
        AirLeveling(bot)
    )

    print(
        "✅ Air Leveling loaded"
    )
