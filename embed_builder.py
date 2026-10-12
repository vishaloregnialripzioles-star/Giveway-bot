from __future__ import annotations
import time, math, random, json, re
from datetime import datetime, timezone
import discord
from discord.ext import commands

TITLE='🎨 Embed Builder'
KEY='embed_builder'

def _embed(desc, color=0x5865F2):
    e=discord.Embed(title=TITLE, description=desc, color=color)
    e.set_footer(text="AirMarshal Commander • Air Commander")
    return e

def setup(bot):
    # Commands are intentionally unique; existing moderation/utility commands are retained.
    if bot.get_command('embedbuilder') is None:
        @bot.command(name='embedbuilder')
        async def _prefix(ctx, *, value: str = ""):
            await _run(ctx, value)
    if bot.tree.get_command('embedbuilder') is None:
        @bot.tree.command(name='embedbuilder', description='Build and send embeds.')
        async def _slash(interaction: discord.Interaction, value: str = ""):
            await _run(interaction, value)

async def _run(target, value=""):
    send = target.response.send_message if isinstance(target, discord.Interaction) else target.send
    if isinstance(target, discord.Interaction) and target.response.is_done():
        send = target.followup.send
    await send(embed=_embed('**Build and send embeds.**\\n\\nConfiguration input: `{value}`\\n\\nUse this command as the control point for the module. Existing Air Commander commands are preserved.'.format(value=value)))
