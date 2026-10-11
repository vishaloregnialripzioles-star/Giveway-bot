const test = require("node:test");
const assert = require("node:assert/strict");
const {
  chooseWeightedWinners,
  getMemberRoleIds,
  parseDuration,
} = require("../src/utils");
const { close, createWebServer, listen } = require("../src/web");

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

test("web service exposes a readiness health endpoint and a simple root page", async () => {
  const appState = { initialized: false };
  const server = createWebServer({
    appState,
    client: { isReady: () => true },
    store: { health: async () => true },
  });

  await listen(server, 0, "127.0.0.1");
  const address = server.address();
  const baseUrl = `http://127.0.0.1:${address.port}`;
  try {
    const starting = await fetch(`${baseUrl}/healthz`);
    assert.equal(starting.status, 503);
    assert.deepEqual(await starting.json(), {
      status: "starting",
      discord: "connected",
      database: "connected",
    });

    appState.initialized = true;
    const healthy = await fetch(`${baseUrl}/healthz`);
    assert.equal(healthy.status, 200);
    assert.equal((await healthy.json()).status, "ok");

    const home = await fetch(baseUrl);
    assert.equal(home.status, 200);
    assert.match(await home.text(), /Giveaway Bot is running/);

    const missing = await fetch(`${baseUrl}/not-a-route`);
    assert.equal(missing.status, 404);
  } finally {
    await close(server);
  }
});

test("health endpoint reports database failures as unhealthy", async () => {
  const server = createWebServer({
    appState: { initialized: true },
    client: { isReady: () => false },
    store: { health: async () => { throw new Error("database unavailable"); } },
  });

  await listen(server, 0, "127.0.0.1");
  try {
    const response = await fetch(`http://127.0.0.1:${server.address().port}/healthz`);
    assert.equal(response.status, 503);
    assert.deepEqual(await response.json(), {
      status: "starting",
      discord: "reconnecting",
      database: "unavailable",
    });
  } finally {
    await close(server);
  }
});
