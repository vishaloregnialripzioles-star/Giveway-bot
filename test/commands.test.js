const test = require("node:test");
const assert = require("node:assert/strict");
const { commandsMatch } = require("../src/index");

test("command registration comparison ignores Discord-generated metadata", () => {
  const desired = [{
    name: "ping",
    description: "Check bot latency",
    type: 1,
    options: [],
  }];
  const registered = [{
    id: "123456789",
    application_id: "987654321",
    version: "1122334455",
    name: "ping",
    description: "Check bot latency",
    type: 1,
    options: [],
  }];

  assert.equal(commandsMatch(registered, desired), true);
});

test("command registration comparison detects changed and stale commands", () => {
  const desired = [
    { name: "ping", description: "Check bot latency", type: 1, options: [] },
    { name: "giveaway", description: "Manage giveaways", type: 1, options: [] },
  ];

  assert.equal(commandsMatch(desired, desired), true);
  assert.equal(commandsMatch([
    desired[0],
    { ...desired[1], description: "Old description" },
  ], desired), false);
  assert.equal(commandsMatch([...desired, {
    name: "old-command",
    description: "Stale",
    type: 1,
    options: [],
  }], desired), false);
});

test("command comparison includes nested options and their constraints", () => {
  const desired = [{
    name: "giveaway",
    description: "Manage giveaways",
    type: 1,
    options: [{
      type: 1,
      name: "create",
      description: "Create a giveaway",
      options: [{
        type: 3,
        name: "prize",
        description: "Prize",
        required: true,
        max_length: 200,
      }],
    }],
  }];

  assert.equal(commandsMatch(desired, desired), true);
  const changed = structuredClone(desired);
  changed[0].options[0].options[0].max_length = 100;
  assert.equal(commandsMatch(desired, changed), false);
});
