const { loadConfig } = require("./config");
const { registerCommands } = require("./index");

async function main() {
  const config = loadConfig();
  await registerCommands(config);
  console.log("Slash command registration check completed.");
}

main().catch((error) => {
  const message = String(error?.message || error)
    .replace(/[\r\n]+/g, " ")
    .replace(/\b[\w-]{24}\.[\w-]{6}\.[\w-]{25,}\b/g, "[redacted token]")
    .slice(0, 300);
  console.error("Could not register commands:", message);
  process.exitCode = 1;
});
