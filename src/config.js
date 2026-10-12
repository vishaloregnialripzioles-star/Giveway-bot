require("dotenv").config();

function loadConfig() {
  const required = ["DISCORD_TOKEN", "CLIENT_ID"];
  const missing = required.filter((key) => !process.env[key]?.trim());
  if (missing.length) {
    throw new Error(`Missing required environment variable(s): ${missing.join(", ")}`);
  }

  return {
    token: process.env.DISCORD_TOKEN.trim(),
    clientId: process.env.CLIENT_ID.trim(),
    guildId: process.env.GUILD_ID?.trim() || null,
  };
}

module.exports = { loadConfig };
