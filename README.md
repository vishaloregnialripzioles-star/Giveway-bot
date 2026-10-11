# Giveway-bot

A Discord giveaway bot built with Discord.js and PostgreSQL. It runs as a
long-lived **Render Background Worker**, stores giveaways and entries in
PostgreSQL, and recovers expired giveaways after a restart.

## Features

- `/giveaway create` posts a button-based giveaway with a prize, duration,
  winner count, optional channel, required role, and 2x bonus-entry role.
- Members can enter once or leave before the giveaway closes. Entry counts
  update on the giveaway post.
- Giveaway records and entries persist in PostgreSQL; due giveaways are
  processed after a restart. Winner announcements are retried if Discord is
  temporarily unavailable just after a draw.
- `/giveaway end`, `/giveaway reroll`, `/giveaway pause`, `/giveaway resume`,
  and `/giveaway cancel` manage a giveaway. Rerolls exclude previous winners.
- `/giveaway list` shows active giveaways; `/giveaway participants` gives the
  host or a Manage Server moderator an entrant count and participant list.
- Winners are announced in the giveaway channel and receive a best-effort DM.

## Discord application setup

1. Create an application and bot in the
   [Discord Developer Portal](https://discord.com/developers/applications).
2. Copy the bot token and application ID (the `CLIENT_ID`).
3. Invite the bot to your server with the `bot` and `applications.commands`
   scopes. Grant it **View Channels**, **Send Messages**, **Embed Links**, and
   **Read Message History** in the channels where giveaways will run.
4. The bot only requests the `Guilds` gateway intent; no privileged member
   intent is needed. Users' roles are checked from the Discord interaction
   payload when they enter.

## Run locally

Requires Node.js 20+ and PostgreSQL.

```sh
npm install
cp .env.example .env
# Fill in DISCORD_TOKEN, CLIENT_ID, and DATABASE_URL in .env
npm start
```

To make slash commands appear quickly in one development server, set
`GUILD_ID` in `.env` before starting the bot. Leave it blank in production to
register commands globally. Global command updates can take a while to appear.
You can also run `npm run register` to register commands without starting the
bot.

## Deploy on Render

Create a **Background Worker** connected to this repository:

- **Build Command:** `npm install`
- **Start Command:** `npm start`
- **Runtime:** Node

Create a Render PostgreSQL database in the same region as the worker, then add
these environment variables under the worker's **Environment** settings:

| Variable | Required | Value |
| --- | --- | --- |
| `DISCORD_TOKEN` | Yes | Bot token from Discord Developer Portal |
| `CLIENT_ID` | Yes | Discord application ID |
| `DATABASE_URL` | Yes | Render PostgreSQL **Internal Database URL** |
| `GUILD_ID` | No | Development server ID for fast command updates; omit in production |
| `PGSSL` | No | Set `true` only if your database provider explicitly requires TLS and the URL doesn't configure it |

Do not commit `.env` or put the bot token in source control. Render's filesystem
is not used for application data; PostgreSQL holds giveaway state.

## Commands

| Command | What it does |
| --- | --- |
| `/giveaway create prize duration [winners] [channel] [required_role] [bonus_role]` | Start a giveaway. Duration examples: `30m`, `2h`, `7d`; allowed range is 1 minute to 30 days. |
| `/giveaway end message_id` | End early and draw winners. |
| `/giveaway reroll message_id [winners]` | Pick replacement winners, excluding all previous winners. |
| `/giveaway pause message_id` | Pause entries and preserve remaining time. |
| `/giveaway resume message_id` | Resume a paused giveaway. |
| `/giveaway cancel message_id` | Cancel without picking a winner. |
| `/giveaway list` | List active and paused giveaways in this server. |
| `/giveaway participants message_id` | View entrants; limited to the host and Manage Server moderators. |

The giveaway host or a member with **Manage Server** can manage that giveaway.
Creating a giveaway requires **Manage Server**. Rerolling works after a giveaway
has ended. Each entrant has one entry by default; members with the optional
bonus role receive two weighted entries.

## Checks

```sh
npm test
npm run check
```
