# ============================================================
# AIR COMMANDER — OWNER PREFIXLESS SYSTEM
# File: owner_prefix.py
# ============================================================

import os
import logging
import discord
from discord.ext import commands

log = logging.getLogger("aircommander.owner_prefix")


def setup_owner_prefixless(bot: commands.Bot):
    """Allow only the configured owner to run selected commands without ','."""

    if getattr(bot, "_air_owner_prefixless_loaded", False):
        return

    bot._air_owner_prefixless_loaded = True

    raw_owner_ids = os.getenv("DISCORD_OWNER_ID", "")
    owner_ids = {
        int(value.strip())
        for value in raw_owner_ids.split(",")
        if value.strip().isdigit()
    }

    allowed_commands = {
        "ping",
        "purge",
        "kick",
        "ban",
        "unban",
        "warn",
        "warnings",
        "unwarn",
        "help",
        "serverpulse",
        "airscan",
    }

    @bot.listen("on_message")
    async def owner_prefixless_listener(message: discord.Message):
        if message.author.bot or not message.guild:
            return

        # Check explicit owner IDs first, then discord.py application owner.
        is_owner = message.author.id in owner_ids

        if not is_owner:
            try:
                is_owner = await bot.is_owner(message.author)
            except discord.DiscordException:
                return

        if not is_owner:
            return

        text = message.content.strip()
        if not text:
            return

        # Leave normal prefixed commands alone.
        prefix = await bot.get_prefix(message)
        prefixes = prefix if isinstance(prefix, (list, tuple)) else [prefix]

        if any(text.startswith(p) for p in prefixes if p):
            return

        # Resolve the first word as an existing command.
        command_name = text.split(maxsplit=1)[0].lower()

        if command_name not in allowed_commands:
            return

        command = bot.get_command(command_name)
        if command is None:
            return

        # Reuse the existing command instead of registering a duplicate.
        # Build a context with a prefixless command view.
        ctx = await bot.get_context(message)

        if ctx.command is not None:
            return

        from discord.ext.commands.view import StringView

        ctx.command = command
        ctx.invoked_with = command_name
        ctx.prefix = ""
        ctx.view = StringView(text)
        ctx.view.skip_string(command_name)
        ctx.view.skip_ws()

        await bot.invoke(ctx)

    log.info("Air Commander owner prefixless system loaded.")

