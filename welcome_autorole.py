# ============================================================
# Air Commander - Welcome + Self Role System
# welcome.py
# ============================================================

import json
import os
import re
from copy import deepcopy

import discord
from discord.ext import commands
from discord import app_commands


# ============================================================
# CONFIG
# ============================================================

DATA_FILE = "welcome_config.json"

DEFAULT_COLOR = 0x5865F2

IMAGE_OPTIONS = {
    "member": "Member Avatar",
    "server": "Server Icon",
    "custom": "Custom URL",
    "none": "None",
}


# ============================================================
# DATABASE
# ============================================================

def load_data():
    if not os.path.exists(DATA_FILE):
        return {}

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_data(data):
    temp_file = DATA_FILE + ".tmp"

    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            indent=4,
            ensure_ascii=False
        )

    os.replace(temp_file, DATA_FILE)


DATA = load_data()


def guild_data(guild_id: int):
    gid = str(guild_id)

    if gid not in DATA:
        DATA[gid] = {
            # ---------------- Welcome ----------------
            "channel_id": None,
            "message": "",
            "active_embed": None,
            "embeds": {},

            # ---------------- Self Role ----------------
            "selfroles": {},
            "reaction_roles": {}
        }

    data = DATA[gid]

    # Old config compatibility
    data.setdefault("channel_id", None)
    data.setdefault("message", "")
    data.setdefault("active_embed", None)
    data.setdefault("embeds", {})

    data.setdefault("selfroles", {})
    data.setdefault("reaction_roles", {})

    return data


# ============================================================
# VARIABLES
# ============================================================

def replace_variables(text: str, member: discord.Member):
    if not text:
        return ""

    guild = member.guild

    replacements = {
        "{user}": member.mention,
        "{username}": member.name,
        "{displayname}": member.display_name,
        "{server}": guild.name,
        "{membercount}": str(
            guild.member_count or len(guild.members)
        ),
        "{user_id}": str(member.id),
        "{server_id}": str(guild.id),
    }

    for key, value in replacements.items():
        text = text.replace(key, value)

    return text


# ============================================================
# IMAGE HELPERS
# ============================================================

def get_member_avatar(member: discord.Member):
    return member.display_avatar.url


def get_server_icon(guild: discord.Guild):
    if guild.icon:
        return guild.icon.url

    return None


def apply_image(
    embed: discord.Embed,
    mode: str,
    custom_url: str,
    member: discord.Member
):
    mode = (mode or "none").lower()

    if mode == "member":
        embed.set_image(
            url=get_member_avatar(member)
        )

    elif mode == "server":
        url = get_server_icon(member.guild)

        if url:
            embed.set_image(url=url)

    elif mode == "custom":
        if custom_url:
            embed.set_image(url=custom_url)


def apply_thumbnail(
    embed: discord.Embed,
    mode: str,
    custom_url: str,
    member: discord.Member
):
    mode = (mode or "none").lower()

    if mode == "member":
        embed.set_thumbnail(
            url=get_member_avatar(member)
        )

    elif mode == "server":
        url = get_server_icon(member.guild)

        if url:
            embed.set_thumbnail(url=url)

    elif mode == "custom":
        if custom_url:
            embed.set_thumbnail(url=custom_url)


# ============================================================
# EMBED BUILDER
# ============================================================

def build_welcome_embed(
    template,
    member: discord.Member
):
    title = replace_variables(
        template.get("title", ""),
        member
    )

    description = replace_variables(
        template.get("description", ""),
        member
    )

    footer = replace_variables(
        template.get("footer", ""),
        member
    )

    author = replace_variables(
        template.get("author", ""),
        member
    )

    color = template.get(
        "color",
        DEFAULT_COLOR
    )

    try:
        color = int(color)

    except (ValueError, TypeError):
        color = DEFAULT_COLOR

    embed = discord.Embed(
        title=title or None,
        description=description or None,
        color=color
    )

    if author:
        embed.set_author(
            name=author
        )

    if footer:
        embed.set_footer(
            text=footer
        )

    apply_image(
        embed,
        template.get(
            "image_mode",
            "none"
        ),
        template.get(
            "image_url",
            ""
        ),
        member
    )

    apply_thumbnail(
        embed,
        template.get(
            "thumbnail_mode",
            "none"
        ),
        template.get(
            "thumbnail_url",
            ""
        ),
        member
    )

    return embed


# ============================================================
# DEFAULT WELCOME TEMPLATE
# ============================================================

def default_template():
    return {
        "title": "Welcome {user}! 👋",

        "description": (
            "Hey {user}, welcome to **{server}**!\n\n"
            "You are our **{membercount}th member.**"
        ),

        "author": "",

        "footer": (
            "Enjoy your stay • {server}"
        ),

        "color": DEFAULT_COLOR,

        "image_mode": "server",
        "image_url": "",

        "thumbnail_mode": "member",
        "thumbnail_url": "",
    }


# ============================================================
# WELCOME TEXT MODAL
# ============================================================

class TextModal(discord.ui.Modal):

    def __init__(
        self,
        cog,
        guild_id,
        template_name,
        field,
        title,
        label,
        current
    ):
        super().__init__(title=title)

        self.cog = cog
        self.guild_id = guild_id
        self.template_name = template_name
        self.field = field

        self.value_input = discord.ui.TextInput(
            label=label,
            default=current[:4000]
            if current
            else "",

            required=False,

            style=discord.TextStyle.paragraph,

            max_length=4000
        )

        self.add_item(
            self.value_input
        )

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):
        data = guild_data(
            self.guild_id
        )

        template = data["embeds"].get(
            self.template_name
        )

        if not template:
            await interaction.response.send_message(
                "❌ That embed template no longer exists.",
                ephemeral=True
            )
            return

        template[self.field] = (
            self.value_input.value
        )

        save_data(DATA)

        await interaction.response.edit_message(
            content=f"✅ `{self.field}` updated.",
            view=EmbedEditorView(
                self.cog,
                self.guild_id,
                self.template_name
            )
        )


# ============================================================
# COLOR MODAL
# ============================================================

class ColorModal(discord.ui.Modal):

    def __init__(
        self,
        cog,
        guild_id,
        template_name,
        current
    ):
        super().__init__(
            title="Edit Embed Color"
        )

        self.cog = cog
        self.guild_id = guild_id
        self.template_name = template_name

        self.color_input = discord.ui.TextInput(
            label="Hex Color",
            placeholder="#5865F2",

            default=f"#{current:06X}",

            required=True,

            max_length=7
        )

        self.add_item(
            self.color_input
        )

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):
        value = (
            self.color_input.value
            .strip()
            .replace("#", "")
        )

        try:
            color = int(
                value,
                16
            )

            if not 0 <= color <= 0xFFFFFF:
                raise ValueError

        except ValueError:
            await interaction.response.send_message(
                "❌ Invalid color. Example: `#5865F2`",
                ephemeral=True
            )
            return

        data = guild_data(
            self.guild_id
        )

        template = data["embeds"].get(
            self.template_name
        )

        if not template:
            await interaction.response.send_message(
                "❌ Template not found.",
                ephemeral=True
            )
            return

        template["color"] = color

        save_data(DATA)

        await interaction.response.edit_message(
            content="✅ Color updated.",

            view=EmbedEditorView(
                self.cog,
                self.guild_id,
                self.template_name
            )
        )


# ============================================================
# IMAGE MODAL
# ============================================================

class ImageModal(discord.ui.Modal):

    def __init__(
        self,
        cog,
        guild_id,
        template_name,
        field,
        title
    ):
        super().__init__(
            title=title
        )

        self.cog = cog
        self.guild_id = guild_id
        self.template_name = template_name
        self.field = field

        self.url_input = discord.ui.TextInput(
            label="Custom Image URL",

            placeholder=(
                "https://example.com/image.png"
            ),

            required=True,

            max_length=1000
        )

        self.add_item(
            self.url_input
        )

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):
        data = guild_data(
            self.guild_id
        )

        template = data["embeds"].get(
            self.template_name
        )

        if not template:
            await interaction.response.send_message(
                "❌ Template not found.",
                ephemeral=True
            )
            return

        template[
            self.field + "_mode"
        ] = "custom"

        template[
            self.field + "_url"
        ] = self.url_input.value.strip()

        save_data(DATA)

        await interaction.response.edit_message(
            content="✅ Custom image saved.",

            view=EmbedEditorView(
                self.cog,
                self.guild_id,
                self.template_name
            )
        )


# ============================================================
# IMAGE SELECT
# ============================================================

class ImageSelect(discord.ui.Select):

    def __init__(
        self,
        cog,
        guild_id,
        template_name,
        field
    ):
        self.cog = cog
        self.guild_id = guild_id
        self.template_name = template_name
        self.field = field

        options = [
            discord.SelectOption(
                label="Member Avatar",
                value="member",
                emoji="👤"
            ),

            discord.SelectOption(
                label="Server Icon",
                value="server",
                emoji="🏠"
            ),

            discord.SelectOption(
                label="Custom URL",
                value="custom",
                emoji="🔗"
            ),

            discord.SelectOption(
                label="None",
                value="none",
                emoji="❌"
            ),
        ]

        super().__init__(
            placeholder="Choose image type...",
            options=options
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):
        value = self.values[0]

        data = guild_data(
            self.guild_id
        )

        template = data["embeds"].get(
            self.template_name
        )

        if not template:
            await interaction.response.send_message(
                "❌ Template not found.",
                ephemeral=True
            )
            return

        template[
            f"{self.field}_mode"
        ] = value

        if value == "custom":

            await interaction.response.send_modal(
                ImageModal(
                    self.cog,
                    self.guild_id,
                    self.template_name,
                    self.field,
                    "Custom Image URL"
                )
            )

            return

        template[
            f"{self.field}_url"
        ] = ""

        save_data(DATA)

        await interaction.response.edit_message(
            content=(
                f"✅ {self.field.title()} set to "
                f"**{IMAGE_OPTIONS[value]}**."
            ),

            view=EmbedEditorView(
                self.cog,
                self.guild_id,
                self.template_name
            )
        )


# ============================================================
# IMAGE VIEW
# ============================================================

class ImageView(discord.ui.View):

    def __init__(
        self,
        cog,
        guild_id,
        template_name,
        field
    ):
        super().__init__(
            timeout=120
        )

        self.add_item(
            ImageSelect(
                cog,
                guild_id,
                template_name,
                field
            )
        )


# ============================================================
# EMBED EDITOR
# ============================================================

class EmbedEditorView(discord.ui.View):

    def __init__(
        self,
        cog,
        guild_id,
        template_name
    ):
        super().__init__(
            timeout=300
        )

        self.cog = cog
        self.guild_id = guild_id
        self.template_name = template_name

        self.add_item(
            self.title_button()
        )

        self.add_item(
            self.description_button()
        )

        self.add_item(
            self.author_button()
        )

        self.add_item(
            self.footer_button()
        )

        self.add_item(
            self.image_button()
        )

        self.add_item(
            self.thumbnail_button()
        )

        self.add_item(
            self.color_button()
        )

        self.add_item(
            self.preview_button()
        )

        self.add_item(
            self.save_button()
        )

    def template(self):
        return guild_data(
            self.guild_id
        )["embeds"].get(
            self.template_name
        )

    # --------------------------------------------------------
    # TITLE
    # --------------------------------------------------------

    def title_button(self):

        button = discord.ui.Button(
            label="Title",
            emoji="📝",
            style=discord.ButtonStyle.secondary
        )

        async def callback(interaction):

            template = self.template()

            if not template:
                await interaction.response.send_message(
                    "❌ Template not found.",
                    ephemeral=True
                )
                return

            await interaction.response.send_modal(
                TextModal(
                    self.cog,
                    self.guild_id,
                    self.template_name,
                    "title",
                    "Edit Title",
                    "Title",
                    template.get(
                        "title",
                        ""
                    )
                )
            )

        button.callback = callback

        return button

    # --------------------------------------------------------
    # DESCRIPTION
    # --------------------------------------------------------

    def description_button(self):

        button = discord.ui.Button(
            label="Description",
            emoji="📄",
            style=discord.ButtonStyle.secondary
        )

        async def callback(interaction):

            template = self.template()

            if not template:
                await interaction.response.send_message(
                    "❌ Template not found.",
                    ephemeral=True
                )
                return

            await interaction.response.send_modal(
                TextModal(
                    self.cog,
                    self.guild_id,
                    self.template_name,
                    "description",
                    "Edit Description",
                    "Description",
                    template.get(
                        "description",
                        ""
                    )
                )
            )

        button.callback = callback

        return button

    # --------------------------------------------------------
    # AUTHOR
    # --------------------------------------------------------

    def author_button(self):

        button = discord.ui.Button(
            label="Author",
            emoji="👤",
            style=discord.ButtonStyle.secondary
        )

        async def callback(interaction):

            template = self.template()

            if not template:
                await interaction.response.send_message(
                    "❌ Template not found.",
                    ephemeral=True
                )
                return

            await interaction.response.send_modal(
                TextModal(
                    self.cog,
                    self.guild_id,
                    self.template_name,
                    "author",
                    "Edit Author",
                    "Author",
                    template.get(
                        "author",
                        ""
                    )
                )
            )

        button.callback = callback

        return button

    # --------------------------------------------------------
    # FOOTER
    # --------------------------------------------------------

    def footer_button(self):

        button = discord.ui.Button(
            label="Footer",
            emoji="🔻",
            style=discord.ButtonStyle.secondary
        )

        async def callback(interaction):

            template = self.template()

            if not template:
                await interaction.response.send_message(
                    "❌ Template not found.",
                    ephemeral=True
                )
                return

            await interaction.response.send_modal(
                TextModal(
                    self.cog,
                    self.guild_id,
                    self.template_name,
                    "footer",
                    "Edit Footer",
                    "Footer",
                    template.get(
                        "footer",
                        ""
                    )
                )
            )

        button.callback = callback

        return button

    # --------------------------------------------------------
    # IMAGE
    # --------------------------------------------------------

    def image_button(self):

        button = discord.ui.Button(
            label="Image",
            emoji="🖼️",
            style=discord.ButtonStyle.secondary
        )

        async def callback(interaction):

            await interaction.response.send_message(
                "Choose what the main image should use:",

                view=ImageView(
                    self.cog,
                    self.guild_id,
                    self.template_name,
                    "image"
                ),

                ephemeral=True
            )

        button.callback = callback

        return button

    # --------------------------------------------------------
    # THUMBNAIL
    # --------------------------------------------------------

    def thumbnail_button(self):

        button = discord.ui.Button(
            label="Thumbnail",
            emoji="🔲",
            style=discord.ButtonStyle.secondary
        )

        async def callback(interaction):

            await interaction.response.send_message(
                "Choose what the thumbnail should use:",

                view=ImageView(
                    self.cog,
                    self.guild_id,
                    self.template_name,
                    "thumbnail"
                ),

                ephemeral=True
            )

        button.callback = callback

        return button

    # --------------------------------------------------------
    # COLOR
    # --------------------------------------------------------

    def color_button(self):

        button = discord.ui.Button(
            label="Color",
            emoji="🎨",
            style=discord.ButtonStyle.secondary
        )

        async def callback(interaction):

            template = self.template()

            if not template:
                await interaction.response.send_message(
                    "❌ Template not found.",
                    ephemeral=True
                )
                return

            await interaction.response.send_modal(
                ColorModal(
                    self.cog,
                    self.guild_id,
                    self.template_name,
                    template.get(
                        "color",
                        DEFAULT_COLOR
                    )
                )
            )

        button.callback = callback

        return button

    # --------------------------------------------------------
    # PREVIEW
    # --------------------------------------------------------

    def preview_button(self):

        button = discord.ui.Button(
            label="Preview",
            emoji="👁️",
            style=discord.ButtonStyle.primary
        )

        async def callback(interaction):

            template = self.template()

            if not template:
                await interaction.response.send_message(
                    "❌ Template not found.",
                    ephemeral=True
                )
                return

            embed = build_welcome_embed(
                template,
                interaction.user
            )

            data = guild_data(
                self.guild_id
            )

            message = replace_variables(
                data.get(
                    "message",
                    ""
                ),
                interaction.user
            )

            message = message.replace(
                "{embed}",
                ""
            ).strip()

            await interaction.response.send_message(
                content=message or None,
                embed=embed,
                ephemeral=True
            )

        button.callback = callback

        return button

    # --------------------------------------------------------
    # SAVE
    # --------------------------------------------------------

    def save_button(self):

        button = discord.ui.Button(
            label="Save",
            emoji="💾",
            style=discord.ButtonStyle.success
        )

        async def callback(interaction):

            save_data(DATA)

            await interaction.response.send_message(
                f"✅ Welcome embed `{self.template_name}` saved.",
                ephemeral=True
            )

        button.callback = callback

        return button


# ============================================================
# END OF PART 1
# ============================================================


# ============================================================
# PART 2 - WELCOME COMMANDS + SELF ROLE SYSTEM
# ============================================================


# ============================================================
# SELF ROLE HELPERS
# ============================================================

def role_from_id(guild: discord.Guild, role_id):
    try:
        role_id = int(role_id)
    except (ValueError, TypeError):
        return None

    return guild.get_role(role_id)


def emoji_key(emoji):
    """
    Converts normal/custom Discord emoji into a stable string key.
    """
    if isinstance(emoji, discord.PartialEmoji):
        return str(emoji)

    return str(emoji)


def make_selfrole_embed(panel):
    color = panel.get("color", DEFAULT_COLOR)

    try:
        color = int(color)
    except (ValueError, TypeError):
        color = DEFAULT_COLOR

    embed = discord.Embed(
        title=panel.get("title") or None,
        description=panel.get("description") or None,
        color=color
    )

    return embed


# ============================================================
# SELF ROLE BUTTON
# ============================================================

class SelfRoleButton(discord.ui.Button):

    def __init__(
        self,
        cog,
        guild_id,
        panel_name,
        role_id,
        label,
        emoji=None
    ):
        self.cog = cog
        self.guild_id = guild_id
        self.panel_name = panel_name
        self.role_id = int(role_id)

        kwargs = {
            "label": label[:80],
            "style": discord.ButtonStyle.secondary,
            "custom_id": (
                f"selfrole:"
                f"{guild_id}:"
                f"{panel_name}:"
                f"{role_id}"
            )
        }

        if emoji:
            try:
                kwargs["emoji"] = emoji
            except Exception:
                pass

        super().__init__(**kwargs)

    async def callback(
        self,
        interaction: discord.Interaction
    ):
        guild = interaction.guild

        if not guild:
            await interaction.response.send_message(
                "❌ This can only be used inside a server.",
                ephemeral=True
            )
            return

        role = guild.get_role(
            self.role_id
        )

        if not role:
            await interaction.response.send_message(
                "❌ This role no longer exists.",
                ephemeral=True
            )
            return

        member = interaction.user

        # Bot cannot manage roles above/equal to its highest role.
        me = guild.me

        if not me:
            await interaction.response.send_message(
                "❌ I couldn't verify my server permissions.",
                ephemeral=True
            )
            return

        if role >= me.top_role:
            await interaction.response.send_message(
                "❌ I cannot manage this role. "
                "Move my bot role above the self-role.",
                ephemeral=True
            )
            return

        try:
            if role in member.roles:
                await member.remove_roles(
                    role,
                    reason="Self-role button"
                )

                await interaction.response.send_message(
                    f"➖ Removed {role.mention}",
                    ephemeral=True
                )

            else:
                await member.add_roles(
                    role,
                    reason="Self-role button"
                )

                await interaction.response.send_message(
                    f"➕ Added {role.mention}",
                    ephemeral=True
                )

        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ I don't have permission to manage this role.",
                ephemeral=True
            )

        except discord.HTTPException:
            await interaction.response.send_message(
                "❌ Discord rejected the role update.",
                ephemeral=True
            )


# ============================================================
# SELF ROLE VIEW
# ============================================================

class SelfRoleView(discord.ui.View):

    def __init__(
        self,
        cog,
        guild_id,
        panel_name,
        panel
    ):
        # Persistent buttons must never timeout.
        super().__init__(timeout=None)

        self.cog = cog
        self.guild_id = guild_id
        self.panel_name = panel_name

        roles = panel.get("roles", [])

        for item in roles[:25]:

            role_id = item.get("role_id")

            if not role_id:
                continue

            self.add_item(
                SelfRoleButton(
                    cog,
                    guild_id,
                    panel_name,
                    role_id,
                    item.get("label", "Role"),
                    item.get("emoji")
                )
            )


# ============================================================
# SELF ROLE EDIT MODAL
# ============================================================

class SelfRoleTextModal(discord.ui.Modal):

    def __init__(
        self,
        cog,
        guild_id,
        panel_name,
        field,
        title,
        label,
        current
    ):
        super().__init__(title=title)

        self.cog = cog
        self.guild_id = guild_id
        self.panel_name = panel_name
        self.field = field

        self.value_input = discord.ui.TextInput(
            label=label,
            default=(current or "")[:4000],
            required=False,
            style=discord.TextStyle.paragraph,
            max_length=4000
        )

        self.add_item(
            self.value_input
        )

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):
        data = guild_data(
            self.guild_id
        )

        panel = data["selfroles"].get(
            self.panel_name
        )

        if not panel:
            await interaction.response.send_message(
                "❌ Self-role panel not found.",
                ephemeral=True
            )
            return

        panel[self.field] = (
            self.value_input.value
        )

        save_data(DATA)

        await interaction.response.edit_message(
            content=f"✅ `{self.field}` updated.",

            view=SelfRoleEditorView(
                self.cog,
                self.guild_id,
                self.panel_name
            )
        )


# ============================================================
# SELF ROLE COLOR MODAL
# ============================================================

class SelfRoleColorModal(discord.ui.Modal):

    def __init__(
        self,
        cog,
        guild_id,
        panel_name,
        current
    ):
        super().__init__(
            title="Edit Self Role Color"
        )

        self.cog = cog
        self.guild_id = guild_id
        self.panel_name = panel_name

        self.color_input = discord.ui.TextInput(
            label="Hex Color",
            placeholder="#5865F2",
            default=f"#{int(current):06X}",
            required=True,
            max_length=7
        )

        self.add_item(
            self.color_input
        )

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):
        value = (
            self.color_input.value
            .strip()
            .replace("#", "")
        )

        try:
            color = int(
                value,
                16
            )

            if not 0 <= color <= 0xFFFFFF:
                raise ValueError

        except ValueError:
            await interaction.response.send_message(
                "❌ Invalid color. Example: `#5865F2`",
                ephemeral=True
            )
            return

        data = guild_data(
            self.guild_id
        )

        panel = data["selfroles"].get(
            self.panel_name
        )

        if not panel:
            await interaction.response.send_message(
                "❌ Panel not found.",
                ephemeral=True
            )
            return

        panel["color"] = color

        save_data(DATA)

        await interaction.response.edit_message(
            content="✅ Self-role panel color updated.",

            view=SelfRoleEditorView(
                self.cog,
                self.guild_id,
                self.panel_name
            )
        )


# ============================================================
# ADD SELF ROLE MODAL
# ============================================================

class AddSelfRoleModal(discord.ui.Modal):

    def __init__(
        self,
        cog,
        guild_id,
        panel_name
    ):
        super().__init__(
            title="Add Self Role"
        )

        self.cog = cog
        self.guild_id = guild_id
        self.panel_name = panel_name

        self.role_input = discord.ui.TextInput(
            label="Role ID",
            placeholder="Enter Discord role ID",
            required=True,
            max_length=25
        )

        self.label_input = discord.ui.TextInput(
            label="Button Label",
            placeholder="Example: Red",
            required=True,
            max_length=80
        )

        self.emoji_input = discord.ui.TextInput(
            label="Emoji",
            placeholder="Example: 🔴",
            required=False,
            max_length=100
        )

        self.add_item(
            self.role_input
        )

        self.add_item(
            self.label_input
        )

        self.add_item(
            self.emoji_input
        )

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):
        guild = interaction.guild

        if not guild:
            await interaction.response.send_message(
                "❌ Server not found.",
                ephemeral=True
            )
            return

        try:
            role_id = int(
                self.role_input.value.strip()
            )
        except ValueError:
            await interaction.response.send_message(
                "❌ Invalid role ID.",
                ephemeral=True
            )
            return

        role = guild.get_role(
            role_id
        )

        if not role:
            await interaction.response.send_message(
                "❌ I couldn't find that role.",
                ephemeral=True
            )
            return

        me = guild.me

        if me and role >= me.top_role:
            await interaction.response.send_message(
                "❌ I cannot manage that role. "
                "Move my bot role above it.",
                ephemeral=True
            )
            return

        data = guild_data(
            self.guild_id
        )

        panel = data["selfroles"].get(
            self.panel_name
        )

        if not panel:
            await interaction.response.send_message(
                "❌ Panel not found.",
                ephemeral=True
            )
            return

        roles = panel.setdefault(
            "roles",
            []
        )

        if len(roles) >= 25:
            await interaction.response.send_message(
                "❌ A Discord button panel can contain "
                "maximum 25 roles.",
                ephemeral=True
            )
            return

        if any(
            int(x.get("role_id", 0)) == role.id
            for x in roles
        ):
            await interaction.response.send_message(
                "❌ This role is already in the panel.",
                ephemeral=True
            )
            return

        roles.append(
            {
                "role_id": role.id,
                "label": self.label_input.value.strip(),
                "emoji": self.emoji_input.value.strip()
            }
        )

        save_data(DATA)

        await interaction.response.edit_message(
            content=f"✅ Added {role.mention} to the panel.",

            view=SelfRoleEditorView(
                self.cog,
                self.guild_id,
                self.panel_name
            )
        )


# ============================================================
# REMOVE SELF ROLE MODAL
# ============================================================

class RemoveSelfRoleModal(discord.ui.Modal):

    def __init__(
        self,
        cog,
        guild_id,
        panel_name
    ):
        super().__init__(
            title="Remove Self Role"
        )

        self.cog = cog
        self.guild_id = guild_id
        self.panel_name = panel_name

        self.role_input = discord.ui.TextInput(
            label="Role ID",
            placeholder="Enter role ID to remove",
            required=True,
            max_length=25
        )

        self.add_item(
            self.role_input
        )

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):
        try:
            role_id = int(
                self.role_input.value.strip()
            )
        except ValueError:
            await interaction.response.send_message(
                "❌ Invalid role ID.",
                ephemeral=True
            )
            return

        data = guild_data(
            self.guild_id
        )

        panel = data["selfroles"].get(
            self.panel_name
        )

        if not panel:
            await interaction.response.send_message(
                "❌ Panel not found.",
                ephemeral=True
            )
            return

        old_roles = panel.get(
            "roles",
            []
        )

        new_roles = [
            x for x in old_roles
            if int(x.get("role_id", 0)) != role_id
        ]

        if len(old_roles) == len(new_roles):
            await interaction.response.send_message(
                "❌ That role isn't in this panel.",
                ephemeral=True
            )
            return

        panel["roles"] = new_roles

        save_data(DATA)

        await interaction.response.edit_message(
            content="✅ Role removed from the panel.",

            view=SelfRoleEditorView(
                self.cog,
                self.guild_id,
                self.panel_name
            )
        )


# ============================================================
# SELF ROLE EDITOR
# ============================================================

class SelfRoleEditorView(discord.ui.View):

    def __init__(
        self,
        cog,
        guild_id,
        panel_name
    ):
        super().__init__(
            timeout=300
        )

        self.cog = cog
        self.guild_id = guild_id
        self.panel_name = panel_name

        self.add_item(
            self.title_button()
        )

        self.add_item(
            self.description_button()
        )

        self.add_item(
            self.color_button()
        )

        self.add_item(
            self.add_role_button()
        )

        self.add_item(
            self.remove_role_button()
        )

        self.add_item(
            self.preview_button()
        )

        self.add_item(
            self.save_button()
        )

    def panel(self):
        return guild_data(
            self.guild_id
        )["selfroles"].get(
            self.panel_name
        )

    # --------------------------------------------------------
    # TITLE
    # --------------------------------------------------------

    def title_button(self):

        button = discord.ui.Button(
            label="Title",
            emoji="📝",
            style=discord.ButtonStyle.secondary
        )

        async def callback(interaction):

            panel = self.panel()

            if not panel:
                await interaction.response.send_message(
                    "❌ Panel not found.",
                    ephemeral=True
                )
                return

            await interaction.response.send_modal(
                SelfRoleTextModal(
                    self.cog,
                    self.guild_id,
                    self.panel_name,
                    "title",
                    "Edit Panel Title",
                    "Title",
                    panel.get("title", "")
                )
            )

        button.callback = callback

        return button

    # --------------------------------------------------------
    # DESCRIPTION
    # --------------------------------------------------------

    def description_button(self):

        button = discord.ui.Button(
            label="Description",
            emoji="📄",
            style=discord.ButtonStyle.secondary
        )

        async def callback(interaction):

            panel = self.panel()

            if not panel:
                await interaction.response.send_message(
                    "❌ Panel not found.",
                    ephemeral=True
                )
                return

            await interaction.response.send_modal(
                SelfRoleTextModal(
                    self.cog,
                    self.guild_id,
                    self.panel_name,
                    "description",
                    "Edit Panel Description",
                    "Description",
                    panel.get("description", "")
                )
            )

        button.callback = callback

        return button

    # --------------------------------------------------------
    # COLOR
    # --------------------------------------------------------

    def color_button(self):

        button = discord.ui.Button(
            label="Color",
            emoji="🎨",
            style=discord.ButtonStyle.secondary
        )

        async def callback(interaction):

            panel = self.panel()

            if not panel:
                await interaction.response.send_message(
                    "❌ Panel not found.",
                    ephemeral=True
                )
                return

            await interaction.response.send_modal(
                SelfRoleColorModal(
                    self.cog,
                    self.guild_id,
                    self.panel_name,
                    panel.get(
                        "color",
                        DEFAULT_COLOR
                    )
                )
            )

        button.callback = callback

        return button

    # --------------------------------------------------------
    # ADD ROLE
    # --------------------------------------------------------

    def add_role_button(self):

        button = discord.ui.Button(
            label="Add Role",
            emoji="➕",
            style=discord.ButtonStyle.success
        )

        async def callback(interaction):

            panel = self.panel()

            if not panel:
                await interaction.response.send_message(
                    "❌ Panel not found.",
                    ephemeral=True
                )
                return

            if len(panel.get("roles", [])) >= 25:
                await interaction.response.send_message(
                    "❌ Maximum 25 roles per panel.",
                    ephemeral=True
                )
                return

            await interaction.response.send_modal(
                AddSelfRoleModal(
                    self.cog,
                    self.guild_id,
                    self.panel_name
                )
            )

        button.callback = callback

        return button

    # --------------------------------------------------------
    # REMOVE ROLE
    # --------------------------------------------------------

    def remove_role_button(self):

        button = discord.ui.Button(
            label="Remove Role",
            emoji="➖",
            style=discord.ButtonStyle.danger
        )

        async def callback(interaction):

            await interaction.response.send_modal(
                RemoveSelfRoleModal(
                    self.cog,
                    self.guild_id,
                    self.panel_name
                )
            )

        button.callback = callback

        return button

    # --------------------------------------------------------
    # PREVIEW
    # --------------------------------------------------------

    def preview_button(self):

        button = discord.ui.Button(
            label="Preview",
            emoji="👁️",
            style=discord.ButtonStyle.primary
        )

        async def callback(interaction):

            panel = self.panel()

            if not panel:
                await interaction.response.send_message(
                    "❌ Panel not found.",
                    ephemeral=True
                )
                return

            embed = make_selfrole_embed(
                panel
            )

            view = SelfRoleView(
                self.cog,
                self.guild_id,
                self.panel_name,
                panel
            )

            await interaction.response.send_message(
                embed=embed,
                view=view,
                ephemeral=True
            )

        button.callback = callback

        return button

    # --------------------------------------------------------
    # SAVE
    # --------------------------------------------------------

    def save_button(self):

        button = discord.ui.Button(
            label="Save",
            emoji="💾",
            style=discord.ButtonStyle.success
        )

        async def callback(interaction):

            save_data(DATA)

            await interaction.response.send_message(
                f"✅ Self-role panel "
                f"`{self.panel_name}` saved.",
                ephemeral=True
            )

        button.callback = callback

        return button


# ============================================================
# MAIN COG
# ============================================================

class Welcome(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

        # Register persistent self-role views
        # after bot startup.
        self._persistent_views_loaded = False

    async def cog_load(self):

        # Register all existing persistent self-role panels.
        self.register_persistent_selfroles()

    def register_persistent_selfroles(self):

        if self._persistent_views_loaded:
            return

        for gid, data in DATA.items():

            panels = data.get(
                "selfroles",
                {}
            )

            for panel_name, panel in panels.items():

                try:
                    view = SelfRoleView(
                        self,
                        int(gid),
                        panel_name,
                        panel
                    )

                    self.bot.add_view(
                        view
                    )

                except Exception:
                    continue

        self._persistent_views_loaded = True

    # ========================================================
    # WELCOME JOIN EVENT
    # ========================================================

    @commands.Cog.listener()
    async def on_member_join(
        self,
        member: discord.Member
    ):
        data = guild_data(
            member.guild.id
        )

        channel_id = data.get(
            "channel_id"
        )

        active_name = data.get(
            "active_embed"
        )

        if not channel_id or not active_name:
            return

        channel = member.guild.get_channel(
            int(channel_id)
        )

        if not channel:
            return

        template = data.get(
            "embeds",
            {}
        ).get(
            active_name
        )

        if not template:
            return

        embed = build_welcome_embed(
            template,
            member
        )

        message = replace_variables(
            data.get(
                "message",
                ""
            ),
            member
        )

        has_embed = "{embed}" in message

        message = message.replace(
            "{embed}",
            ""
        ).strip()

        try:
            await channel.send(
                content=message or None,
                embed=embed if has_embed else None
            )

        except discord.Forbidden:
            pass

        except discord.HTTPException:
            pass

    # ========================================================
    # WELCOME GROUP
    # ========================================================

    welcome_group = app_commands.Group(
        name="welcome",
        description="Configure the welcome system"
    )

    # ========================================================
    # /welcome embed create
    # ========================================================

    @welcome_group.command(
        name="embed-create",
        description="Create a welcome embed template"
    )
    @app_commands.checks.has_permissions(
        manage_guild=True
    )
    async def welcome_embed_create(
        self,
        interaction: discord.Interaction,
        name: str
    ):
        if not interaction.guild:
            return

        name = name.strip()

        if not re.match(
            r"^[a-zA-Z0-9_-]{1,32}$",
            name
        ):
            await interaction.response.send_message(
                "❌ Name can only contain letters, "
                "numbers, `_` and `-`.",
                ephemeral=True
            )
            return

        data = guild_data(
            interaction.guild.id
        )

        if name in data["embeds"]:
            await interaction.response.send_message(
                f"❌ Welcome embed `{name}` already exists.",
                ephemeral=True
            )
            return

        data["embeds"][name] = default_template()

        save_data(DATA)

        await interaction.response.send_message(
            f"✅ Created welcome embed `{name}`.\n"
            f"Use the editor below to customize it.",

            view=EmbedEditorView(
                self,
                interaction.guild.id,
                name
            )
        )

    # ========================================================
    # /welcome embed edit
    # ========================================================

    @welcome_group.command(
        name="embed-edit",
        description="Edit a welcome embed template"
    )
    @app_commands.checks.has_permissions(
        manage_guild=True
    )
    async def welcome_embed_edit(
        self,
        interaction: discord.Interaction,
        name: str
    ):
        if not interaction.guild:
            return

        data = guild_data(
            interaction.guild.id
        )

        if name not in data["embeds"]:
            await interaction.response.send_message(
                f"❌ Welcome embed `{name}` doesn't exist.",
            )
            return

        await interaction.response.send_message(
            f"🛠️ Editing welcome embed `{name}`.",

            view=EmbedEditorView(
                self,
                interaction.guild.id,
                name
            )
        )

    # ========================================================
    # /welcome embed delete
    # ========================================================

    @welcome_group.command(
        name="embed-delete",
        description="Delete a welcome embed template"
    )
    @app_commands.checks.has_permissions(
        manage_guild=True
    )
    async def welcome_embed_delete(
        self,
        interaction: discord.Interaction,
        name: str
    ):
        if not interaction.guild:
            return

        data = guild_data(
            interaction.guild.id
        )

        if name not in data["embeds"]:
            await interaction.response.send_message(
                f"❌ Welcome embed `{name}` doesn't exist.",
            )
            return

        del data["embeds"][name]

        if data.get("active_embed") == name:
            data["active_embed"] = None

        save_data(DATA)

        await interaction.response.send_message(
            f"🗑️ Welcome embed `{name}` deleted."
        )

    # ========================================================
    # /welcome embed list
    # ========================================================

    @welcome_group.command(
        name="embed-list",
        description="List welcome embed templates"
    )
    async def welcome_embed_list(
        self,
        interaction: discord.Interaction
    ):
        if not interaction.guild:
            return

        data = guild_data(
            interaction.guild.id
        )

        embeds = data.get(
            "embeds",
            {}
        )

        if not embeds:
            await interaction.response.send_message(
                "📭 No welcome embed templates created.",
            )
            return

        lines = []

        for name in embeds:
            active = (
                " 🟢 ACTIVE"
                if data.get("active_embed") == name
                else ""
            )

            lines.append(
                f"• `{name}`{active}"
            )

        embed = discord.Embed(
            title="Welcome Embed Templates",
            description="\n".join(lines),
            color=DEFAULT_COLOR
        )

        await interaction.response.send_message(
            embed=embed
        )

    # ========================================================
    # /welcome enable
    # ========================================================

    @welcome_group.command(
        name="enable",
        description="Enable a welcome template in a channel"
    )
    @app_commands.checks.has_permissions(
        manage_guild=True
    )
    async def welcome_enable(
        self,
        interaction: discord.Interaction,
        name: str,
        channel: discord.TextChannel
    ):
        if not interaction.guild:
            return

        data = guild_data(
            interaction.guild.id
        )

        if name not in data["embeds"]:
            await interaction.response.send_message(
                f"❌ Welcome embed `{name}` doesn't exist.",
            )
            return

        data["active_embed"] = name
        data["channel_id"] = channel.id

        save_data(DATA)

        await interaction.response.send_message(
            f"✅ Welcome template `{name}` is now active "
            f"in {channel.mention}.",
        )

    # ========================================================
    # /welcome disable
    # ========================================================

    @welcome_group.command(
        name="disable",
        description="Disable the welcome system"
    )
    @app_commands.checks.has_permissions(
        manage_guild=True
    )
    async def welcome_disable(
        self,
        interaction: discord.Interaction
    ):
        if not interaction.guild:
            return

        data = guild_data(
            interaction.guild.id
        )

        data["active_embed"] = None

        save_data(DATA)

        await interaction.response.send_message(
            "🔴 Welcome system disabled"
            
        )

    # ========================================================
    # /welcome channel set
    # ========================================================

    @welcome_group.command(
        name="channel-set",
        description="Set the welcome channel"
    )
    @app_commands.checks.has_permissions(
        manage_guild=True
    )
    async def welcome_channel_set(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel
    ):
        if not interaction.guild:
            return

        data = guild_data(
            interaction.guild.id
        )

        data["channel_id"] = channel.id

        save_data(DATA)

        await interaction.response.send_message(
            f"✅ Welcome channel set to {channel.mention}."
        )

    # ========================================================
    # /welcome channel view
    # ========================================================

    @welcome_group.command(
        name="channel-view",
        description="View the configured welcome channel"
    )
    async def welcome_channel_view(
        self,
        interaction: discord.Interaction
    ):
        if not interaction.guild:
            return

        data = guild_data(
            interaction.guild.id
        )

        channel_id = data.get(
            "channel_id"
        )

        if not channel_id:
            await interaction.response.send_message(
                "📭 No welcome channel is configured.",
            )
            return

        channel = interaction.guild.get_channel(
            int(channel_id)
        )

        if channel:
            await interaction.response.send_message(
                f"📍 Welcome channel: {channel.mention}",
            )
        else:
            await interaction.response.send_message(
                "⚠️ The configured welcome channel "
                "no longer exists."
            )

    # ========================================================
    # /welcome message set
    # ========================================================

    @welcome_group.command(
        name="message-set",
        description="Set the welcome message"
    )
    @app_commands.checks.has_permissions(
        manage_guild=True
    )
    async def welcome_message_set(
        self,
        interaction: discord.Interaction,
        message: str
    ):
        if not interaction.guild:
            return

        data = guild_data(
            interaction.guild.id
        )

        data["message"] = message

        save_data(DATA)

        await interaction.response.send_message(
            "✅ Welcome message saved.\n\n"
            "Use `{embed}` in the message if you "
            "want the active embed to be sent too."
        )

    # ========================================================
    # /welcome message clear
    # ========================================================

    @welcome_group.command(
        name="message-clear",
        description="Clear the welcome message"
    )
    @app_commands.checks.has_permissions(
        manage_guild=True
    )
    async def welcome_message_clear(
        self,
        interaction: discord.Interaction
    ):
        if not interaction.guild:
            return

        data = guild_data(
            interaction.guild.id
        )

        data["message"] = ""

        save_data(DATA)

        await interaction.response.send_message(
            "🗑️ Welcome message cleared."
        )

    # ========================================================
    # /welcome test
    # ========================================================

    @welcome_group.command(
        name="test",
        description="Test a welcome template"
    )
    @app_commands.checks.has_permissions(
        manage_guild=True
    )
    async def welcome_test(
        self,
        interaction: discord.Interaction,
        name: str | None = None,
        channel: discord.TextChannel | None = None
    ):
        if not interaction.guild:
            return

        data = guild_data(
            interaction.guild.id
        )

        name = (
            name
            or data.get("active_embed")
        )

        if not name:
            await interaction.response.send_message(
                "❌ No template specified or active."
            )
            return

        template = data["embeds"].get(
            name
        )

        if not template:
            await interaction.response.send_message(
                f"❌ Welcome embed `{name}` doesn't exist."
            )
            return

        embed = build_welcome_embed(
            template,
            interaction.user
        )

        message = replace_variables(
            data.get(
                "message",
                ""
            ),
            interaction.user
        )

        has_embed = "{embed}" in message

        message = message.replace(
            "{embed}",
            ""
        ).strip()

        target = channel

        if not target:
            channel_id = data.get(
                "channel_id"
            )

            if channel_id:
                target = interaction.guild.get_channel(
                    int(channel_id)
                )

        if target:

            try:
                await target.send(
                    content=message or None,
                    embed=embed if has_embed else None
                )

                await interaction.response.send_message(
                    f"✅ Welcome test sent to {target.mention}."
                )

                return

            except discord.Forbidden:
                pass

            except discord.HTTPException:
                pass

        await interaction.response.send_message(
            content=message or None,
            embed=embed,
        )

    # ========================================================
    # SELFROLE GROUP
    # ========================================================

    selfrole_group = app_commands.Group(
        name="selfrole",
        description="Configure self-role panels"
    )

    # ========================================================
    # /selfrole create
    # ========================================================

    @selfrole_group.command(
        name="create",
        description="Create a self-role panel"
    )
    @app_commands.checks.has_permissions(
        manage_guild=True
    )
    async def selfrole_create(
        self,
        interaction: discord.Interaction,
        name: str
    ):
        if not interaction.guild:
            return

        name = name.strip()

        if not re.match(
            r"^[a-zA-Z0-9_-]{1,32}$",
            name
        ):
            await interaction.response.send_message(
                "❌ Invalid panel name.",
                ephemeral=True
            )
            return

        data = guild_data(
            interaction.guild.id
        )

        if name in data["selfroles"]:
            await interaction.response.send_message(
                f"❌ Self-role panel `{name}` already exists.",
                ephemeral=True
            )
            return

        data["selfroles"][name] = {
            "title": "Choose Your Roles",
            "description": (
                "Select the roles you want."
            ),
            "color": DEFAULT_COLOR,
            "roles": []
        }

        save_data(DATA)

        await interaction.response.send_message(
            f"✅ Created self-role panel `{name}`.",

            view=SelfRoleEditorView(
                self,
                interaction.guild.id,
                name
            ),

            ephemeral=True
        )

    # ========================================================
    # /selfrole edit
    # ========================================================

    @selfrole_group.command(
        name="edit",
        description="Edit a self-role panel"
    )
    @app_commands.checks.has_permissions(
        manage_guild=True
    )
    async def selfrole_edit(
        self,
        interaction: discord.Interaction,
        name: str
    ):
        if not interaction.guild:
            return

        data = guild_data(
            interaction.guild.id
        )

        if name not in data["selfroles"]:
            await interaction.response.send_message(
                f"❌ Self-role panel `{name}` doesn't exist.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"🛠️ Editing self-role panel `{name}`.",

            view=SelfRoleEditorView(
                self,
                interaction.guild.id,
                name
            ),

            ephemeral=True
        )

    # ========================================================
    # /selfrole delete
    # ========================================================

    @selfrole_group.command(
        name="delete",
        description="Delete a self-role panel"
    )
    @app_commands.checks.has_permissions(
        manage_guild=True
    )
    async def selfrole_delete(
        self,
        interaction: discord.Interaction,
        name: str
    ):
        if not interaction.guild:
            return

        data = guild_data(
            interaction.guild.id
        )

        if name not in data["selfroles"]:
            await interaction.response.send_message(
                f"❌ Panel `{name}` doesn't exist.",
                ephemeral=True
            )
            return

        del data["selfroles"][name]

        save_data(DATA)

        await interaction.response.send_message(
            f"🗑️ Self-role panel `{name}` deleted.",
            ephemeral=True
        )

    # ========================================================
    # /selfrole list
    # ========================================================

    @selfrole_group.command(
        name="list",
        description="List self-role panels"
    )
    async def selfrole_list(
        self,
        interaction: discord.Interaction
    ):
        if not interaction.guild:
            return

        data = guild_data(
            interaction.guild.id
        )

        panels = data.get(
            "selfroles",
            {}
        )

        if not panels:
            await interaction.response.send_message(
                "📭 No self-role panels created.",
                ephemeral=True
            )
            return

        lines = []

        for name, panel in panels.items():
            count = len(
                panel.get("roles", [])
            )

            lines.append(
                f"• `{name}` — {count} role(s)"
            )

        embed = discord.Embed(
            title="Self Role Panels",
            description="\n".join(lines),
            color=DEFAULT_COLOR
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )

    # ========================================================
    # /selfrole send
    # ========================================================

    @selfrole_group.command(
        name="send",
        description="Send a self-role panel"
    )
    @app_commands.checks.has_permissions(
        manage_guild=True
    )
    async def selfrole_send(
        self,
        interaction: discord.Interaction,
        name: str,
        channel: discord.TextChannel
    ):
        if not interaction.guild:
            return

        data = guild_data(
            interaction.guild.id
        )

        panel = data["selfroles"].get(
            name
        )

        if not panel:
            await interaction.response.send_message(
                f"❌ Panel `{name}` doesn't exist.",
                ephemeral=True
            )
            return

        if not panel.get("roles"):
            await interaction.response.send_message(
                "❌ This panel has no roles yet.",
                ephemeral=True
            )
            return

        embed = make_selfrole_embed(
            panel
        )

        view = SelfRoleView(
            self,
            interaction.guild.id,
            name,
            panel
        )

        try:
            message = await channel.send(
                embed=embed,
                view=view
            )

            await interaction.response.send_message(
                f"✅ Self-role panel sent to "
                f"{channel.mention}.\n"
                f"Message ID: `{message.id}`",
                ephemeral=True
            )

        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ I cannot send messages in that channel.",
                ephemeral=True
            )

        except discord.HTTPException:
            await interaction.response.send_message(
                "❌ Discord rejected the message.",
                ephemeral=True
            )

    # ========================================================
    # /selfrole test
    # ========================================================

    @selfrole_group.command(
        name="test",
        description="Preview a self-role panel"
    )
    @app_commands.checks.has_permissions(
        manage_guild=True
    )
    async def selfrole_test(
        self,
        interaction: discord.Interaction,
        name: str
    ):
        if not interaction.guild:
            return

        data = guild_data(
            interaction.guild.id
        )

        panel = data["selfroles"].get(
            name
        )

        if not panel:
            await interaction.response.send_message(
                f"❌ Panel `{name}` doesn't exist.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            embed=make_selfrole_embed(
                panel
            ),
            view=SelfRoleView(
                self,
                interaction.guild.id,
                name,
                panel
            ),
            ephemeral=True
        )

    # ========================================================
    # /selfrole reaction add
    # ========================================================

    @selfrole_group.command(
        name="reaction-add",
        description="Add a reaction role to a message"
    )
    @app_commands.checks.has_permissions(
        manage_guild=True
    )
    async def selfrole_reaction_add(
        self,
        interaction: discord.Interaction,
        message_id: str,
        emoji: str,
        role: discord.Role
    ):
        if not interaction.guild:
            return

        try:
            message_id_int = int(
                message_id
            )
        except ValueError:
            await interaction.response.send_message(
                "❌ Invalid message ID.",
                ephemeral=True
            )
            return

        me = interaction.guild.me

        if me and role >= me.top_role:
            await interaction.response.send_message(
                "❌ I cannot manage that role. "
                "Move my bot role above it.",
                ephemeral=True
            )
            return

        channel = interaction.channel

        if not isinstance(
            channel,
            discord.TextChannel
        ):
            await interaction.response.send_message(
                "❌ Run this command inside the channel "
                "where the target message exists.",
                ephemeral=True
            )
            return

        try:
            message = await channel.fetch_message(
                message_id_int
            )

        except discord.NotFound:
            await interaction.response.send_message(
                "❌ Message not found.",
                ephemeral=True
            )
            return

        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ I cannot read that message.",
                ephemeral=True
            )
            return

        except discord.HTTPException:
            await interaction.response.send_message(
                "❌ Failed to fetch the message.",
                ephemeral=True
            )
            return

        emoji = emoji.strip()

        if not emoji:
            await interaction.response.send_message(
                "❌ Emoji cannot be empty.",
                ephemeral=True
            )
            return

        try:
            await message.add_reaction(
                emoji
            )

        except discord.HTTPException:
            await interaction.response.send_message(
                "❌ I couldn't add that emoji. "
                "Make sure it is a valid emoji.",
                ephemeral=True
            )
            return

        data = guild_data(
            interaction.guild.id
        )

        mappings = data.setdefault(
            "reaction_roles",
            {}
        )

        message_key = str(
            message_id_int
        )

        mappings.setdefault(
            message_key,
            {}
        )

        mappings[message_key][
            emoji_key(emoji)
        ] = role.id

        save_data(DATA)

        await interaction.response.send_message(
            f"✅ Reaction role added.\n"
            f"{emoji} → {role.mention}\n"
            f"Message: `{message_id_int}`",
            ephemeral=True
        )

    # ========================================================
    # REACTION ROLE ADD - PREFIX
    # ========================================================

    @commands.command(
        name="selfrole_reaction_add"
    )
    @commands.has_guild_permissions(
        manage_guild=True
    )
    async def prefix_selfrole_reaction_add(
        self,
        ctx,
        message_id: str,
        emoji: str,
        role: discord.Role
    ):
        if not ctx.guild:
            return

        try:
            message_id_int = int(
                message_id
            )
        except ValueError:
            await ctx.send(
                "❌ Invalid message ID."
            )
            return

        if ctx.channel is None:
            return

        try:
            message = await ctx.channel.fetch_message(
                message_id_int
            )
        except discord.NotFound:
            await ctx.send(
                "❌ Message not found."
            )
            return
        except discord.Forbidden:
            await ctx.send(
                "❌ I cannot read that message."
            )
            return
        except discord.HTTPException:
            await ctx.send(
                "❌ Failed to fetch the message."
            )
            return

        me = ctx.guild.me

        if me and role >= me.top_role:
            await ctx.send(
                "❌ I cannot manage that role. "
                "Move my bot role above it."
            )
            return

        try:
            await message.add_reaction(
                emoji
            )
        except discord.HTTPException:
            await ctx.send(
                "❌ Invalid emoji or I cannot add it."
            )
            return

        data = guild_data(
            ctx.guild.id
        )

        mappings = data.setdefault(
            "reaction_roles",
            {}
        )

        message_key = str(
            message_id_int
        )

        mappings.setdefault(
            message_key,
            {}
        )

        mappings[message_key][
            emoji_key(emoji)
        ] = role.id

        save_data(DATA)

        await ctx.send(
            f"✅ Reaction role added.\n"
            f"{emoji} → {role.mention}"
        )

    # ========================================================
    # RAW REACTION ADD
    # ========================================================

    @commands.Cog.listener()
    async def on_raw_reaction_add(
        self,
        payload: discord.RawReactionActionEvent
    ):
        if payload.guild_id is None:
            return

        # Ignore bot reactions.
        if self.bot.user and payload.user_id == self.bot.user.id:
            return

        data = guild_data(
            payload.guild_id
        )

        mappings = data.get(
            "reaction_roles",
            {}
        )

        message_mapping = mappings.get(
            str(payload.message_id)
        )

        if not message_mapping:
            return

        key = emoji_key(
            payload.emoji
        )

        role_id = message_mapping.get(
            key
        )

        if not role_id:
            return

        guild = self.bot.get_guild(
            payload.guild_id
        )

        if not guild:
            return

        role = guild.get_role(
            int(role_id)
        )

        if not role:
            return

        member = guild.get_member(
            payload.user_id
        )

        if not member:
            try:
                member = await guild.fetch_member(
                    payload.user_id
                )
            except (
                discord.NotFound,
                discord.HTTPException
            ):
                return

        me = guild.me

        if not me or role >= me.top_role:
            return

        try:
            await member.add_roles(
                role,
                reason="Reaction self-role"
            )
        except (
            discord.Forbidden,
            discord.HTTPException
        ):
            return

    # ========================================================
    # RAW REACTION REMOVE
    # ========================================================

    @commands.Cog.listener()
    async def on_raw_reaction_remove(
        self,
        payload: discord.RawReactionActionEvent
    ):
        if payload.guild_id is None:
            return

        if self.bot.user and payload.user_id == self.bot.user.id:
            return

        data = guild_data(
            payload.guild_id
        )

        mappings = data.get(
            "reaction_roles",
            {}
        )

        message_mapping = mappings.get(
            str(payload.message_id)
        )

        if not message_mapping:
            return

        key = emoji_key(
            payload.emoji
        )

        role_id = message_mapping.get(
            key
        )

        if not role_id:
            return

        guild = self.bot.get_guild(
            payload.guild_id
        )

        if not guild:
            return

        role = guild.get_role(
            int(role_id)
        )

        if not role:
            return

        member = guild.get_member(
            payload.user_id
        )

        if not member:
            try:
                member = await guild.fetch_member(
                    payload.user_id
                )
            except (
                discord.NotFound,
                discord.HTTPException
            ):
                return

        me = guild.me

        if not me or role >= me.top_role:
            return

        try:
            await member.remove_roles(
                role,
                reason="Reaction self-role removed"
            )
        except (
            discord.Forbidden,
            discord.HTTPException
        ):
            return


# ============================================================
# PREFIX WELCOME COMMANDS
# ============================================================

    @commands.group(
        name="welcome",
        invoke_without_command=True
    )
    @commands.has_guild_permissions(
        manage_guild=True
    )
    async def prefix_welcome(
        self,
        ctx
    ):
        if ctx.invoked_subcommand is None:

            embed = discord.Embed(
                title="Air Commander Welcome",
                description=(
                    "**Welcome Commands**\n\n"
                    "`,welcome embed create <name>`\n"
                    "`,welcome embed edit <name>`\n"
                    "`,welcome embed delete <name>`\n"
                    "`,welcome embed list`\n"
                    "`,welcome enable <name> #channel`\n"
                    "`,welcome disable`\n"
                    "`,welcome channel set #channel`\n"
                    "`,welcome channel view`\n"
                    "`,welcome message set <message>`\n"
                    "`,welcome message clear`\n"
                    "`,welcome test [name] [#channel]`"
                ),
                color=DEFAULT_COLOR
            )

            await ctx.send(
                embed=embed
            )

    @prefix_welcome.group(
        name="embed",
        invoke_without_command=True
    )
    async def prefix_welcome_embed(
        self,
        ctx
    ):
        if ctx.invoked_subcommand is None:
            await ctx.send(
                "Use `,welcome embed create <name>` "
                "or `,welcome embed list`."
            )

    @prefix_welcome_embed.command(
        name="create"
    )
    async def prefix_welcome_embed_create(
        self,
        ctx,
        name: str
    ):
        data = guild_data(
            ctx.guild.id
        )

        if name in data["embeds"]:
            await ctx.send(
                f"❌ Welcome embed `{name}` already exists."
            )
            return

        data["embeds"][name] = default_template()

        save_data(DATA)

        await ctx.send(
            f"✅ Created `{name}`. "
            f"Use the buttons below to edit it.",

            view=EmbedEditorView(
                self,
                ctx.guild.id,
                name
            )
        )

    @prefix_welcome_embed.command(
        name="edit"
    )
    async def prefix_welcome_embed_edit(
        self,
        ctx,
        name: str
    ):
        data = guild_data(
            ctx.guild.id
        )

        if name not in data["embeds"]:
            await ctx.send(
                f"❌ Welcome embed `{name}` doesn't exist."
            )
            return

        await ctx.send(
            f"🛠️ Editing `{name}`.",

            view=EmbedEditorView(
                self,
                ctx.guild.id,
                name
            )
        )

    @prefix_welcome_embed.command(
        name="delete"
    )
    async def prefix_welcome_embed_delete(
        self,
        ctx,
        name: str
    ):
        data = guild_data(
            ctx.guild.id
        )

        if name not in data["embeds"]:
            await ctx.send(
                f"❌ Welcome embed `{name}` doesn't exist."
            )
            return

        del data["embeds"][name]

        if data.get("active_embed") == name:
            data["active_embed"] = None

        save_data(DATA)

        await ctx.send(
            f"🗑️ Welcome embed `{name}` deleted."
        )

    @prefix_welcome_embed.command(
        name="list"
    )
    async def prefix_welcome_embed_list(
        self,
        ctx
    ):
        data = guild_data(
            ctx.guild.id
        )

        embeds = data.get(
            "embeds",
            {}
        )

        if not embeds:
            await ctx.send(
                "📭 No welcome embeds created."
            )
            return

        lines = []

        for name in embeds:
            active = (
                " 🟢 ACTIVE"
                if data.get("active_embed") == name
                else ""
            )

            lines.append(
                f"• `{name}`{active}"
            )

        embed = discord.Embed(
            title="Welcome Embeds",
            description="\n".join(lines),
            color=DEFAULT_COLOR
        )

        await ctx.send(
            embed=embed
        )

    @prefix_welcome.command(
        name="enable"
    )
    async def prefix_welcome_enable(
        self,
        ctx,
        name: str,
        channel: discord.TextChannel
    ):
        data = guild_data(
            ctx.guild.id
        )

        if name not in data["embeds"]:
            await ctx.send(
                f"❌ Welcome embed `{name}` doesn't exist."
            )
            return

        data["active_embed"] = name
        data["channel_id"] = channel.id

        save_data(DATA)

        await ctx.send(
            f"✅ Welcome `{name}` enabled in "
            f"{channel.mention}."
        )

    @prefix_welcome.command(
        name="disable"
    )
    async def prefix_welcome_disable(
        self,
        ctx
    ):
        data = guild_data(
            ctx.guild.id
        )

        data["active_embed"] = None

        save_data(DATA)

        await ctx.send(
            "🔴 Welcome system disabled."
        )

    @prefix_welcome.group(
        name="channel",
        invoke_without_command=True
    )
    async def prefix_welcome_channel(
        self,
        ctx
    ):
        if ctx.invoked_subcommand is None:
            await ctx.send(
                "Use `,welcome channel set #channel` "
                "or `,welcome channel view`."
            )

    @prefix_welcome_channel.command(
        name="set"
    )
    async def prefix_welcome_channel_set(
        self,
        ctx,
        channel: discord.TextChannel
    ):
        data = guild_data(
            ctx.guild.id
        )

        data["channel_id"] = channel.id

        save_data(DATA)

        await ctx.send(
            f"✅ Welcome channel set to "
            f"{channel.mention}."
        )

    @prefix_welcome_channel.command(
        name="view"
    )
    async def prefix_welcome_channel_view(
        self,
        ctx
    ):
        data = guild_data(
            ctx.guild.id
        )

        channel_id = data.get(
            "channel_id"
        )

        if not channel_id:
            await ctx.send(
                "📭 No welcome channel configured."
            )
            return

        channel = ctx.guild.get_channel(
            int(channel_id)
        )

        if channel:
            await ctx.send(
                f"📍 Welcome channel: "
                f"{channel.mention}"
            )
        else:
            await ctx.send(
                "⚠️ Configured channel no longer exists."
            )

    @prefix_welcome.group(
        name="message",
        invoke_without_command=True
    )
    async def prefix_welcome_message(
        self,
        ctx
    ):
        if ctx.invoked_subcommand is None:
            await ctx.send(
                "Use `,welcome message set <message>`."
            )

    @prefix_welcome_message.command(
        name="set"
    )
    async def prefix_welcome_message_set(
        self,
        ctx,
        *,
        message: str
    ):
        data = guild_data(
            ctx.guild.id
        )

        data["message"] = message

        save_data(DATA)

        await ctx.send(
            "✅ Welcome message saved."
        )

    @prefix_welcome_message.command(
        name="clear"
    )
    async def prefix_welcome_message_clear(
        self,
        ctx
    ):
        data = guild_data(
            ctx.guild.id
        )

        data["message"] = ""

        save_data(DATA)

        await ctx.send(
            "🗑️ Welcome message cleared."
        )

    @prefix_welcome.command(
        name="test"
    )
    async def prefix_welcome_test(
        self,
        ctx,
        name: str = None,
        channel: discord.TextChannel = None
    ):
        data = guild_data(
            ctx.guild.id
        )

        name = (
            name
            or data.get("active_embed")
        )

        if not name:
            await ctx.send(
                "❌ No active welcome template."
            )
            return

        template = data["embeds"].get(
            name
        )

        if not template:
            await ctx.send(
                f"❌ Welcome embed `{name}` doesn't exist."
            )
            return

        embed = build_welcome_embed(
            template,
            ctx.author
        )

        message = replace_variables(
            data.get("message", ""),
            ctx.author
        )

        has_embed = "{embed}" in message

        message = message.replace(
            "{embed}",
            ""
        ).strip()

        target = channel

        if not target:
            channel_id = data.get(
                "channel_id"
            )

            if channel_id:
                target = ctx.guild.get_channel(
                    int(channel_id)
                )

        if target:
            try:
                await target.send(
                    content=message or None,
                    embed=embed if has_embed else None
                )

                await ctx.send(
                    f"✅ Test sent to {target.mention}."
                )

                return

            except (
                discord.Forbidden,
                discord.HTTPException
            ):
                pass

        await ctx.send(
            content=message or None,
            embed=embed
        )


# ============================================================
# PREFIX SELFROLE COMMANDS
# ============================================================

    @commands.group(
        name="selfrole",
        invoke_without_command=True
    )
    @commands.has_guild_permissions(
        manage_guild=True
    )
    async def prefix_selfrole(
        self,
        ctx
    ):
        if ctx.invoked_subcommand is None:

            embed = discord.Embed(
                title="Air Commander Self Role",
                description=(
                    "`,selfrole create <name>`\n"
                    "`,selfrole edit <name>`\n"
                    "`,selfrole delete <name>`\n"
                    "`,selfrole list`\n"
                    "`,selfrole send <name> #channel`\n"
                    "`,selfrole test <name>`\n\n"
                    "**Reaction Role**\n"
                    "`,selfrole_reaction_add "
                    "<message_id> <emoji> @role`"
                ),
                color=DEFAULT_COLOR
            )

            await ctx.send(
                embed=embed
            )

    @prefix_selfrole.command(
        name="create"
    )
    async def prefix_selfrole_create(
        self,
        ctx,
        name: str
    ):
        data = guild_data(
            ctx.guild.id
        )

        if name in data["selfroles"]:
            await ctx.send(
                f"❌ Panel `{name}` already exists."
            )
            return

        data["selfroles"][name] = {
            "title": "Choose Your Roles",
            "description": (
                "Select the roles you want."
            ),
            "color": DEFAULT_COLOR,
            "roles": []
        }

        save_data(DATA)

        await ctx.send(
            f"✅ Created self-role panel `{name}`.",

            view=SelfRoleEditorView(
                self,
                ctx.guild.id,
                name
            )
        )

    @prefix_selfrole.command(
        name="edit"
    )
    async def prefix_selfrole_edit(
        self,
        ctx,
        name: str
    ):
        data = guild_data(
            ctx.guild.id
        )

        if name not in data["selfroles"]:
            await ctx.send(
                f"❌ Panel `{name}` doesn't exist."
            )
            return

        await ctx.send(
            f"🛠️ Editing `{name}`.",

            view=SelfRoleEditorView(
                self,
                ctx.guild.id,
                name
            )
        )

    @prefix_selfrole.command(
        name="delete"
    )
    async def prefix_selfrole_delete(
        self,
        ctx,
        name: str
    ):
        data = guild_data(
            ctx.guild.id
        )

        if name not in data["selfroles"]:
            await ctx.send(
                f"❌ Panel `{name}` doesn't exist."
            )
            return

        del data["selfroles"][name]

        save_data(DATA)

        await ctx.send(
            f"🗑️ Panel `{name}` deleted."
        )

    @prefix_selfrole.command(
        name="list"
    )
    async def prefix_selfrole_list(
        self,
        ctx
    ):
        data = guild_data(
            ctx.guild.id
        )

        panels = data.get(
            "selfroles",
            {}
        )

        if not panels:
            await ctx.send(
                "📭 No self-role panels created."
            )
            return

        lines = []

        for name, panel in panels.items():
            lines.append(
                f"• `{name}` — "
                f"{len(panel.get('roles', []))} role(s)"
            )

        embed = discord.Embed(
            title="Self Role Panels",
            description="\n".join(lines),
            color=DEFAULT_COLOR
        )

        await ctx.send(
            embed=embed
        )

    @prefix_selfrole.command(
        name="send"
    )
    async def prefix_selfrole_send(
        self,
        ctx,
        name: str,
        channel: discord.TextChannel
    ):
        data = guild_data(
            ctx.guild.id
        )

        panel = data["selfroles"].get(
            name
        )

        if not panel:
            await ctx.send(
                f"❌ Panel `{name}` doesn't exist."
            )
            return

        if not panel.get("roles"):
            await ctx.send(
                "❌ This panel has no roles."
            )
            return

        embed = make_selfrole_embed(
            panel
        )

        view = SelfRoleView(
            self,
            ctx.guild.id,
            name,
            panel
        )

        try:
            message = await channel.send(
                embed=embed,
                view=view
            )

            await ctx.send(
                f"✅ Panel sent to {channel.mention}.\n"
                f"Message ID: `{message.id}`"
            )

        except discord.Forbidden:
            await ctx.send(
                "❌ I cannot send messages there."
            )

        except discord.HTTPException:
            await ctx.send(
                "❌ Failed to send panel."
            )

    @prefix_selfrole.command(
        name="test"
    )
    async def prefix_selfrole_test(
        self,
        ctx,
        name: str
    ):
        data = guild_data(
            ctx.guild.id
        )

        panel = data["selfroles"].get(
            name
        )

        if not panel:
            await ctx.send(
                f"❌ Panel `{name}` doesn't exist."
            )
            return

        await ctx.send(
            embed=make_selfrole_embed(
                panel
            ),
            view=SelfRoleView(
                self,
                ctx.guild.id,
                name,
                panel
            )
        )


# ============================================================
# APP COMMAND ERROR HANDLER
# ============================================================

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error
    ):
        if isinstance(
            error,
            app_commands.errors.MissingPermissions
        ):
            message = (
                "❌ You need **Manage Server** "
                "permission to use this command."
            )

        else:
            message = (
                "❌ Something went wrong while "
                "running this command."
            )

        try:
            if interaction.response.is_done():
                await interaction.followup.send(
                    message,
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    message,
                    ephemeral=True
                )
        except discord.HTTPException:
            pass


# ============================================================
# COG SETUP
# ============================================================

async def setup(bot):
    await bot.add_cog(
        Welcome(bot)
    )
