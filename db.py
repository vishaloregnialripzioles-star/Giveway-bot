# ============================================================
# AIR COMMANDER — CENTRAL POSTGRESQL DATABASE
# ============================================================
#
# Persistent storage for:
#   • Players / Coins / XP / Levels
#   • Game statistics / inventories / sessions
#   • Achievements / Missions / Bounties
#   • Market / Territories
#   • Guild prefix / settings
#   • Warnings
#   • Command logs / analytics
#   • Welcome / Autorole
#   • Selfrole / Reaction roles
#   • Tickets
#   • YouTube Alerts
#   • Giveaways
#   • Leveling / Rewards / Boosters / Seasons / Quests
#   • Automation / AutoMode
#   • AntiNuke / Security
#   • Snipe
#   • Custom Commands
#
# PostgreSQL + asyncpg
# ============================================================

import os
import json
import time
import asyncio
from urllib.parse import urlparse
from functools import wraps

import asyncpg
import discord
from discord.ext import commands


DATABASE_URL = os.getenv("DATABASE_URL")
_pool = None


# ============================================================
# BASIC DATABASE HELPERS
# ============================================================

async def db_execute(query, *args):
    if not _pool:
        return None

    try:
        return await _pool.execute(query, *args)
    except Exception as exc:
        print(f"❌ DB execute error: {type(exc).__name__}: {exc}")
        return None


async def db_fetch(query, *args):
    if not _pool:
        return []

    try:
        return await _pool.fetch(query, *args)
    except Exception as exc:
        print(f"❌ DB fetch error: {type(exc).__name__}: {exc}")
        return []


async def db_fetchrow(query, *args):
    if not _pool:
        return None

    try:
        return await _pool.fetchrow(query, *args)
    except Exception as exc:
        print(f"❌ DB fetchrow error: {type(exc).__name__}: {exc}")
        return None


async def db_fetchval(query, *args):
    if not _pool:
        return None

    try:
        return await _pool.fetchval(query, *args)
    except Exception as exc:
        print(f"❌ DB fetchval error: {type(exc).__name__}: {exc}")
        return None


# ============================================================
# JSON HELPERS
# ============================================================

def json_load(value, default=None):
    if default is None:
        default = {}

    if value is None:
        return default

    if isinstance(value, (dict, list)):
        return value

    try:
        return json.loads(value)
    except Exception:
        return default


def json_dump(value):
    return json.dumps(value if value is not None else {})


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

async def init_db():
    global _pool

    if _pool:
        return True

    if not DATABASE_URL:
        print("⚠️ DATABASE_URL is not set; database features are disabled.")
        return False

    parsed = urlparse(DATABASE_URL)
    host = (parsed.hostname or "").lower()

    if host.startswith("db.") and host.endswith(".supabase.co"):
        print(
            "❌ Supabase direct database URL detected. "
            "Use the Session Pooler connection string."
        )
        return False

    for attempt in range(1, 4):
        try:
            print(f"🗄️ Connecting to PostgreSQL... attempt {attempt}/3")

            _pool = await asyncpg.create_pool(
                DATABASE_URL,
                min_size=1,
                max_size=8,
                command_timeout=30,
                timeout=15,
            )

            async with _pool.acquire() as conn:

                # ====================================================
                # CORE PLAYER SYSTEM
                # ====================================================

                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS players(
                        guild_id BIGINT NOT NULL,
                        user_id BIGINT NOT NULL,
                        coins BIGINT DEFAULT 100,
                        xp BIGINT DEFAULT 0,
                        level INT DEFAULT 1,
                        total_messages BIGINT DEFAULT 0,
                        last_xp_at TIMESTAMPTZ,
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        updated_at TIMESTAMPTZ DEFAULT NOW(),
                        PRIMARY KEY(guild_id, user_id)
                    );

                    CREATE TABLE IF NOT EXISTS player_stats(
                        guild_id BIGINT,
                        user_id BIGINT,
                        game TEXT,
                        wins INT DEFAULT 0,
                        losses INT DEFAULT 0,
                        score BIGINT DEFAULT 0,
                        data JSONB DEFAULT '{}'::jsonb,
                        PRIMARY KEY(guild_id,user_id,game)
                    );

                    CREATE TABLE IF NOT EXISTS inventories(
                        guild_id BIGINT,
                        user_id BIGINT,
                        item TEXT,
                        quantity INT DEFAULT 0,
                        PRIMARY KEY(guild_id,user_id,item)
                    );

                    CREATE TABLE IF NOT EXISTS game_sessions(
                        id BIGSERIAL PRIMARY KEY,
                        guild_id BIGINT,
                        game TEXT,
                        owner_id BIGINT,
                        state JSONB DEFAULT '{}'::jsonb,
                        status TEXT DEFAULT 'active',
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    );

                    CREATE TABLE IF NOT EXISTS game_players(
                        session_id BIGINT REFERENCES game_sessions(id)
                            ON DELETE CASCADE,
                        user_id BIGINT,
                        state JSONB DEFAULT '{}'::jsonb,
                        PRIMARY KEY(session_id,user_id)
                    );

                    CREATE TABLE IF NOT EXISTS achievements(
                        guild_id BIGINT,
                        user_id BIGINT,
                        achievement TEXT,
                        unlocked_at TIMESTAMPTZ DEFAULT NOW(),
                        PRIMARY KEY(guild_id,user_id,achievement)
                    );

                    CREATE TABLE IF NOT EXISTS missions(
                        id BIGSERIAL PRIMARY KEY,
                        guild_id BIGINT,
                        user_id BIGINT,
                        mission TEXT,
                        reward INT,
                        completed BOOLEAN DEFAULT FALSE,
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    );

                    CREATE TABLE IF NOT EXISTS bounties(
                        id BIGSERIAL PRIMARY KEY,
                        guild_id BIGINT,
                        target_id BIGINT,
                        creator_id BIGINT,
                        challenge TEXT,
                        reward INT,
                        completed BOOLEAN DEFAULT FALSE,
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    );

                    CREATE TABLE IF NOT EXISTS market(
                        guild_id BIGINT,
                        item TEXT,
                        price INT,
                        stock INT DEFAULT 1,
                        PRIMARY KEY(guild_id,item)
                    );

                    CREATE TABLE IF NOT EXISTS territories(
                        guild_id BIGINT,
                        territory TEXT,
                        owner_team TEXT,
                        level INT DEFAULT 1,
                        resources INT DEFAULT 100,
                        PRIMARY KEY(guild_id,territory)
                    );
                """)

                # ====================================================
                # SAFE MIGRATIONS FOR OLD DATABASES
                # ====================================================

                await conn.execute("""
                    ALTER TABLE players
                    ADD COLUMN IF NOT EXISTS total_messages BIGINT DEFAULT 0;

                    ALTER TABLE players
                    ADD COLUMN IF NOT EXISTS last_xp_at TIMESTAMPTZ;

                    ALTER TABLE players
                    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();

                    ALTER TABLE players
                    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

                """)

                # ====================================================
                # GUILD SETTINGS
                # ====================================================

                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS guild_settings(
                        guild_id BIGINT PRIMARY KEY,
                        prefix TEXT NOT NULL DEFAULT ',',
                        data JSONB DEFAULT '{}'::jsonb,
                        updated_at TIMESTAMPTZ DEFAULT NOW()
                    );

                    ALTER TABLE guild_settings
                    ADD COLUMN IF NOT EXISTS data JSONB DEFAULT '{}'::jsonb;

                    ALTER TABLE guild_settings
                    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

                    ALTER TABLE guild_settings
                    ALTER COLUMN prefix SET DEFAULT ',';
                """)

                # Existing old "!" prefixes are changed to Air Commander's ","
                await conn.execute("""
                    UPDATE guild_settings
                    SET prefix = ',',
                        updated_at = NOW()
                    WHERE prefix IS NULL OR prefix = '!';
                """)

                # ====================================================
                # WARNINGS
                # ====================================================

                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS warnings(
                        id BIGSERIAL PRIMARY KEY,
                        guild_id BIGINT NOT NULL,
                        user_id BIGINT NOT NULL,
                        moderator_id BIGINT NOT NULL,
                        reason TEXT NOT NULL,
                        evidence TEXT NOT NULL DEFAULT 'Not provided',
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    );

                    CREATE INDEX IF NOT EXISTS idx_warnings_user
                    ON warnings(guild_id,user_id);
                """)

                # ====================================================
                # COMMAND LOGS
                # ====================================================

                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS command_logs(
                        id BIGSERIAL PRIMARY KEY,
                        guild_id BIGINT NOT NULL,
                        user_id BIGINT NOT NULL,
                        username TEXT,
                        command_name TEXT NOT NULL,
                        command_type TEXT DEFAULT 'prefix',
                        arguments TEXT,
                        channel_id BIGINT,
                        channel_name TEXT,
                        success BOOLEAN DEFAULT TRUE,
                        error_message TEXT,
                        execution_time_ms DOUBLE PRECISION DEFAULT 0,
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    );

                    CREATE INDEX IF NOT EXISTS idx_guild_logs
                        ON command_logs(guild_id);

                    CREATE INDEX IF NOT EXISTS idx_user_logs
                        ON command_logs(user_id);

                    CREATE INDEX IF NOT EXISTS idx_command_logs
                        ON command_logs(command_name);

                    CREATE INDEX IF NOT EXISTS idx_created_at
                        ON command_logs(created_at);
                """)

                # ====================================================
                # WELCOME / AUTOROLE
                # ====================================================

                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS welcome_config(
                        guild_id BIGINT PRIMARY KEY,
                        enabled BOOLEAN DEFAULT FALSE,
                        channel_id BIGINT,
                        message TEXT,
                        embed_enabled BOOLEAN DEFAULT TRUE,
                        embed_title TEXT,
                        embed_description TEXT,
                        embed_color BIGINT DEFAULT 5793266,
                        image_url TEXT,
                        thumbnail_url TEXT,
                        footer TEXT,
                        dm_enabled BOOLEAN DEFAULT FALSE,
                        dm_message TEXT,
                        autorole_id BIGINT,
                        data JSONB DEFAULT '{}'::jsonb,
                        updated_at TIMESTAMPTZ DEFAULT NOW()
                    );
                """)

                # ====================================================
                # SELFROLE / REACTION ROLE
                # ====================================================

                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS selfrole_panels(
                        id BIGSERIAL PRIMARY KEY,
                        guild_id BIGINT NOT NULL,
                        channel_id BIGINT,
                        message_id BIGINT,
                        title TEXT,
                        description TEXT,
                        panel_type TEXT DEFAULT 'button',
                        data JSONB DEFAULT '{}'::jsonb,
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    );

                    CREATE TABLE IF NOT EXISTS selfrole_entries(
                        id BIGSERIAL PRIMARY KEY,
                        panel_id BIGINT REFERENCES selfrole_panels(id)
                            ON DELETE CASCADE,
                        guild_id BIGINT NOT NULL,
                        role_id BIGINT NOT NULL,
                        label TEXT,
                        emoji TEXT,
                        description TEXT,
                        custom_id TEXT,
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    );

                    CREATE INDEX IF NOT EXISTS idx_selfrole_guild
                        ON selfrole_panels(guild_id);

                    CREATE INDEX IF NOT EXISTS idx_selfrole_entries_panel
                        ON selfrole_entries(panel_id);
                """)

                # ====================================================
                # TICKETS
                # ====================================================

                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS ticket_config(
                        guild_id BIGINT PRIMARY KEY,
                        support_role_id BIGINT,
                        log_channel_id BIGINT,
                        ticket_category_id BIGINT,
                        transcript_enabled BOOLEAN DEFAULT TRUE,
                        naming_format TEXT DEFAULT 'ticket-{username}',
                        panel_channel_id BIGINT,
                        panel_message_id BIGINT,
                        enabled BOOLEAN DEFAULT TRUE,
                        data JSONB DEFAULT '{}'::jsonb,
                        updated_at TIMESTAMPTZ DEFAULT NOW()
                    );

                    CREATE TABLE IF NOT EXISTS ticket_categories(
                        id BIGSERIAL PRIMARY KEY,
                        guild_id BIGINT NOT NULL,
                        category_key TEXT NOT NULL,
                        name TEXT NOT NULL,
                        emoji TEXT,
                        description TEXT,
                        support_role_id BIGINT,
                        channel_category_id BIGINT,
                        enabled BOOLEAN DEFAULT TRUE,
                        data JSONB DEFAULT '{}'::jsonb,
                        UNIQUE(guild_id,category_key)
                    );

                    CREATE TABLE IF NOT EXISTS tickets(
                        id BIGSERIAL PRIMARY KEY,
                        guild_id BIGINT NOT NULL,
                        channel_id BIGINT,
                        user_id BIGINT NOT NULL,
                        category_key TEXT,
                        claimed_by BIGINT,
                        status TEXT DEFAULT 'open',
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        closed_at TIMESTAMPTZ,
                        data JSONB DEFAULT '{}'::jsonb
                    );

                    CREATE INDEX IF NOT EXISTS idx_tickets_guild
                        ON tickets(guild_id);

                    CREATE INDEX IF NOT EXISTS idx_tickets_user
                        ON tickets(guild_id,user_id);

                    CREATE INDEX IF NOT EXISTS idx_tickets_channel
                        ON tickets(channel_id);

                    CREATE UNIQUE INDEX IF NOT EXISTS idx_one_open_ticket
                        ON tickets(guild_id,user_id)
                        WHERE status = 'open';
                """)

                # ====================================================
                # YOUTUBE ALERTS
                # ====================================================

                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS youtube_config(
                        guild_id BIGINT PRIMARY KEY,
                        enabled BOOLEAN DEFAULT FALSE,
                        alert_channel_id BIGINT,
                        role_id BIGINT,
                        message_template TEXT,
                        data JSONB DEFAULT '{}'::jsonb,
                        updated_at TIMESTAMPTZ DEFAULT NOW()
                    );

                    CREATE TABLE IF NOT EXISTS youtube_channels(
                        id BIGSERIAL PRIMARY KEY,
                        guild_id BIGINT NOT NULL,
                        channel_key TEXT NOT NULL,
                        channel_name TEXT,
                        channel_url TEXT,
                        channel_id TEXT,
                        last_video_id TEXT,
                        enabled BOOLEAN DEFAULT TRUE,
                        data JSONB DEFAULT '{}'::jsonb,
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        UNIQUE(guild_id,channel_key)
                    );

                    CREATE INDEX IF NOT EXISTS idx_youtube_guild
                        ON youtube_channels(guild_id);
                """)

                # ====================================================
                # GIVEAWAYS
                # ====================================================

                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS giveaways(
                        id BIGSERIAL PRIMARY KEY,
                        guild_id BIGINT NOT NULL,
                        channel_id BIGINT,
                        message_id BIGINT,
                        host_id BIGINT,
                        prize TEXT NOT NULL,
                        winner_count INT DEFAULT 1,
                        ends_at TIMESTAMPTZ,
                        status TEXT DEFAULT 'active',
                        winners JSONB DEFAULT '[]'::jsonb,
                        requirements JSONB DEFAULT '{}'::jsonb,
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    );

                    CREATE TABLE IF NOT EXISTS giveaway_entries(
                        giveaway_id BIGINT
                            REFERENCES giveaways(id)
                            ON DELETE CASCADE,
                        user_id BIGINT NOT NULL,
                        joined_at TIMESTAMPTZ DEFAULT NOW(),
                        PRIMARY KEY(giveaway_id,user_id)
                    );

                    CREATE INDEX IF NOT EXISTS idx_giveaway_guild
                        ON giveaways(guild_id);
                """)

                # ====================================================
                # LEVELING
                # ====================================================

                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS leveling_config(
                        guild_id BIGINT PRIMARY KEY,
                        enabled BOOLEAN DEFAULT TRUE,
                        xp_min INT DEFAULT 15,
                        xp_max INT DEFAULT 30,
                        cooldown_seconds INT DEFAULT 60,
                        levelup_channel_id BIGINT,
                        levelup_message TEXT,
                        announce_levelup BOOLEAN DEFAULT TRUE,
                        stack_rewards BOOLEAN DEFAULT FALSE,
                        data JSONB DEFAULT '{}'::jsonb,
                        updated_at TIMESTAMPTZ DEFAULT NOW()
                    );

                    CREATE TABLE IF NOT EXISTS level_rewards(
                        id BIGSERIAL PRIMARY KEY,
                        guild_id BIGINT NOT NULL,
                        level INT NOT NULL,
                        role_id BIGINT NOT NULL,
                        remove_previous BOOLEAN DEFAULT FALSE,
                        data JSONB DEFAULT '{}'::jsonb,
                        UNIQUE(guild_id,level,role_id)
                    );

                    CREATE TABLE IF NOT EXISTS xp_boosters(
                        id BIGSERIAL PRIMARY KEY,
                        guild_id BIGINT NOT NULL,
                        target_type TEXT NOT NULL,
                        target_id BIGINT NOT NULL,
                        multiplier DOUBLE PRECISION DEFAULT 1.0,
                        enabled BOOLEAN DEFAULT TRUE,
                        data JSONB DEFAULT '{}'::jsonb,
                        UNIQUE(guild_id,target_type,target_id)
                    );

                    CREATE TABLE IF NOT EXISTS leveling_seasons(
                        id BIGSERIAL PRIMARY KEY,
                        guild_id BIGINT NOT NULL,
                        name TEXT NOT NULL,
                        started_at TIMESTAMPTZ DEFAULT NOW(),
                        ended_at TIMESTAMPTZ,
                        active BOOLEAN DEFAULT TRUE,
                        data JSONB DEFAULT '{}'::jsonb
                    );

                    CREATE TABLE IF NOT EXISTS leveling_quests(
                        id BIGSERIAL PRIMARY KEY,
                        guild_id BIGINT NOT NULL,
                        user_id BIGINT NOT NULL,
                        quest_key TEXT NOT NULL,
                        progress INT DEFAULT 0,
                        target INT DEFAULT 1,
                        reward_xp BIGINT DEFAULT 0,
                        reward_coins BIGINT DEFAULT 0,
                        completed BOOLEAN DEFAULT FALSE,
                        expires_at TIMESTAMPTZ,
                        data JSONB DEFAULT '{}'::jsonb
                    );

                    CREATE INDEX IF NOT EXISTS idx_leveling_quests_user
                        ON leveling_quests(guild_id,user_id);
                """)

                # ====================================================
                # AUTOMATION / AUTOMODE
                # ====================================================

                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS automation_config(
                        guild_id BIGINT PRIMARY KEY,
                        enabled BOOLEAN DEFAULT FALSE,
                        log_channel_id BIGINT,
                        spam_enabled BOOLEAN DEFAULT TRUE,
                        spam_limit INT DEFAULT 5,
                        spam_window_seconds INT DEFAULT 7,
                        warning_limit INT DEFAULT 3,
                        timeout_limit INT DEFAULT 5,
                        timeout_minutes INT DEFAULT 10,
                        mention_limit INT DEFAULT 5,
                        duplicate_limit INT DEFAULT 3,
                        link_protection BOOLEAN DEFAULT TRUE,
                        data JSONB DEFAULT '{}'::jsonb,
                        updated_at TIMESTAMPTZ DEFAULT NOW()
                    );

                    CREATE TABLE IF NOT EXISTS automation_whitelist(
                        guild_id BIGINT NOT NULL,
                        target_type TEXT NOT NULL,
                        target_id BIGINT NOT NULL,
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        PRIMARY KEY(guild_id,target_type,target_id)
                    );

                    CREATE TABLE IF NOT EXISTS automations(
                        id BIGSERIAL PRIMARY KEY,
                        guild_id BIGINT NOT NULL,
                        name TEXT NOT NULL,
                        trigger_type TEXT NOT NULL,
                        trigger_data JSONB DEFAULT '{}'::jsonb,
                        action_data JSONB DEFAULT '{}'::jsonb,
                        enabled BOOLEAN DEFAULT TRUE,
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    );
                """)

                # ====================================================
                # ANTINUKE / SECURITY
                # ====================================================

                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS antinuke_config(
                        guild_id BIGINT PRIMARY KEY,
                        enabled BOOLEAN DEFAULT FALSE,
                        log_channel_id BIGINT,
                        punishment TEXT DEFAULT 'ban',
                        extra_owners JSONB DEFAULT '[]'::jsonb,
                        whitelist JSONB DEFAULT '[]'::jsonb,
                        thresholds JSONB DEFAULT '{}'::jsonb,
                        animation_enabled BOOLEAN DEFAULT FALSE,
                        data JSONB DEFAULT '{}'::jsonb,
                        updated_at TIMESTAMPTZ DEFAULT NOW()
                    );

                    CREATE TABLE IF NOT EXISTS security_config(
                        guild_id BIGINT PRIMARY KEY,
                        enabled BOOLEAN DEFAULT FALSE,
                        log_channel_id BIGINT,
                        anti_link BOOLEAN DEFAULT FALSE,
                        anti_invite BOOLEAN DEFAULT FALSE,
                        anti_gif BOOLEAN DEFAULT FALSE,
                        anti_youtube BOOLEAN DEFAULT FALSE,
                        anti_mass_mention BOOLEAN DEFAULT FALSE,
                        punishment TEXT DEFAULT 'delete',
                        data JSONB DEFAULT '{}'::jsonb,
                        updated_at TIMESTAMPTZ DEFAULT NOW()
                    );

                    CREATE TABLE IF NOT EXISTS security_whitelist(
                        guild_id BIGINT NOT NULL,
                        target_type TEXT NOT NULL,
                        target_id BIGINT NOT NULL,
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        PRIMARY KEY(guild_id,target_type,target_id)
                    );
                """)

                # ====================================================
                # SNIPE
                # ====================================================

                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS snipe_messages(
                        id BIGSERIAL PRIMARY KEY,
                        guild_id BIGINT NOT NULL,
                        channel_id BIGINT NOT NULL,
                        message_id BIGINT,
                        author_id BIGINT,
                        author_name TEXT,
                        content TEXT,
                        attachments JSONB DEFAULT '[]'::jsonb,
                        deleted_at TIMESTAMPTZ DEFAULT NOW()
                    );

                    CREATE INDEX IF NOT EXISTS idx_snipe_guild_channel
                        ON snipe_messages(guild_id,channel_id);

                    CREATE INDEX IF NOT EXISTS idx_snipe_deleted_at
                        ON snipe_messages(deleted_at);
                """)

                # ====================================================
                # CUSTOM COMMANDS
                # ====================================================

                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS custom_commands(
                        id BIGSERIAL PRIMARY KEY,
                        guild_id BIGINT NOT NULL,
                        name TEXT NOT NULL,
                        response TEXT,
                        embed_data JSONB DEFAULT '{}'::jsonb,
                        enabled BOOLEAN DEFAULT TRUE,
                        creator_id BIGINT,
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        updated_at TIMESTAMPTZ DEFAULT NOW(),
                        UNIQUE(guild_id,name)
                    );

                    ALTER TABLE custom_commands
                        ADD COLUMN IF NOT EXISTS id BIGSERIAL;
                    ALTER TABLE custom_commands
                        ADD COLUMN IF NOT EXISTS name TEXT;
                    ALTER TABLE custom_commands
                        ADD COLUMN IF NOT EXISTS response TEXT;
                    ALTER TABLE custom_commands
                        ADD COLUMN IF NOT EXISTS embed_data JSONB DEFAULT '{}'::jsonb;
                    ALTER TABLE custom_commands
                        ADD COLUMN IF NOT EXISTS enabled BOOLEAN DEFAULT TRUE;
                    ALTER TABLE custom_commands
                        ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();
                    ALTER TABLE custom_commands
                        ADD COLUMN IF NOT EXISTS command_name TEXT;
                    ALTER TABLE custom_commands
                        ADD COLUMN IF NOT EXISTS usage TEXT;
                    ALTER TABLE custom_commands
                        ADD COLUMN IF NOT EXISTS prompt TEXT;

                    -- Keep older central-schema rows usable by cmdmaker.py.
                    UPDATE custom_commands
                    SET command_name = COALESCE(NULLIF(command_name, ''), name),
                        usage = COALESCE(usage, ''),
                        prompt = COALESCE(prompt, response, '')
                    WHERE command_name IS NULL OR usage IS NULL OR prompt IS NULL;

                    ALTER TABLE custom_commands ALTER COLUMN name DROP NOT NULL;
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_custom_commands_guild_name
                        ON custom_commands(guild_id, name) WHERE name IS NOT NULL;
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_custom_commands_guild_command_name
                        ON custom_commands(guild_id, command_name) WHERE command_name IS NOT NULL;

                    CREATE INDEX IF NOT EXISTS idx_custom_commands_guild
                        ON custom_commands(guild_id);
                """)

                # ====================================================
                # GENERIC GUILD DATA
                # ====================================================

                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS guild_data(
                        guild_id BIGINT NOT NULL,
                        data_key TEXT NOT NULL,
                        data JSONB DEFAULT '{}'::jsonb,
                        updated_at TIMESTAMPTZ DEFAULT NOW(),
                        PRIMARY KEY(guild_id,data_key)
                    );
                """)

            print("✅ Air Commander PostgreSQL database initialized.")
            return True

        except Exception as exc:
            print(
                f"❌ Database initialization attempt {attempt} failed: "
                f"{type(exc).__name__}: {exc}"
            )

            if _pool:
                try:
                    await _pool.close()
                except Exception:
                    pass

                _pool = None

            if attempt < 3:
                await asyncio.sleep(3)

    print("❌ PostgreSQL initialization failed after 3 attempts.")
    return False


# ============================================================
# GENERIC GUILD DATA
# ============================================================

async def save_guild_data(guild_id, key, data):
    return await db_execute("""
        INSERT INTO guild_data(guild_id,data_key,data,updated_at)
        VALUES($1,$2,$3::jsonb,NOW())
        ON CONFLICT(guild_id,data_key)
        DO UPDATE SET
            data=EXCLUDED.data,
            updated_at=NOW()
    """, guild_id, key, json_dump(data))


async def get_guild_data(guild_id, key, default=None):
    if default is None:
        default = {}

    row = await db_fetchrow("""
        SELECT data
        FROM guild_data
        WHERE guild_id=$1 AND data_key=$2
    """, guild_id, key)

    if not row:
        return default

    return json_load(row["data"], default)


async def delete_guild_data(guild_id, key):
    return await db_execute("""
        DELETE FROM guild_data
        WHERE guild_id=$1 AND data_key=$2
    """, guild_id, key)


async def save_feature_config(guild_id, feature, config):
    """Persist any module configuration as JSONB under guild_data."""
    feature = str(feature).strip().lower()
    if not feature:
        raise ValueError("feature must be a non-empty string")
    return await save_guild_data(int(guild_id), f"config:{feature}", config)


async def get_feature_config(guild_id, feature, default=None):
    """Load a module configuration previously saved with save_feature_config."""
    feature = str(feature).strip().lower()
    if not feature:
        raise ValueError("feature must be a non-empty string")
    return await get_guild_data(int(guild_id), f"config:{feature}", default or {})


# ============================================================
# PLAYER SYSTEM
# ============================================================

async def ensure_player(guild_id, user_id):
    return await db_fetchrow("""
        INSERT INTO players(
            guild_id,user_id,coins,xp,level,total_messages
        )
        VALUES($1,$2,100,0,1,0)
        ON CONFLICT(guild_id,user_id)
        DO UPDATE SET updated_at=NOW()
        RETURNING *
    """, guild_id, user_id)


async def get_player(guild_id, user_id):
    return await db_fetchrow("""
        SELECT *
        FROM players
        WHERE guild_id=$1 AND user_id=$2
    """, guild_id, user_id)


async def add_coins(guild_id, user_id, amount):
    await ensure_player(guild_id, user_id)

    return await db_fetchrow("""
        UPDATE players
        SET coins=GREATEST(0,coins+$3),
            updated_at=NOW()
        WHERE guild_id=$1 AND user_id=$2
        RETURNING *
    """, guild_id, user_id, amount)


async def add_xp(guild_id, user_id, amount):
    await ensure_player(guild_id, user_id)

    return await db_fetchrow("""
        UPDATE players
        SET
            xp=xp+$3,
            level=GREATEST(1,FLOOR((xp+$3)/100)::INT+1),
            total_messages=total_messages+1,
            last_xp_at=NOW(),
            updated_at=NOW()
        WHERE guild_id=$1 AND user_id=$2
        RETURNING *
    """, guild_id, user_id, amount)


async def increment_message_count(guild_id, user_id):
    await ensure_player(guild_id, user_id)

    return await db_fetchval("""
        UPDATE players
        SET total_messages=total_messages+1,
            updated_at=NOW()
        WHERE guild_id=$1 AND user_id=$2
        RETURNING total_messages
    """, guild_id, user_id)


# ============================================================
# PLAYER GAME STATS
# ============================================================

async def game_stat(
    guild_id,
    user_id,
    game,
    wins=0,
    losses=0,
    score=0,
):
    await db_execute("""
        INSERT INTO player_stats(
            guild_id,user_id,game,wins,losses,score
        )
        VALUES($1,$2,$3,$4,$5,$6)
        ON CONFLICT(guild_id,user_id,game)
        DO UPDATE SET
            wins=player_stats.wins+$4,
            losses=player_stats.losses+$5,
            score=player_stats.score+$6
    """, guild_id, user_id, game, wins, losses, score)

    return await db_fetchrow("""
        SELECT *
        FROM player_stats
        WHERE guild_id=$1 AND user_id=$2 AND game=$3
    """, guild_id, user_id, game)


# ============================================================
# INVENTORY
# ============================================================

async def add_item(guild_id, user_id, item, quantity=1):
    await db_execute("""
        INSERT INTO inventories(
            guild_id,user_id,item,quantity
        )
        VALUES($1,$2,$3,$4)
        ON CONFLICT(guild_id,user_id,item)
        DO UPDATE SET quantity=inventories.quantity+$4
    """, guild_id, user_id, item, quantity)

    return await db_fetchval("""
        SELECT quantity
        FROM inventories
        WHERE guild_id=$1 AND user_id=$2 AND item=$3
    """, guild_id, user_id, item)


async def get_inventory(guild_id, user_id):
    return await db_fetch("""
        SELECT *
        FROM inventories
        WHERE guild_id=$1 AND user_id=$2
        ORDER BY item
    """, guild_id, user_id)


# ============================================================
# GAME SESSIONS
# ============================================================

async def new_session(guild_id, game, owner_id, state=None):
    return await db_fetchrow("""
        INSERT INTO game_sessions(
            guild_id,game,owner_id,state
        )
        VALUES($1,$2,$3,$4::jsonb)
        RETURNING *
    """, guild_id, game, owner_id, json_dump(state or {}))


async def session_info(session_id):
    return await db_fetchrow("""
        SELECT *
        FROM game_sessions
        WHERE id=$1
    """, session_id)


async def session_players(session_id):
    return await db_fetch("""
        SELECT *
        FROM game_players
        WHERE session_id=$1
    """, session_id)


async def join_session(session_id, user_id, state=None):
    return await db_execute("""
        INSERT INTO game_players(
            session_id,user_id,state
        )
        VALUES($1,$2,$3::jsonb)
        ON CONFLICT(session_id,user_id)
        DO UPDATE SET state=EXCLUDED.state
    """, session_id, user_id, json_dump(state or {}))


async def close_session(session_id):
    return await db_execute("""
        UPDATE game_sessions
        SET status='closed'
        WHERE id=$1
    """, session_id)


# ============================================================
# PREFIX
# ============================================================

async def set_prefix(guild_id, prefix=","):
    prefix = prefix or ","

    return await db_execute("""
        INSERT INTO guild_settings(
            guild_id,prefix,updated_at
        )
        VALUES($1,$2,NOW())
        ON CONFLICT(guild_id)
        DO UPDATE SET
            prefix=EXCLUDED.prefix,
            updated_at=NOW()
    """, guild_id, prefix)


async def get_prefix(guild_id):
    value = await db_fetchval("""
        SELECT prefix
        FROM guild_settings
        WHERE guild_id=$1
    """, guild_id)

    return value or ","


async def all_prefixes():
    return await db_fetch("""
        SELECT guild_id,prefix
        FROM guild_settings
        ORDER BY guild_id
    """)


# ============================================================
# WARNINGS
# ============================================================

async def create_warning(
    guild_id,
    user_id,
    moderator_id,
    reason,
    evidence="Not provided",
):
    """Create a warning and return (case_code, total_warning_count).

    This return contract matches bot.py's ,warn command.
    Returns (None, 0) on database failure so the caller can fail safely.
    """
    row = await db_fetchrow("""
        INSERT INTO warnings(
            guild_id, user_id, moderator_id, reason, evidence
        )
        VALUES($1,$2,$3,$4,$5)
        RETURNING id
    """, guild_id, user_id, moderator_id, reason, evidence)

    if not row:
        return None, 0

    warning_id = int(row["id"])
    count = await db_fetchval("""
        SELECT COUNT(*)
        FROM warnings
        WHERE guild_id=$1 AND user_id=$2
    """, guild_id, user_id)

    if count is None:
        return f"AC-W{warning_id:04d}", 0
    return f"AC-W{warning_id:04d}", int(count)


async def get_warnings(guild_id, user_id):
    return await db_fetch("""
        SELECT *, ('AC-W' || LPAD(id::text, 4, '0')) AS case_code
        FROM warnings
        WHERE guild_id=$1 AND user_id=$2
        ORDER BY created_at DESC
    """, guild_id, user_id)


async def delete_warning(guild_id, warning_id):
    return await db_execute("""
        DELETE FROM warnings
        WHERE guild_id=$1 AND id=$2
    """, guild_id, warning_id)


# ============================================================
# COMMAND LOGGING
# ============================================================

async def log_command(
    guild_id,
    user_id,
    username,
    command_name,
    command_type="prefix",
    arguments="",
    channel_id=None,
    channel_name=None,
    success=True,
    error_message=None,
    execution_time_ms=0,
):
    return await db_execute("""
        INSERT INTO command_logs(
            guild_id,
            user_id,
            username,
            command_name,
            command_type,
            arguments,
            channel_id,
            channel_name,
            success,
            error_message,
            execution_time_ms
        )
        VALUES(
            $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11
        )
    """,
        guild_id,
        user_id,
        username,
        command_name,
        command_type,
        arguments,
        channel_id,
        channel_name,
        success,
        error_message,
        execution_time_ms,
    )


async def get_command_history(guild_id, limit=50):
    limit = max(1, min(int(limit), 500))

    return await db_fetch("""
        SELECT *
        FROM command_logs
        WHERE guild_id=$1
        ORDER BY created_at DESC
        LIMIT $2
    """, guild_id, limit)


async def get_user_command_stats(guild_id, user_id):
    return await db_fetch("""
        SELECT
            command_name,
            COUNT(*) AS uses,
            SUM(
                CASE WHEN success THEN 1 ELSE 0 END
            ) AS successful,
            SUM(
                CASE WHEN success THEN 0 ELSE 1 END
            ) AS failed
        FROM command_logs
        WHERE guild_id=$1 AND user_id=$2
        GROUP BY command_name
        ORDER BY uses DESC
    """, guild_id, user_id)


async def get_most_used_commands(guild_id, limit=10):
    limit = max(1, min(int(limit), 100))

    return await db_fetch("""
        SELECT
            command_name,
            COUNT(*) AS uses
        FROM command_logs
        WHERE guild_id=$1
        GROUP BY command_name
        ORDER BY uses DESC
        LIMIT $2
    """, guild_id, limit)


async def get_failed_commands(guild_id, limit=50):
    limit = max(1, min(int(limit), 500))

    return await db_fetch("""
        SELECT *
        FROM command_logs
        WHERE guild_id=$1
          AND success=FALSE
        ORDER BY created_at DESC
        LIMIT $2
    """, guild_id, limit)


async def clear_old_logs(days=30):
    days = max(1, int(days))

    return await db_execute("""
        DELETE FROM command_logs
        WHERE created_at < NOW() - ($1 * INTERVAL '1 day')
    """, days)


# ============================================================
# COMMAND LOG DECORATORS
# ============================================================

def log_prefix_command(func):
    @wraps(func)
    async def wrapper(ctx, *args, **kwargs):
        started = time.perf_counter()
        success = True
        error_message = None

        try:
            return await func(ctx, *args, **kwargs)

        except Exception as exc:
            success = False
            error_message = str(exc)
            raise

        finally:
            elapsed = (time.perf_counter() - started) * 1000

            try:
                guild_id = ctx.guild.id if ctx.guild else 0
                user_id = ctx.author.id
                username = str(ctx.author)
                command_name = (
                    ctx.command.qualified_name
                    if ctx.command
                    else "unknown"
                )
                channel_id = ctx.channel.id if ctx.channel else None
                channel_name = (
                    getattr(ctx.channel, "name", None)
                    if ctx.channel
                    else None
                )

                await log_command(
                    guild_id,
                    user_id,
                    username,
                    command_name,
                    "prefix",
                    "",
                    channel_id,
                    channel_name,
                    success,
                    error_message,
                    elapsed,
                )
            except Exception:
                pass

    return wrapper


def log_slash_command(func):
    @wraps(func)
    async def wrapper(interaction, *args, **kwargs):
        started = time.perf_counter()
        success = True
        error_message = None

        try:
            return await func(interaction, *args, **kwargs)

        except Exception as exc:
            success = False
            error_message = str(exc)
            raise

        finally:
            elapsed = (time.perf_counter() - started) * 1000

            try:
                guild_id = interaction.guild.id if interaction.guild else 0
                user_id = interaction.user.id
                username = str(interaction.user)

                command_name = "unknown"

                if interaction.command:
                    command_name = interaction.command.qualified_name

                channel_id = (
                    interaction.channel.id
                    if interaction.channel
                    else None
                )

                channel_name = (
                    getattr(interaction.channel, "name", None)
                    if interaction.channel
                    else None
                )

                await log_command(
                    guild_id,
                    user_id,
                    username,
                    command_name,
                    "slash",
                    "",
                    channel_id,
                    channel_name,
                    success,
                    error_message,
                    elapsed,
                )

            except Exception:
                pass

    return wrapper


# ============================================================
# WELCOME
# ============================================================

async def save_welcome_config(guild_id, config):
    config = config or {}

    return await db_execute("""
        INSERT INTO welcome_config(
            guild_id,
            enabled,
            channel_id,
            message,
            embed_enabled,
            embed_title,
            embed_description,
            embed_color,
            image_url,
            thumbnail_url,
            footer,
            dm_enabled,
            dm_message,
            autorole_id,
            data,
            updated_at
        )
        VALUES(
            $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,
            $11,$12,$13,$14,$15::jsonb,NOW()
        )
        ON CONFLICT(guild_id)
        DO UPDATE SET
            enabled=EXCLUDED.enabled,
            channel_id=EXCLUDED.channel_id,
            message=EXCLUDED.message,
            embed_enabled=EXCLUDED.embed_enabled,
            embed_title=EXCLUDED.embed_title,
            embed_description=EXCLUDED.embed_description,
            embed_color=EXCLUDED.embed_color,
            image_url=EXCLUDED.image_url,
            thumbnail_url=EXCLUDED.thumbnail_url,
            footer=EXCLUDED.footer,
            dm_enabled=EXCLUDED.dm_enabled,
            dm_message=EXCLUDED.dm_message,
            autorole_id=EXCLUDED.autorole_id,
            data=EXCLUDED.data,
            updated_at=NOW()
    """,
        guild_id,
        config.get("enabled", False),
        config.get("channel_id"),
        config.get("message"),
        config.get("embed_enabled", True),
        config.get("embed_title"),
        config.get("embed_description"),
        config.get("embed_color", 5793266),
        config.get("image_url"),
        config.get("thumbnail_url"),
        config.get("footer"),
        config.get("dm_enabled", False),
        config.get("dm_message"),
        config.get("autorole_id"),
        json_dump(config.get("data", {})),
    )


async def get_welcome_config(guild_id):
    row = await db_fetchrow("""
        SELECT *
        FROM welcome_config
        WHERE guild_id=$1
    """, guild_id)

    if not row:
        return None

    result = dict(row)
    result["data"] = json_load(result.get("data"), {})
    return result


# ============================================================
# SELFROLE
# ============================================================

async def create_selfrole_panel(
    guild_id,
    channel_id=None,
    message_id=None,
    title=None,
    description=None,
    panel_type="button",
    data=None,
):
    return await db_fetchrow("""
        INSERT INTO selfrole_panels(
            guild_id,
            channel_id,
            message_id,
            title,
            description,
            panel_type,
            data
        )
        VALUES($1,$2,$3,$4,$5,$6,$7::jsonb)
        RETURNING *
    """,
        guild_id,
        channel_id,
        message_id,
        title,
        description,
        panel_type,
        json_dump(data or {}),
    )


async def add_selfrole_entry(
    panel_id,
    guild_id,
    role_id,
    label=None,
    emoji=None,
    description=None,
    custom_id=None,
):
    return await db_fetchrow("""
        INSERT INTO selfrole_entries(
            panel_id,
            guild_id,
            role_id,
            label,
            emoji,
            description,
            custom_id
        )
        VALUES($1,$2,$3,$4,$5,$6,$7)
        RETURNING *
    """,
        panel_id,
        guild_id,
        role_id,
        label,
        emoji,
        description,
        custom_id,
    )


async def get_selfrole_panels(guild_id):
    return await db_fetch("""
        SELECT *
        FROM selfrole_panels
        WHERE guild_id=$1
        ORDER BY id
    """, guild_id)


async def get_selfrole_entries(panel_id):
    return await db_fetch("""
        SELECT *
        FROM selfrole_entries
        WHERE panel_id=$1
        ORDER BY id
    """, panel_id)


# ============================================================
# TICKETS
# ============================================================

async def save_ticket_config(guild_id, config):
    config = config or {}

    return await db_execute("""
        INSERT INTO ticket_config(
            guild_id,
            support_role_id,
            log_channel_id,
            ticket_category_id,
            transcript_enabled,
            naming_format,
            panel_channel_id,
            panel_message_id,
            enabled,
            data,
            updated_at
        )
        VALUES(
            $1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,NOW()
        )
        ON CONFLICT(guild_id)
        DO UPDATE SET
            support_role_id=EXCLUDED.support_role_id,
            log_channel_id=EXCLUDED.log_channel_id,
            ticket_category_id=EXCLUDED.ticket_category_id,
            transcript_enabled=EXCLUDED.transcript_enabled,
            naming_format=EXCLUDED.naming_format,
            panel_channel_id=EXCLUDED.panel_channel_id,
            panel_message_id=EXCLUDED.panel_message_id,
            enabled=EXCLUDED.enabled,
            data=EXCLUDED.data,
            updated_at=NOW()
    """,
        guild_id,
        config.get("support_role_id"),
        config.get("log_channel_id"),
        config.get("ticket_category_id"),
        config.get("transcript_enabled", True),
        config.get("naming_format", "ticket-{username}"),
        config.get("panel_channel_id"),
        config.get("panel_message_id"),
        config.get("enabled", True),
        json_dump(config.get("data", {})),
    )


async def get_ticket_config(guild_id):
    row = await db_fetchrow("""
        SELECT *
        FROM ticket_config
        WHERE guild_id=$1
    """, guild_id)

    if not row:
        return None

    result = dict(row)
    result["data"] = json_load(result.get("data"), {})
    return result


async def add_ticket_category(
    guild_id,
    category_key,
    name,
    emoji=None,
    description=None,
    support_role_id=None,
    channel_category_id=None,
    data=None,
):
    return await db_fetchrow("""
        INSERT INTO ticket_categories(
            guild_id,
            category_key,
            name,
            emoji,
            description,
            support_role_id,
            channel_category_id,
            data
        )
        VALUES($1,$2,$3,$4,$5,$6,$7,$8::jsonb)
        ON CONFLICT(guild_id,category_key)
        DO UPDATE SET
            name=EXCLUDED.name,
            emoji=EXCLUDED.emoji,
            description=EXCLUDED.description,
            support_role_id=EXCLUDED.support_role_id,
            channel_category_id=EXCLUDED.channel_category_id,
            data=EXCLUDED.data
        RETURNING *
    """,
        guild_id,
        category_key,
        name,
        emoji,
        description,
        support_role_id,
        channel_category_id,
        json_dump(data or {}),
    )


async def get_ticket_categories(guild_id):
    return await db_fetch("""
        SELECT *
        FROM ticket_categories
        WHERE guild_id=$1 AND enabled=TRUE
        ORDER BY id
    """, guild_id)


async def create_ticket(
    guild_id,
    user_id,
    channel_id,
    category_key=None,
):
    return await db_fetchrow("""
        INSERT INTO tickets(
            guild_id,
            channel_id,
            user_id,
            category_key
        )
        VALUES($1,$2,$3,$4)
        RETURNING *
    """,
        guild_id,
        channel_id,
        user_id,
        category_key,
    )


async def get_open_ticket(guild_id, user_id):
    return await db_fetchrow("""
        SELECT *
        FROM tickets
        WHERE guild_id=$1
          AND user_id=$2
          AND status='open'
        ORDER BY created_at DESC
        LIMIT 1
    """, guild_id, user_id)


async def get_ticket_by_channel(channel_id):
    return await db_fetchrow("""
        SELECT *
        FROM tickets
        WHERE channel_id=$1
        ORDER BY created_at DESC
        LIMIT 1
    """, channel_id)


async def close_ticket(channel_id):
    return await db_execute("""
        UPDATE tickets
        SET status='closed',
            closed_at=NOW()
        WHERE channel_id=$1
          AND status='open'
    """, channel_id)


# ============================================================
# YOUTUBE ALERTS
# ============================================================

async def save_youtube_config(guild_id, config):
    config = config or {}

    return await db_execute("""
        INSERT INTO youtube_config(
            guild_id,
            enabled,
            alert_channel_id,
            role_id,
            message_template,
            data,
            updated_at
        )
        VALUES($1,$2,$3,$4,$5,$6::jsonb,NOW())
        ON CONFLICT(guild_id)
        DO UPDATE SET
            enabled=EXCLUDED.enabled,
            alert_channel_id=EXCLUDED.alert_channel_id,
            role_id=EXCLUDED.role_id,
            message_template=EXCLUDED.message_template,
            data=EXCLUDED.data,
            updated_at=NOW()
    """,
        guild_id,
        config.get("enabled", False),
        config.get("alert_channel_id"),
        config.get("role_id"),
        config.get("message_template"),
        json_dump(config.get("data", {})),
    )


async def get_youtube_config(guild_id):
    row = await db_fetchrow("""
        SELECT *
        FROM youtube_config
        WHERE guild_id=$1
    """, guild_id)

    if not row:
        return None

    result = dict(row)
    result["data"] = json_load(result.get("data"), {})
    return result


async def add_youtube_channel(
    guild_id,
    channel_key,
    channel_name=None,
    channel_url=None,
    channel_id=None,
    data=None,
):
    return await db_fetchrow("""
        INSERT INTO youtube_channels(
            guild_id,
            channel_key,
            channel_name,
            channel_url,
            channel_id,
            data
        )
        VALUES($1,$2,$3,$4,$5,$6::jsonb)
        ON CONFLICT(guild_id,channel_key)
        DO UPDATE SET
            channel_name=EXCLUDED.channel_name,
            channel_url=EXCLUDED.channel_url,
            channel_id=EXCLUDED.channel_id,
            data=EXCLUDED.data
        RETURNING *
    """,
        guild_id,
        channel_key,
        channel_name,
        channel_url,
        channel_id,
        json_dump(data or {}),
    )


async def get_youtube_channels(guild_id):
    return await db_fetch("""
        SELECT *
        FROM youtube_channels
        WHERE guild_id=$1
        ORDER BY id
    """, guild_id)


async def remove_youtube_channel(guild_id, channel_key):
    return await db_execute("""
        DELETE FROM youtube_channels
        WHERE guild_id=$1 AND channel_key=$2
    """, guild_id, channel_key)


async def update_youtube_last_video(guild_id, channel_key, video_id):
    return await db_execute("""
        UPDATE youtube_channels
        SET last_video_id=$3
        WHERE guild_id=$1 AND channel_key=$2
    """, guild_id, channel_key, video_id)


# ============================================================
# GIVEAWAYS
# ============================================================

async def create_giveaway(
    guild_id,
    channel_id,
    message_id,
    host_id,
    prize,
    winner_count=1,
    ends_at=None,
    requirements=None,
):
    return await db_fetchrow("""
        INSERT INTO giveaways(
            guild_id,
            channel_id,
            message_id,
            host_id,
            prize,
            winner_count,
            ends_at,
            requirements
        )
        VALUES($1,$2,$3,$4,$5,$6,$7,$8::jsonb)
        RETURNING *
    """,
        guild_id,
        channel_id,
        message_id,
        host_id,
        prize,
        winner_count,
        ends_at,
        json_dump(requirements or {}),
    )


async def join_giveaway(giveaway_id, user_id):
    return await db_execute("""
        INSERT INTO giveaway_entries(
            giveaway_id,user_id
        )
        VALUES($1,$2)
        ON CONFLICT(giveaway_id,user_id)
        DO NOTHING
    """, giveaway_id, user_id)


async def get_giveaway_entries(giveaway_id):
    return await db_fetch("""
        SELECT user_id,joined_at
        FROM giveaway_entries
        WHERE giveaway_id=$1
        ORDER BY joined_at
    """, giveaway_id)


async def end_giveaway(giveaway_id, winners):
    return await db_execute("""
        UPDATE giveaways
        SET status='ended',
            winners=$2::jsonb
        WHERE id=$1
    """, giveaway_id, json_dump(winners or []))


# ============================================================
# LEVELING CONFIG
# ============================================================

async def save_leveling_config(guild_id, config):
    config = config or {}

    return await db_execute("""
        INSERT INTO leveling_config(
            guild_id,
            enabled,
            xp_min,
            xp_max,
            cooldown_seconds,
            levelup_channel_id,
            levelup_message,
            announce_levelup,
            stack_rewards,
            data,
            updated_at
        )
        VALUES(
            $1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,NOW()
        )
        ON CONFLICT(guild_id)
        DO UPDATE SET
            enabled=EXCLUDED.enabled,
            xp_min=EXCLUDED.xp_min,
            xp_max=EXCLUDED.xp_max,
            cooldown_seconds=EXCLUDED.cooldown_seconds,
            levelup_channel_id=EXCLUDED.levelup_channel_id,
            levelup_message=EXCLUDED.levelup_message,
            announce_levelup=EXCLUDED.announce_levelup,
            stack_rewards=EXCLUDED.stack_rewards,
            data=EXCLUDED.data,
            updated_at=NOW()
    """,
        guild_id,
        config.get("enabled", True),
        config.get("xp_min", 15),
        config.get("xp_max", 30),
        config.get("cooldown_seconds", 60),
        config.get("levelup_channel_id"),
        config.get("levelup_message"),
        config.get("announce_levelup", True),
        config.get("stack_rewards", False),
        json_dump(config.get("data", {})),
    )


async def get_leveling_config(guild_id):
    row = await db_fetchrow("""
        SELECT *
        FROM leveling_config
        WHERE guild_id=$1
    """, guild_id)

    if not row:
        return None

    result = dict(row)
    result["data"] = json_load(result.get("data"), {})
    return result


async def add_level_reward(
    guild_id,
    level,
    role_id,
    remove_previous=False,
    data=None,
):
    return await db_execute("""
        INSERT INTO level_rewards(
            guild_id,
            level,
            role_id,
            remove_previous,
            data
        )
        VALUES($1,$2,$3,$4,$5::jsonb)
        ON CONFLICT(guild_id,level,role_id)
        DO UPDATE SET
            remove_previous=EXCLUDED.remove_previous,
            data=EXCLUDED.data
    """,
        guild_id,
        level,
        role_id,
        remove_previous,
        json_dump(data or {}),
    )


async def get_level_rewards(guild_id):
    return await db_fetch("""
        SELECT *
        FROM level_rewards
        WHERE guild_id=$1
        ORDER BY level ASC
    """, guild_id)


async def add_xp_booster(
    guild_id,
    target_type,
    target_id,
    multiplier,
    enabled=True,
    data=None,
):
    return await db_execute("""
        INSERT INTO xp_boosters(
            guild_id,
            target_type,
            target_id,
            multiplier,
            enabled,
            data
        )
        VALUES($1,$2,$3,$4,$5,$6::jsonb)
        ON CONFLICT(guild_id,target_type,target_id)
        DO UPDATE SET
            multiplier=EXCLUDED.multiplier,
            enabled=EXCLUDED.enabled,
            data=EXCLUDED.data
    """,
        guild_id,
        target_type,
        target_id,
        multiplier,
        enabled,
        json_dump(data or {}),
    )


async def get_xp_boosters(guild_id):
    return await db_fetch("""
        SELECT *
        FROM xp_boosters
        WHERE guild_id=$1 AND enabled=TRUE
        ORDER BY id
    """, guild_id)


# ============================================================
# AUTOMATION / AUTOMODE
# ============================================================

async def save_automation_config(guild_id, config):
    config = config or {}

    return await db_execute("""
        INSERT INTO automation_config(
            guild_id,
            enabled,
            log_channel_id,
            spam_enabled,
            spam_limit,
            spam_window_seconds,
            warning_limit,
            timeout_limit,
            timeout_minutes,
            mention_limit,
            duplicate_limit,
            link_protection,
            data,
            updated_at
        )
        VALUES(
            $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13::jsonb,NOW()
        )
        ON CONFLICT(guild_id)
        DO UPDATE SET
            enabled=EXCLUDED.enabled,
            log_channel_id=EXCLUDED.log_channel_id,
            spam_enabled=EXCLUDED.spam_enabled,
            spam_limit=EXCLUDED.spam_limit,
            spam_window_seconds=EXCLUDED.spam_window_seconds,
            warning_limit=EXCLUDED.warning_limit,
            timeout_limit=EXCLUDED.timeout_limit,
            timeout_minutes=EXCLUDED.timeout_minutes,
            mention_limit=EXCLUDED.mention_limit,
            duplicate_limit=EXCLUDED.duplicate_limit,
            link_protection=EXCLUDED.link_protection,
            data=EXCLUDED.data,
            updated_at=NOW()
    """,
        guild_id,
        config.get("enabled", False),
        config.get("log_channel_id"),
        config.get("spam_enabled", True),
        config.get("spam_limit", 5),
        config.get("spam_window_seconds", 7),
        config.get("warning_limit", 3),
        config.get("timeout_limit", 5),
        config.get("timeout_minutes", 10),
        config.get("mention_limit", 5),
        config.get("duplicate_limit", 3),
        config.get("link_protection", True),
        json_dump(config.get("data", {})),
    )


async def get_automation_config(guild_id):
    row = await db_fetchrow("""
        SELECT *
        FROM automation_config
        WHERE guild_id=$1
    """, guild_id)

    if not row:
        return None

    result = dict(row)
    result["data"] = json_load(result.get("data"), {})
    return result


async def add_automation_whitelist(
    guild_id,
    target_type,
    target_id,
):
    return await db_execute("""
        INSERT INTO automation_whitelist(
            guild_id,target_type,target_id
        )
        VALUES($1,$2,$3)
        ON CONFLICT(guild_id,target_type,target_id)
        DO NOTHING
    """, guild_id, target_type, target_id)


async def remove_automation_whitelist(
    guild_id,
    target_type,
    target_id,
):
    return await db_execute("""
        DELETE FROM automation_whitelist
        WHERE guild_id=$1
          AND target_type=$2
          AND target_id=$3
    """, guild_id, target_type, target_id)


async def get_automation_whitelist(guild_id):
    return await db_fetch("""
        SELECT *
        FROM automation_whitelist
        WHERE guild_id=$1
        ORDER BY created_at
    """, guild_id)


# ============================================================
# ANTINUKE
# ============================================================

async def save_antinuke_config(guild_id, config):
    config = config or {}

    return await db_execute("""
        INSERT INTO antinuke_config(
            guild_id,
            enabled,
            log_channel_id,
            punishment,
            extra_owners,
            whitelist,
            thresholds,
            animation_enabled,
            data,
            updated_at
        )
        VALUES(
            $1,$2,$3,$4,$5::jsonb,$6::jsonb,$7::jsonb,$8,$9::jsonb,NOW()
        )
        ON CONFLICT(guild_id)
        DO UPDATE SET
            enabled=EXCLUDED.enabled,
            log_channel_id=EXCLUDED.log_channel_id,
            punishment=EXCLUDED.punishment,
            extra_owners=EXCLUDED.extra_owners,
            whitelist=EXCLUDED.whitelist,
            thresholds=EXCLUDED.thresholds,
            animation_enabled=EXCLUDED.animation_enabled,
            data=EXCLUDED.data,
            updated_at=NOW()
    """,
        guild_id,
        config.get("enabled", False),
        config.get("log_channel_id"),
        config.get("punishment", "ban"),
        json_dump(config.get("extra_owners", [])),
        json_dump(config.get("whitelist", [])),
        json_dump(config.get("thresholds", {})),
        config.get("animation_enabled", False),
        json_dump(config.get("data", {})),
    )


async def get_antinuke_config(guild_id):
    row = await db_fetchrow("""
        SELECT *
        FROM antinuke_config
        WHERE guild_id=$1
    """, guild_id)

    if not row:
        return None

    result = dict(row)

    for key in (
        "extra_owners",
        "whitelist",
        "thresholds",
        "data",
    ):
        result[key] = json_load(result.get(key), [])

    return result


# ============================================================
# SECURITY
# ============================================================

async def save_security_config(guild_id, config):
    config = config or {}

    return await db_execute("""
        INSERT INTO security_config(
            guild_id,
            enabled,
            log_channel_id,
            anti_link,
            anti_invite,
            anti_gif,
            anti_youtube,
            anti_mass_mention,
            punishment,
            data,
            updated_at
        )
        VALUES(
            $1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,NOW()
        )
        ON CONFLICT(guild_id)
        DO UPDATE SET
            enabled=EXCLUDED.enabled,
            log_channel_id=EXCLUDED.log_channel_id,
            anti_link=EXCLUDED.anti_link,
            anti_invite=EXCLUDED.anti_invite,
            anti_gif=EXCLUDED.anti_gif,
            anti_youtube=EXCLUDED.anti_youtube,
            anti_mass_mention=EXCLUDED.anti_mass_mention,
            punishment=EXCLUDED.punishment,
            data=EXCLUDED.data,
            updated_at=NOW()
    """,
        guild_id,
        config.get("enabled", False),
        config.get("log_channel_id"),
        config.get("anti_link", False),
        config.get("anti_invite", False),
        config.get("anti_gif", False),
        config.get("anti_youtube", False),
        config.get("anti_mass_mention", False),
        config.get("punishment", "delete"),
        json_dump(config.get("data", {})),
    )


async def get_security_config(guild_id):
    row = await db_fetchrow("""
        SELECT *
        FROM security_config
        WHERE guild_id=$1
    """, guild_id)

    if not row:
        return None

    result = dict(row)
    result["data"] = json_load(result.get("data"), {})
    return result


async def add_security_whitelist(
    guild_id,
    target_type,
    target_id,
):
    return await db_execute("""
        INSERT INTO security_whitelist(
            guild_id,target_type,target_id
        )
        VALUES($1,$2,$3)
        ON CONFLICT(guild_id,target_type,target_id)
        DO NOTHING
    """, guild_id, target_type, target_id)


async def remove_security_whitelist(
    guild_id,
    target_type,
    target_id,
):
    return await db_execute("""
        DELETE FROM security_whitelist
        WHERE guild_id=$1
          AND target_type=$2
          AND target_id=$3
    """, guild_id, target_type, target_id)


async def get_security_whitelist(guild_id):
    return await db_fetch("""
        SELECT *
        FROM security_whitelist
        WHERE guild_id=$1
        ORDER BY created_at
    """, guild_id)


# ============================================================
# SNIPE
# ============================================================

async def save_snipe_message(
    guild_id,
    channel_id,
    message_id,
    author_id,
    author_name,
    content,
    attachments=None,
):
    return await db_fetchrow("""
        INSERT INTO snipe_messages(
            guild_id,
            channel_id,
            message_id,
            author_id,
            author_name,
            content,
            attachments
        )
        VALUES($1,$2,$3,$4,$5,$6,$7::jsonb)
        RETURNING *
    """,
        guild_id,
        channel_id,
        message_id,
        author_id,
        author_name,
        content,
        json_dump(attachments or []),
    )


async def get_latest_snipe(guild_id, channel_id):
    row = await db_fetchrow("""
        SELECT *
        FROM snipe_messages
        WHERE guild_id=$1 AND channel_id=$2
        ORDER BY deleted_at DESC
        LIMIT 1
    """, guild_id, channel_id)

    if not row:
        return None

    result = dict(row)
    result["attachments"] = json_load(
        result.get("attachments"),
        [],
    )

    return result


async def get_snipes(guild_id, channel_id, limit=10):
    limit = max(1, min(int(limit), 100))

    rows = await db_fetch("""
        SELECT *
        FROM snipe_messages
        WHERE guild_id=$1 AND channel_id=$2
        ORDER BY deleted_at DESC
        LIMIT $3
    """, guild_id, channel_id, limit)

    result = []

    for row in rows:
        item = dict(row)
        item["attachments"] = json_load(
            item.get("attachments"),
            [],
        )
        result.append(item)

    return result


async def cleanup_snipes(hours=24):
    hours = max(1, int(hours))

    return await db_execute("""
        DELETE FROM snipe_messages
        WHERE deleted_at < NOW() - ($1 * INTERVAL '1 hour')
    """, hours)


# ============================================================
# CUSTOM COMMANDS
# ============================================================

async def save_custom_command(
    guild_id,
    name,
    response=None,
    embed_data=None,
    creator_id=None,
    enabled=True,
):
    return await db_fetchrow("""
        INSERT INTO custom_commands(
            guild_id,
            name,
            response,
            embed_data,
            enabled,
            creator_id,
            updated_at
        )
        VALUES($1,$2,$3,$4::jsonb,$5,$6,NOW())
        ON CONFLICT(guild_id,name)
        DO UPDATE SET
            response=EXCLUDED.response,
            embed_data=EXCLUDED.embed_data,
            enabled=EXCLUDED.enabled,
            updated_at=NOW()
        RETURNING *
    """,
        guild_id,
        name,
        response,
        json_dump(embed_data or {}),
        enabled,
        creator_id,
    )


async def get_custom_command(guild_id, name):
    row = await db_fetchrow("""
        SELECT *
        FROM custom_commands
        WHERE guild_id=$1
          AND LOWER(name)=LOWER($2)
    """, guild_id, name)

    if not row:
        return None

    result = dict(row)
    result["embed_data"] = json_load(
        result.get("embed_data"),
        {},
    )

    return result


async def get_custom_commands(guild_id):
    rows = await db_fetch("""
        SELECT *
        FROM custom_commands
        WHERE guild_id=$1
        ORDER BY name
    """, guild_id)

    result = []

    for row in rows:
        item = dict(row)
        item["embed_data"] = json_load(
            item.get("embed_data"),
            {},
        )
        result.append(item)

    return result


async def delete_custom_command(guild_id, name):
    return await db_execute("""
        DELETE FROM custom_commands
        WHERE guild_id=$1
          AND LOWER(name)=LOWER($2)
    """, guild_id, name)


# ============================================================
# DATABASE STATUS
# ============================================================

async def database_status():
    if not _pool:
        return {
            "connected": False,
            "pool": False,
        }

    try:
        result = await _pool.fetchval("SELECT 1")

        return {
            "connected": result == 1,
            "pool": True,
        }

    except Exception as exc:
        return {
            "connected": False,
            "pool": True,
            "error": str(exc),
        }


# ============================================================
# CLOSE DATABASE
# ============================================================

async def close_db():
    global _pool

    if _pool:
        try:
            await _pool.close()
            print("🗄️ PostgreSQL connection pool closed.")
        except Exception as exc:
            print(f"⚠️ DB close error: {exc}")
        finally:
            _pool = None


# ============================================================
# OPTIONAL BOT HOOK
# ============================================================

# Kept intentionally lightweight.
# Database initialization should be called explicitly from bot.py.
#
# Example:
#
# async def on_ready():
#     if not getattr(bot, "_air_db_initialized", False):
#         if await db.init_db():
#             bot._air_db_initialized = True
#
# This avoids circular imports and duplicate module setup.
# ============================================================
