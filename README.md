# Giveway-bot

A Discord bot with a button-based giveaway system, persistent entry tracking, automatic winner selection, and moderator controls. Giveaway records are stored in Supabase PostgreSQL.

## Giveaway commands

- `/giveaway start` — Start a giveaway with a prize, duration, winner count, channel, and optional rules.
- `/giveaway end` — End an active giveaway early and select winner(s).
- `/giveaway reroll` — Select replacement winner(s) from remaining entrants.
- `/giveaway cancel` — Cancel an active giveaway without selecting winners.
- `/giveaway entrants` — Privately view the entrant list.

Durations use `30s`, `10m`, `2h`, or `1d` format. Allowed duration is 30 seconds to 30 days. Each user can enter once, can leave before the draw, and bots cannot enter. Active giveaway buttons and entries survive restarts when the Supabase database remains available.

## Other commands

- `/help`, `/ping`
- `/kick`, `/ban`, `/timeout`, `/untimeout`, `/purge`, `/warn`
- `/slowmode`, `/lock`, `/unlock`, `/nickname`

Moderation commands require the appropriate server permissions and role hierarchy.

## Render setup

- Build command: `pip install -r requirements.txt`
- Start command: `python bot.py`
- Required environment variables: `DISCORD_TOKEN`, `DATABASE_URL`
- Recommended environment variable: `GUILD_ID` — numeric ID of the server where commands should appear quickly.

### Supabase database

Set `DATABASE_URL` in Render to your Supabase PostgreSQL connection URI. Use the Supabase **Session Pooler** connection string when needed for IPv4-only hosts, and ensure the URI contains the correct database password. The bot uses TLS (`sslmode=require`) and creates its `giveaways` table automatically on startup. URL-encode special characters in the password before inserting it into the URI.

The service exposes `/` and `/health`; these report web health separately from Discord gateway connection state.

## Discord permissions

Invite the bot with the `bot` and `applications.commands` scopes. For giveaway channels, allow View Channel, Send Messages, Embed Links, and Read Message History. Moderation features need their own permissions. The bot's role should be positioned appropriately for moderation commands.

Never paste your bot token or database password into chat or commit them to GitHub.
