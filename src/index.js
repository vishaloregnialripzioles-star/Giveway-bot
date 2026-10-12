require("node:dns").setDefaultResultOrder("ipv4first");

const http = require("node:http");
const {
  Client,
  Events,
  GatewayIntentBits,
  REST,
  Routes,
  SlashCommandBuilder,
} = require("discord.js");

const { loadConfig } = require("./config");

const commandData = [
  new SlashCommandBuilder()
    .setName("ping")
    .setDescription("Check whether the bot is online and responding")
    .toJSON(),
];

function createHealthServer(client) {
  return http.createServer((request, response) => {
    const pathname = new URL(request.url || "/", "http://localhost").pathname;
    response.setHeader("Cache-Control", "no-store");
    response.setHeader("Content-Type", "application/json; charset=utf-8");

    if (request.method !== "GET") {
      response.writeHead(405, { Allow: "GET" });
      response.end(JSON.stringify({ status: "method_not_allowed" }));
      return;
    }

    if (pathname === "/" || ["/health", "/healthz", "/ping"].includes(pathname)) {
      response.writeHead(200);
      response.end(JSON.stringify({
        status: "ok",
        service: "sparkxie-ping-bot",
        discord: client.isReady() ? "connected" : "connecting",
      }));
      return;
    }

    response.writeHead(404);
    response.end(JSON.stringify({ status: "not_found" }));
  });
}

function commandsMatch(current, desired) {
  if (!Array.isArray(current) || current.length !== desired.length) return false;
  const normalizeOption = (option) => {
    const normalized = {
      name: option.name,
      description: option.description,
      type: option.type,
      required: option.required === true,
    };
    if (Array.isArray(option.options) && option.options.length) {
      normalized.options = option.options.map(normalizeOption);
    }
    if (Array.isArray(option.choices) && option.choices.length) {
      normalized.choices = option.choices.map(({ name, value }) => ({ name, value }));
    }
    if (Array.isArray(option.channel_types) && option.channel_types.length) {
      normalized.channel_types = [...option.channel_types].sort((a, b) => a - b);
    }
    for (const key of ["min_value", "max_value", "min_length", "max_length"]) {
      if (option[key] !== undefined && option[key] !== null) normalized[key] = option[key];
    }
    if (option.autocomplete === true) normalized.autocomplete = true;
    return normalized;
  };
  const normalize = (command) => ({
    name: command.name,
    description: command.description,
    type: command.type ?? 1,
    options: (command.options ?? []).map(normalizeOption),
  });
  const currentByName = new Map(current.map((command) => [command.name, command]));
  return desired.every((command) => {
    const registered = currentByName.get(command.name);
    return registered && JSON.stringify(normalize(registered)) === JSON.stringify(normalize(command));
  });
}

async function registerCommands(config, client) {
  const rest = new REST({ version: "10" }).setToken(config.token);
  const guildIds = config.guildId
    ? [config.guildId]
    : [...new Set(client?.guilds?.cache?.keys?.() ?? [])];

  if (guildIds.length) {
    for (const guildId of guildIds) {
      const route = Routes.applicationGuildCommands(config.clientId, guildId);
      const existing = await rest.get(route);
      if (commandsMatch(existing, commandData)) {
        console.log("Slash commands already match: ping only (guild " + guildId + ").");
        continue;
      }
      await rest.put(route, { body: commandData });
      console.log("Registered only /ping for guild " + guildId + ".");
    }
    return;
  }

  const route = Routes.applicationCommands(config.clientId);
  const existing = await rest.get(route);
  if (!commandsMatch(existing, commandData)) {
    await rest.put(route, { body: commandData });
    console.log("Registered only the global /ping command.");
  } else {
    console.log("Global slash commands already match: ping only.");
  }
}

async function main() {
  const config = loadConfig();
  const client = new Client({
    intents: [GatewayIntentBits.Guilds],
    rest: { timeout: 15_000 },
  });

  const port = Number(process.env.PORT || 10000);
  const server = createHealthServer(client);
  server.on("error", (error) => console.error("Health server error:", error.message));
  server.listen(port, "0.0.0.0", () => {
    console.log("Health server listening on 0.0.0.0:" + port);
  });

  client.once(Events.ClientReady, async (readyClient) => {
    console.log("Logged in as " + readyClient.user.tag);
    try {
      await registerCommands(config, readyClient);
      console.log("Bot is ready. The only command enabled is /ping.");
    } catch (error) {
      console.error("Slash command sync failed:", safeError(error));
      console.error("The bot will stay online; /ping works wherever it is already registered.");
    }
  });

  client.on(Events.InteractionCreate, async (interaction) => {
    if (!interaction.isChatInputCommand()) return;
    console.log("Received slash interaction: " + interaction.commandName);

    if (interaction.commandName !== "ping") {
      await interaction.reply({
        content: "Only /ping is enabled on this bot.",
        ephemeral: true,
      }).catch((error) => console.error("Could not acknowledge disabled command:", safeError(error)));
      return;
    }

    const started = Date.now();
    try {
      await interaction.reply({
        content: "🏓 Pong! Bot is online. Gateway latency: " +
          (client.ws.ping >= 0 ? Math.round(client.ws.ping) + " ms" : "measuring") + ".",
      });
      console.log("Successfully replied to /ping in " + (Date.now() - started) + " ms.");
    } catch (error) {
      console.error("Failed to reply to /ping:", safeError(error));
    }
  });

  client.on(Events.Error, (error) => console.error("Discord client error:", safeError(error)));
  client.on(Events.ShardError, (error, shardId) => {
    console.error("Discord shard " + shardId + " error:", safeError(error));
  });

  const shutdown = async (signal) => {
    console.log("Received " + signal + "; shutting down.");
    server.close();
    client.destroy();
    process.exit(0);
  };
  process.once("SIGINT", () => void shutdown("SIGINT"));
  process.once("SIGTERM", () => void shutdown("SIGTERM"));

  await client.login(config.token);
}

function safeError(error) {
  return String(error?.message || error || "Unknown error")
    .replace(/\s+/g, " ")
    .replace(/\b[\w-]{24}\.[\w-]{6}\.[\w-]{25,}\b/g, "[redacted token]")
    .slice(0, 300);
}

module.exports = { main, registerCommands, commandsMatch };

if (require.main === module) {
  main().catch((error) => {
    console.error("Bot failed to start:", safeError(error));
    process.exitCode = 1;
  });
}
