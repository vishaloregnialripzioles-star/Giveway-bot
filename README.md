# Giveway-bot

A Discord giveaway bot built with Discord.js and PostgreSQL. It runs as a
**Render Web Service**, exposes a health endpoint, stores giveaways and entries
in PostgreSQL, and recovers expired giveaways after a restart.

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
`GUILD_ID` in `.env` before starting the bot. With `GUILD_ID` blank, the
running bot checks the guilds it is connected to and updates those guild
commands (falling back to global registration only if no guild is cached).
Global command updates can take a while to appear. `npm run register` checks
and registers globally (or to `GUILD_ID`, when set) without starting the bot.
Before writing, the bot compares the current command definitions so routine
restarts do not keep replacing identical commands. Discord rate-limit cooldowns
are saved in PostgreSQL and survive service restarts.

## Deploy on Render

Create a **Web Service** connected to this repository and choose the **Free**
instance plan:

- **Build Command:** `npm install`
- **Start Command:** `npm start`
- **Runtime:** Node
- **Health Check Path:** `/healthz`

The bot listens on Render's injected `PORT` value and binds to `0.0.0.0`.
Create a PostgreSQL database and add these environment variables under the
web service's **Environment** settings:

| Variable | Required | Value |
| --- | --- | --- |
| `DISCORD_TOKEN` | Yes | Bot token from Discord Developer Portal |
| `CLIENT_ID` | Yes | Discord application ID |
| `DATABASE_URL` | Yes | PostgreSQL connection URL; use Render's **Internal Database URL** if the database is on Render |
| `GUILD_ID` | No | Development server ID for fast command updates; omit in production |
| `PGSSL` | No | Set `true` only if your database provider explicitly requires TLS and the URL doesn't configure it |

`GET /healthz` returns `200` when the bot has initialized and PostgreSQL is
reachable; it returns `503` while starting or if the database is unreachable.
The root URL returns a small status message.

### Free-plan limitations

Render's Free Web Services spin down after 15 minutes without inbound traffic
and can take about a minute to wake on the next request. That means this bot is
not guaranteed to stay connected to Discord 24/7 on the free plan; it can miss
events while sleeping and will reconnect when Render starts it again. The health
endpoint makes it a valid Web Service, but does not guarantee always-on uptime.

Render's Free PostgreSQL databases are limited to 1 GB and expire 30 days after
creation; use a database provider with suitable persistence if you need giveaway
records to last longer. The service's local filesystem is not used for giveaway
data. Do not commit `.env` or put the bot token in source control.

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
