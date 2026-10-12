import asyncio
import logging
import os
import threading

import discord
from discord import app_commands
from flask import Flask, jsonify

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("giveway-bot")

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")
PORT = int(os.getenv("PORT", "10000"))

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing. Set it in Render Environment.")

if GUILD_ID and not GUILD_ID.isdigit():
    raise RuntimeError("GUILD_ID must be a numeric Discord server ID.")

web = Flask(__name__)


@web.get("/")
def home():
    return jsonify({"status": "ok", "bot": "Giveway-bot", "command": "/ping"})


@web.get("/health")
def health():
    return jsonify({"status": "ok"})


def run_health_server():
    # Keep Render health checks independent from Discord gateway availability.
    web.run(host="0.0.0.0", port=PORT, use_reloader=False)


threading.Thread(target=run_health_server, daemon=True, name="health-server").start()


def create_bot():
    client = discord.Client(intents=discord.Intents.none())
    tree = app_commands.CommandTree(client)
    synced = False

    @tree.command(name="ping", description="Check whether the bot is online.")
    async def ping(interaction: discord.Interaction):
        latency_ms = round(client.latency * 1000)
        await interaction.response.send_message(f"🏓 Pong! Latency: {latency_ms} ms")

    @client.event
    async def on_ready():
        nonlocal synced
        log.info("Discord connected as %s (ID: %s)", client.user, client.user.id)
        if synced:
            return

        try:
            if GUILD_ID:
                # Copy the locally defined command into this guild and perform
                # one guild sync. Do not clear remote commands or also sync globally.
                guild = discord.Object(id=int(GUILD_ID))
                tree.copy_global_to(guild=guild)
                commands = await tree.sync(guild=guild)
                log.info("Synced %d command(s) to guild %s.", len(commands), GUILD_ID)
            else:
                commands = await tree.sync()
                log.info("Synced %d global command(s).", len(commands))
            synced = True
        except discord.HTTPException as exc:
            if exc.status == 429:
                log.error(
                    "Discord rate-limited slash-command sync (HTTP 429). "
                    "Bot is connected, but command sync did not complete; "
                    "not retrying sync repeatedly in this session."
                )
                return
            log.exception("Slash-command sync failed with HTTP %s.", exc.status)
        except Exception:
            log.exception("Unexpected slash-command sync failure.")

    return client


async def main():
    delay = 120
    while True:
        client = create_bot()
        try:
            await client.start(TOKEN, reconnect=True)
            return
        except discord.HTTPException as exc:
            await client.close()
            if exc.status != 429:
                log.exception("Discord login failed with HTTP %s.", exc.status)
                raise
            log.warning(
                "Discord login rate-limited (HTTP 429); waiting %s seconds before retry.",
                delay,
            )
            await asyncio.sleep(delay)
            delay = min(delay * 2, 900)
        except Exception:
            await client.close()
            log.exception("Discord client stopped unexpectedly.")
            raise


if __name__ == "__main__":
    asyncio.run(main())
