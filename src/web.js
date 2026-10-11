const { createServer } = require("node:http");

function createWebServer({ client, store, appState }) {
  let lastDatabaseHealthError = null;
  return createServer(async (request, response) => {
    const pathname = new URL(request.url ?? "/", "http://localhost").pathname;
    response.setHeader("Cache-Control", "no-store");

    // Liveness endpoints should answer whether this HTTP process is alive.
    // Discord can be reconnecting temporarily without the web process being down.
    if (request.method === "GET" && ["/", "/health", "/healthz", "/ping", "/uptime"].includes(pathname)) {
      response.writeHead(200, { "Content-Type": "application/json; charset=utf-8" });
      response.end(JSON.stringify({
        status: "ok",
        service: "giveaway-bot",
        discord: client.isReady() ? "connected" : "reconnecting",
      }));
      return;
    }

    if (request.method === "GET" && pathname === "/readyz") {
      let databaseConnected = false;
      try {
        await store.health();
        databaseConnected = true;
        lastDatabaseHealthError = null;
      } catch (error) {
        const code = typeof error?.code === "string" ? error.code : "UNKNOWN";
        const name = typeof error?.name === "string" ? error.name : "Error";
        const message = String(error?.message || "Unknown database error.")
          .replace(/postgres(?:ql)?:\/\/[^\s]+/gi, "[redacted database URL]")
          .replace(/\b[\w-]{24}\.[\w-]{6}\.[\w-]{25,}\b/g, "[redacted token]")
          .replace(/[\r\n]+/g, " ")
          .slice(0, 300);
        const signature = code + "/" + name + ": " + message;
        if (signature !== lastDatabaseHealthError) {
          console.error("Database health check failed: " + signature);
          lastDatabaseHealthError = signature;
        }
      }

      const ready = appState.initialized && databaseConnected && client.isReady();
      response.writeHead(ready ? 200 : 503, {
        "Content-Type": "application/json; charset=utf-8",
      });
      response.end(JSON.stringify({
        status: ready ? "ok" : "starting",
        discord: client.isReady() ? "connected" : "reconnecting",
        database: databaseConnected ? "connected" : "unavailable",
      }));
      return;
    }

    response.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
    response.end("Not found\n");
  });
}

function listen(server, port, host = "0.0.0.0") {
  return new Promise((resolve, reject) => {
    const onError = (error) => reject(error);
    server.once("error", onError);
    server.listen(port, host, () => {
      server.off("error", onError);
      resolve();
    });
  });
}

function close(server) {
  return new Promise((resolve) => {
    if (!server.listening) {
      resolve();
      return;
    }
    server.close((error) => {
      if (error) console.error("HTTP server shutdown error:", error.message);
      resolve();
    });
  });
}

module.exports = { close, createWebServer, listen };
