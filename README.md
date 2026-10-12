# Giveway-bot

A clean, minimal Discord bot with exactly one application command: `/ping`.

## Render setup

- Runtime: Python
- Build command: `pip install -r requirements.txt`
- Start command: `python bot.py`
- Required environment variable: `DISCORD_TOKEN`
- Optional environment variable: `GUILD_ID` (your test server ID; makes `/ping` appear faster in that server)

The Flask health endpoint is available at `/health` for Render.

After deployment, check Render logs for **Discord connected as ...** and **Synced 1 command(s)**. Never share your bot token in chat.
