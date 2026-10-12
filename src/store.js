const { Pool } = require("pg");

function createStore({ connectionString, ssl }) {
  const pool = new Pool({
    connectionString,
    ssl: ssl ? { rejectUnauthorized: false } : undefined,
    max: 5,
    idleTimeoutMillis: 30_000,
    connectionTimeoutMillis: 10_000,
  });

  pool.on("error", (error) => {
    console.error("Unexpected PostgreSQL pool error:", error.message);
  });

  async function initialize() {
    await pool.query(`
      CREATE TABLE IF NOT EXISTS giveaways (
        id BIGSERIAL PRIMARY KEY,
        guild_id TEXT NOT NULL,
        channel_id TEXT NOT NULL,
        message_id TEXT NOT NULL UNIQUE,
        host_id TEXT NOT NULL,
        prize TEXT NOT NULL,
        winner_count INTEGER NOT NULL CHECK (winner_count BETWEEN 1 AND 20),
        required_role_id TEXT,
        bonus_role_id TEXT,
        ends_at TIMESTAMPTZ NOT NULL,
        status TEXT NOT NULL DEFAULT 'active'
          CHECK (status IN ('active', 'paused', 'ended', 'cancelled')),
        paused_remaining_ms BIGINT,
        winner_ids TEXT[] NOT NULL DEFAULT '{}',
        last_winner_ids TEXT[] NOT NULL DEFAULT '{}',
        last_draw_is_reroll BOOLEAN NOT NULL DEFAULT FALSE,
        announcement_sent_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        ended_at TIMESTAMPTZ
      );

      ALTER TABLE giveaways
        ADD COLUMN IF NOT EXISTS last_winner_ids TEXT[] NOT NULL DEFAULT '{}',
        ADD COLUMN IF NOT EXISTS last_draw_is_reroll BOOLEAN NOT NULL DEFAULT FALSE,
        ADD COLUMN IF NOT EXISTS announcement_sent_at TIMESTAMPTZ;

      CREATE INDEX IF NOT EXISTS giveaways_due_idx
        ON giveaways (ends_at) WHERE status = 'active';
      CREATE INDEX IF NOT EXISTS giveaways_guild_status_idx
        ON giveaways (guild_id, status, ends_at);

      CREATE TABLE IF NOT EXISTS giveaway_entries (
        giveaway_id BIGINT NOT NULL REFERENCES giveaways(id) ON DELETE CASCADE,
        user_id TEXT NOT NULL,
        weight INTEGER NOT NULL DEFAULT 1 CHECK (weight BETWEEN 1 AND 2),
        joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY (giveaway_id, user_id)
      );

      CREATE INDEX IF NOT EXISTS giveaway_entries_user_idx
        ON giveaway_entries (user_id);

      CREATE TABLE IF NOT EXISTS bot_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
      );
    `);
  }

  async function getSetting(key) {
    const result = await pool.query("SELECT value FROM bot_settings WHERE key = $1", [key]);
    return result.rows[0]?.value ?? null;
  }

  async function setSetting(key, value) {
    if (value === null || value === undefined || value === "") {
      await pool.query("DELETE FROM bot_settings WHERE key = $1", [key]);
      return;
    }
    await pool.query(
      `INSERT INTO bot_settings (key, value, updated_at)
       VALUES ($1, $2, NOW())
       ON CONFLICT (key) DO UPDATE
       SET value = EXCLUDED.value, updated_at = NOW()`,
      [key, String(value)],
    );
  }

  async function health() {
    await pool.query("SELECT 1");
    return true;
  }

  async function createGiveaway(data) {
    const result = await pool.query(
      `INSERT INTO giveaways
        (guild_id, channel_id, message_id, host_id, prize, winner_count,
         required_role_id, bonus_role_id, ends_at)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
       RETURNING *`,
      [
        data.guildId,
        data.channelId,
        data.messageId,
        data.hostId,
        data.prize,
        data.winnerCount,
        data.requiredRoleId,
        data.bonusRoleId,
        data.endsAt,
      ],
    );
    return result.rows[0];
  }

  async function getById(id) {
    const result = await pool.query("SELECT * FROM giveaways WHERE id = $1", [id]);
    return result.rows[0] ?? null;
  }

  async function getByMessage(guildId, messageId) {
    const result = await pool.query(
      "SELECT * FROM giveaways WHERE guild_id = $1 AND message_id = $2",
      [guildId, messageId],
    );
    return result.rows[0] ?? null;
  }

  async function join(id, userId, weight) {
    const client = await pool.connect();
    try {
      await client.query("BEGIN");
      const giveawayResult = await client.query(
        "SELECT status, ends_at FROM giveaways WHERE id = $1 FOR UPDATE",
        [id],
      );
      const giveaway = giveawayResult.rows[0];
      if (!giveaway) {
        await client.query("ROLLBACK");
        return "missing";
      }
      if (giveaway.status !== "active" || new Date(giveaway.ends_at) <= new Date()) {
        await client.query("ROLLBACK");
        return giveaway.status === "paused" ? "paused" : "closed";
      }

      const entry = await client.query(
        `INSERT INTO giveaway_entries (giveaway_id, user_id, weight)
         VALUES ($1, $2, $3)
         ON CONFLICT (giveaway_id, user_id) DO NOTHING
         RETURNING user_id`,
        [id, userId, weight],
      );
      await client.query("COMMIT");
      return entry.rowCount ? "joined" : "already";
    } catch (error) {
      await client.query("ROLLBACK").catch(() => {});
      throw error;
    } finally {
      client.release();
    }
  }

  async function leave(id, userId) {
    const client = await pool.connect();
    try {
      await client.query("BEGIN");
      const giveawayResult = await client.query(
        "SELECT status, ends_at FROM giveaways WHERE id = $1 FOR UPDATE",
        [id],
      );
      const giveaway = giveawayResult.rows[0];
      if (!giveaway) {
        await client.query("ROLLBACK");
        return "missing";
      }
      if (giveaway.status !== "active" || new Date(giveaway.ends_at) <= new Date()) {
        await client.query("ROLLBACK");
        return giveaway.status === "paused" ? "paused" : "closed";
      }
      const deleted = await client.query(
        "DELETE FROM giveaway_entries WHERE giveaway_id = $1 AND user_id = $2",
        [id, userId],
      );
      await client.query("COMMIT");
      return deleted.rowCount ? "left" : "not-entered";
    } catch (error) {
      await client.query("ROLLBACK").catch(() => {});
      throw error;
    } finally {
      client.release();
    }
  }

  async function entryCount(id) {
    const result = await pool.query(
      "SELECT COUNT(*)::integer AS count FROM giveaway_entries WHERE giveaway_id = $1",
      [id],
    );
    return result.rows[0].count;
  }

  async function listEntries(id, limit = 100) {
    const result = await pool.query(
      `SELECT user_id, weight, joined_at
       FROM giveaway_entries WHERE giveaway_id = $1
       ORDER BY joined_at ASC LIMIT $2`,
      [id, limit],
    );
    return result.rows;
  }

  async function listGuild(guildId, limit = 10) {
    const result = await pool.query(
      `SELECT * FROM giveaways
       WHERE guild_id = $1 AND status IN ('active', 'paused')
       ORDER BY ends_at ASC LIMIT $2`,
      [guildId, limit],
    );
    return result.rows;
  }

  async function pause(id) {
    const result = await pool.query(
      `UPDATE giveaways
       SET paused_remaining_ms = GREATEST(0, FLOOR(EXTRACT(EPOCH FROM (ends_at - NOW())) * 1000)),
           status = 'paused'
       WHERE id = $1 AND status = 'active'
       RETURNING *`,
      [id],
    );
    return result.rows[0] ?? null;
  }

  async function resume(id) {
    const result = await pool.query(
      `UPDATE giveaways
       SET ends_at = NOW() + (COALESCE(paused_remaining_ms, 0) * INTERVAL '1 millisecond'),
           paused_remaining_ms = NULL,
           status = 'active'
       WHERE id = $1 AND status = 'paused'
       RETURNING *`,
      [id],
    );
    return result.rows[0] ?? null;
  }

  async function cancel(id) {
    const result = await pool.query(
      `UPDATE giveaways SET status = 'cancelled', ended_at = NOW()
       WHERE id = $1 AND status IN ('active', 'paused') RETURNING *`,
      [id],
    );
    return result.rows[0] ?? null;
  }

  async function dueIds(limit = 50) {
    const result = await pool.query(
      `SELECT id FROM giveaways
       WHERE status = 'active' AND ends_at <= NOW()
       ORDER BY ends_at ASC LIMIT $1`,
      [limit],
    );
    return result.rows.map((row) => String(row.id));
  }

  async function pendingAnnouncements(limit = 50) {
    const result = await pool.query(
      `SELECT * FROM giveaways
       WHERE status = 'ended' AND announcement_sent_at IS NULL
       ORDER BY ended_at ASC NULLS FIRST LIMIT $1`,
      [limit],
    );
    return result.rows;
  }

  async function markAnnouncementSent(id) {
    await pool.query(
      "UPDATE giveaways SET announcement_sent_at = NOW() WHERE id = $1 AND status = 'ended'",
      [id],
    );
  }

  async function finish(id, winnerCount, pickWinners) {
    const client = await pool.connect();
    try {
      await client.query("BEGIN");
      const result = await client.query(
        "SELECT * FROM giveaways WHERE id = $1 FOR UPDATE",
        [id],
      );
      const giveaway = result.rows[0];
      if (!giveaway) {
        await client.query("ROLLBACK");
        return { state: "missing" };
      }
      if (giveaway.status !== "active") {
        await client.query("ROLLBACK");
        return { state: giveaway.status };
      }

      const entrantsResult = await client.query(
        "SELECT user_id, weight FROM giveaway_entries WHERE giveaway_id = $1",
        [id],
      );
      const entrants = entrantsResult.rows;
      const winners = pickWinners(entrants, winnerCount);
      const updated = await client.query(
        `UPDATE giveaways
         SET status = 'ended', ended_at = NOW(), winner_ids = $2,
             last_winner_ids = $2, last_draw_is_reroll = FALSE,
             announcement_sent_at = NULL
         WHERE id = $1
         RETURNING *`,
        [id, winners],
      );
      await client.query("COMMIT");
      return { state: "ended", giveaway: updated.rows[0], winners, entrantCount: entrants.length };
    } catch (error) {
      await client.query("ROLLBACK").catch(() => {});
      throw error;
    } finally {
      client.release();
    }
  }

  async function reroll(id, winnerCount, pickWinners) {
    const client = await pool.connect();
    try {
      await client.query("BEGIN");
      const result = await client.query(
        "SELECT * FROM giveaways WHERE id = $1 FOR UPDATE",
        [id],
      );
      const giveaway = result.rows[0];
      if (!giveaway) {
        await client.query("ROLLBACK");
        return { state: "missing" };
      }
      if (giveaway.status !== "ended") {
        await client.query("ROLLBACK");
        return { state: giveaway.status };
      }

      const entrantsResult = await client.query(
        "SELECT user_id, weight FROM giveaway_entries WHERE giveaway_id = $1",
        [id],
      );
      const priorWinners = new Set((giveaway.winner_ids ?? []).map(String));
      const winners = pickWinners(entrantsResult.rows, winnerCount, priorWinners);
      const updatedWinnerIds = [...priorWinners, ...winners];
      await client.query(
        `UPDATE giveaways
         SET winner_ids = $2, last_winner_ids = $3,
             last_draw_is_reroll = TRUE, announcement_sent_at = NULL
         WHERE id = $1`,
        [id, updatedWinnerIds, winners],
      );
      await client.query("COMMIT");
      return {
        state: "ended",
        giveaway,
        winners,
        entrantCount: entrantsResult.rowCount,
      };
    } catch (error) {
      await client.query("ROLLBACK").catch(() => {});
      throw error;
    } finally {
      client.release();
    }
  }

  async function close() {
    await pool.end();
  }

  return {
    cancel,
    close,
    createGiveaway,
    dueIds,
    entryCount,
    finish,
    getById,
    getByMessage,
    getSetting,
    health,
    initialize,
    join,
    leave,
    listEntries,
    listGuild,
    markAnnouncementSent,
    pause,
    pendingAnnouncements,
    reroll,
    resume,
    setSetting,
  };
}

module.exports = { createStore };
