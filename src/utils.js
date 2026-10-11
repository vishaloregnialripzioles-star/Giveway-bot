const { randomInt } = require("node:crypto");

const MIN_DURATION_MS = 60_000;
const MAX_DURATION_MS = 30 * 24 * 60 * 60 * 1_000;

function parseDuration(input) {
  const match = /^(\d+)\s*(s|m|h|d)$/i.exec(String(input ?? "").trim());
  if (!match) {
    throw new Error("Use a duration like 30m, 2h, or 7d.");
  }

  const amount = Number(match[1]);
  const unitMs = { s: 1_000, m: 60_000, h: 3_600_000, d: 86_400_000 }[
    match[2].toLowerCase()
  ];
  const duration = amount * unitMs;

  if (!Number.isSafeInteger(amount) || duration < MIN_DURATION_MS) {
    throw new Error("Giveaways must last at least 1 minute.");
  }
  if (!Number.isSafeInteger(duration) || duration > MAX_DURATION_MS) {
    throw new Error("Giveaways can last at most 30 days.");
  }
  return duration;
}

function chooseWeightedWinners(entries, winnerCount, excludedIds = new Set()) {
  const pool = entries
    .filter((entry) => !excludedIds.has(String(entry.user_id)))
    .map((entry) => ({
      userId: String(entry.user_id),
      weight: Math.max(1, Number(entry.weight) || 1),
    }));
  const winners = [];

  while (pool.length && winners.length < winnerCount) {
    const totalWeight = pool.reduce((sum, entry) => sum + entry.weight, 0);
    if (!Number.isSafeInteger(totalWeight) || totalWeight <= 0) break;

    let ticket = randomInt(totalWeight);
    let selectedIndex = 0;
    for (let index = 0; index < pool.length; index += 1) {
      ticket -= pool[index].weight;
      if (ticket < 0) {
        selectedIndex = index;
        break;
      }
    }
    winners.push(pool.splice(selectedIndex, 1)[0].userId);
  }

  return winners;
}

function formatTimestamp(value) {
  const date = value instanceof Date ? value : new Date(value);
  return `<t:${Math.floor(date.getTime() / 1_000)}:R>`;
}

function getMemberRoleIds(member) {
  if (!member) return [];
  if (Array.isArray(member.roles)) return member.roles.map(String);
  if (member.roles?.cache) return [...member.roles.cache.keys()].map(String);
  return [];
}

module.exports = {
  MAX_DURATION_MS,
  MIN_DURATION_MS,
  chooseWeightedWinners,
  formatTimestamp,
  getMemberRoleIds,
  parseDuration,
};
