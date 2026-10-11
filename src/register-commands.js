const { REST, Routes } = require("discord.js");
const { loadConfig } = require("./config");
const { commandData } = require("./commands");

async function main() {
  const config = loadConfig();
  const rest = new REST({ version: "10" }).setToken(config.token);
  const route = config.guildId
    ? Routes.applicationGuildCommands(config.clientId, config.guildId)
    : Routes.applicationCommands(config.clientId);
  await rest.put(route, { body: commandData });
  console.log(`Registered giveaway slash commands${config.guildId ? ` for guild ${config.guildId}` : " globally"}.`);
}

main().catch((error) => {
  console.error("Could not register commands:", error.message);
  process.exitCode = 1;
});
