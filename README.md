# Giveway-bot

A clean Discord server bot with utility and moderation slash commands, built with discord.py and hosted on Render.

## Commands

### General
- /help — Private command guide
- /ping — Check bot gateway latency

### Moderation
- /kick member reason
- /ban member reason
- /timeout member minutes reason — 1 to 40,320 minutes (28 days)
- /untimeout member reason
- /purge amount — Delete 1–100 recent messages
- /warn member reason — Sends a warning DM
- /slowmode seconds — 0 disables slowmode
- /lock channel and /unlock channel
- /nickname member nickname — Leave nickname empty to reset

Moderation commands have Discord default permission restrictions and runtime permission checks. The bot also respects role hierarchy for member actions. Its role must be above the members it moderates.

## Render setup

- Build command: pip install -r requirements.txt
- Start command: python bot.py
- Required environment variable: DISCORD_TOKEN
- Recommended environment variable: GUILD_ID — numeric ID of the server where commands should appear quickly

The service exposes / and /health. These report the web process and separately indicate whether the Discord gateway is connected.

## Discord setup checklist

1. Invite the bot using the bot and applications.commands scopes.
2. Grant only the permissions needed: Kick Members, Ban Members, Moderate Members, Manage Messages, Read Message History, Manage Channels, and Manage Nicknames.
3. Move the bot role above members and roles it should moderate.
4. Set DISCORD_TOKEN and GUILD_ID in Render Environment. Never paste your token into chat or commit it to GitHub.
5. Check Render logs for the Discord connection and slash-command sync messages after deployment.

If Discord returns Cloudflare Error 1015 / HTTP 429, the service may stay healthy while Discord interactions fail. Do not repeatedly redeploy or retry commands during that upstream block; wait for it to clear or contact Discord Support with the Ray ID and timestamp.
