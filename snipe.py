from __future__ import annotations

import discord
from discord.ext import commands
from discord import app_commands

import asyncio
import json
import os
import re
import io
from pathlib import Path
from datetime import datetime, timezone


# ============================================================
# AIR COMMANDER — SNIPE SYSTEM
# ============================================================

_snipes = {}


async def send_snipe(target):
    cid = target.channel.id
    data = _snipes.get(cid)

    if not data:
        msg = "❌ No recently deleted message found in this channel."

        if isinstance(target, discord.Interaction):
            if not target.response.is_done():
                return await target.response.send_message(
                    msg,
                    ephemeral=True
                )

            return await target.followup.send(
                msg,
                ephemeral=True
            )

        return await target.send(msg)

    content = data.get("content") or "[attachment/embed/no text]"

    embed = discord.Embed(
        title="🕵️ Snipe",
        description=content[:4000],
        color=0x5865F2
    )

    author = data.get("author")

    if author:
        try:
            embed.set_author(
                name=author.display_name,
                icon_url=author.display_avatar.url
            )
        except Exception:
            embed.set_author(
                name=str(author)
            )

    embed.add_field(
        name="👤 Author",
        value=author.mention if author else "Unknown",
        inline=True
    )

    embed.set_footer(
        text="Air Commander • Snipe"
    )

    if isinstance(target, discord.Interaction):

        if not target.response.is_done():
            return await target.response.send_message(
                embed=embed
            )

        return await target.followup.send(
            embed=embed
        )

    return await target.send(
        embed=embed
    )


async def snipe_message_delete(message):
    """
    Listener instead of @bot.event so this module
    does not overwrite another on_message_delete listener.
    """

    if not message.guild:
        return

    if not message.author:
        return

    if message.author.bot:
        return

    _snipes[message.channel.id] = {
        "author": message.author,
        "content": message.content,
        "created": message.created_at
    }


# ============================================================
# SNIPE PREFIX COMMAND
# ============================================================

@commands.command(
    name="snipe",
    description="Show the most recently deleted message."
)
async def snipe_prefix(ctx):
    await send_snipe(ctx)


# ============================================================
# SNIPE SLASH COMMAND
# ============================================================

async def snipe_slash(interaction: discord.Interaction):
    await send_snipe(interaction)


# ============================================================
# TICKET SYSTEM
# ============================================================

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

DATA_FILE = DATA_DIR / "tickets.json"


DEFAULT_GUILD_DATA = {
    "categories": {
        "general": {
            "name": "General Support",
            "emoji": "🎫",
            "description": "Get general help from our support team.",
            "prefix": "support"
        }
    },

    "panel": {
        "title": "✈️ Air Commander Support Center",
        "description": (
            "Need help? Open a support ticket below.\n\n"
            "Our support team will assist you as soon as possible.\n\n"
            "Select a category from the menu below."
        ),
        "color": 0x5865F2,
        "footer": "Air Commander • Support System",
        "channel_id": None,
        "message_id": None
    },

    "config": {
        "support_role_id": None,
        "log_channel_id": None,
        "ticket_category_id": None,
        "transcript": True,
        "naming": "ticket-{username}"
    },

    "tickets": {}
}


# ============================================================
# DATABASE HELPERS
# ============================================================

def load_data():
    if not DATA_FILE.exists():
        try:
            DATA_FILE.write_text(
                json.dumps({}, indent=4),
                encoding="utf-8"
            )
        except Exception:
            return {}

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            return {}

        return data

    except Exception as e:
        print(
            f"[Ticket] Data load error: "
            f"{type(e).__name__}: {e}"
        )
        return {}


def save_data(data):
    try:
        temp_file = DATA_FILE.with_suffix(".tmp")

        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(
                data,
                f,
                indent=4,
                ensure_ascii=False
            )

        temp_file.replace(DATA_FILE)

    except Exception as e:
        print(
            f"[Ticket] Data save error: "
            f"{type(e).__name__}: {e}"
        )


def ensure_guild(data, guild_id):
    gid = str(guild_id)

    if gid not in data:
        data[gid] = json.loads(
            json.dumps(DEFAULT_GUILD_DATA)
        )

    guild_data = data[gid]

    guild_data.setdefault(
        "categories",
        {}
    )

    guild_data.setdefault(
        "panel",
        {}
    )

    guild_data.setdefault(
        "config",
        {}
    )

    guild_data.setdefault(
        "tickets",
        {}
    )

    # Existing old data compatibility
    panel = guild_data["panel"]

    panel.setdefault(
        "title",
        DEFAULT_GUILD_DATA["panel"]["title"]
    )

    panel.setdefault(
        "description",
        DEFAULT_GUILD_DATA["panel"]["description"]
    )

    panel.setdefault(
        "color",
        DEFAULT_GUILD_DATA["panel"]["color"]
    )

    panel.setdefault(
        "footer",
        DEFAULT_GUILD_DATA["panel"]["footer"]
    )

    panel.setdefault(
        "channel_id",
        None
    )

    panel.setdefault(
        "message_id",
        None
    )

    config = guild_data["config"]

    config.setdefault(
        "support_role_id",
        None
    )

    config.setdefault(
        "log_channel_id",
        None
    )

    config.setdefault(
        "ticket_category_id",
        None
    )

    config.setdefault(
        "transcript",
        True
    )

    config.setdefault(
        "naming",
        "ticket-{username}"
    )

    # Make sure old guilds have General Support
    if not guild_data["categories"]:
        guild_data["categories"] = json.loads(
            json.dumps(
                DEFAULT_GUILD_DATA["categories"]
            )
        )

    return guild_data


# ============================================================
# HELPERS
# ============================================================

def is_admin(member: discord.Member):
    return (
        member.guild_permissions.administrator
        or member.guild_permissions.manage_guild
    )


def clean_channel_name(name):
    name = str(name or "").lower().strip()

    name = re.sub(
        r"[^a-z0-9\-_ ]+",
        "",
        name
    )

    name = name.replace(
        " ",
        "-"
    )

    name = re.sub(
        r"-{2,}",
        "-",
        name
    )

    if not name:
        name = "ticket"

    return name[:80].strip("-") or "ticket"


def make_category_key(name):
    key = re.sub(
        r"[^a-z0-9]+",
        "-",
        str(name).lower()
    ).strip("-")

    return key[:80]


def category_name_from_key(key, category_data):
    emoji = category_data.get(
        "emoji",
        "🎫"
    )

    name = category_data.get(
        "name",
        "General Support"
    )

    return f"{emoji} {name}"


def find_category(guild_data, value):
    """
    Finds category by:
    - exact key
    - category display name
    - case-insensitive key/name
    """

    categories = guild_data.get(
        "categories",
        {}
    )

    if not value:
        return None, None

    value = str(value).strip()

    # Exact key
    if value in categories:
        return value, categories[value]

    # Case-insensitive key
    lowered = value.lower()

    for key, category in categories.items():

        if str(key).lower() == lowered:
            return key, category

    # Display name
    for key, category in categories.items():

        category_name = str(
            category.get("name", "")
        ).strip()

        if category_name.lower() == lowered:
            return key, category

    return None, None


def make_unique_category_key(
    guild_data,
    name,
    old_key=None
):
    base = make_category_key(name)

    if not base:
        return None

    if old_key:
        if base == old_key:
            return base

    categories = guild_data.get(
        "categories",
        {}
    )

    if base not in categories:
        return base

    counter = 2

    while f"{base}-{counter}" in categories:
        counter += 1

    return f"{base}-{counter}"


def make_ticket_name(template, member, category_key):

    username = clean_channel_name(
        member.name
    )

    replacements = {
        "{username}": username,
        "{user}": username,
        "{category}": clean_channel_name(
            category_key
        ),
        "{userid}": str(member.id)
    }

    result = template or "ticket-{username}"

    for key, value in replacements.items():
        result = result.replace(
            key,
            value
        )

    return clean_channel_name(result)


def find_ticket(guild_data, channel_id):

    channel_id = str(channel_id)

    for ticket_id, ticket in guild_data["tickets"].items():

        if str(
            ticket.get("channel_id")
        ) == channel_id:
            return ticket_id, ticket

    return None, None


def get_ticket_by_user(guild_data, user_id):

    user_id = str(user_id)

    for ticket_id, ticket in guild_data["tickets"].items():

        if (
            str(ticket.get("user_id")) == user_id
            and ticket.get("closed") is False
        ):
            return ticket_id, ticket

    return None, None


# ============================================================
# CATEGORY OPTION BUILDER
# ============================================================

def build_category_options(guild_data):

    categories = guild_data.get(
        "categories",
        {}
    )

    options = []

    for key, category in list(
        categories.items()
    )[:25]:

        name = str(
            category.get(
                "name",
                key
            )
        )[:100]

        description = str(
            category.get(
                "description",
                "Open a support ticket."
            )
        ).replace(
            "\n",
            " "
        )[:100]

        emoji = category.get(
            "emoji",
            "🎫"
        )

        # Discord requires valid SelectOption emoji
        if not emoji:
            emoji = "🎫"

        options.append(
            discord.SelectOption(
                label=name,
                description=description,
                emoji=emoji[:32],
                value=str(key)[:100]
            )
        )

    return options


# ============================================================
# TICKET PANEL
# ============================================================

class TicketPanelView(discord.ui.View):

    def __init__(
        self,
        cog,
        guild_id=None
    ):
        super().__init__(
            timeout=None
        )

        self.cog = cog
        self.guild_id = guild_id

        self.add_item(
            TicketCategorySelect(
                cog,
                guild_id
            )
        )


class TicketCategorySelect(discord.ui.Select):

    def __init__(
        self,
        cog,
        guild_id=None
    ):

        self.cog = cog
        self.guild_id = guild_id

        options = []

        try:
            data = load_data()

            if guild_id is not None:

                guild_data = ensure_guild(
                    data,
                    guild_id
                )

                options = build_category_options(
                    guild_data
                )

        except Exception as e:
            print(
                f"[Ticket] Category option error: "
                f"{type(e).__name__}: {e}"
            )

        # Fallback
        if not options:

            options = [
                discord.SelectOption(
                    label="General Support",
                    description="Get general support.",
                    emoji="🎫",
                    value="general"
                )
            ]

        custom_id = (
            f"aircommander:ticket_category:"
            f"{guild_id}"
            if guild_id
            else
            "aircommander:ticket_category"
        )

        super().__init__(
            placeholder="🎫 Select a ticket category...",
            min_values=1,
            max_values=1,
            options=options[:25],
            custom_id=custom_id
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):

        await self.cog.handle_category_select(
            interaction,
            self.values[0]
        )


# ============================================================
# MAIN TICKET COG
# ============================================================

class TicketSystem(commands.Cog):

    ticket = app_commands.Group(
        name="ticket",
        description="Air Commander ticket system."
    )

    panel = app_commands.Group(
        name="panel",
        description="Manage ticket panels.",
        parent=ticket
    )

    category = app_commands.Group(
        name="category",
        description="Manage ticket categories.",
        parent=ticket
    )

    def __init__(self, bot):

        self.bot = bot
        self.data = load_data()

    # ========================================================
    # PERSISTENT VIEWS
    # ========================================================

    async def restore_persistent_views(self):

        try:

            # Ticket control buttons
            self.bot.add_view(
                TicketControlView(self)
            )

            data = load_data()

            # Restore configured panels individually
            for guild_id, guild_data in data.items():

                try:
                    if not str(guild_id).isdigit():
                        continue

                    panel = guild_data.get(
                        "panel",
                        {}
                    )

                    channel_id = panel.get(
                        "channel_id"
                    )

                    message_id = panel.get(
                        "message_id"
                    )

                    if not channel_id or not message_id:
                        continue

                    view = TicketPanelView(
                        self,
                        int(guild_id)
                    )

                    self.bot.add_view(
                        view,
                        message_id=int(message_id)
                    )

                except Exception as e:
                    print(
                        f"[Ticket] Panel restore failed "
                        f"for guild {guild_id}: "
                        f"{type(e).__name__}: {e}"
                    )

        except Exception as e:

            print(
                f"[Ticket] Persistent view error: "
                f"{type(e).__name__}: {e}"
            )

    # ========================================================
    # REFRESH PANEL
    # ========================================================

    async def refresh_panel(
        self,
        guild: discord.Guild
    ):

        try:

            data = load_data()

            guild_data = ensure_guild(
                data,
                guild.id
            )

            panel = guild_data.get(
                "panel",
                {}
            )

            channel_id = panel.get(
                "channel_id"
            )

            message_id = panel.get(
                "message_id"
            )

            if not channel_id or not message_id:
                return

            channel = guild.get_channel(
                int(channel_id)
            )

            if not channel:
                return

            try:
                message = await channel.fetch_message(
                    int(message_id)
                )

            except Exception:
                return

            embed = self.panel_embed(
                guild_data
            )

            view = TicketPanelView(
                self,
                guild.id
            )

            try:
                await message.edit(
                    embed=embed,
                    view=view
                )

            except Exception as e:
                print(
                    f"[Ticket] Panel refresh failed: "
                    f"{type(e).__name__}: {e}"
                )

        except Exception as e:

            print(
                f"[Ticket] Panel refresh error: "
                f"{type(e).__name__}: {e}"
            )

    # ========================================================
    # EMBED
    # ========================================================

    def panel_embed(self, guild_data):

        panel = guild_data["panel"]

        embed = discord.Embed(
            title=panel.get(
                "title",
                "✈️ Air Commander Support Center"
            ),
            description=panel.get(
                "description",
                "Select a ticket category below."
            ),
            color=panel.get(
                "color",
                0x5865F2
            ),
            timestamp=datetime.now(
                timezone.utc
            )
        )

        embed.set_footer(
            text=panel.get(
                "footer",
                "Air Commander • Support System"
            )
        )

        return embed

    # ========================================================
    # CATEGORY SELECT
    # ========================================================

    async def handle_category_select(
        self,
        interaction: discord.Interaction,
        category_key: str
    ):

        guild = interaction.guild

        if guild is None:
            return

        data = load_data()

        guild_data = ensure_guild(
            data,
            guild.id
        )

        categories = guild_data["categories"]

        if category_key not in categories:

            await interaction.response.send_message(
                "❌ This ticket category no longer exists.",
                ephemeral=False
            )

            return

        _, existing_ticket = get_ticket_by_user(
            guild_data,
            interaction.user.id
        )

        if existing_ticket:

            try:
                channel = guild.get_channel(
                    int(existing_ticket["channel_id"])
                )

            except Exception:
                channel = None

            if channel:

                await interaction.response.send_message(
                    f"❌ You already have an open ticket: "
                    f"{channel.mention}",
                    ephemeral=False
                )

                return

        await interaction.response.defer(
            ephemeral=False
        )

        category_data = categories[
            category_key
        ]

        channel = await self.create_ticket(
            guild,
            interaction.user,
            category_key,
            category_data,
            guild_data
        )

        if channel is None:

            await interaction.followup.send(
                "❌ I couldn't create the ticket. "
                "Check my permissions.",
                ephemeral=False
            )

            return

        await interaction.followup.send(
            f"🎫 Your ticket has been created: "
            f"{channel.mention}",
            ephemeral=False
        )

    # ========================================================
    # CREATE TICKET
    # ========================================================

    async def create_ticket(
        self,
        guild,
        member,
        category_key,
        category_data,
        guild_data
    ):

        config = guild_data["config"]

        support_role = None

        support_role_id = config.get(
            "support_role_id"
        )

        if support_role_id:

            try:
                support_role = guild.get_role(
                    int(support_role_id)
                )

            except Exception:
                support_role = None

        overwrites = {
            guild.default_role:
                discord.PermissionOverwrite(
                    view_channel=False
                ),

            member:
                discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    attach_files=True,
                    embed_links=True
                )
        }

        if support_role:

            overwrites[support_role] = (
                discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    manage_messages=True,
                    attach_files=True,
                    embed_links=True
                )
            )

        if guild.me:

            overwrites[guild.me] = (
                discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    manage_channels=True,
                    manage_messages=True,
                    attach_files=True,
                    embed_links=True
                )
            )

        parent = None

        parent_id = config.get(
            "ticket_category_id"
        )

        if parent_id:

            try:
                parent = guild.get_channel(
                    int(parent_id)
                )

            except Exception:
                parent = None

        channel_name = make_ticket_name(
            config.get(
                "naming",
                "ticket-{username}"
            ),
            member,
            category_key
        )

        try:

            channel = await guild.create_text_channel(
                channel_name,
                category=parent,
                overwrites=overwrites,
                reason="Air Commander Ticket Creation"
            )

        except Exception as e:

            print(
                f"[Ticket] Channel creation failed: "
                f"{type(e).__name__}: {e}"
            )

            return None

        data = load_data()

        guild_data = ensure_guild(
            data,
            guild.id
        )

        ticket_id = str(
            channel.id
        )

        guild_data["tickets"][ticket_id] = {

            "channel_id":
                channel.id,

            "user_id":
                member.id,

            "category":
                category_key,

            "created_at":
                datetime.now(
                    timezone.utc
                ).isoformat(),

            "closed":
                False,

            "claimed_by":
                None,

            "added_users":
                []
        }

        save_data(data)

        embed = discord.Embed(
            title=(
                f"{category_data.get('emoji', '🎫')} "
                f"{category_data.get('name', 'Support')}"
            ),
            description=(
                f"Welcome {member.mention}! 👋\n\n"
                f"{category_data.get('description', '')}\n\n"
                "Please explain your issue clearly and "
                "a member of the support team will assist you."
            ),
            color=0x5865F2,
            timestamp=datetime.now(
                timezone.utc
            )
        )

        embed.add_field(
            name="👤 Created By",
            value=member.mention,
            inline=True
        )

        embed.add_field(
            name="🏷️ Category",
            value=category_data.get(
                "name",
                "General Support"
            ),
            inline=True
        )

        embed.set_footer(
            text="Air Commander • Ticket System"
        )

        view = TicketControlView(
            self
        )

        content = member.mention

        if support_role:
            content += (
                f" {support_role.mention}"
            )

        try:

            await channel.send(
                content=content,
                embed=embed,
                view=view
            )

        except Exception as e:

            print(
                f"[Ticket] Initial ticket message failed: "
                f"{type(e).__name__}: {e}"
            )

        await self.log_event(
            guild,
            guild_data,
            "🎫 Ticket Created",
            (
                f"Ticket: {channel.mention}\n"
                f"User: {member.mention}\n"
                f"Category: "
                f"{category_data.get('name')}"
            )
        )

        return channel

    # ========================================================
    # LOGGING
    # ========================================================

    async def log_event(
        self,
        guild,
        guild_data,
        title,
        description
    ):

        channel_id = guild_data["config"].get(
            "log_channel_id"
        )

        if not channel_id:
            return

        try:

            channel = guild.get_channel(
                int(channel_id)
            )

        except Exception:
            channel = None

        if not channel:
            return

        embed = discord.Embed(
            title=title,
            description=description,
            color=0x5865F2,
            timestamp=datetime.now(
                timezone.utc
            )
        )

        embed.set_footer(
            text="Air Commander • Ticket Logs"
        )

        try:

            await channel.send(
                embed=embed
            )

        except Exception:
            pass

    # ========================================================
    # TRANSCRIPT
    # ========================================================

    async def create_transcript(
        self,
        channel
    ):

        lines = []

        try:

            async for message in channel.history(
                limit=None,
                oldest_first=True
            ):

                timestamp = message.created_at.strftime(
                    "%Y-%m-%d %H:%M:%S"
                )

                content = message.content or ""

                if message.attachments:

                    attachments = " ".join(
                        a.url
                        for a in message.attachments
                    )

                    content += (
                        f" [Attachments: {attachments}]"
                    )

                lines.append(
                    f"[{timestamp}] "
                    f"{message.author} "
                    f"({message.author.id}): "
                    f"{content}"
                )

        except Exception as e:

            lines.append(
                f"Transcript error: {e}"
            )

        return "\n".join(lines)

    # ========================================================
    # /ticket setup
    # ========================================================

    @ticket.command(
        name="setup",
        description="Create the basic ticket system configuration."
    )
    @app_commands.checks.has_permissions(
        administrator=True
    )
    async def ticket_setup(
        self,
        interaction: discord.Interaction
    ):

        if not interaction.guild:
            await interaction.response.send_message(
                "❌ This command can only be used in a server."
            )
            return

        data = load_data()

        ensure_guild(
            data,
            interaction.guild.id
        )

        save_data(data)

        embed = discord.Embed(
            title="🎫 Ticket System Ready",
            description=(
                "Air Commander Ticket System has been initialized.\n\n"
                "Default category:\n"
                "🎫 **General Support**\n\n"
                "You can now customize categories "
                "and send a panel."
            ),
            color=0x5865F2
        )

        await interaction.response.send_message(
            embed=embed
        )

    # ========================================================
    # PANEL CREATE
    # ========================================================

    @panel.command(
        name="create",
        description="Create or reset the ticket panel."
    )
    @app_commands.checks.has_permissions(
        administrator=True
    )
    async def panel_create(
        self,
        interaction: discord.Interaction
    ):

        if not interaction.guild:
            await interaction.response.send_message(
                "❌ This command can only be used in a server."
            )
            return

        data = load_data()

        guild_data = ensure_guild(
            data,
            interaction.guild.id
        )

        guild_data["panel"] = {
            "title":
                "✈️ Air Commander Support Center",

            "description":
                (
                    "Need help? Open a support ticket below.\n\n"
                    "Our support team will assist you as soon as possible.\n\n"
                    "Select a category from the menu below."
                ),

            "color":
                0x5865F2,

            "footer":
                "Air Commander • Support System",

            "channel_id":
                None,

            "message_id":
                None
        }

        save_data(data)

        await interaction.response.send_message(
            "✅ Ticket panel created/reset successfully."
        )

    # ========================================================
    # PANEL EDIT
    # ========================================================

    @panel.command(
        name="edit",
        description="Edit the ticket panel."
    )
    @app_commands.describe(
        title="Panel title",
        description="Panel description",
        color="Hex color, example: #5865F2"
    )
    @app_commands.checks.has_permissions(
        administrator=True
    )
    async def panel_edit(
        self,
        interaction: discord.Interaction,
        title: str = None,
        description: str = None,
        color: str = None
    ):

        if not interaction.guild:
            await interaction.response.send_message(
                "❌ This command can only be used in a server."
            )
            return

        data = load_data()

        guild_data = ensure_guild(
            data,
            interaction.guild.id
        )

        panel = guild_data["panel"]

        if title:
            panel["title"] = title[:256]

        if description:
            panel["description"] = description[:4000]

        if color:

            try:

                color_value = color.replace(
                    "#",
                    ""
                ).strip()

                if len(color_value) not in (
                    3,
                    6
                ):
                    raise ValueError

                if len(color_value) == 3:
                    color_value = "".join(
                        x + x
                        for x in color_value
                    )

                panel["color"] = int(
                    color_value,
                    16
                )

            except ValueError:

                await interaction.response.send_message(
                    "❌ Invalid color. Example: `#5865F2`"
                )

                return

        save_data(data)

        await self.refresh_panel(
            interaction.guild
        )

        await interaction.response.send_message(
            "✅ Ticket panel updated."
        )

    # ========================================================
    # PANEL SEND
    # ========================================================

    @panel.command(
        name="send",
        description="Send the ticket panel."
    )
    @app_commands.describe(
        channel="Channel where the panel should be sent."
    )
    @app_commands.checks.has_permissions(
        administrator=True
    )
    async def panel_send(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel
    ):

        if not interaction.guild:
            await interaction.response.send_message(
                "❌ This command can only be used in a server."
            )
            return

        data = load_data()

        guild_data = ensure_guild(
            data,
            interaction.guild.id
        )

        embed = self.panel_embed(
            guild_data
        )

        # Guild-specific category dropdown
        view = TicketPanelView(
            self,
            interaction.guild.id
        )

        try:

            message = await channel.send(
                embed=embed,
                view=view
            )

        except Exception as e:

            await interaction.response.send_message(
                f"❌ Failed to send panel: `{e}`"
            )

            return

        guild_data["panel"]["channel_id"] = (
            channel.id
        )

        guild_data["panel"]["message_id"] = (
            message.id
        )

        save_data(data)

        # Register this exact panel as persistent
        try:

            self.bot.add_view(
                TicketPanelView(
                    self,
                    interaction.guild.id
                ),
                message_id=message.id
            )

        except Exception as e:

            print(
                f"[Ticket] Panel persistent registration "
                f"failed: {type(e).__name__}: {e}"
            )

        await interaction.response.send_message(
            f"✅ Ticket panel sent to {channel.mention}."
        )

    # ========================================================
    # PANEL DELETE
    # ========================================================

    @panel.command(
        name="delete",
        description="Delete the configured ticket panel."
    )
    @app_commands.checks.has_permissions(
        administrator=True
    )
    async def panel_delete(
        self,
        interaction: discord.Interaction
    ):

        if not interaction.guild:
            await interaction.response.send_message(
                "❌ This command can only be used in a server."
            )
            return

        data = load_data()

        guild_data = ensure_guild(
            data,
            interaction.guild.id
        )

        channel_id = guild_data["panel"].get(
            "channel_id"
        )

        message_id = guild_data["panel"].get(
            "message_id"
        )

        if not channel_id or not message_id:

            await interaction.response.send_message(
                "❌ No saved ticket panel found."
            )

            return

        channel = interaction.guild.get_channel(
            int(channel_id)
        )

        if channel:

            try:

                message = await channel.fetch_message(
                    int(message_id)
                )

                await message.delete()

            except Exception:
                pass

        guild_data["panel"]["channel_id"] = None
        guild_data["panel"]["message_id"] = None

        save_data(data)

        await interaction.response.send_message(
            "🗑️ Ticket panel deleted."
        )

    # ========================================================
    # CATEGORY ADD
    #
    # IMPORTANT:
    # Discord does NOT allow:
    # /ticket category add panel
    #
    # because /ticket/category is already nested.
    #
    # Instead:
    # /ticket category add
    #     name:
    #     emoji:
    #     description:
    #     prefix:
    #     type:
    # ========================================================

    @category.command(
        name="add",
        description="Add a ticket dropdown category."
    )
    @app_commands.describe(
        name="Category name",
        emoji="Category emoji",
        description="Category description",
        prefix="Ticket channel prefix",
        category_type="Category type. Use panel for dropdown categories."
    )
    @app_commands.choices(
        category_type=[
            app_commands.Choice(
                name="Panel",
                value="panel"
            )
        ]
    )
    @app_commands.checks.has_permissions(
        administrator=True
    )
    async def category_add(
        self,
        interaction: discord.Interaction,
        name: str,
        emoji: str = "🎫",
        description: str = "Get help from our support team.",
        prefix: str = "ticket",
        category_type: app_commands.Choice[str] = None
    ):

        if not interaction.guild:
            await interaction.response.send_message(
                "❌ This command can only be used in a server."
            )
            return

        data = load_data()

        guild_data = ensure_guild(
            data,
            interaction.guild.id
        )

        name = name.strip()

        if not name:

            await interaction.response.send_message(
                "❌ Category name cannot be empty."
            )

            return

        key = make_category_key(
            name
        )

        if not key:

            await interaction.response.send_message(
                "❌ Invalid category name."
            )

            return

        # Prevent same display name
        for existing_key, existing_category in (
            guild_data["categories"].items()
        ):

            if (
                existing_category.get(
                    "name",
                    ""
                ).lower()
                == name.lower()
            ):

                await interaction.response.send_message(
                    "❌ A category with this name already exists."
                )

                return

        # Prevent same key
        if key in guild_data["categories"]:

            await interaction.response.send_message(
                "❌ A category with this key already exists."
            )

            return

        category_type_value = (
            category_type.value
            if category_type
            else "panel"
        )

        guild_data["categories"][key] = {

            "name":
                name[:100],

            "emoji":
                (emoji or "🎫")[:10],

            "description":
                description[:300],

            "prefix":
                clean_channel_name(
                    prefix
                ),

            "type":
                category_type_value
        }

        save_data(data)

        # Automatically update existing panel
        await self.refresh_panel(
            interaction.guild
        )

        await interaction.response.send_message(
            (
                f"✅ Added `{name}` to the ticket panel.\n\n"
                f"🔑 Category key: `{key}`\n"
                f"📌 Type: `panel`"
            )
        )

    # ========================================================
    # CATEGORY EDIT
    # ========================================================

    @category.command(
        name="edit",
        description="Edit a ticket dropdown category."
    )
    @app_commands.describe(
        category_key="Existing category key or category name",
        name="New category name",
        emoji="New emoji",
        description="New description",
        prefix="New channel prefix"
    )
    @app_commands.checks.has_permissions(
        administrator=True
    )
    async def category_edit(
        self,
        interaction: discord.Interaction,
        category_key: str,
        name: str = None,
        emoji: str = None,
        description: str = None,
        prefix: str = None
    ):

        if not interaction.guild:
            await interaction.response.send_message(
                "❌ This command can only be used in a server."
            )
            return

        data = load_data()

        guild_data = ensure_guild(
            data,
            interaction.guild.id
        )

        found_key, category_data = find_category(
            guild_data,
            category_key
        )

        if not found_key:

            await interaction.response.send_message(
                "❌ Category not found. Use `/ticket category list`."
            )

            return

        old_key = found_key

        if name:

            name = name.strip()

            if not name:

                await interaction.response.send_message(
                    "❌ Category name cannot be empty."
                )

                return

            # Check duplicate display name
            for key, existing in (
                guild_data["categories"].items()
            ):

                if key == old_key:
                    continue

                if (
                    existing.get(
                        "name",
                        ""
                    ).lower()
                    == name.lower()
                ):

                    await interaction.response.send_message(
                        "❌ Another category already uses this name."
                    )

                    return

            new_key = make_category_key(
                name
            )

            if not new_key:

                await interaction.response.send_message(
                    "❌ Invalid new category name."
                )

                return

            if (
                new_key != old_key
                and new_key in guild_data["categories"]
            ):

                await interaction.response.send_message(
                    "❌ The new category key already exists."
                )

                return

            if new_key != old_key:

                guild_data["categories"][new_key] = (
                    guild_data["categories"].pop(
                        old_key
                    )
                )

                category_data = guild_data[
                    "categories"
                ][new_key]

                # Update old ticket records
                for ticket in guild_data["tickets"].values():

                    if ticket.get("category") == old_key:
                        ticket["category"] = new_key

                found_key = new_key

            category_data["name"] = name[:100]

        if emoji:
            category_data["emoji"] = emoji[:10]

        if description:
            category_data["description"] = (
                description[:300]
            )

        if prefix:
            category_data["prefix"] = (
                clean_channel_name(prefix)
            )

        category_data.setdefault(
            "type",
            "panel"
        )

        save_data(data)

        await self.refresh_panel(
            interaction.guild
        )

        await interaction.response.send_message(
            (
                f"✅ Ticket category updated.\n\n"
                f"🔑 Key: `{found_key}`\n"
                f"🎫 Name: `{category_data.get('name')}`"
            )
        )

    # ========================================================
    # CATEGORY REMOVE
    # ========================================================

    @category.command(
        name="remove",
        description="Remove a ticket dropdown category."
    )
    @app_commands.describe(
        category_key="Category key or category name to remove."
    )
    @app_commands.checks.has_permissions(
        administrator=True
    )
    async def category_remove(
        self,
        interaction: discord.Interaction,
        category_key: str
    ):

        if not interaction.guild:
            await interaction.response.send_message(
                "❌ This command can only be used in a server."
            )
            return

        data = load_data()

        guild_data = ensure_guild(
            data,
            interaction.guild.id
        )

        found_key, category_data = find_category(
            guild_data,
            category_key
        )

        if not found_key:

            await interaction.response.send_message(
                "❌ Category not found."
            )

            return

        # Don't allow deleting the final category
        if len(
            guild_data["categories"]
        ) <= 1:

            await interaction.response.send_message(
                "❌ You must keep at least one ticket category."
            )

            return

        removed_name = category_data.get(
            "name",
            found_key
        )

        del guild_data["categories"][
            found_key
        ]

        save_data(data)

        await self.refresh_panel(
            interaction.guild
        )

        await interaction.response.send_message(
            (
                f"🗑️ Removed `{removed_name}` "
                f"(`{found_key}`) from the ticket panel."
            )
        )

    # ========================================================
    # CATEGORY LIST
    # ========================================================

    @category.command(
        name="list",
        description="List all ticket categories."
    )
    @app_commands.checks.has_permissions(
        administrator=True
    )
    async def category_list(
        self,
        interaction: discord.Interaction
    ):

        if not interaction.guild:
            await interaction.response.send_message(
                "❌ This command can only be used in a server."
            )
            return

        data = load_data()

        guild_data = ensure_guild(
            data,
            interaction.guild.id
        )

        embed = discord.Embed(
            title="🎫 Ticket Categories",
            description=(
                "Categories currently available "
                "in the ticket panel."
            ),
            color=0x5865F2
        )

        categories = guild_data[
            "categories"
        ]

        if not categories:

            embed.description = (
                "❌ No ticket categories configured."
            )

        else:

            lines = []

            for key, value in list(
                categories.items()
            )[:25]:

                lines.append(
                    (
                        f"{value.get('emoji', '🎫')} "
                        f"**{value.get('name', key)}**\n"
                        f"🔑 Key: `{key}`\n"
                        f"📝 {value.get('description', '')}\n"
                        f"🏷️ Prefix: "
                        f"`{value.get('prefix', 'ticket')}`"
                    )
                )

            embed.description = (
                "\n\n".join(lines)
            )

            if len(categories) > 25:

                embed.set_footer(
                    text=(
                        "Discord dropdowns support a maximum "
                        "of 25 options."
                    )
                )

        await interaction.response.send_message(
            embed=embed
        )

    # ========================================================
    # CONFIG
    # ========================================================

    @ticket.command(
        name="config",
        description="Configure ticket system settings."
    )
    @app_commands.describe(
        support_role="Support team role",
        log_channel="Ticket log channel",
        ticket_category="Discord category for tickets",
        transcript="Enable transcripts",
        naming="Ticket channel naming template"
    )
    @app_commands.checks.has_permissions(
        administrator=True
    )
    async def ticket_config(
        self,
        interaction: discord.Interaction,
        support_role: discord.Role = None,
        log_channel: discord.TextChannel = None,
        ticket_category: discord.CategoryChannel = None,
        transcript: bool = None,
        naming: str = None
    ):

        if not interaction.guild:
            await interaction.response.send_message(
                "❌ This command can only be used in a server."
            )
            return

        data = load_data()

        guild_data = ensure_guild(
            data,
            interaction.guild.id
        )

        config = guild_data["config"]

        if support_role:
            config["support_role_id"] = (
                support_role.id
            )

        if log_channel:
            config["log_channel_id"] = (
                log_channel.id
            )

        if ticket_category:
            config["ticket_category_id"] = (
                ticket_category.id
            )

        if transcript is not None:
            config["transcript"] = transcript

        if naming:
            config["naming"] = naming[:80]

        save_data(data)

        embed = discord.Embed(
            title="⚙️ Ticket Configuration",
            color=0x5865F2
        )

        role_text = "Not set"

        if config.get("support_role_id"):

            role = interaction.guild.get_role(
                int(
                    config["support_role_id"]
                )
            )

            if role:
                role_text = role.mention

        log_text = "Not set"

        if config.get("log_channel_id"):

            channel = interaction.guild.get_channel(
                int(
                    config["log_channel_id"]
                )
            )

            if channel:
                log_text = channel.mention

        category_text = "Not set"

        if config.get("ticket_category_id"):

            category = interaction.guild.get_channel(
                int(
                    config["ticket_category_id"]
                )
            )

            if category:
                category_text = category.name

        embed.add_field(
            name="🛡️ Support Role",
            value=role_text,
            inline=True
        )

        embed.add_field(
            name="📋 Log Channel",
            value=log_text,
            inline=True
        )

        embed.add_field(
            name="📂 Ticket Category",
            value=category_text,
            inline=True
        )

        embed.add_field(
            name="📄 Transcript",
            value=str(
                config.get(
                    "transcript",
                    True
                )
            ),
            inline=True
        )

        embed.add_field(
            name="🏷️ Naming",
            value=(
                f"`{config.get('naming')}`"
            ),
            inline=True
        )

        await interaction.response.send_message(
            embed=embed
        )

    # ========================================================
    # CLOSE
    # ========================================================

    @ticket.command(
        name="close",
        description="Close the current ticket."
    )
    async def ticket_close(
        self,
        interaction: discord.Interaction
    ):

        await self.close_ticket(
            interaction
        )

    # ========================================================
    # REOPEN
    # ========================================================

    @ticket.command(
        name="reopen",
        description="Reopen the current ticket."
    )
    @app_commands.checks.has_permissions(
        manage_channels=True
    )
    async def ticket_reopen(
        self,
        interaction: discord.Interaction
    ):

        if not interaction.guild:
            await interaction.response.send_message(
                "❌ This command can only be used in a server."
            )
            return

        data = load_data()

        guild_data = ensure_guild(
            data,
            interaction.guild.id
        )

        _, ticket = find_ticket(
            guild_data,
            interaction.channel.id
        )

        if not ticket:

            await interaction.response.send_message(
                "❌ This is not a ticket channel."
            )

            return

        member = interaction.guild.get_member(
            int(ticket["user_id"])
        )

        if member:

            await interaction.channel.set_permissions(
                member,
                view_channel=True,
                send_messages=True,
                read_message_history=True
            )

        ticket["closed"] = False

        save_data(data)

        await interaction.response.send_message(
            "🔓 Ticket reopened."
        )

    # ========================================================
    # CLAIM
    # ========================================================

    @ticket.command(
        name="claim",
        description="Claim the current ticket."
    )
    async def ticket_claim(
        self,
        interaction: discord.Interaction
    ):

        if not interaction.guild:
            await interaction.response.send_message(
                "❌ This command can only be used in a server."
            )
            return

        data = load_data()

        guild_data = ensure_guild(
            data,
            interaction.guild.id
        )

        _, ticket = find_ticket(
            guild_data,
            interaction.channel.id
        )

        if not ticket:

            await interaction.response.send_message(
                "❌ This is not a ticket channel."
            )

            return

        if not is_admin(
            interaction.user
        ):

            support_role_id = (
                guild_data["config"].get(
                    "support_role_id"
                )
            )

            if (
                not support_role_id
                or not any(
                    role.id == int(
                        support_role_id
                    )
                    for role in interaction.user.roles
                )
            ):

                await interaction.response.send_message(
                    "❌ You are not part of the support team."
                )

                return

        ticket["claimed_by"] = (
            interaction.user.id
        )

        save_data(data)

        await interaction.response.send_message(
            f"🙋 Ticket claimed by "
            f"{interaction.user.mention}."
        )

    # ========================================================
    # ADD USER
    # ========================================================

    @ticket.command(
        name="add",
        description="Add a user to the current ticket."
    )
    @app_commands.describe(
        user="User to add."
    )
    async def ticket_add(
        self,
        interaction: discord.Interaction,
        user: discord.Member
    ):

        if not is_admin(
            interaction.user
        ):

            await interaction.response.send_message(
                "❌ You need administrator permissions."
            )

            return

        if not interaction.guild:
            await interaction.response.send_message(
                "❌ This command can only be used in a server."
            )
            return

        data = load_data()

        guild_data = ensure_guild(
            data,
            interaction.guild.id
        )

        _, ticket = find_ticket(
            guild_data,
            interaction.channel.id
        )

        if not ticket:

            await interaction.response.send_message(
                "❌ This is not a ticket channel."
            )

            return

        await interaction.channel.set_permissions(
            user,
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
            embed_links=True
        )

        ticket.setdefault(
            "added_users",
            []
        )

        if user.id not in ticket[
            "added_users"
        ]:

            ticket[
                "added_users"
            ].append(
                user.id
            )

        save_data(data)

        await interaction.response.send_message(
            f"👥 Added {user.mention} to the ticket."
        )

    # ========================================================
    # REMOVE USER
    # ========================================================

    @ticket.command(
        name="remove",
        description="Remove a user from the current ticket."
    )
    @app_commands.describe(
        user="User to remove."
    )
    async def ticket_remove(
        self,
        interaction: discord.Interaction,
        user: discord.Member
    ):

        if not is_admin(
            interaction.user
        ):

            await interaction.response.send_message(
                "❌ You need administrator permissions."
            )

            return

        if not interaction.guild:
            await interaction.response.send_message(
                "❌ This command can only be used in a server."
            )
            return

        data = load_data()

        guild_data = ensure_guild(
            data,
            interaction.guild.id
        )

        _, ticket = find_ticket(
            guild_data,
            interaction.channel.id
        )

        if not ticket:

            await interaction.response.send_message(
                "❌ This is not a ticket channel."
            )

            return

        if user.id == ticket.get(
            "user_id"
        ):

            await interaction.response.send_message(
                "❌ You cannot remove the ticket creator."
            )

            return

        await interaction.channel.set_permissions(
            user,
            overwrite=None
        )

        if user.id in ticket.get(
            "added_users",
            []
        ):

            ticket[
                "added_users"
            ].remove(
                user.id
            )

        save_data(data)

        await interaction.response.send_message(
            f"👋 Removed {user.mention} from the ticket."
        )

    # ========================================================
    # RENAME
    # ========================================================

    @ticket.command(
        name="rename",
        description="Rename the current ticket."
    )
    @app_commands.describe(
        name="New channel name."
    )
    async def ticket_rename(
        self,
        interaction: discord.Interaction,
        name: str
    ):

        if not is_admin(
            interaction.user
        ):

            await interaction.response.send_message(
                "❌ You need administrator permissions."
            )

            return

        if not interaction.guild:
            await interaction.response.send_message(
                "❌ This command can only be used in a server."
            )
            return

        data = load_data()

        guild_data = ensure_guild(
            data,
            interaction.guild.id
        )

        _, ticket = find_ticket(
            guild_data,
            interaction.channel.id
        )

        if not ticket:

            await interaction.response.send_message(
                "❌ This is not a ticket channel."
            )

            return

        name = clean_channel_name(
            name
        )

        await interaction.channel.edit(
            name=name,
            reason="Air Commander Ticket Rename"
        )

        await interaction.response.send_message(
            f"✏️ Ticket renamed to `{name}`."
        )

    # ========================================================
    # PREFIX TICKET GROUP
    # ========================================================

    @commands.group(
        name="ticket",
        invoke_without_command=True
    )
    async def ticket_prefix(
        self,
        ctx
    ):

        embed = discord.Embed(
            title="🎫 Air Commander Ticket System",
            description=(
                "`,ticket setup`\n"
                "`,ticket panel create`\n"
                "`,ticket panel edit`\n"
                "`,ticket panel send #channel`\n"
                "`,ticket panel delete`\n\n"

                "`,ticket category add`\n"
                "`,ticket category edit`\n"
                "`,ticket category remove`\n"
                "`,ticket category list`\n\n"

                "`,ticket config`\n"
                "`,ticket close`\n"
                "`,ticket reopen`\n"
                "`,ticket claim`\n"
                "`,ticket add @user`\n"
                "`,ticket remove @user`\n"
                "`,ticket rename name`"
            ),
            color=0x5865F2
        )

        await ctx.send(
            embed=embed
        )

    # ========================================================
    # PREFIX SETUP
    # ========================================================

    @ticket_prefix.command(
        name="setup"
    )
    @commands.has_permissions(
        administrator=True
    )
    async def prefix_setup(
        self,
        ctx
    ):

        data = load_data()

        ensure_guild(
            data,
            ctx.guild.id
        )

        save_data(data)

        await ctx.send(
            "✅ Ticket system initialized."
        )

    # ========================================================
    # PREFIX PANEL GROUP
    # ========================================================

    @ticket_prefix.group(
        name="panel",
        invoke_without_command=True
    )
    @commands.has_permissions(
        administrator=True
    )
    async def prefix_panel(
        self,
        ctx
    ):

        await ctx.send(
            "🎫 Use `,ticket panel create/edit/send/delete`."
        )

    # ========================================================
    # PREFIX PANEL CREATE
    # ========================================================

    @prefix_panel.command(
        name="create"
    )
    async def prefix_panel_create(
        self,
        ctx
    ):

        data = load_data()

        guild_data = ensure_guild(
            data,
            ctx.guild.id
        )

        guild_data["panel"] = {
            "title":
                "✈️ Air Commander Support Center",

            "description":
                (
                    "Need help? Open a support ticket below.\n\n"
                    "Our support team will assist you as soon as possible.\n\n"
                    "Select a category from the menu below."
                ),

            "color":
                0x5865F2,

            "footer":
                "Air Commander • Support System",

            "channel_id":
                None,

            "message_id":
                None
        }

        save_data(data)

        await ctx.send(
            "✅ Ticket panel created/reset."
        )

    # ========================================================
    # PREFIX PANEL SEND
    # ========================================================

    @prefix_panel.command(
        name="send"
    )
    async def prefix_panel_send(
        self,
        ctx,
        channel: discord.TextChannel
    ):

        data = load_data()

        guild_data = ensure_guild(
            data,
            ctx.guild.id
        )

        embed = self.panel_embed(
            guild_data
        )

        view = TicketPanelView(
            self,
            ctx.guild.id
        )

        try:

            message = await channel.send(
                embed=embed,
                view=view
            )

        except Exception as e:

            await ctx.send(
                f"❌ Failed to send panel: `{e}`"
            )

            return

        guild_data["panel"][
            "channel_id"
        ] = channel.id

        guild_data["panel"][
            "message_id"
        ] = message.id

        save_data(data)

        try:

            self.bot.add_view(
                TicketPanelView(
                    self,
                    ctx.guild.id
                ),
                message_id=message.id
            )

        except Exception:
            pass

        await ctx.send(
            f"✅ Ticket panel sent to {channel.mention}."
        )

    # ========================================================
    # PREFIX PANEL DELETE
    # ========================================================

    @prefix_panel.command(
        name="delete"
    )
    async def prefix_panel_delete(
        self,
        ctx
    ):

        data = load_data()

        guild_data = ensure_guild(
            data,
            ctx.guild.id
        )

        channel_id = guild_data["panel"].get(
            "channel_id"
        )

        message_id = guild_data["panel"].get(
            "message_id"
        )

        if not channel_id or not message_id:

            await ctx.send(
                "❌ No saved ticket panel found."
            )

            return

        channel = ctx.guild.get_channel(
            int(channel_id)
        )

        if channel:

            try:

                message = await channel.fetch_message(
                    int(message_id)
                )

                await message.delete()

            except Exception:
                pass

        guild_data["panel"][
            "channel_id"
        ] = None

        guild_data["panel"][
            "message_id"
        ] = None

        save_data(data)

        await ctx.send(
            "🗑️ Ticket panel deleted."
        )

    # ========================================================
    # PREFIX CATEGORY GROUP
    # ========================================================

    @ticket_prefix.group(
        name="category",
        invoke_without_command=True
    )
    @commands.has_permissions(
        administrator=True
    )
    async def prefix_category(
        self,
        ctx
    ):

        await ctx.send(
            "🎫 Use `,ticket category add/edit/remove/list`."
        )

    # ========================================================
    # PREFIX CATEGORY ADD
    # ========================================================

    @prefix_category.command(
        name="add"
    )
    async def prefix_category_add(
        self,
        ctx,
        name: str,
        emoji: str = "🎫",
        *,
        description: str = "Get help from our support team."
    ):

        data = load_data()

        guild_data = ensure_guild(
            data,
            ctx.guild.id
        )

        name = name.strip()

        key = make_category_key(
            name
        )

        if not key:

            await ctx.send(
                "❌ Invalid category name."
            )

            return

        if key in guild_data[
            "categories"
        ]:

            await ctx.send(
                "❌ Category already exists."
            )

            return

        guild_data["categories"][key] = {

            "name":
                name[:100],

            "emoji":
                emoji[:10],

            "description":
                description[:300],

            "prefix":
                "ticket",

            "type":
                "panel"
        }

        save_data(data)

        await self.refresh_panel(
            ctx.guild
        )

        await ctx.send(
            f"✅ Added `{name}` to the dropdown."
        )

    # ========================================================
    # PREFIX CATEGORY LIST
    # ========================================================

    @prefix_category.command(
        name="list"
    )
    async def prefix_category_list(
        self,
        ctx
    ):

        data = load_data()

        guild_data = ensure_guild(
            data,
            ctx.guild.id
        )

        embed = discord.Embed(
            title="🎫 Ticket Categories",
            color=0x5865F2
        )

        lines = []

        for key, value in list(
            guild_data[
                "categories"
            ].items()
        )[:25]:

            lines.append(
                (
                    f"{value.get('emoji', '🎫')} "
                    f"**{value.get('name', key)}** "
                    f"— `{key}`"
                )
            )

        embed.description = (
            "\n".join(lines)
            if lines
            else "No categories."
        )

        await ctx.send(
            embed=embed
        )

    # ========================================================
    # PREFIX CATEGORY REMOVE
    # ========================================================

    @prefix_category.command(
        name="remove"
    )
    async def prefix_category_remove(
        self,
        ctx,
        category_key: str
    ):

        data = load_data()

        guild_data = ensure_guild(
            data,
            ctx.guild.id
        )

        found_key, category_data = find_category(
            guild_data,
            category_key
        )

        if not found_key:

            await ctx.send(
                "❌ Category not found."
            )

            return

        if len(
            guild_data["categories"]
        ) <= 1:

            await ctx.send(
                "❌ You must keep at least one ticket category."
            )

            return

        del guild_data[
            "categories"
        ][found_key]

        save_data(data)

        await self.refresh_panel(
            ctx.guild
        )

        await ctx.send(
            f"🗑️ Removed `{found_key}`."
        )

    # ========================================================
    # PREFIX CLOSE
    # ========================================================

    @ticket_prefix.command(
        name="close"
    )
    async def prefix_close(
        self,
        ctx
    ):

        await self.close_ticket(
            ctx
        )

    # ========================================================
    # PREFIX CLAIM
    # ========================================================

    @ticket_prefix.command(
        name="claim"
    )
    async def prefix_claim(
        self,
        ctx
    ):

        data = load_data()

        guild_data = ensure_guild(
            data,
            ctx.guild.id
        )

        _, ticket = find_ticket(
            guild_data,
            ctx.channel.id
        )

        if not ticket:

            await ctx.send(
                "❌ This is not a ticket."
            )

            return

        if not is_admin(
            ctx.author
        ):

            support_role_id = (
                guild_data["config"].get(
                    "support_role_id"
                )
            )

            if (
                not support_role_id
                or not any(
                    role.id == int(
                        support_role_id
                    )
                    for role in ctx.author.roles
                )
            ):

                await ctx.send(
                    "❌ You are not support staff."
                )

                return

        ticket[
            "claimed_by"
        ] = ctx.author.id

        save_data(data)

        await ctx.send(
            f"🙋 Ticket claimed by "
            f"{ctx.author.mention}."
        )

    # ========================================================
    # PREFIX RENAME
    # ========================================================

    @ticket_prefix.command(
        name="rename"
    )
    @commands.has_permissions(
        manage_channels=True
    )
    async def prefix_rename(
        self,
        ctx,
        *,
        name: str
    ):

        data = load_data()

        guild_data = ensure_guild(
            data,
            ctx.guild.id
        )

        _, ticket = find_ticket(
            guild_data,
            ctx.channel.id
        )

        if not ticket:

            await ctx.send(
                "❌ This is not a ticket."
            )

            return

        name = clean_channel_name(
            name
        )

        await ctx.channel.edit(
            name=name
        )

        await ctx.send(
            f"✏️ Renamed to `{name}`."
        )

    # ========================================================
    # CLOSE ENGINE
    # ========================================================

    async def close_ticket(
        self,
        source
    ):

        if isinstance(
            source,
            discord.Interaction
        ):

            guild = source.guild
            channel = source.channel
            user = source.user

            async def send(
                *args,
                **kwargs
            ):

                if not source.response.is_done():

                    return await source.response.send_message(
                        *args,
                        **kwargs
                    )

                return await source.followup.send(
                    *args,
                    **kwargs
                )

        else:

            guild = source.guild
            channel = source.channel
            user = source.author

            async def send(
                *args,
                **kwargs
            ):

                return await source.send(
                    *args,
                    **kwargs
                )

        if guild is None:
            return

        data = load_data()

        guild_data = ensure_guild(
            data,
            guild.id
        )

        _, ticket = find_ticket(
            guild_data,
            channel.id
        )

        if not ticket:

            await send(
                "❌ This is not a ticket channel."
            )

            return

        if ticket.get(
            "closed"
        ):

            await send(
                "🔒 This ticket is already closed."
            )

            return

        if not is_admin(
            user
        ):

            owner_id = int(
                ticket.get(
                    "user_id"
                )
            )

            support_role_id = (
                guild_data["config"].get(
                    "support_role_id"
                )
            )

            is_support = False

            if support_role_id:

                is_support = any(
                    role.id == int(
                        support_role_id
                    )
                    for role in user.roles
                )

            if (
                user.id != owner_id
                and not is_support
            ):

                await send(
                    "❌ Only the ticket creator or "
                    "support team can close this ticket."
                )

                return

        ticket["closed"] = True

        save_data(data)

        transcript_file = None

        if guild_data[
            "config"
        ].get(
            "transcript",
            True
        ):

            transcript = await self.create_transcript(
                channel
            )

            transcript_file = discord.File(
                fp=io.BytesIO(
                    transcript.encode(
                        "utf-8",
                        errors="replace"
                    )
                ),
                filename=(
                    f"{channel.name}-transcript.txt"
                )
            )

        embed = discord.Embed(
            title="🔒 Ticket Closed",
            description=(
                f"This ticket has been closed by "
                f"{user.mention}.\n\n"
                "Staff can reopen it if needed."
            ),
            color=0xED4245,
            timestamp=datetime.now(
                timezone.utc
            )
        )

        if transcript_file:

            await send(
                embed=embed,
                file=transcript_file
            )

        else:

            await send(
                embed=embed
            )

        owner = guild.get_member(
            int(
                ticket["user_id"]
            )
        )

        if owner:

            try:

                await channel.set_permissions(
                    owner,
                    view_channel=False,
                    send_messages=False
                )

            except Exception:
                pass

        await self.log_event(
            guild,
            guild_data,
            "🔒 Ticket Closed",
            (
                f"Channel: {channel.mention}\n"
                f"Closed by: {user.mention}"
            )
        )

    # ========================================================
    # PREFIX ERROR
    # ========================================================

    @ticket_prefix.error
    async def ticket_prefix_error(
        self,
        ctx,
        error
    ):

        if isinstance(
            error,
            commands.MissingPermissions
        ):

            await ctx.send(
                "❌ You don't have permission to use "
                "this command."
            )


# ============================================================
# TICKET CONTROL VIEW
# ============================================================

class TicketControlView(
    discord.ui.View
):

    def __init__(
        self,
        cog
    ):

        super().__init__(
            timeout=None
        )

        self.cog = cog

    # ========================================================
    # CLOSE BUTTON
    # ========================================================

    @discord.ui.button(
        label="Close Ticket",
        emoji="🔒",
        style=discord.ButtonStyle.danger,
        custom_id="aircommander:ticket_close"
    )
    async def close_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        await self.cog.close_ticket(
            interaction
        )

    # ========================================================
    # CLAIM BUTTON
    # ========================================================

    @discord.ui.button(
        label="Claim",
        emoji="🙋",
        style=discord.ButtonStyle.primary,
        custom_id="aircommander:ticket_claim"
    )
    async def claim_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if not interaction.guild:

            await interaction.response.send_message(
                "❌ This can only be used in a server."
            )

            return

        data = load_data()

        guild_data = ensure_guild(
            data,
            interaction.guild.id
        )

        _, ticket = find_ticket(
            guild_data,
            interaction.channel.id
        )

        if not ticket:

            await interaction.response.send_message(
                "❌ This is not a ticket."
            )

            return

        if not is_admin(
            interaction.user
        ):

            role_id = (
                guild_data["config"].get(
                    "support_role_id"
                )
            )

            if (
                not role_id
                or not any(
                    role.id == int(role_id)
                    for role in interaction.user.roles
                )
            ):

                await interaction.response.send_message(
                    "❌ You are not support staff."
                )

                return

        ticket[
            "claimed_by"
        ] = interaction.user.id

        save_data(data)

        await interaction.response.send_message(
            f"🙋 Ticket claimed by "
            f"{interaction.user.mention}."
        )

    # ========================================================
    # ADD USER BUTTON
    # ========================================================

    @discord.ui.button(
        label="Add User",
        emoji="👥",
        style=discord.ButtonStyle.secondary,
        custom_id="aircommander:ticket_add"
    )
    async def add_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        await interaction.response.send_message(
            "👥 Use `/ticket add @user` "
            "to add someone."
        )


# ============================================================
# ONE AND ONLY SETUP
# ============================================================

async def setup(bot):

    # ========================================================
    # SNIPE
    # ========================================================

    if bot.get_command(
        "snipe"
    ) is None:

        bot.add_command(
            snipe_prefix
        )

    if bot.tree.get_command(
        "snipe"
    ) is None:

        bot.tree.add_command(
            app_commands.Command(
                name="snipe",
                description=(
                    "Show the most recently "
                    "deleted message in this channel"
                ),
                callback=snipe_slash
            )
        )

    # IMPORTANT:
    # add_listener instead of @bot.event.
    # This prevents Snipe from replacing another
    # module's on_message_delete listener.

    bot.add_listener(
        snipe_message_delete,
        "on_message_delete"
    )

    # ========================================================
    # TICKET
    # ========================================================

    if bot.get_cog(
        "TicketSystem"
    ) is None:

        cog = TicketSystem(
            bot
        )

        await bot.add_cog(
            cog
        )

        # Restore persistent views after
        # the cog has been registered.
        await cog.restore_persistent_views()

    print(
        "✅ Air Commander Ticket + Snipe System loaded."
    )
