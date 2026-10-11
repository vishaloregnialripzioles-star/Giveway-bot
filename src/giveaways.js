const {
  ActionRowBuilder,
  ButtonBuilder,
  ButtonStyle,
  EmbedBuilder,
} = require("discord.js");
const { chooseWeightedWinners, formatTimestamp } = require("./utils");

const COLORS = {
  active: 0x5865f2,
  paused: 0xf1c40f,
  ended: 0x57f287,
  cancelled: 0x747f8d,
};

function entryButtons(id, disabled = false) {
  return [
    new ActionRowBuilder().addComponents(
      new ButtonBuilder()
        .setCustomId(`giveaway:enter:${id}`)
        .setLabel("Enter")
        .setEmoji("🎉")
        .setStyle(ButtonStyle.Success)
        .setDisabled(disabled),
      new ButtonBuilder()
        .setCustomId(`giveaway:leave:${id}`)
        .setLabel("Leave")
        .setEmoji("↩️")
        .setStyle(ButtonStyle.Secondary)
        .setDisabled(disabled),
    ),
  ];
}

function makeGiveawayEmbed(giveaway, entries, status = giveaway.status) {
  const paused = status === "paused";
  const ended = status === "ended";
  const cancelled = status === "cancelled";
  const endsText = paused ? "Paused" : ended || cancelled
    ? `Ended <t:${Math.floor(new Date(giveaway.ended_at ?? Date.now()).getTime() / 1000)}:R>`
    : `Ends ${formatTimestamp(giveaway.ends_at)}`;

  const embed = new EmbedBuilder()
    .setColor(COLORS[status] ?? COLORS.active)
    .setTitle(`${cancelled ? "Giveaway cancelled" : ended ? "Giveaway ended" : paused ? "Giveaway paused" : "🎉 Giveaway"}`)
    .setDescription(`**${giveaway.prize}**`)
    .addFields(
      { name: "Winners", value: String(giveaway.winner_count), inline: true },
      { name: "Entries", value: String(entries), inline: true },
      { name: "Status", value: endsText, inline: true },
    )
    .setFooter({ text: `Hosted by ${giveaway.host_id} • Giveaway #${giveaway.id}` });

  if (giveaway.required_role_id) {
    embed.addFields({ name: "Entry requirement", value: `<@&${giveaway.required_role_id}>`, inline: true });
  }
  if (giveaway.bonus_role_id) {
    embed.addFields({
      name: "Bonus entries",
      value: `<@&${giveaway.bonus_role_id}> members receive 2 entries.`,
      inline: true,
    });
  }
  const lastWinners = giveaway.last_winner_ids?.length
    ? giveaway.last_winner_ids
    : giveaway.winner_ids;
  if (ended && lastWinners?.length) {
    embed.addFields({
      name: "Winner(s)",
      value: lastWinners.map((id) => `<@${id}>`).join(", "),
    });
  }
  if (ended && !lastWinners?.length) {
    embed.addFields({ name: "Result", value: "No eligible entries were received." });
  }
  if (cancelled) embed.addFields({ name: "Result", value: "This giveaway was cancelled by a moderator." });

  return embed;
}

async function updateGiveawayMessage(client, store, giveaway, status) {
  const channel = await client.channels.fetch(giveaway.channel_id).catch(() => null);
  if (!channel?.isTextBased()) return false;
  const message = await channel.messages.fetch(giveaway.message_id).catch(() => null);
  if (!message) return false;
  const count = await store.entryCount(giveaway.id).catch(() => 0);
  const finalStatus = status ?? giveaway.status;
  await message.edit({
    embeds: [makeGiveawayEmbed(giveaway, count, finalStatus)],
    components: entryButtons(giveaway.id, finalStatus !== "active"),
  });
  return true;
}

async function publishWinners(client, store, result, { reroll = false } = {}) {
  if (result.state !== "ended") return;
  const { giveaway, winners } = result;
  await updateGiveawayMessage(client, {
    entryCount: async () => result.entrantCount,
  }, giveaway, "ended").catch((error) => {
    console.error(`Could not update giveaway ${giveaway.id}:`, error.message);
  });

  const channel = await client.channels.fetch(giveaway.channel_id).catch(() => null);
  if (!channel?.isTextBased()) {
    console.warn(`Could not find the giveaway channel for #${giveaway.id}.`);
    return;
  }

  const announcement = winners.length
    ? `${reroll ? "🔁 New winner" : "🎉 Congratulations"}${winners.length > 1 ? "s" : ""}: ${winners.map((id) => `<@${id}>`)} — you ${winners.length > 1 ? "have" : "have"} won **${giveaway.prize}**!`
    : `No eligible entries for **${giveaway.prize}**.`;
  const announcementMessage = await channel.send({
    content: announcement,
    allowedMentions: { users: winners, parse: [] },
    reply: { messageReference: giveaway.message_id, failIfNotExists: false },
  }).catch((error) => {
    console.error(`Could not announce giveaway #${giveaway.id}:`, error.message);
    return null;
  });
  if (!announcementMessage) return;
  await store.markAnnouncementSent(giveaway.id);

  for (const userId of winners) {
    const user = await client.users.fetch(userId).catch(() => null);
    if (!user) continue;
    await user.send(`You won **${giveaway.prize}** in **${channel.guild?.name ?? "a Discord server"}**!`)
      .catch(() => {});
  }
}

async function finishGiveaway(client, store, id, requestedWinnerCount) {
  const giveaway = await store.getById(id);
  if (!giveaway) return { state: "missing" };

  const result = await store.finish(
    id,
    requestedWinnerCount ?? giveaway.winner_count,
    (entries, count) => chooseWeightedWinners(entries, count),
  );
  if (result.state === "ended") {
    await publishWinners(client, store, result);
  }
  return result;
}

async function rerollGiveaway(client, store, id, requestedWinnerCount) {
  const giveaway = await store.getById(id);
  if (!giveaway) return { state: "missing" };

  const result = await store.reroll(
    id,
    requestedWinnerCount ?? giveaway.winner_count,
    (entries, count, excluded) => chooseWeightedWinners(entries, count, excluded),
  );
  if (result.state === "ended") {
    const updated = await store.getById(id);
    await updateGiveawayMessage(client, store, updated, "ended").catch((error) => {
      console.error(`Could not update rerolled giveaway ${id}:`, error.message);
    });
    await publishWinners(client, store, {
      ...result,
      giveaway: updated,
    }, { reroll: true });
  }
  return result;
}

module.exports = {
  entryButtons,
  finishGiveaway,
  makeGiveawayEmbed,
  publishWinners,
  rerollGiveaway,
  updateGiveawayMessage,
};
