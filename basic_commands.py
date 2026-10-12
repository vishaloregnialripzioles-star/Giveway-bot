import discord
from discord import app_commands
from discord.ext import commands
from datetime import timedelta
import time


# =========================================================
# AIR COMMANDER — COMMON EMBED
# =========================================================

def embed(title, description="", color=discord.Color.blurple()):
    e = discord.Embed(
        title=f"✈️ {title}",
        description=description,
        color=color,
        timestamp=discord.utils.utcnow()
    )
    e.set_footer(text="Air Commander • Clean control center")
    return e


def format_count(number: int) -> str:
    if number >= 1_000_000_000:
        return f"{number / 1_000_000_000:.1f}B".rstrip("0").rstrip(".")

    if number >= 1_000_000:
        return f"{number / 1_000_000:.1f}M".rstrip("0").rstrip(".")

    if number >= 1_000:
        return f"{number / 1_000:.1f}k".rstrip("0").rstrip(".")

    return str(number)


# =========================================================
# AIR COMMANDER — ADVANCED HELP CENTER DATA
# =========================================================

HELP_CATEGORIES = [
    ("⚙️", "Setup"),
    ("🛠️", "Moderation"),
    ("🛡️", "Security"),
    ("📢", "Channels"),
    ("🚫", "Restrictions"),
    ("🔧", "Utility"),
    ("📈", "Leveling"),
    ("🎭", "Roles"),
    ("🎫", "Tickets"),
    ("💰", "Economy"),
    ("🎮", "Games"),
    ("🎉", "Fun"),
    ("🎁", "Giveaways"),
    ("🎵", "Music"),
    ("🌐", "Social"),
    ("🍎", "Blox Fruits"),
    ("🤖", "AI"),
    ("✨", "Other"),
]


# =========================================================
# COMMAND CATEGORY MAPPING
# =========================================================

HELP_COMMAND_MAP = {

    "⚙️ Setup": {
        "setup",
        "config",
        "settings",
        "serverconfig",
        "prefix",
        "automode",
        "antinuke",
        "antilink",
    },

    "🛠️ Moderation": {
        "clear",
        "purge",
        "kick",
        "ban",
        "unban",
        "timeout",
        "untimeout",
        "warn",
        "warnings",
        "unwarn",
        "mute",
        "unmute",
        "slowmode",
        "lock",
        "unlock",
        "nick",
        "role",
    },

    "🛡️ Security": {
        "antinuke",
        "automode",
        "antilink",
        "security",
        "securitycenter",
        "airscan",
        "snipe",
        "diagnostics",
        "backup",
        "restore",
    },

    "📢 Channels": {
        "channel",
        "channelinfo",
        "announce",
        "announcement",
        "say",
        "poll",
        "welcome",
        "log",
        "logs",
        "modlog",
    },

    "🚫 Restrictions": {
        "restriction",
        "restrictions",
        "commandpermissions",
        "permissions",
        "blacklist",
        "whitelist",
        "badword",
        "filter",
    },

    "🔧 Utility": {
        "ping",
        "help",
        "about",
        "uptime",
        "botinfo",
        "serverinfo",
        "userinfo",
        "membercount",
        "membercard",
        "avatar",
        "servericon",
        "banner",
        "roleinfo",
        "channelinfo",
        "calculator",
        "translate",
        "weather",
        "remind",
        "reminder",
    },

    "📈 Leveling": {
        "level",
        "levels",
        "rank",
        "xp",
        "leveling",
        "leaderboard",
        "levelrole",
    },

    "🎭 Roles": {
        "role",
        "roles",
        "selfrole",
        "reactionrole",
        "autorole",
        "welcome",
        "rolepanel",
    },

    "🎫 Tickets": {
        "ticket",
        "tickets",
        "close",
        "reopen",
        "claim",
        "add",
        "remove",
        "rename",
    },

    "💰 Economy": {
        "balance",
        "bal",
        "cash",
        "money",
        "pay",
        "daily",
        "work",
        "shop",
        "buy",
        "sell",
        "deposit",
        "withdraw",
    },

    "🎮 Games": {
        "game",
        "games",
        "8ball",
        "coinflip",
        "dice",
        "rps",
    },

    "🎉 Fun": {
        "fun",
        "meme",
        "joke",
        "hug",
        "ship",
        "roast",
        "say",
        "poll",
    },

    "🎁 Giveaways": {
        "giveaway",
        "giveaways",
        "gstart",
        "gend",
        "greroll",
    },

    "🎵 Music": {
        "play",
        "pause",
        "resume",
        "skip",
        "stop",
        "queue",
        "volume",
        "loop",
        "music",
    },

    "🌐 Social": {
        "social",
        "profile",
        "bio",
        "friend",
        "friends",
        "youtube",
        "youtubealert",
    },

    "🍎 Blox Fruits": {
        "blox",
        "bloxfruits",
        "fruit",
        "fruits",
        "stock",
        "raid",
        "race",
    },

    "🤖 AI": {
        "ai",
        "ask",
        "chat",
        "search",
        "summarize",
        "translate",
        "image",
    },
}


# =========================================================
# HELP CATEGORY DETECTOR
# =========================================================

def _help_category(command_name: str) -> str:
    name = command_name.lower().strip()

    for category, names in HELP_COMMAND_MAP.items():
        if name in names:
            return category

    if "ticket" in name:
        return "🎫 Tickets"

    if "level" in name or "xp" in name or "rank" in name:
        return "📈 Leveling"

    if "role" in name:
        return "🎭 Roles"

    if any(x in name for x in (
        "ban",
        "kick",
        "warn",
        "mute",
        "timeout",
        "purge",
        "clear",
        "lock",
        "unlock"
    )):
        return "🛠️ Moderation"

    if any(x in name for x in (
        "security",
        "antinuke",
        "automode",
        "antilink",
        "protect",
        "scan"
    )):
        return "🛡️ Security"

    if any(x in name for x in (
        "giveaway",
        "giveaways"
    )):
        return "🎁 Giveaways"

    if any(x in name for x in (
        "music",
        "play",
        "pause",
        "skip",
        "queue"
    )):
        return "🎵 Music"

    if any(x in name for x in (
        "game",
        "dice",
        "coin",
        "rps"
    )):
        return "🎮 Games"

    if any(x in name for x in (
        "ai",
        "ask",
        "chat",
        "search"
    )):
        return "🤖 AI"

    return "✨ Other"


# =========================================================
# GET PREFIX COMMANDS
# =========================================================

def _get_prefix_commands(bot):
    result = {}

    for cmd in bot.commands:
        if getattr(cmd, "hidden", False):
            continue

        name = cmd.name.lower()

        if name not in result:
            result[name] = cmd

    return result


# =========================================================
# GET SLASH COMMANDS
# =========================================================

def _get_slash_commands(bot):
    result = {}

    try:
        for cmd in bot.tree.get_commands():

            if cmd.name.lower() not in result:
                result[cmd.name.lower()] = cmd

    except Exception as exc:
        print(
            f"⚠️ Help slash command collection error: {exc}"
        )

    return result


# =========================================================
# BUILD HELP COMMAND MAP
# =========================================================

def _build_help_command_map(bot, mode="prefix"):

    if mode == "slash":
        commands_map = _get_slash_commands(bot)
    else:
        commands_map = _get_prefix_commands(bot)

    categories = {
        category: []
        for _, category in HELP_CATEGORIES
    }

    for name, command in commands_map.items():

        category = _help_category(name)

        categories.setdefault(
            category,
            []
        ).append(command)

    for category in categories:
        categories[category].sort(
            key=lambda command: command.name.lower()
        )

    return categories


def _command_count(categories):
    return sum(
        len(commands_list)
        for commands_list in categories.values()
    )


# =========================================================
# HELP HOME EMBED
# =========================================================

def _help_home_embed(bot, mode="prefix"):

    categories = _build_help_command_map(
        bot,
        mode
    )

    total = _command_count(categories)

    prefix_text = "," if mode == "prefix" else "/"

    e = discord.Embed(
        title="✈️ Air Commander Help Center",
        description=(
            "✨ **Welcome to Air Commander**\n\n"
            "Your complete command directory, "
            "organized by category.\n\n"
            f"**Prefix:** `{prefix_text}`\n"
            f"**Command entries:** **{total}**\n\n"
        ),
        color=discord.Color.blurple(),
        timestamp=discord.utils.utcnow()
    )

    lines = []

    for emoji, category in HELP_CATEGORIES:

        amount = len(
            categories.get(
                category,
                []
            )
        )

        if amount > 0:
            lines.append(
                f"{emoji} **{category}** — **{amount}**"
            )

    e.description += (
        "\n".join(lines)
        + "\n\n"
        f"Use `{prefix_text}help <command>` "
        "or select a category below."
    )

    e.set_footer(
        text="✈️ Air Commander • Complete Command Directory"
    )

    return e


# =========================================================
# HELP CATEGORY EMBED
# =========================================================

def _help_category_embed(
    bot,
    category,
    mode="prefix"
):

    categories = _build_help_command_map(
        bot,
        mode
    )

    commands_list = categories.get(
        category,
        []
    )

    if not commands_list:

        return discord.Embed(
            title=f"✈️ {category}",
            description=(
                "No commands are currently "
                "registered in this category."
            ),
            color=discord.Color.orange(),
            timestamp=discord.utils.utcnow()
        )

    command_lines = []

    for command in commands_list:

        name = command.name

        if mode == "slash":

            description = getattr(
                command,
                "description",
                ""
            ) or "No description."

            command_lines.append(
                f"`/{name}` — {description}"
            )

        else:

            description = (
                getattr(
                    command,
                    "help",
                    None
                )
                or
                getattr(
                    command,
                    "brief",
                    None
                )
                or
                "No description."
            )

            command_lines.append(
                f"`,{name}` — {description}"
            )

    chunks = []
    current = []

    for line in command_lines:

        test_text = "\n".join(
            current + [line]
        )

        if len(test_text) > 1000:

            if current:
                chunks.append(
                    "\n".join(current)
                )

            current = [line]

        else:
            current.append(line)

    if current:
        chunks.append(
            "\n".join(current)
        )

    e = discord.Embed(
        title=f"✈️ Air Commander • {category}",
        description=(
            f"**{len(commands_list)} command(s)** "
            "available in this category."
        ),
        color=discord.Color.blurple(),
        timestamp=discord.utils.utcnow()
    )

    for index, chunk in enumerate(chunks):

        field_name = (
            "Commands"
            if index == 0
            else f"Commands • Page {index + 1}"
        )

        e.add_field(
            name=field_name,
            value=chunk,
            inline=False
        )

    e.set_footer(
        text="✈️ Air Commander • Command Directory"
    )

    return e


# =========================================================
# ALL COMMANDS EMBED
# =========================================================

def _help_all_embed(bot, mode="prefix"):

    categories = _build_help_command_map(
        bot,
        mode
    )

    prefix_text = "," if mode == "prefix" else "/"

    all_commands = []

    for _, category in HELP_CATEGORIES:

        for command in categories.get(
            category,
            []
        ):

            all_commands.append(
                (
                    category,
                    command
                )
            )

    known_categories = {
        category
        for _, category in HELP_CATEGORIES
    }

    for category, commands_list in categories.items():

        if category in known_categories:
            continue

        for command in commands_list:
            all_commands.append(
                (
                    category,
                    command
                )
            )

    e = discord.Embed(
        title="📚 Air Commander • All Commands",
        description=(
            f"**{len(all_commands)} command(s)**\n\n"
            "Complete command directory."
        ),
        color=discord.Color.blurple(),
        timestamp=discord.utils.utcnow()
    )

    lines = []

    for category, command in all_commands:

        lines.append(
            f"`{prefix_text}{command.name}`"
        )

    chunks = []
    current = []

    for line in lines:

        test = " • ".join(
            current + [line]
        )

        if len(test) > 3800:

            if current:
                chunks.append(
                    " • ".join(current)
                )

            current = [line]

        else:
            current.append(line)

    if current:
        chunks.append(
            " • ".join(current)
        )

    if not chunks:
        chunks = ["No commands are currently registered."]

    for index, chunk in enumerate(chunks):

        e.add_field(
            name=(
                "Commands"
                if index == 0
                else f"Commands • Page {index + 1}"
            ),
            value=chunk,
            inline=False
        )

    e.set_footer(
        text="✈️ Air Commander • All Commands"
    )

    return e


# =========================================================
# HELP SELECT MENU
# =========================================================

class HelpCategorySelect(discord.ui.Select):

    def __init__(self, bot, mode="prefix"):

        self.bot = bot
        self.mode = mode

        options = [
            discord.SelectOption(
                label="All Commands",
                value="__all__",
                emoji="📚",
                description="Show every available command"
            )
        ]

        categories = _build_help_command_map(
            bot,
            mode
        )

        for emoji, category in HELP_CATEGORIES:

            count = len(
                categories.get(
                    category,
                    []
                )
            )

            if count <= 0:
                continue

            options.append(
                discord.SelectOption(
                    label=category,
                    value=category,
                    emoji=emoji,
                    description=f"{count} command(s)"
                )
            )

        # Discord maximum = 25 options
        options = options[:25]

        super().__init__(
            placeholder="📚 Select a command category...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id=f"aircommander:help:{mode}"
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):

        selected = self.values[0]

        if selected == "__all__":

            result_embed = _help_all_embed(
                self.bot,
                self.mode
            )

        else:

            result_embed = _help_category_embed(
                self.bot,
                selected,
                self.mode
            )

        await interaction.response.edit_message(
            embed=result_embed,
            view=HelpView(
                self.bot,
                self.mode
            )
        )


# =========================================================
# HELP VIEW
# =========================================================

class HelpView(discord.ui.View):

    def __init__(
        self,
        bot,
        mode="prefix"
    ):

        super().__init__(
            timeout=300
        )

        self.add_item(
            HelpCategorySelect(
                bot,
                mode
            )
        )


# =========================================================
# SETUP
# =========================================================

def setup(bot: commands.Bot):

    # =====================================================
    # SLASH COMMANDS
    # =====================================================

    @bot.tree.command(
        name="clear",
        description="Delete recent messages"
    )
    @app_commands.describe(
        amount="Number of messages to delete (1-100)"
    )
    @app_commands.checks.has_permissions(
        manage_messages=True
    )
    async def clear(
        i: discord.Interaction,
        amount: app_commands.Range[int, 1, 100]
    ):

        if not isinstance(
            i.channel,
            discord.TextChannel
        ):
            return await i.response.send_message(
                "❌ This command works in text channels only.",
                ephemeral=True
            )

        await i.response.defer(
            ephemeral=True
        )

        deleted = await i.channel.purge(
            limit=amount
        )

        await i.followup.send(
            embed=embed(
                "Messages Cleared",
                f"Removed **{len(deleted)}** message(s) from {i.channel.mention}.",
                discord.Color.orange()
            ),
            ephemeral=True
        )

    # =====================================================
    # KICK
    # =====================================================

    @bot.tree.command(
        name="kick",
        description="Kick a member"
    )
    @app_commands.describe(
        member="Member to kick",
        reason="Reason for the action"
    )
    @app_commands.checks.has_permissions(
        kick_members=True
    )
    async def kick(
        i: discord.Interaction,
        member: discord.Member,
        reason: str = "No reason provided"
    ):

        if (
            member == i.user
            or member.top_role >= i.user.top_role
            or member.top_role >= i.guild.me.top_role
        ):
            return await i.response.send_message(
                "❌ That member cannot be kicked due to role hierarchy.",
                ephemeral=True
            )

        await member.kick(
            reason=f"{reason} | Moderator: {i.user}"
        )

        e = embed(
            "Member Kicked",
            f"{member.mention} was removed from the server.",
            discord.Color.red()
        )

        e.add_field(
            name="Moderator",
            value=i.user.mention
        )

        e.add_field(
            name="Reason",
            value=reason[:1024]
        )

        await i.response.send_message(
            embed=e
        )

    # =====================================================
    # BAN
    # =====================================================

    @bot.tree.command(
        name="ban",
        description="Ban a member"
    )
    @app_commands.describe(
        member="Member to ban",
        reason="Reason for the action",
        delete_days="Delete message history in days (0-7)"
    )
    @app_commands.checks.has_permissions(
        ban_members=True
    )
    async def ban(
        i: discord.Interaction,
        member: discord.Member,
        reason: str = "No reason provided",
        delete_days: app_commands.Range[int, 0, 7] = 0
    ):

        if (
            member == i.user
            or member.top_role >= i.user.top_role
            or member.top_role >= i.guild.me.top_role
        ):
            return await i.response.send_message(
                "❌ That member cannot be banned due to role hierarchy.",
                ephemeral=True
            )

        await member.ban(
            reason=f"{reason} | Moderator: {i.user}",
            delete_message_days=delete_days
        )

        e = embed(
            "Member Banned",
            f"{member.mention} was banned from the server.",
            discord.Color.red()
        )

        e.add_field(
            name="Moderator",
            value=i.user.mention
        )

        e.add_field(
            name="Reason",
            value=reason[:1024]
        )

        await i.response.send_message(
            embed=e
        )

    # =====================================================
    # UNBAN
    # =====================================================

    @bot.tree.command(
        name="unban",
        description="Unban a user by ID"
    )
    @app_commands.describe(
        user_id="Discord user ID",
        reason="Reason for the action"
    )
    @app_commands.checks.has_permissions(
        ban_members=True
    )
    async def unban(
        i: discord.Interaction,
        user_id: str,
        reason: str = "No reason provided"
    ):

        try:
            uid = int(user_id)

            await i.guild.unban(
                discord.Object(id=uid),
                reason=f"{reason} | Moderator: {i.user}"
            )

        except (
            ValueError,
            discord.NotFound
        ):
            return await i.response.send_message(
                "❌ No matching banned user was found.",
                ephemeral=True
            )

        e = embed(
            "Member Unbanned",
            f"User ID **{uid}** is no longer banned.",
            discord.Color.green()
        )

        e.add_field(
            name="Moderator",
            value=i.user.mention
        )

        e.add_field(
            name="Reason",
            value=reason[:1024]
        )

        await i.response.send_message(
            embed=e
        )

    # =====================================================
    # TIMEOUT
    # =====================================================

    @bot.tree.command(
        name="timeout",
        description="Timeout a member"
    )
    @app_commands.describe(
        member="Member to timeout",
        minutes="Timeout duration in minutes",
        reason="Reason"
    )
    @app_commands.checks.has_permissions(
        moderate_members=True
    )
    async def timeout(
        i: discord.Interaction,
        member: discord.Member,
        minutes: app_commands.Range[int, 1, 40320],
        reason: str = "No reason provided"
    ):

        if (
            member == i.user
            or member.top_role >= i.user.top_role
            or member.top_role >= i.guild.me.top_role
        ):
            return await i.response.send_message(
                "❌ That member cannot be timed out due to role hierarchy.",
                ephemeral=True
            )

        await member.timeout(
            timedelta(minutes=minutes),
            reason=f"{reason} | Moderator: {i.user}"
        )

        e = embed(
            "Member Timed Out",
            f"{member.mention} is timed out for **{minutes} minute(s)**.",
            discord.Color.orange()
        )

        e.add_field(
            name="Moderator",
            value=i.user.mention
        )

        e.add_field(
            name="Reason",
            value=reason[:1024]
        )

        await i.response.send_message(
            embed=e
        )

    # =====================================================
    # UNTIMEOUT
    # =====================================================

    @bot.tree.command(
        name="untimeout",
        description="Remove a member timeout"
    )
    @app_commands.describe(
        member="Member to untimeout",
        reason="Reason"
    )
    @app_commands.checks.has_permissions(
        moderate_members=True
    )
    async def untimeout(
        i: discord.Interaction,
        member: discord.Member,
        reason: str = "No reason provided"
    ):

        await member.timeout(
            None,
            reason=f"{reason} | Moderator: {i.user}"
        )

        e = embed(
            "Timeout Removed",
            f"Timeout removed from {member.mention}.",
            discord.Color.green()
        )

        e.add_field(
            name="Moderator",
            value=i.user.mention
        )

        e.add_field(
            name="Reason",
            value=reason[:1024]
        )

        await i.response.send_message(
            embed=e
        )

    # =====================================================
    # SLOWMODE
    # =====================================================

    @bot.tree.command(
        name="slowmode",
        description="Set channel slowmode"
    )
    @app_commands.describe(
        seconds="Slowmode seconds (0 disables it)"
    )
    @app_commands.checks.has_permissions(
        manage_channels=True
    )
    async def slowmode(
        i: discord.Interaction,
        seconds: app_commands.Range[int, 0, 21600]
    ):

        if not hasattr(i.channel, "edit"):
            return await i.response.send_message(
                "❌ This channel cannot use slowmode.",
                ephemeral=True
            )

        await i.channel.edit(
            slowmode_delay=seconds,
            reason=f"Changed by {i.user}"
        )

        e = embed(
            "Slowmode Updated",
            f"{i.channel.mention} slowmode is now **{seconds}s**.",
            discord.Color.teal()
        )

        await i.response.send_message(
            embed=e
        )

    # =====================================================
    # LOCK / UNLOCK
    # =====================================================

    async def set_lock(i, locked):

        if not isinstance(
            i.channel,
            discord.TextChannel
        ):
            return await i.response.send_message(
                "❌ Text channel only.",
                ephemeral=True
            )

        overwrite = i.channel.overwrites_for(
            i.guild.default_role
        )

        overwrite.send_messages = (
            False if locked else None
        )

        await i.channel.set_permissions(
            i.guild.default_role,
            overwrite=overwrite,
            reason=(
                f"Channel "
                f"{'locked' if locked else 'unlocked'} "
                f"by {i.user}"
            )
        )

        e = embed(
            "Channel Locked" if locked else "Channel Unlocked",
            (
                f"{i.channel.mention} is now "
                f"**{'locked' if locked else 'open'}** "
                "for @everyone."
            ),
            discord.Color.red()
            if locked
            else discord.Color.green()
        )

        await i.response.send_message(
            embed=e
        )

    @bot.tree.command(
        name="lock",
        description="Lock the current text channel"
    )
    @app_commands.checks.has_permissions(
        manage_channels=True
    )
    async def lock(i: discord.Interaction):
        await set_lock(i, True)

    @bot.tree.command(
        name="unlock",
        description="Unlock the current text channel"
    )
    @app_commands.checks.has_permissions(
        manage_channels=True
    )
    async def unlock(i: discord.Interaction):
        await set_lock(i, False)

    # =====================================================
    # NICK
    # =====================================================

    @bot.tree.command(
        name="nick",
        description="Change a member nickname"
    )
    @app_commands.describe(
        member="Member",
        nickname="New nickname"
    )
    @app_commands.checks.has_permissions(
        manage_nicknames=True
    )
    async def nick(
        i: discord.Interaction,
        member: discord.Member,
        nickname: str | None = None
    ):

        await member.edit(
            nick=nickname,
            reason=f"Nickname changed by {i.user}"
        )

        e = embed(
            "Nickname Updated",
            f"Updated nickname for {member.mention}."
        )

        e.add_field(
            name="New Nickname",
            value=nickname or "Reset to username"
        )

        await i.response.send_message(
            embed=e
        )

    # =====================================================
    # ROLE
    # =====================================================

    @bot.tree.command(
        name="role",
        description="Add or remove a role from a member"
    )
    @app_commands.describe(
        action="Add or remove",
        member="Member",
        role="Role"
    )
    @app_commands.choices(
        action=[
            app_commands.Choice(
                name="Add",
                value="add"
            ),
            app_commands.Choice(
                name="Remove",
                value="remove"
            )
        ]
    )
    @app_commands.checks.has_permissions(
        manage_roles=True
    )
    async def role(
        i: discord.Interaction,
        action: app_commands.Choice[str],
        member: discord.Member,
        role: discord.Role
    ):

        if (
            role.is_default()
            or role >= i.guild.me.top_role
        ):
            return await i.response.send_message(
                "❌ I cannot manage that role because of role hierarchy.",
                ephemeral=True
            )

        if action.value == "add":

            await member.add_roles(
                role,
                reason=f"Role added by {i.user}"
            )

        else:

            await member.remove_roles(
                role,
                reason=f"Role removed by {i.user}"
            )

        e = embed(
            "Role Updated",
            (
                f"{role.mention} was "
                f"**{action.name.lower()}** "
                f"for {member.mention}."
            ),
            discord.Color.green()
        )

        await i.response.send_message(
            embed=e
        )

    # =====================================================
    # SAY
    # =====================================================

    @bot.tree.command(
        name="say",
        description="Make Air Commander send a message"
    )
    @app_commands.describe(
        message="Message to send"
    )
    @app_commands.checks.has_permissions(
        manage_messages=True
    )
    async def say(
        i: discord.Interaction,
        message: str
    ):

        await i.response.send_message(
            embed=embed(
                "Message Sent",
                message,
                discord.Color.blurple()
            )
        )

    # =====================================================
    # ANNOUNCE
    # =====================================================

    @bot.tree.command(
        name="announce",
        description="Send a styled announcement"
    )
    @app_commands.describe(
        message="Announcement text"
    )
    @app_commands.checks.has_permissions(
        manage_guild=True
    )
    async def announce(
        i: discord.Interaction,
        message: str
    ):

        e = embed(
            "Announcement",
            message,
            discord.Color.gold()
        )

        if i.guild.icon:
            e.set_author(
                name=i.guild.name,
                icon_url=i.guild.icon.url
            )
        else:
            e.set_author(
                name=i.guild.name
            )

        await i.response.send_message(
            embed=e
        )

    # =====================================================
    # POLL
    # =====================================================

    @bot.tree.command(
        name="poll",
        description="Create a simple yes/no poll"
    )
    @app_commands.describe(
        question="Poll question"
    )
    async def poll(
        i: discord.Interaction,
        question: str
    ):

        e = embed(
            "Community Poll",
            question,
            discord.Color.blurple()
        )

        e.add_field(
            name="Vote",
            value="👍 Yes\n👎 No",
            inline=False
        )

        await i.response.send_message(
            embed=e
        )

        msg = await i.original_response()

        await msg.add_reaction("👍")
        await msg.add_reaction("👎")

    # =====================================================
    # SERVER ICON
    # =====================================================

    @bot.tree.command(
        name="servericon",
        description="Show the server icon"
    )
    async def servericon(
        i: discord.Interaction
    ):

        if not i.guild.icon:
            return await i.response.send_message(
                "This server has no icon.",
                ephemeral=True
            )

        e = embed(
            f"{i.guild.name} • Server Icon"
        )

        e.set_image(
            url=i.guild.icon.replace(
                size=1024
            ).url
        )

        await i.response.send_message(
            embed=e
        )

    # =====================================================
    # BANNER
    # =====================================================

    @bot.tree.command(
        name="banner",
        description="Show the server banner"
    )
    async def banner(
        i: discord.Interaction
    ):

        if not i.guild.banner:
            return await i.response.send_message(
                "This server has no banner.",
                ephemeral=True
            )

        e = embed(
            f"{i.guild.name} • Server Banner"
        )

        e.set_image(
            url=i.guild.banner.replace(
                size=1024
            ).url
        )

        await i.response.send_message(
            embed=e
        )

    # =====================================================
    # MEMBER COUNT
    # =====================================================

    @bot.tree.command(
        name="membercount",
        description="Show server member counts"
    )
    async def membercount(
        i: discord.Interaction
    ):

        g = i.guild

        bots = sum(
            1
            for m in g.members
            if m.bot
        )

        total = g.member_count or len(g.members)

        e = embed(
            "Member Count",
            f"Live member breakdown for **{g.name}**."
        )

        e.add_field(
            name="Total",
            value=str(total),
            inline=True
        )

        e.add_field(
            name="Humans",
            value=str(max(total - bots, 0)),
            inline=True
        )

        e.add_field(
            name="Bots",
            value=str(bots),
            inline=True
        )

        await i.response.send_message(
            embed=e
        )

    # =====================================================
    # CHANNEL INFO
    # =====================================================

    @bot.tree.command(
        name="channelinfo",
        description="Show channel information"
    )
    @app_commands.describe(
        channel="Channel to inspect"
    )
    async def channelinfo(
        i: discord.Interaction,
        channel: discord.TextChannel | None = None
    ):

        c = channel or i.channel

        e = embed(
            f"Channel Info • {c.name}"
        )

        e.add_field(
            name="ID",
            value=str(c.id),
            inline=True
        )

        e.add_field(
            name="Type",
            value=str(c.type),
            inline=True
        )

        e.add_field(
            name="Category",
            value=(
                c.category.name
                if c.category
                else "None"
            ),
            inline=True
        )

        await i.response.send_message(
            embed=e
        )

    # =====================================================
    # ROLE INFO
    # =====================================================

    @bot.tree.command(
        name="roleinfo",
        description="Show role information"
    )
    @app_commands.describe(
        role="Role to inspect"
    )
    async def roleinfo(
        i: discord.Interaction,
        role: discord.Role
    ):

        e = embed(
            f"Role Info • {role.name}"
        )

        e.add_field(
            name="ID",
            value=str(role.id),
            inline=True
        )

        e.add_field(
            name="Members",
            value=str(len(role.members)),
            inline=True
        )

        e.add_field(
            name="Position",
            value=str(role.position),
            inline=True
        )

        e.add_field(
            name="Mentionable",
            value="Yes" if role.mentionable else "No",
            inline=True
        )

        e.add_field(
            name="Managed",
            value="Yes" if role.managed else "No",
            inline=True
        )

        await i.response.send_message(
            embed=e
        )

    # =====================================================
    # BOT INFO
    # =====================================================

    @bot.tree.command(
        name="botinfo",
        description="Show Air Commander status"
    )
    async def botinfo(
        i: discord.Interaction
    ):

        uptime = int(
            time.time()
            - getattr(
                bot,
                "_air_start_time",
                time.time()
            )
        )

        total_members = sum(
            g.member_count or len(g.members)
            for g in bot.guilds
        )

        e = embed(
            "✈️ Air Commander • System Status",
            "🟢 **Online & Operational** • Clean, fast and ready.",
            discord.Color.blurple()
        )

        e.add_field(
            name="🌐 Servers",
            value=f"**{len(bot.guilds):,}**",
            inline=True
        )

        e.add_field(
            name="👥 Members",
            value=(
                f"**{total_members:,}** "
                f"({format_count(total_members)})"
            ),
            inline=True
        )

        e.add_field(
            name="📡 Latency",
            value=f"**{round(bot.latency * 1000)} ms**",
            inline=True
        )

        e.add_field(
            name="⏱️ Uptime",
            value=(
                f"**{uptime // 3600}h "
                f"{(uptime % 3600) // 60}m**"
            ),
            inline=True
        )

        e.add_field(
            name="🛠️ Framework",
            value="**discord.py**",
            inline=True
        )

        e.add_field(
            name="🟢 Status",
            value="**Operational**",
            inline=True
        )

        e.add_field(
            name="💬 Support Server",
            value="[🚀 Join Air Commander Support Server](https://discord.gg/hVpaK2gbhh)",
            inline=False
        )

        if bot.user:
            e.set_thumbnail(
                url=bot.user.display_avatar.url
            )

        e.set_footer(
            text="✈️ Air Commander • Systems Operational"
        )

        await i.response.send_message(
            embed=e
        )

    # =====================================================
    # PREFIX COMMANDS
    # Prefix: ,
    # =====================================================

    @bot.command(name="ping")
    async def prefix_ping(ctx):

        await ctx.send(
            embed=embed(
                "Pong!",
                f"Latency: **{round(bot.latency * 1000)} ms**",
                discord.Color.green()
            )
        )

    @bot.command(name="clear")
    @commands.has_permissions(
        manage_messages=True
    )
    async def prefix_clear(
        ctx,
        amount: int
    ):

        if amount < 1 or amount > 100:
            return await ctx.send(
                "❌ Amount must be between **1 and 100**."
            )

        if not isinstance(
            ctx.channel,
            discord.TextChannel
        ):
            return await ctx.send(
                "❌ This command works in text channels only."
            )

        deleted = await ctx.channel.purge(
            limit=amount
        )

        await ctx.send(
            embed=embed(
                "Messages Cleared",
                f"Removed **{len(deleted)}** message(s) from {ctx.channel.mention}.",
                discord.Color.orange()
            ),
            delete_after=5
        )

    @bot.command(name="kick")
    @commands.has_permissions(
        kick_members=True
    )
    async def prefix_kick(
        ctx,
        member: discord.Member,
        *,
        reason="No reason provided"
    ):

        if (
            member == ctx.author
            or member.top_role >= ctx.author.top_role
            or member.top_role >= ctx.guild.me.top_role
        ):
            return await ctx.send(
                "❌ That member cannot be kicked due to role hierarchy."
            )

        await member.kick(
            reason=f"{reason} | Moderator: {ctx.author}"
        )

        e = embed(
            "Member Kicked",
            f"{member.mention} was removed from the server.",
            discord.Color.red()
        )

        e.add_field(
            name="Moderator",
            value=ctx.author.mention
        )

        e.add_field(
            name="Reason",
            value=reason[:1024]
        )

        await ctx.send(
            embed=e
        )

    @bot.command(name="ban")
    @commands.has_permissions(
        ban_members=True
    )
    async def prefix_ban(
        ctx,
        member: discord.Member,
        *,
        reason="No reason provided"
    ):

        if (
            member == ctx.author
            or member.top_role >= ctx.author.top_role
            or member.top_role >= ctx.guild.me.top_role
        ):
            return await ctx.send(
                "❌ That member cannot be banned due to role hierarchy."
            )

        await member.ban(
            reason=f"{reason} | Moderator: {ctx.author}"
        )

        e = embed(
            "Member Banned",
            f"{member.mention} was banned from the server.",
            discord.Color.red()
        )

        e.add_field(
            name="Moderator",
            value=ctx.author.mention
        )

        e.add_field(
            name="Reason",
            value=reason[:1024]
        )

        await ctx.send(
            embed=e
        )

    @bot.command(name="unban")
    @commands.has_permissions(
        ban_members=True
    )
    async def prefix_unban(
        ctx,
        user_id: int,
        *,
        reason="No reason provided"
    ):

        try:

            await ctx.guild.unban(
                discord.Object(id=user_id),
                reason=f"{reason} | Moderator: {ctx.author}"
            )

        except discord.NotFound:

            return await ctx.send(
                "❌ No matching banned user was found."
            )

        e = embed(
            "Member Unbanned",
            f"User ID **{user_id}** is no longer banned.",
            discord.Color.green()
        )

        e.add_field(
            name="Moderator",
            value=ctx.author.mention
        )

        e.add_field(
            name="Reason",
            value=reason[:1024]
        )

        await ctx.send(
            embed=e
        )

    @bot.command(name="timeout")
    @commands.has_permissions(
        moderate_members=True
    )
    async def prefix_timeout(
        ctx,
        member: discord.Member,
        minutes: int,
        *,
        reason="No reason provided"
    ):

        if minutes < 1 or minutes > 40320:
            return await ctx.send(
                "❌ Timeout must be between **1 and 40320 minutes**."
            )

        if (
            member == ctx.author
            or member.top_role >= ctx.author.top_role
            or member.top_role >= ctx.guild.me.top_role
        ):
            return await ctx.send(
                "❌ That member cannot be timed out due to role hierarchy."
            )

        await member.timeout(
            timedelta(minutes=minutes),
            reason=f"{reason} | Moderator: {ctx.author}"
        )

        e = embed(
            "Member Timed Out",
            f"{member.mention} is timed out for **{minutes} minute(s)**.",
            discord.Color.orange()
        )

        e.add_field(
            name="Moderator",
            value=ctx.author.mention
        )

        e.add_field(
            name="Reason",
            value=reason[:1024]
        )

        await ctx.send(
            embed=e
        )

    @bot.command(name="untimeout")
    @commands.has_permissions(
        moderate_members=True
    )
    async def prefix_untimeout(
        ctx,
        member: discord.Member,
        *,
        reason="No reason provided"
    ):

        await member.timeout(
            None,
            reason=f"{reason} | Moderator: {ctx.author}"
        )

        e = embed(
            "Timeout Removed",
            f"Timeout removed from {member.mention}.",
            discord.Color.green()
        )

        e.add_field(
            name="Moderator",
            value=ctx.author.mention
        )

        e.add_field(
            name="Reason",
            value=reason[:1024]
        )

        await ctx.send(
            embed=e
        )

    @bot.command(name="slowmode")
    @commands.has_permissions(
        manage_channels=True
    )
    async def prefix_slowmode(
        ctx,
        seconds: int
    ):

        if seconds < 0 or seconds > 21600:
            return await ctx.send(
                "❌ Slowmode must be between **0 and 21600 seconds**."
            )

        if not isinstance(
            ctx.channel,
            discord.TextChannel
        ):
            return await ctx.send(
                "❌ Text channel only."
            )

        await ctx.channel.edit(
            slowmode_delay=seconds,
            reason=f"Changed by {ctx.author}"
        )

        await ctx.send(
            embed=embed(
                "Slowmode Updated",
                f"{ctx.channel.mention} slowmode is now **{seconds}s**.",
                discord.Color.teal()
            )
        )

    @bot.command(name="lock")
    @commands.has_permissions(
        manage_channels=True
    )
    async def prefix_lock(ctx):

        if not isinstance(
            ctx.channel,
            discord.TextChannel
        ):
            return await ctx.send(
                "❌ Text channel only."
            )

        overwrite = ctx.channel.overwrites_for(
            ctx.guild.default_role
        )

        overwrite.send_messages = False

        await ctx.channel.set_permissions(
            ctx.guild.default_role,
            overwrite=overwrite,
            reason=f"Channel locked by {ctx.author}"
        )

        await ctx.send(
            embed=embed(
                "Channel Locked",
                f"{ctx.channel.mention} is now **locked** for @everyone.",
                discord.Color.red()
            )
        )

    @bot.command(name="unlock")
    @commands.has_permissions(
        manage_channels=True
    )
    async def prefix_unlock(ctx):

        if not isinstance(
            ctx.channel,
            discord.TextChannel
        ):
            return await ctx.send(
                "❌ Text channel only."
            )

        overwrite = ctx.channel.overwrites_for(
            ctx.guild.default_role
        )

        overwrite.send_messages = None

        await ctx.channel.set_permissions(
            ctx.guild.default_role,
            overwrite=overwrite,
            reason=f"Channel unlocked by {ctx.author}"
        )

        await ctx.send(
            embed=embed(
                "Channel Unlocked",
                f"{ctx.channel.mention} is now **open** for @everyone.",
                discord.Color.green()
            )
        )

    @bot.command(name="nick")
    @commands.has_permissions(
        manage_nicknames=True
    )
    async def prefix_nick(
        ctx,
        member: discord.Member,
        *,
        nickname=None
    ):

        await member.edit(
            nick=nickname,
            reason=f"Nickname changed by {ctx.author}"
        )

        e = embed(
            "Nickname Updated",
            f"Updated nickname for {member.mention}."
        )

        e.add_field(
            name="New Nickname",
            value=nickname or "Reset to username"
        )

        await ctx.send(
            embed=e
        )

    @bot.command(name="role")
    @commands.has_permissions(
        manage_roles=True
    )
    async def prefix_role(
        ctx,
        action: str,
        member: discord.Member,
        role: discord.Role
    ):

        action = action.lower()

        if action not in (
            "add",
            "remove"
        ):
            return await ctx.send(
                "❌ Use `,role add @user @role` or `,role remove @user @role`."
            )

        if (
            role.is_default()
            or role >= ctx.guild.me.top_role
        ):
            return await ctx.send(
                "❌ I cannot manage that role because of role hierarchy."
            )

        if action == "add":

            await member.add_roles(
                role,
                reason=f"Role added by {ctx.author}"
            )

        else:

            await member.remove_roles(
                role,
                reason=f"Role removed by {ctx.author}"
            )

        await ctx.send(
            embed=embed(
                "Role Updated",
                f"{role.mention} was **{action}** for {member.mention}.",
                discord.Color.green()
            )
        )

    @bot.command(name="say")
    @commands.has_permissions(
        manage_messages=True
    )
    async def prefix_say(
        ctx,
        *,
        message: str
    ):

        await ctx.send(
            embed=embed(
                "Message Sent",
                message
            )
        )

    @bot.command(name="announce")
    @commands.has_permissions(
        manage_guild=True
    )
    async def prefix_announce(
        ctx,
        *,
        message: str
    ):

        e = embed(
            "Announcement",
            message,
            discord.Color.gold()
        )

        if ctx.guild.icon:

            e.set_author(
                name=ctx.guild.name,
                icon_url=ctx.guild.icon.url
            )

        else:

            e.set_author(
                name=ctx.guild.name
            )

        await ctx.send(
            embed=e
        )

    @bot.command(name="poll")
    async def prefix_poll(
        ctx,
        *,
        question: str
    ):

        e = embed(
            "Community Poll",
            question
        )

        e.add_field(
            name="Vote",
            value="👍 Yes\n👎 No",
            inline=False
        )

        msg = await ctx.send(
            embed=e
        )

        await msg.add_reaction("👍")
        await msg.add_reaction("👎")

    @bot.command(name="servericon")
    async def prefix_servericon(ctx):

        if not ctx.guild.icon:
            return await ctx.send(
                "This server has no icon."
            )

        e = embed(
            f"{ctx.guild.name} • Server Icon"
        )

        e.set_image(
            url=ctx.guild.icon.replace(
                size=1024
            ).url
        )

        await ctx.send(
            embed=e
        )

    @bot.command(name="banner")
    async def prefix_banner(ctx):

        if not ctx.guild.banner:
            return await ctx.send(
                "This server has no banner."
            )

        e = embed(
            f"{ctx.guild.name} • Server Banner"
        )

        e.set_image(
            url=ctx.guild.banner.replace(
                size=1024
            ).url
        )

        await ctx.send(
            embed=e
        )

    @bot.command(name="membercount")
    async def prefix_membercount(ctx):

        g = ctx.guild

        bots = sum(
            1
            for m in g.members
            if m.bot
        )

        total = g.member_count or len(g.members)

        e = embed(
            "Member Count",
            f"Live member breakdown for **{g.name}**."
        )

        e.add_field(
            name="Total",
            value=str(total),
            inline=True
        )

        e.add_field(
            name="Humans",
            value=str(max(total - bots, 0)),
            inline=True
        )

        e.add_field(
            name="Bots",
            value=str(bots),
            inline=True
        )

        await ctx.send(
            embed=e
        )

    @bot.command(name="channelinfo")
    async def prefix_channelinfo(
        ctx,
        channel: discord.TextChannel | None = None
    ):

        c = channel or ctx.channel

        e = embed(
            f"Channel Info • {c.name}"
        )

        e.add_field(
            name="ID",
            value=str(c.id),
            inline=True
        )

        e.add_field(
            name="Type",
            value=str(c.type),
            inline=True
        )

        e.add_field(
            name="Category",
            value=(
                c.category.name
                if c.category
                else "None"
            ),
            inline=True
        )

        await ctx.send(
            embed=e
        )

    @bot.command(name="roleinfo")
    async def prefix_roleinfo(
        ctx,
        role: discord.Role
    ):

        e = embed(
            f"Role Info • {role.name}"
        )

        e.add_field(
            name="ID",
            value=str(role.id),
            inline=True
        )

        e.add_field(
            name="Members",
            value=str(len(role.members)),
            inline=True
        )

        e.add_field(
            name="Position",
            value=str(role.position),
            inline=True
        )

        e.add_field(
            name="Mentionable",
            value="Yes" if role.mentionable else "No",
            inline=True
        )

        e.add_field(
            name="Managed",
            value="Yes" if role.managed else "No",
            inline=True
        )

        await ctx.send(
            embed=e
        )

    @bot.command(name="botinfo")
    async def prefix_botinfo(ctx):

        uptime = int(
            time.time()
            - getattr(
                bot,
                "_air_start_time",
                time.time()
            )
        )

        total_members = sum(
            g.member_count or len(g.members)
            for g in bot.guilds
        )

        e = embed(
            "✈️ Air Commander • System Status",
            "🟢 **Online & Operational** • Clean, fast and ready.",
            discord.Color.blurple()
        )

        e.add_field(
            name="🌐 Servers",
            value=f"**{len(bot.guilds):,}**",
            inline=True
        )

        e.add_field(
            name="👥 Members",
            value=(
                f"**{total_members:,}** "
                f"({format_count(total_members)})"
            ),
            inline=True
        )

        e.add_field(
            name="📡 Latency",
            value=f"**{round(bot.latency * 1000)} ms**",
            inline=True
        )

        e.add_field(
            name="⏱️ Uptime",
            value=(
                f"**{uptime // 3600}h "
                f"{(uptime % 3600) // 60}m**"
            ),
            inline=True
        )

        e.add_field(
            name="🛠️ Framework",
            value="**discord.py**",
            inline=True
        )

        e.add_field(
            name="🟢 Status",
            value="**Operational**",
            inline=True
        )

        e.add_field(
            name="💬 Support Server",
            value="[🚀 Join Air Commander Support Server](https://discord.gg/hVpaK2gbhh)",
            inline=False
        )

        if bot.user:
            e.set_thumbnail(
                url=bot.user.display_avatar.url
            )

        e.set_footer(
            text="✈️ Air Commander • Systems Operational"
        )

        await ctx.send(
            embed=e
        )

    # =====================================================
    # PREFIX COMMAND ERROR HANDLER
    # =====================================================

    @bot.event
    async def on_command_error(
        ctx,
        error
    ):

        if isinstance(
            error,
            commands.CommandNotFound
        ):
            return

        if isinstance(
            error,
            commands.MissingPermissions
        ):
            return await ctx.send(
                "❌ You don't have the required permission."
            )

        if isinstance(
            error,
            commands.BotMissingPermissions
        ):
            return await ctx.send(
                "❌ I don't have the required Discord permission."
            )

        if isinstance(
            error,
            commands.MissingRequiredArgument
        ):
            return await ctx.send(
                f"❌ Missing argument: `{error.param.name}`."
            )

        if isinstance(
            error,
            commands.BadArgument
        ):
            return await ctx.send(
                "❌ Invalid argument. Please check the command format."
            )

        print(
            f"Prefix command error: "
            f"{type(error).__name__}: {error}"
        )

    # =====================================================
    # PREFIX ,HELP
    # =====================================================

    @bot.command(
        name="help"
    )
    async def prefix_help(
        ctx,
        command_name: str | None = None
    ):

        # Detailed command help
        if command_name:

            command = bot.get_command(
                command_name.lower()
            )

            if not command:

                return await ctx.send(
                    embed=embed(
                        "Command Not Found",
                        (
                            f"❌ Command "
                            f"`,{command_name}` not found."
                        ),
                        discord.Color.red()
                    )
                )

            description = (
                getattr(
                    command,
                    "help",
                    None
                )
                or
                getattr(
                    command,
                    "brief",
                    None
                )
                or
                "No description available."
            )

            e = embed(
                f"Help • ,{command.name}",
                description,
                discord.Color.blurple()
            )

            usage = (
                f"`,{command.qualified_name}"
                f" {command.signature}`"
            ).strip()

            e.add_field(
                name="Usage",
                value=usage,
                inline=False
            )

            if command.aliases:

                e.add_field(
                    name="Aliases",
                    value=" ".join(
                        f"`,{alias}`"
                        for alias in command.aliases
                    ),
                    inline=False
                )

            return await ctx.send(
                embed=e
            )

        await ctx.send(
            embed=_help_home_embed(
                bot,
                "prefix"
            ),
            view=HelpView(
                bot,
                "prefix"
            )
        )

    # =====================================================
    # SLASH /HELP
    # =====================================================

    # Remove an older help command if another basic
    # help registration was left behind.
    existing_help = bot.tree.get_command(
        "help"
    )

    if existing_help is not None:
        bot.tree.remove_command(
            "help"
        )

    @bot.tree.command(
        name="help",
        description="Open the Air Commander Help Center"
    )
    async def slash_help(
        i: discord.Interaction
    ):

        await i.response.send_message(
            embed=_help_home_embed(
                bot,
                "slash"
            ),
            view=HelpView(
                bot,
                "slash"
            ),
            ephemeral=False
        )

    # =====================================================
    # SLASH COMMAND ERROR HANDLER
    # =====================================================

    @bot.tree.error
    async def on_app_command_error(
        i: discord.Interaction,
        error: app_commands.AppCommandError
    ):

        if isinstance(
            error,
            app_commands.MissingPermissions
        ):

            msg = (
                "❌ You don't have the required "
                "permission for this command."
            )

        elif isinstance(
            error,
            app_commands.BotMissingPermissions
        ):

            msg = (
                "❌ I don't have the required Discord "
                "permission to do that."
            )

        elif isinstance(
            error,
            app_commands.CommandOnCooldown
        ):

            msg = (
                "⏳ Please wait before using "
                "that command again."
            )

        elif isinstance(
            error,
            app_commands.CheckFailure
        ):

            msg = (
                "❌ You cannot use this command "
                "here or right now."
            )

        else:

            print(
                f"Basic slash command error: "
                f"{type(error).__name__}: {error}"
            )

            msg = (
                "❌ Something went wrong while "
                "running that command."
            )

        try:

            if i.response.is_done():

                await i.followup.send(
                    msg,
                    ephemeral=True
                )

            else:

                await i.response.send_message(
                    msg,
                    ephemeral=True
                )

        except discord.HTTPException as exc:

            print(
                f"⚠️ Could not send slash error response: {exc}"
            )


# =========================================================
# END OF BASIC COMMANDS
# =========================================================
