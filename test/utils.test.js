const test = require("node:test");
const assert = require("node:assert/strict");
const {
  chooseWeightedWinners,
  getMemberRoleIds,
  parseDuration,
} = require("../src/utils");

test("parseDuration accepts supported units and trims whitespace", () => {
  assert.equal(parseDuration("1m"), 60_000);
  assert.equal(parseDuration(" 2 H "), 7_200_000);
  assert.equal(parseDuration("30d"), 30 * 24 * 60 * 60 * 1_000);
});

test("parseDuration rejects malformed, too-short, and too-long durations", () => {
  for (const value of ["", "tomorrow", "1w", "0m", "30s", "31d", "-1h"]) {
    assert.throws(() => parseDuration(value));
  }
});

test("weighted winner selection returns unique winners and respects exclusions", () => {
  const entrants = [
    { user_id: "one", weight: 2 },
    { user_id: "two", weight: 1 },
    { user_id: "three", weight: 1 },
  ];
  const winners = chooseWeightedWinners(entrants, 3);
  assert.equal(winners.length, 3);
  assert.equal(new Set(winners).size, 3);
  assert.deepEqual(new Set(winners), new Set(["one", "two", "three"]));
  assert.deepEqual(
    chooseWeightedWinners(entrants, 3, new Set(["one"])).sort(),
    ["three", "two"],
  );
});

test("role extraction supports both Discord interaction member shapes", () => {
  assert.deepEqual(getMemberRoleIds({ roles: ["member", "vip"] }), ["member", "vip"]);
  assert.deepEqual(
    getMemberRoleIds({ roles: { cache: new Map([["member", {}], ["vip", {}]]) } }),
    ["member", "vip"],
  );
});
