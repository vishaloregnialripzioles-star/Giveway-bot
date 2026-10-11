// Prefer IPv4 first on hosts where IPv6 routes can stall outbound Discord API requests.
require("node:dns").setDefaultResultOrder("ipv4first");

const {
  Client,
  Events,
  GatewayIntentBits,
  MessageFlags,
  REST,
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

  const client = new Client({
    intents: [GatewayIntentBits.Guilds],
  });
  const appState = { initialized: false };
  const server = createWebServer({ client, store, appState });
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

  client.once(Events.ClientReady, async (readyClient) => {
    try {
      console.log(`Logged in as ${readyClient.user.tag}`);
      await registerCommands(config);
      console.log(`Slash commands registered${config.guildId ? ` for guild ${config.guildId}` : " globally"}.`);
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
      if (interaction.isChatInputCommand() && interaction.commandName === "giveaway") {
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
  process.once("SIGTERM", () => shutdown(client, store, server));
  process.once("SIGINT", () => shutdown(client, store, server));

  // Avoid an extra authenticated REST probe at startup. A proxy/edge 429 can
  // be unrelated to the token, and repeated probes may prolong an outage.
  // Keep the HTTP server and database alive while connecting. discord.js
  // handles normal Gateway reconnects itself.
  console.log("Connecting to Discord Gateway...");
  let retryDelayMs = 30_000;
  while (!client.isReady()) {
    try {
      await client.login(config.token);
      break;
    } catch (error) {
      const message = String(error?.message || error)
        .replace(/[\r\n]+/g, " ")
        .replace(/\b[\w-]{24}\.[\w-]{6}\.[\w-]{25,}\b/g, "[redacted token]")
        .slice(0, 300);
      console.error("Discord Gateway login failed; keeping health server alive and retrying:", message);
      await new Promise((resolve) => setTimeout(resolve, retryDelayMs));
      retryDelayMs = Math.min(retryDelayMs * 2, 15 * 60_000);
    }
  }
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

async function registerCommands(config) {
  const rest = new REST({ version: "10" }).setToken(config.token);
  const route = config.guildId
    ? Routes.applicationGuildCommands(config.clientId, config.guildId)
    : Routes.applicationCommands(config.clientId);
  await rest.put(route, { body: commandData });
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
};

if (require.main === module) {
  main().catch((error) => {
    console.error("Bot failed to start:", error.message);
    process.exitCode = 1;
  });
}
