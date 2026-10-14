# Giveway-bot

A Discord bot with a full button-based giveaway system, persistent entry tracking, automatic winner selection, and moderator controls.

## Giveaway commands

- `/giveaway start` — Start a giveaway with a prize, duration, winner count, channel, and optional rules.
- `/giveaway end` — End an active giveaway early and select winner(s).
- `/giveaway reroll` — Select replacement winner(s) from remaining entrants.
- `/giveaway cancel` — Cancel an active giveaway without selecting winners.
- `/giveaway entrants` — Privately view the entrant list.

Durations use `30s`, `10m`, `2h`, or `1d` format. Allowed duration is 30 seconds to 30 days. Each user can enter once, can leave before the draw, and bots cannot enter. Giveaway buttons are persistent across bot restarts when the database is preserved.

## Other commands

- `/help`, `/ping`
- `/kick`, `/ban`, `/timeout`, `/untimeout`, `/purge`, `/warn`
- `/slowmode`, `/lock`, `/unlock`, `/nickname`

Moderation commands require the appropriate Discord permissions and role hierarchy.

## Render setup

- Build command: `pip install -r requirements.txt`
- Start command: `python bot.py`
- Required environment variable: `DISCORD_TOKEN`
- Recommended environment variable: `GUILD_ID` — numeric ID of the server where commands should appear quickly.
- Optional environment variable: `GIVEAWAY_DB_PATH` — full path to the SQLite database file.

### Keep giveaway data through deploys

Render's normal filesystem may be ephemeral. To preserve giveaway entries and active giveaways across restarts/deploys, attach a persistent disk to the service (for example mounted at `/var/data`) and set:

```env
GIVEAWAY_DB_PATH=/var/data/giveaways.sqlite3
```

The service exposes `/` and `/health`; both report web health separately from Discord gateway connection state.

## Discord permissions

Invite the bot with the `bot` and `applications.commands` scopes. For giveaway channels, allow View Channel, Send Messages, Embed Links, and Read Message History. Moderation features need their own permissions. The bot's role should be positioned appropriately for moderation commands.

Never paste your bot token into chat or commit it to GitHub.
