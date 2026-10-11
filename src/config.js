require("dotenv").config();

function loadConfig() {
  const required = ["DISCORD_TOKEN", "CLIENT_ID", "DATABASE_URL"];
  const missing = required.filter((key) => !process.env[key]?.trim());
  if (missing.length) {
    throw new Error(`Missing required environment variable(s): ${missing.join(", ")}`);
  }

  return {
    token: process.env.DISCORD_TOKEN.trim(),
    clientId: process.env.CLIENT_ID.trim(),
    databaseUrl: process.env.DATABASE_URL.trim(),
    guildId: process.env.GUILD_ID?.trim() || null,
    pgSsl: process.env.PGSSL?.toLowerCase() === "true",
  };
}

module.exports = { loadConfig };
