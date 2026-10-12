import re
import discord
from discord import app_commands
from discord.ext import commands

HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")


def _embed(title, description, color=None):
    embed = discord.Embed(
        title=f"✈️ {title}",
        description=description,
        color=color or discord.Color.blurple(),
        timestamp=discord.utils.utcnow(),
    )
    embed.set_footer(text="Air Commander • Setup Center")
    return embed


def _parse_role_layout(layout: str):
    roles, seen = [], set()
    for raw in layout.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if " - " not in line:
            raise ValueError(f"Invalid line: `{line}`. Use `Role Name - #RRGGBB`.")
        name, hexcode = (part.strip() for part in line.rsplit(" - ", 1))
        match = HEX_RE.fullmatch(hexcode)
        if not name:
            raise ValueError("A role name cannot be empty.")
        if not match:
            raise ValueError(f"Invalid hex code for **{name}**. Use `#5865F2` format.")
        key = name.casefold()
        if key not in seen:
            seen.add(key)
            roles.append((name[:100], int(match.group(1), 16)))
    if not roles:
        raise ValueError("No roles found. Add lines like `Admin - #5865F2`.")
    return roles


async def _apply_roles(guild: discord.Guild, layout: str):
    specs = _parse_role_layout(layout)
    me = guild.me
    if me is None:
        raise RuntimeError("Could not determine the bot's server member.")
    if not me.guild_permissions.manage_roles:
        raise PermissionError("Air Commander needs **Manage Roles** permission.")
    bot_top = me.top_role
    created, existing, skipped = 0, 0, []
    for name, colour_value in specs:
        role = discord.utils.find(lambda r: r.name.casefold() == name.casefold(), guild.roles)
        if role:
            existing += 1
            if role >= bot_top and role != guild.default_role:
                skipped.append(f"{role.name} (at/above my role)")
            continue
        if bot_top <= guild.default_role:
            raise PermissionError("Move the bot role above @everyone and grant **Manage Roles**.")
        await guild.create_role(
            name=name,
            colour=discord.Colour(colour_value),
            reason="Air Commander auto role setup",
        )
        created += 1
    return created, existing, skipped


def _clean_channel_name(name: str):
    name = name.strip().strip("`").lower()
    name = re.sub(r"\s+", "-", name)
    name = re.sub(r"[^a-z0-9\-_]", "", name)
    name = re.sub(r"-{2,}", "-", name)
    return name.strip("-_")[:100]


def _parse_channel_layout(layout: str):
    categories, current, seen = [], None, set()
    for raw in layout.splitlines():
        if not raw.strip():
            continue
        stripped = raw.strip()
        if stripped.startswith("#"):
            continue
        is_indented = raw[:1].isspace()
        is_bullet = stripped.startswith(("-", ">"))
        if is_bullet or is_indented:
            raw_name = stripped[1:].strip() if is_bullet else stripped
            channel_name = _clean_channel_name(raw_name)
            if current is None:
                raise ValueError(f"Channel `{channel_name}` has no category heading above it.")
            if not channel_name:
                raise ValueError("A channel name cannot be empty.")
            if channel_name not in current["channels"]:
                current["channels"].append(channel_name)
            continue
        category_name = stripped[:100]
        key = category_name.casefold()
        if key in seen:
            raise ValueError(f"Duplicate category heading: **{category_name}**")
        seen.add(key)
        current = {"name": category_name, "channels": []}
        categories.append(current)
    if not categories:
        raise ValueError("No categories found. Add a heading like `INFORMATION`.")
    if not any(item["channels"] for item in categories):
        raise ValueError("No channels found. Add channel names under category headings.")
    return categories


async def _apply_channels(guild: discord.Guild, layout: str):
    if guild is None:
        raise ValueError("This command can only be used inside a server.")
    me = guild.me
    if me is None:
        raise RuntimeError("Could not determine the bot's server member.")
    if not me.guild_permissions.manage_channels:
        raise PermissionError("Air Commander needs **Manage Channels** permission.")
    categories = _parse_channel_layout(layout)
    new_cats = old_cats = new_channels = old_channels = 0
    errors = []
    for item in categories:
        category = discord.utils.find(lambda c: c.name.casefold() == item["name"].casefold(), guild.categories)
        if category is None:
            try:
                category = await guild.create_category(name=item["name"], reason="Air Commander auto channel setup")
                new_cats += 1
            except discord.Forbidden:
                raise PermissionError("Discord denied category creation. Check **Manage Channels**.")
            except discord.HTTPException as exc:
                errors.append(f"Category {item['name']}: {exc}")
                continue
        else:
            old_cats += 1
        for channel_name in item["channels"]:
            exists = discord.utils.find(
                lambda c: isinstance(c, discord.TextChannel)
                and c.name.casefold() == channel_name.casefold()
                and c.category_id == category.id,
                guild.channels,
            )
            if exists:
                old_channels += 1
                continue
            try:
                await guild.create_text_channel(
                    name=channel_name, category=category,
                    reason="Air Commander auto channel setup",
                )
                new_channels += 1
            except discord.Forbidden:
                errors.append(f"#{channel_name}: missing permission")
            except discord.HTTPException as exc:
                errors.append(f"#{channel_name}: {exc}")
    return new_cats, old_cats, new_channels, old_channels, errors


def _channel_result_embed(result):
    nc, oc, nch, och, errors = result
    description = (
        f"📂 Categories created: **{nc}**\n↪️ Existing categories: **{oc}**\n\n"
        f"📝 Channels created: **{nch}**\n↪️ Existing channels: **{och}**"
    )
    if errors:
        description += "\n\n⚠️ **Items not completed:**\n" + "\n".join(f"• {e}" for e in errors[:10])
        if len(errors) > 10:
            description += f"\n• And {len(errors) - 10} more errors."
    return _embed("Auto Channel Setup Complete", description, discord.Color.orange() if errors else discord.Color.green())


class _ClearChannelsConfirm(discord.ui.View):
    def __init__(self, guild_id: int, owner_id: int):
        super().__init__(timeout=45)
        self.guild_id, self.owner_id = guild_id, owner_id

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Only the command invoker can use these buttons.", ephemeral=True)
            return False
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Administrator permission is required.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Continue", style=discord.ButtonStyle.danger, emoji="⚠️")
    async def continue_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=_embed(
                "FINAL CONFIRMATION",
                "This deletes **all server channels and categories**. This cannot be automatically undone.",
                discord.Color.red(),
            ),
            view=_ClearChannelsFinal(self.guild_id, self.owner_id),
        )
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="✖️")
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="Cancelled. Nothing was deleted.", embed=None, view=self)
        self.stop()


class _ClearChannelsFinal(discord.ui.View):
    def __init__(self, guild_id: int, owner_id: int):
        super().__init__(timeout=45)
        self.guild_id, self.owner_id = guild_id, owner_id

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Only the command invoker can use these buttons.", ephemeral=True)
            return False
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Administrator permission is required.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="DELETE EVERYTHING", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def delete_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        if guild is None or guild.id != self.guild_id:
            return await interaction.response.send_message("Invalid server.", ephemeral=True)
        me = guild.me
        if me is None or not me.guild_permissions.manage_channels:
            return await interaction.response.send_message("Air Commander needs Manage Channels permission.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        for child in self.children:
            child.disabled = True
        try:
            await interaction.message.edit(view=self)
        except discord.HTTPException:
            pass
        channels = list(guild.channels)
        channels.sort(key=lambda channel: isinstance(channel, discord.CategoryChannel))
        deleted, failed = 0, []
        for channel in channels:
            try:
                await channel.delete(reason=f"Clear channels confirmed by {interaction.user} ({interaction.user.id})")
                deleted += 1
            except discord.NotFound:
                continue
            except (discord.Forbidden, discord.HTTPException) as exc:
                failed.append(f"{channel.name}: {type(exc).__name__}")
        result = _embed(
            "Channel Cleanup Finished",
            f"Deleted: **{deleted}**\nFailed: **{len(failed)}**\n\nThe server and its roles were not deleted.",
            discord.Color.orange() if failed else discord.Color.green(),
        )
        if failed:
            result.add_field(name="Failed items", value="\n".join(failed[:10]), inline=False)
        await interaction.followup.send(embed=result, ephemeral=True)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="✖️")
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="Cancelled. Nothing was deleted.", embed=None, view=self)
        self.stop()


def setup(bot: commands.Bot):
    """Register this module once. Safe to call from bot.py's startup loader."""
    if getattr(bot, "_air_autorolesetup_loaded", False):
        print("ℹ️ AutoRoleSetup already registered; skipping duplicate setup.")
        return

    # ---------------------------------------------------------
    # /autorolesetup (only add if another module hasn't added it)
    # ---------------------------------------------------------
    if bot.tree.get_command("autorolesetup") is None:
        @bot.tree.command(name="autorolesetup", description="Create roles from Role Name - #RRGGBB lines")
        @app_commands.describe(layout="Example: Admin - #5865F2\nOwner - #FF0000")
        @app_commands.checks.has_permissions(manage_roles=True)
        async def slash_autorolesetup(interaction: discord.Interaction, *, layout: str):
            if interaction.guild is None:
                return await interaction.response.send_message(
                    embed=_embed("Server Only", "Use this in a server.", discord.Color.red()), ephemeral=True
                )
            await interaction.response.defer(ephemeral=True)
            try:
                created, existing, skipped = await _apply_roles(interaction.guild, layout)
            except (ValueError, PermissionError) as exc:
                return await interaction.followup.send(
                    embed=_embed("Setup Failed", str(exc), discord.Color.red()), ephemeral=True
                )
            except discord.Forbidden:
                return await interaction.followup.send(
                    embed=_embed("Permission Error", "Give Air Commander Manage Roles and move its bot role above the roles it must create.", discord.Color.red()), ephemeral=True
                )
            except Exception as exc:
                print(f"[AutoRoleSetup] {type(exc).__name__}: {exc}")
                return await interaction.followup.send(
                    embed=_embed("Setup Failed", "Check bot permissions and Render logs.", discord.Color.red()), ephemeral=True
                )
            text = f"🎨 Roles created: **{created}**\n↪️ Roles already present: **{existing}**"
            if skipped:
                text += "\n\n⚠️ At/above my role:\n" + "\n".join(f"• {x}" for x in skipped)
            await interaction.followup.send(
                embed=_embed("Auto Role Setup Complete", text, discord.Color.green()), ephemeral=True
            )
    else:
        print("ℹ️ /autorolesetup already exists; keeping the existing command.")

    if bot.get_command("autorolesetup") is None:
        @bot.command(name="autorolesetup")
        @commands.has_guild_permissions(manage_roles=True)
        async def prefix_autorolesetup(ctx: commands.Context, *, layout: str):
            if ctx.guild is None:
                return await ctx.send(embed=_embed("Server Only", "Use this in a server.", discord.Color.red()))
            try:
                created, existing, skipped = await _apply_roles(ctx.guild, layout)
            except (ValueError, PermissionError) as exc:
                return await ctx.send(embed=_embed("Setup Failed", str(exc), discord.Color.red()))
            except discord.Forbidden:
                return await ctx.send(embed=_embed("Permission Error", "Give Air Commander Manage Roles and move its role above the roles it must create.", discord.Color.red()))
            except Exception as exc:
                print(f"[AutoRoleSetup] prefix {type(exc).__name__}: {exc}")
                return await ctx.send(embed=_embed("Setup Failed", "Check permissions and Render logs.", discord.Color.red()))
            text = f"🎨 Roles created: **{created}**\n↪️ Roles already present: **{existing}**"
            if skipped:
                text += "\n\n⚠️ At/above my role:\n" + "\n".join(f"• {x}" for x in skipped)
            await ctx.send(embed=_embed("Auto Role Setup Complete", text, discord.Color.green()))
    else:
        print("ℹ️ ,autorolesetup already exists; keeping the existing command.")

    # ---------------------------------------------------------
    # /autochannel setup; merge into an existing /autochannel group
    # rather than silently skipping the setup subcommand.
    # ---------------------------------------------------------
    @app_commands.command(name="setup", description="Create categories and text channels from a layout")
    @app_commands.describe(layout="Category headings on separate lines; prefix channels with - or indent them")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def slash_autochannel_setup(interaction: discord.Interaction, *, layout: str):
        if interaction.guild is None:
            return await interaction.response.send_message(
                embed=_embed("Server Only", "Use this in a server.", discord.Color.red()), ephemeral=True
            )
        await interaction.response.defer(ephemeral=True)
        try:
            result = await _apply_channels(interaction.guild, layout)
        except (ValueError, PermissionError) as exc:
            return await interaction.followup.send(
                embed=_embed("Setup Failed", str(exc), discord.Color.red()), ephemeral=True
            )
        except Exception as exc:
            print(f"[AutoRoleSetup] {type(exc).__name__}: {exc}")
            return await interaction.followup.send(
                embed=_embed("Setup Failed", "Check permissions and Render logs.", discord.Color.red()), ephemeral=True
            )
        await interaction.followup.send(embed=_channel_result_embed(result), ephemeral=True)

    existing_group = bot.tree.get_command("autochannel")
    if existing_group is None:
        autochannel_group = app_commands.Group(
            name="autochannel", description="Automatically create categories and channels"
        )
        autochannel_group.add_command(slash_autochannel_setup)
        bot.tree.add_command(autochannel_group)
    elif isinstance(existing_group, app_commands.Group):
        if existing_group.get_command("setup") is None:
            existing_group.add_command(slash_autochannel_setup)
            print("✅ Added /autochannel setup to the existing /autochannel group.")
        else:
            print("ℹ️ /autochannel setup already exists; keeping the existing subcommand.")
    else:
        print("⚠️ /autochannel is already registered as a non-group command; cannot add /autochannel setup.")

    # Prefix command group. Merge setup into an existing group safely.
    @commands.command(name="setup", aliases=["create"])
    @commands.has_guild_permissions(manage_channels=True)
    async def prefix_autochannel_setup(ctx: commands.Context, *, layout: str):
        if ctx.guild is None:
            return await ctx.send(embed=_embed("Server Only", "Use this in a server.", discord.Color.red()))
        try:
            result = await _apply_channels(ctx.guild, layout)
        except (ValueError, PermissionError) as exc:
            return await ctx.send(embed=_embed("Setup Failed", str(exc), discord.Color.red()))
        except Exception as exc:
            print(f"[AutoRoleSetup] prefix {type(exc).__name__}: {exc}")
            return await ctx.send(embed=_embed("Setup Failed", "Check permissions and Render logs.", discord.Color.red()))
        await ctx.send(embed=_channel_result_embed(result))

    existing_prefix_group = bot.get_command("autochannel")
    if existing_prefix_group is None:
        @commands.group(name="autochannel", invoke_without_command=True)
        @commands.has_guild_permissions(manage_channels=True)
        async def prefix_autochannel(ctx: commands.Context):
            await ctx.send(embed=_embed("Auto Channel Setup", "Use `,autochannel setup` followed by your layout."))

        prefix_autochannel.add_command(prefix_autochannel_setup)
        bot.add_command(prefix_autochannel)
    elif isinstance(existing_prefix_group, commands.Group):
        if existing_prefix_group.get_command("setup") is None:
            existing_prefix_group.add_command(prefix_autochannel_setup)
            print("✅ Added ,autochannel setup to the existing prefix group.")
        else:
            print("ℹ️ ,autochannel setup already exists; keeping the existing subcommand.")
    else:
        print("⚠️ ,autochannel already exists as a non-group command; cannot add setup subcommand.")

    # ---------------------------------------------------------
    # /clearchannels and ,clearchannels: two-step, admin-only
    # destructive action. Avoid duplicate registrations.
    # ---------------------------------------------------------
    if bot.tree.get_command("clearchannels") is None:
        @bot.tree.command(name="clearchannels", description="Delete all channels and categories after two confirmations")
        @app_commands.checks.has_permissions(administrator=True)
        async def slash_clearchannels(interaction: discord.Interaction):
            guild = interaction.guild
            if guild is None:
                return await interaction.response.send_message("Use this command inside a server.", ephemeral=True)
            me = guild.me
            if me is None or not me.guild_permissions.manage_channels:
                return await interaction.response.send_message("Air Commander needs Manage Channels permission.", ephemeral=True)
            channels = list(guild.channels)
            categories = sum(isinstance(c, discord.CategoryChannel) for c in channels)
            await interaction.response.send_message(
                embed=_embed(
                    "Clear All Channels?",
                    f"Server: **{guild.name}**\nChannels and categories: **{len(channels)}**\nCategories: **{categories}**\n\nThis requires two confirmations. Deletion cannot be automatically undone.",
                    discord.Color.red(),
                ),
                view=_ClearChannelsConfirm(guild.id, interaction.user.id), ephemeral=True,
            )
    else:
        print("ℹ️ /clearchannels already exists; keeping the existing command.")

    if bot.get_command("clearchannels") is None:
        @bot.command(name="clearchannels")
        @commands.has_guild_permissions(administrator=True)
        async def prefix_clearchannels(ctx: commands.Context):
            guild = ctx.guild
            if guild is None:
                return await ctx.send("Use this command inside a server.")
            me = guild.me
            if me is None or not me.guild_permissions.manage_channels:
                return await ctx.send("Air Commander needs Manage Channels permission.")
            channels = list(guild.channels)
            categories = sum(isinstance(c, discord.CategoryChannel) for c in channels)
            await ctx.send(
                embed=_embed(
                    "Clear All Channels?",
                    f"Server: **{guild.name}**\nChannels and categories: **{len(channels)}**\nCategories: **{categories}**\n\nThis requires two confirmations. Deletion cannot be automatically undone.",
                    discord.Color.red(),
                ),
                view=_ClearChannelsConfirm(guild.id, ctx.author.id),
            )
    else:
        print("ℹ️ ,clearchannels already exists; keeping the existing command.")

    bot._air_autorolesetup_loaded = True
    print("✅ AutoRoleSetup registered: autorolesetup, autochannel setup, clearchannels (slash/prefix where available).")
