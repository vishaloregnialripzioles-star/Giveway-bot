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

web = Flask(__name__)

@web.get("/")
def home():
    return jsonify({"status": "ok", "bot": "Giveway-bot", "command": "/ping"})

@web.get("/health")
def health():
    return jsonify({"status": "ok"})

def run_health_server():
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
        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))
            tree.clear_commands(guild=guild)
            tree.copy_global_to(guild=guild)
            guild_commands = await tree.sync(guild=guild)
            log.info("Synced %d command(s) to guild %s.", len(guild_commands), GUILD_ID)
        global_commands = await tree.sync()
        log.info("Synced %d global command(s). Only /ping is defined.", len(global_commands))
        synced = True

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
                raise
            log.warning("Discord login rate-limited (HTTP 429); retrying with a fresh client in %s seconds.", delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 900)
        except Exception:
            await client.close()
            raise

if __name__ == "__main__":
    asyncio.run(main())
