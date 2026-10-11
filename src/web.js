const { createServer } = require("node:http");

function createWebServer({ client, store, appState }) {
  return createServer(async (request, response) => {
    const pathname = new URL(request.url ?? "/", "http://localhost").pathname;
    response.setHeader("Cache-Control", "no-store");

    if (request.method === "GET" && pathname === "/") {
      response.writeHead(200, { "Content-Type": "text/plain; charset=utf-8" });
      response.end("Giveaway Bot is running. Health check: /healthz\n");
      return;
    }

    if (request.method === "GET" && pathname === "/healthz") {
      let databaseConnected = false;
      try {
        await store.health();
        databaseConnected = true;
      } catch {
        // Return an unhealthy status so Render can detect a database outage.
      }

      const ready = appState.initialized && databaseConnected;
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
