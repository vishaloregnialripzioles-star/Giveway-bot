const {
  ChannelType,
  PermissionFlagsBits,
  SlashCommandBuilder,
} = require("discord.js");

const giveawayCommand = new SlashCommandBuilder()
  .setName("giveaway")
  .setDescription("Create and manage server giveaways")
  .addSubcommand((subcommand) =>
    subcommand
      .setName("create")
      .setDescription("Start a giveaway")
      .addStringOption((option) =>
        option.setName("prize").setDescription("What the winner gets").setRequired(true).setMaxLength(200),
      )
      .addStringOption((option) =>
        option.setName("duration").setDescription("For example: 30m, 2h, or 7d").setRequired(true).setMaxLength(10),
      )
      .addIntegerOption((option) =>
        option.setName("winners").setDescription("Number of winners (default 1)").setMinValue(1).setMaxValue(20),
      )
      .addChannelOption((option) =>
        option
          .setName("channel")
          .setDescription("Where to post (defaults to this channel)")
          .addChannelTypes(ChannelType.GuildText, ChannelType.GuildAnnouncement),
      )
      .addRoleOption((option) =>
        option.setName("required_role").setDescription("Only members with this role can enter"),
      )
      .addRoleOption((option) =>
        option.setName("bonus_role").setDescription("Members with this role get 2 entries"),
      ),
  )
  .addSubcommand((subcommand) =>
    subcommand
      .setName("end")
      .setDescription("End a running giveaway early")
      .addStringOption((option) =>
        option.setName("message_id").setDescription("Giveaway message ID").setRequired(true),
      ),
  )
  .addSubcommand((subcommand) =>
    subcommand
      .setName("reroll")
      .setDescription("Pick replacement winner(s), excluding all previous winners")
      .addStringOption((option) =>
        option.setName("message_id").setDescription("Giveaway message ID").setRequired(true),
      )
      .addIntegerOption((option) =>
        option.setName("winners").setDescription("How many new winners to pick").setMinValue(1).setMaxValue(20),
      ),
  )
  .addSubcommand((subcommand) =>
    subcommand
      .setName("pause")
      .setDescription("Pause a giveaway and preserve its remaining time")
      .addStringOption((option) =>
        option.setName("message_id").setDescription("Giveaway message ID").setRequired(true),
      ),
  )
  .addSubcommand((subcommand) =>
    subcommand
      .setName("resume")
      .setDescription("Resume a paused giveaway")
      .addStringOption((option) =>
        option.setName("message_id").setDescription("Giveaway message ID").setRequired(true),
      ),
  )
  .addSubcommand((subcommand) =>
    subcommand
      .setName("cancel")
      .setDescription("Cancel a giveaway without choosing winners")
      .addStringOption((option) =>
        option.setName("message_id").setDescription("Giveaway message ID").setRequired(true),
      ),
  )
  .addSubcommand((subcommand) =>
    subcommand.setName("list").setDescription("List this server's active and paused giveaways"),
  )
  .addSubcommand((subcommand) =>
    subcommand
      .setName("participants")
      .setDescription("View entry counts and participant IDs")
      .addStringOption((option) =>
        option.setName("message_id").setDescription("Giveaway message ID").setRequired(true),
      ),
  );

const commandData = [giveawayCommand.toJSON()];

async function handleGiveawayCommand(interaction, { store, client }) {
  if (!interaction.inGuild()) {
    await interaction.reply({ content: "Giveaways can only be managed inside a server.", ephemeral: true });
    return;
  }

  const subcommand = interaction.options.getSubcommand();
  if (subcommand === "create") {
    await createGiveaway(interaction, store);
    return;
  }
  if (subcommand === "list") {
    await listGiveaways(interaction, store);
    return;
  }
  if (subcommand === "participants") {
    await showParticipants(interaction, store);
    return;
  }

  await interaction.deferReply({ ephemeral: true });
  const messageId = interaction.options.getString("message_id", true);
  const giveaway = await store.getByMessage(interaction.guildId, messageId);
  if (!giveaway) {
    await interaction.editReply("I couldn't find that giveaway in this server. Check the message ID.");
    return;
  }
  if (!canManageGiveaway(interaction, giveaway)) {
    await interaction.editReply("Only the giveaway host or a server member with Manage Server can do that.");
    return;
  }

  if (subcommand === "end") {
    const result = await require("./giveaways").finishGiveaway(client, store, giveaway.id);
    await interaction.editReply(result.state === "ended"
      ? `Giveaway ended. Picked ${result.winners.length} winner(s) from ${result.entrantCount} entrant(s).`
      : `This giveaway is ${result.state}.`);
    return;
  }

  if (subcommand === "reroll") {
    const count = interaction.options.getInteger("winners");
    const result = await require("./giveaways").rerollGiveaway(client, store, giveaway.id, count);
    const message = result.state === "ended"
      ? result.winners.length
        ? `Picked ${result.winners.length} replacement winner(s). Previous winners were excluded.`
        : "No eligible entrants remain who have not already won."
      : result.state === "missing"
        ? "Giveaway not found."
        : `A giveaway can only be rerolled after it ends (current status: ${result.state}).`;
    await interaction.editReply(message);
    return;
  }

  if (subcommand === "pause") {
    const updated = await store.pause(giveaway.id);
    if (!updated) {
      await interaction.editReply("That giveaway is not currently running.");
      return;
    }
    await require("./giveaways").updateGiveawayMessage(client, store, updated, "paused");
    await interaction.editReply("Giveaway paused; its remaining time is saved.");
    return;
  }

  if (subcommand === "resume") {
    const updated = await store.resume(giveaway.id);
    if (!updated) {
      await interaction.editReply("That giveaway is not paused.");
      return;
    }
    await require("./giveaways").updateGiveawayMessage(client, store, updated, "active");
    await interaction.editReply("Giveaway resumed.");
    return;
  }

  if (subcommand === "cancel") {
    const updated = await store.cancel(giveaway.id);
    if (!updated) {
      await interaction.editReply("That giveaway is already closed.");
      return;
    }
    await require("./giveaways").updateGiveawayMessage(client, store, updated, "cancelled");
    await interaction.editReply("Giveaway cancelled; no winner was selected.");
  }
}

async function createGiveaway(interaction, store) {
  if (!interaction.memberPermissions?.has(PermissionFlagsBits.ManageGuild)) {
    await interaction.reply({ content: "You need the Manage Server permission to create giveaways.", ephemeral: true });
    return;
  }

  const { parseDuration } = require("./utils");
  const { entryButtons, makeGiveawayEmbed } = require("./giveaways");
  let duration;
  try {
    duration = parseDuration(interaction.options.getString("duration", true));
  } catch (error) {
    await interaction.reply({ content: error.message, ephemeral: true });
    return;
  }

  const prize = interaction.options.getString("prize", true).trim();
  if (!prize) {
    await interaction.reply({ content: "Prize cannot be empty.", ephemeral: true });
    return;
  }
  const channel = interaction.options.getChannel("channel") ?? interaction.channel;
  if (!channel?.isTextBased() || !channel.messages) {
    await interaction.reply({ content: "Choose a text channel I can post in.", ephemeral: true });
    return;
  }

  const requiredRole = interaction.options.getRole("required_role");
  const bonusRole = interaction.options.getRole("bonus_role");
  const winnerCount = interaction.options.getInteger("winners") ?? 1;
  const temporary = {
    id: "pending",
    guild_id: interaction.guildId,
    host_id: interaction.user.id,
    prize,
    winner_count: winnerCount,
    required_role_id: requiredRole?.id ?? null,
    bonus_role_id: bonusRole?.id ?? null,
    ends_at: new Date(Date.now() + duration),
    status: "active",
  };

  await interaction.deferReply({ ephemeral: true });
  const message = await channel.send({
    embeds: [makeGiveawayEmbed(temporary, 0)],
    components: entryButtons("pending"),
  }).catch(() => null);
  if (!message) {
    await interaction.editReply(`I couldn't post in ${channel}. Check that I have View Channel, Send Messages, Embed Links, and Read Message History.`);
    return;
  }

  try {
    const giveaway = await store.createGiveaway({
      guildId: interaction.guildId,
      channelId: channel.id,
      messageId: message.id,
      hostId: interaction.user.id,
      prize,
      winnerCount,
      requiredRoleId: requiredRole?.id ?? null,
      bonusRoleId: bonusRole?.id ?? null,
      endsAt: temporary.ends_at,
    });

    await message.edit({
      embeds: [makeGiveawayEmbed(giveaway, 0)],
      components: entryButtons(giveaway.id),
    });
    await interaction.editReply(`Giveaway created in ${channel}: ${message.url}`);
  } catch (error) {
    await message.delete().catch(() => {});
    throw error;
  }
}

async function listGiveaways(interaction, store) {
  await interaction.deferReply({ ephemeral: true });
  const giveaways = await store.listGuild(interaction.guildId);
  if (!giveaways.length) {
    await interaction.editReply("There are no active or paused giveaways in this server.");
    return;
  }
  const lines = await Promise.all(giveaways.map(async (giveaway) => {
    const entries = await store.entryCount(giveaway.id);
    const timing = giveaway.status === "paused"
      ? "paused"
      : `ends <t:${Math.floor(new Date(giveaway.ends_at).getTime() / 1_000)}:R>`;
    return `• **${giveaway.prize}** — ${giveaway.status}, ${entries} entr${entries === 1 ? "y" : "ies"}, ${timing} — [jump](https://discord.com/channels/${giveaway.guild_id}/${giveaway.channel_id}/${giveaway.message_id})`;
  }));
  await interaction.editReply(lines.join("\n").slice(0, 1900));
}

async function showParticipants(interaction, store) {
  await interaction.deferReply({ ephemeral: true });
  const messageId = interaction.options.getString("message_id", true);
  const giveaway = await store.getByMessage(interaction.guildId, messageId);
  if (!giveaway) {
    await interaction.editReply("I couldn't find that giveaway in this server.");
    return;
  }
  if (!canManageGiveaway(interaction, giveaway)) {
    await interaction.editReply("Only the giveaway host or a server member with Manage Server can view the participant list.");
    return;
  }
  const [count, entries] = await Promise.all([
    store.entryCount(giveaway.id),
    store.listEntries(giveaway.id, 30),
  ]);
  const shown = entries.map((entry) => `• <@${entry.user_id}>${entry.weight > 1 ? " (2 entries)" : ""}`).join("\n");
  const more = count > entries.length ? `\n…and ${count - entries.length} more.` : "";
  await interaction.editReply({
    content: `**${count} entrant(s)** for **${giveaway.prize}**:\n${shown || "No entries yet."}${more}`,
    allowedMentions: { parse: [] },
  });
}

function canManageGiveaway(interaction, giveaway) {
  return interaction.user.id === giveaway.host_id
    || interaction.memberPermissions?.has(PermissionFlagsBits.ManageGuild);
}

module.exports = { commandData, handleGiveawayCommand };
