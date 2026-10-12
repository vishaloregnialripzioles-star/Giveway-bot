// Prefer IPv4 first on hosts where IPv6 routes can stall outbound Discord API requests.
require("node:dns").setDefaultResultOrder("ipv4first");

const https = require("node:https");
const {
  Client,
  Events,
  GatewayIntentBits,
  MessageFlags,
  Routes,
} = require("discord.js");
const { loadConfig } = require("./config");
const { commandData, handleGiveawayCommand } = require("./commands");
const {
  finishGiveaway,
  updateGiveawayMessage,
} = require("./giveaways");
const { createStore } = require("./store");
const { getMemberRoleIds } = require("./utils");
const { close: closeWebServer, createWebServer, listen } = require("./web");

async function main() {
  const config = loadConfig();
  const store = createStore({ connectionString: config.databaseUrl, ssl: config.pgSsl });
  try {
    await store.initialize();
  } catch (error) {
    await store.close().catch(() => {});
    throw error;
  }

  let client = createClient();
  const clientState = { isReady: () => Boolean(client?.isReady()) };
  const appState = { initialized: false };
  const server = createWebServer({ client: clientState, store, appState });
  const port = Number(process.env.PORT || 3000);
  if (!Number.isInteger(port) || port < 1 || port > 65_535) {
    await store.close();
    throw new Error("PORT must be an integer between 1 and 65535.");
  }
  try {
    await listen(server, port);
  } catch (error) {
    await store.close().catch(() => {});
    throw error;
  }
  console.log(`HTTP health server listening on 0.0.0.0:${port}`);

  configureClient(client, config, store, appState, server);



  // Avoid an extra authenticated REST probe at startup. A proxy/edge 429 can
  // be unrelated to the token, and repeated probes may prolong an outage.
  // Keep the HTTP server and database alive while connecting. discord.js
  // handles normal Gateway reconnects itself.
  console.log("Connecting to Discord Gateway...");
  let retryDelayMs = 30_000;
  while (!client.isReady()) {
    // Attach before login so a fast READY event cannot be missed. Some network
    // failures leave login pending instead of rejecting, so bound both phases.
    const readyPromise = client.isReady()
      ? Promise.resolve()
      : new Promise((resolve) => client.once(Events.ClientReady, resolve));
    try {
      console.log("Discord login starting; gateway=" + String(client.ws?.gateway || "default") + "; shardStatus=" + String(client.ws?.status ?? "unknown"));
      await withTimeout(
        client.login(config.token),
        180_000,
        "Discord login timed out before completing.",
      );
      console.log("Discord login promise resolved; waiting for Gateway READY.");
      await withTimeout(
        readyPromise,
        180_000,
        "Discord Gateway did not become ready within 180 seconds.",
      );
      break;
    } catch (error) {
      const message = String(error?.message || error)
        .replace(/[\r\n]+/g, " ")
        .replace(/\b[\w-]{24}\.[\w-]{6}\.[\w-]{25,}\b/g, "[redacted token]")
        .slice(0, 300);
      console.error("Discord connection attempt failed; keeping health server alive and retrying:", message);
      console.error("Discord connection diagnostics:", JSON.stringify({ gateway: client.ws?.gateway || null, shardStatus: client.ws?.status ?? null, shardCount: client.ws?.shards?.size ?? null }));
      client.destroy();
      client = createClient();
      configureClient(client, config, store, appState, server);
      await new Promise((resolve) => setTimeout(resolve, retryDelayMs));
      retryDelayMs = Math.min(retryDelayMs * 2, 15 * 60_000);
    }
  }
}


function createClient() {
  const client = new Client({
    intents: [GatewayIntentBits.Guilds],
    ws: {
      // Avoid the /gateway/bot REST discovery request during login. This can
      // keep Gateway startup independent from a REST edge/rate-limit outage.
      fetchGatewayInformation: async () => {
        console.log("Gateway discovery callback invoked; using direct Discord Gateway URL.");
        return {
        url: "wss://gateway.discord.gg",
        shards: 1,
        session_start_limit: {
          total: 1000,
          remaining: 1000,
          reset_after: 86_400_000,
          max_concurrency: 1,
        },
        };
      },
    },
  });
  installGatewayDiscoveryBypass(client);
  return client;
}

// discord.js v14's Client constructor may not forward the undocumented
// fetchGatewayInformation option into its legacy WebSocketManager. Intercept
// only the Gateway-discovery route on the same REST instance used by the
// manager; all other REST requests retain the original implementation.
function installGatewayDiscoveryBypass(client) {
  const rest = client.rest;
  if (!rest || typeof rest.get !== "function" || rest.__gatewayBypassInstalled) {
    console.warn("Gateway discovery bypass could not be installed on the Discord REST client.");
    return;
  }

  const originalGet = rest.get.bind(rest);
  const gatewayRoute = Routes.gatewayBot();
  rest.get = function (route, ...args) {
    const routePath = typeof route === "string" ? route : route?.path;
    if (routePath === gatewayRoute || routePath === "/gateway/bot") {
      console.log("Gateway discovery intercepted locally; using direct Discord Gateway URL.");
      return Promise.resolve({
        url: "wss://gateway.discord.gg",
        shards: 1,
        session_start_limit: {
          total: 1000,
          remaining: 1000,
          reset_after: 86_400_000,
          max_concurrency: 1,
        },
      });
    }
    return originalGet(route, ...args);
  };
  Object.defineProperty(rest, "__gatewayBypassInstalled", { value: true });
}

function configureClient(client, config, store, appState, server) {
    client.once(Events.ClientReady, async (readyClient) => {
      try {
        console.log(`Logged in as ${readyClient.user.tag}`);
        // Register commands independently: REST rate limits must not take the Gateway bot offline.
        registerCommandsWithRetry(config, readyClient).catch((error) => {
          console.error("Slash command registration retry worker stopped:", error.message);
        });
        let schedulerBusy = false;
        const schedulerTick = async () => {
          if (schedulerBusy) return;
          schedulerBusy = true;
          try {
            await processDueGiveaways(client, store);
            await processPendingAnnouncements(client, store);
          } finally {
            schedulerBusy = false;
          }
        };
        await schedulerTick();
        appState.initialized = true;
        setInterval(() => {
          schedulerTick().catch((error) => {
              console.error("Giveaway scheduler error:", error.message);
          });
        }, 10_000).unref();
      } catch (error) {
        console.error("Bot initialization failed after login:", error);
        await closeWebServer(server);
        client.destroy();
        await store.close().catch(() => {});
        process.exitCode = 1;
      }
    });
  
    client.on(Events.InteractionCreate, async (interaction) => {
      try {
        if (interaction.isChatInputCommand() && interaction.commandName === "ping") {
          const gatewayLatency = client.ws.ping;
          await interaction.reply({
            content: `🏓 Pong! Gateway latency: ${gatewayLatency >= 0 ? Math.round(gatewayLatency) + " ms" : "connecting"}.`,
          });
        } else if (interaction.isChatInputCommand() && interaction.commandName === "giveaway") {
          await handleGiveawayCommand(interaction, { store, client });
        } else if (interaction.isButton() && interaction.customId.startsWith("giveaway:")) {
          await handleGiveawayButton(interaction, store);
        }
      } catch (error) {
        console.error("Interaction failed:", error);
        const payload = {
          content: "Something went wrong handling that action. Please try again; the error has been logged.",
          flags: MessageFlags.Ephemeral,
        };
        if (interaction.deferred || interaction.replied) {
          await interaction.followUp(payload).catch(() => {});
        } else {
          await interaction.reply(payload).catch(() => {});
        }
      }
    });
  
    client.on(Events.Debug, (message) => {
      const rawMessage = String(message || "");
      if (/provided token/i.test(rawMessage)) {
        console.log("Discord debug: token supplied to Discord.js (value intentionally omitted).");
        return;
      }
      const safeMessage = rawMessage.replace(/[\\r\\n]+/g, " ").replace(/[A-Za-z0-9_-]{20,}\\.[A-Za-z0-9_-]{5,}\\.[A-Za-z0-9_-]{20,}/g, "[redacted token]").slice(0, 500);
      console.log("Discord debug:", safeMessage);
    });
    client.on(Events.Error, (error) => console.error("Discord client error:", error.message));
    client.on(Events.ShardError, (error, shardId) => {
      const name = typeof error?.name === "string" ? error.name : "Error";
      const message = String(error?.message || "Unknown shard error.")
        .replace(/[\r\n]+/g, " ")
        .replace(/\b[\w-]{24}\.[\w-]{6}\.[\w-]{25,}\b/g, "[redacted token]")
        .slice(0, 300);
      console.error("Discord shard " + shardId + " error (" + name + "): " + message);
    });
    client.on(Events.ShardDisconnect, (closeEvent, shardId) => {
      const reason = String(closeEvent.reason || "")
        .replace(/[\r\n]+/g, " ")
        .replace(/\b[\w-]{24}\.[\w-]{6}\.[\w-]{25,}\b/g, "[redacted token]")
        .slice(0, 200);
      console.error("Discord shard " + shardId + " disconnected (code=" + closeEvent.code + ", clean=" + closeEvent.wasClean + ")" + (reason ? "; reason=" + reason : ""));
    });
    client.on(Events.ShardReconnecting, (shardId) => {
      console.warn("Discord shard " + shardId + " reconnecting.");
    });
    client.on(Events.ShardReady, (shardId) => {
      console.log("Discord shard " + shardId + " ready.");
    });
}

function withTimeout(promise, timeoutMs, message) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(message)), timeoutMs);
    promise.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (error) => {
        clearTimeout(timer);
        reject(error);
      },
    );
  });
}

async function registerCommandsWithRetry(config, client) {
  console.log("Slash command registration worker started.");
  let delayMs = 60_000;
  while (client.isReady()) {
    try {
      await registerCommands(config, client);
      console.log("Slash command registration completed successfully.");
      return;
    } catch (error) {
      const message = String(error?.message || error)
        .replace(/[\\r\\n]+/g, " ")
        .replace(/\\b[\\w-]{24}\\.[\\w-]{6}\\.[\\w-]{25,}\\b/g, "[redacted token]")
        .slice(0, 250);
      const retryAfterMs = Number(error?.retryAfterMs);
      const waitMs = Number.isFinite(retryAfterMs) && retryAfterMs > 0
        ? Math.min(retryAfterMs + 1_000, 24 * 60 * 60_000)
        : delayMs;
      console.error(`Slash command registration failed; bot remains online and will retry in ${Math.ceil(waitMs / 1_000)} seconds:`, message);
      await new Promise((resolve) => setTimeout(resolve, waitMs));
      if (!(Number.isFinite(retryAfterMs) && retryAfterMs > 0)) {
        delayMs = Math.min(delayMs * 2, 15 * 60_000);
      }
    }
  }
}

async function registerCommands(config, client) {
  // GUILD_ID targets one server explicitly. Otherwise update each server this
  // bot is connected to for immediate command visibility; fall back to global
  // registration only if no guild is available.
  const guildIds = config.guildId
    ? [config.guildId]
    : [...new Set(client?.guilds?.cache?.keys?.() ?? [])];
  const targets = guildIds.length
    ? guildIds.map((guildId) => ({
      route: Routes.applicationGuildCommands(config.clientId, guildId),
      scope: `guild ${guildId}`,
    }))
    : [{ route: Routes.applicationCommands(config.clientId), scope: "globally" }];

  for (const target of targets) {
    // Read first so a restart/redeploy does not repeatedly PUT identical command
    // definitions and consume Discord's command-registration rate limit.
    const current = await discordApiRequest(target.route, config.token, undefined, "GET");
    if (commandsMatch(current, commandData)) {
      console.log(`Slash commands already match Discord's registered commands (${target.scope}); skipping write.`);
      continue;
    }

    console.log(`Registering ${commandData.length} slash commands ${target.scope}...`);
    const registered = await discordApiRequest(target.route, config.token, commandData, "PUT");
    console.log(`Discord accepted ${Array.isArray(registered) ? registered.length : commandData.length} slash command(s) ${target.scope}.`);
  }
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
  const normalizeCommand = (command) => ({
    name: command.name,
    description: command.description,
    type: command.type ?? 1,
    options: (command.options ?? []).map(normalizeOption),
  });
  const currentByName = new Map(current.map((command) => [command.name, command]));
  return desired.every((command) => {
    const existing = currentByName.get(command.name);
    return existing && JSON.stringify(normalizeCommand(existing)) === JSON.stringify(normalizeCommand(command));
  });
}

function discordApiRequest(route, token, body, method = "PUT") {
  return new Promise((resolve, reject) => {
    const hasBody = body !== undefined && body !== null;
    const payload = hasBody ? JSON.stringify(body) : "";
    const headers = { Authorization: `Bot ${token}` };
    if (hasBody) {
      headers["Content-Type"] = "application/json";
      headers["Content-Length"] = Buffer.byteLength(payload);
    }
    const request = https.request({
      hostname: "discord.com",
      path: `/api/v10${route}`,
      method,
      timeout: 12_000,
      headers,
    }, (response) => {
      let responseBody = "";
      response.setEncoding("utf8");
      response.on("data", (chunk) => { responseBody += chunk; });
      response.on("end", () => {
        let data = null;
        try { data = responseBody ? JSON.parse(responseBody) : null; } catch {}
        if (response.statusCode >= 200 && response.statusCode < 300) {
          resolve(data);
          return;
        }
        const headerRetry = Number(response.headers["retry-after"]);
        const bodyRetry = Number(data?.retry_after);
        const retryAfter = Number.isFinite(headerRetry) && headerRetry > 0
          ? headerRetry
          : Number.isFinite(bodyRetry) && bodyRetry > 0 ? bodyRetry : 0;
        const details = typeof data?.message === "string" ? data.message : "Discord returned an error response.";
        const error = new Error(`Discord API HTTP ${response.statusCode}${retryAfter > 0 ? ` (retry-after ${retryAfter}s)` : ""}: ${details.slice(0, 180)}`);
        if (retryAfter > 0) error.retryAfterMs = retryAfter * 1_000;
        reject(error);
      });
    });
    request.on("timeout", () => request.destroy(new Error("Discord API command request timed out after 12 seconds.")));
    request.on("error", (error) => reject(error));
    request.end(hasBody ? payload : undefined);
  });
}

async function handleGiveawayButton(interaction, store) {
  if (!interaction.inGuild()) {
    await interaction.reply({ content: "Giveaways only work inside a server.", ephemeral: true });
    return;
  }

  const [, action, id] = interaction.customId.split(":");
  const giveaway = await store.getById(id);
  if (!giveaway || giveaway.guild_id !== interaction.guildId) {
    await interaction.reply({ content: "This giveaway is no longer available.", ephemeral: true });
    return;
  }

  if (action === "enter") {
    const roleIds = getMemberRoleIds(interaction.member);
    if (giveaway.required_role_id && !roleIds.includes(giveaway.required_role_id)) {
      await interaction.reply({
        content: `You need the <@&${giveaway.required_role_id}> role to enter.`,
        ephemeral: true,
        allowedMentions: { parse: [] },
      });
      return;
    }
    const weight = giveaway.bonus_role_id && roleIds.includes(giveaway.bonus_role_id) ? 2 : 1;
    await interaction.deferReply({ ephemeral: true });
    const result = await store.join(id, interaction.user.id, weight);
    const responses = {
      joined: "You're entered! Good luck 🎉",
      already: "You're already entered.",
      paused: "This giveaway is paused, so entries are temporarily closed.",
      closed: "This giveaway has ended or is closed.",
      missing: "This giveaway is no longer available.",
    };
    await interaction.editReply(responses[result]);
    if (result === "joined") {
      const latest = await store.getById(id);
      await updateGiveawayMessage(interaction.client, store, latest).catch((error) => {
        console.error(`Could not refresh entry count for giveaway ${id}:`, error.message);
      });
    }
    return;
  }

  if (action === "leave") {
    await interaction.deferReply({ ephemeral: true });
    const result = await store.leave(id, interaction.user.id);
    const responses = {
      left: "You've left the giveaway.",
      "not-entered": "You weren't entered in this giveaway.",
      paused: "This giveaway is paused, so entries are temporarily closed.",
      closed: "This giveaway has ended or is closed.",
      missing: "This giveaway is no longer available.",
    };
    await interaction.editReply(responses[result]);
    if (result === "left") {
      const latest = await store.getById(id);
      await updateGiveawayMessage(interaction.client, store, latest).catch((error) => {
        console.error(`Could not refresh entry count for giveaway ${id}:`, error.message);
      });
    }
  }
}

async function processDueGiveaways(client, store) {
  const ids = await store.dueIds();
  for (const id of ids) {
    try {
      const result = await finishGiveaway(client, store, id);
      if (result.state === "ended") {
        console.log(`Ended giveaway #${id}; selected ${result.winners.length} winner(s).`);
      }
    } catch (error) {
      console.error(`Failed to end giveaway #${id}:`, error.message);
    }
  }
}

async function processPendingAnnouncements(client, store) {
  const giveaways = await store.pendingAnnouncements();
  for (const giveaway of giveaways) {
    const winners = giveaway.last_winner_ids ?? [];
    await require("./giveaways").publishWinners(
      client,
      store,
      { state: "ended", giveaway, winners, entrantCount: await store.entryCount(giveaway.id) },
      { reroll: giveaway.last_draw_is_reroll },
    );
  }
}

async function shutdown(client, store, server) {
  console.log("Shutting down...");
  await closeWebServer(server);
  client.destroy();
  await store.close().catch((error) => console.error("Database shutdown error:", error.message));
  process.exit(0);
}

module.exports = {
  handleGiveawayButton,
  main,
  processPendingAnnouncements,
  processDueGiveaways,
  registerCommands,
  commandsMatch,
};

if (require.main === module) {
  main().catch((error) => {
    console.error("Bot failed to start:", error.message);
    process.exitCode = 1;
  });
}
