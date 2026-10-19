import { defineConfig, type Plugin } from "vite";
import { readFileSync, existsSync } from "fs";
import { join } from "path";
import type { IncomingMessage, ServerResponse } from "http";

// Serve JARVIS state files to the galaxy via HTTP.
// The galaxy polls /state/galaxy-state.json, /state/galaxy-audio.json and
// /state/galaxy-events.json to learn what JARVIS is doing.
const STATE_DIR = join(process.env.HOME || "/home/kingmike", "jarvis", "state");

function statePlugin(): Plugin {
  return {
    name: "jarvis-state",
    configureServer(server) {
      server.middlewares.use((req: IncomingMessage, res: ServerResponse, next: () => void) => {
        if (!req.url?.startsWith("/state/")) {
          return next();
        }
        const filePath = join(STATE_DIR, req.url.slice("/state/".length));
        if (!existsSync(filePath)) {
          res.statusCode = 404;
          res.end("not found");
          return;
        }
        try {
          const content = readFileSync(filePath, "utf-8");
          res.setHeader("Content-Type", "application/json");
          res.setHeader("Cache-Control", "no-cache");
          res.end(content);
        } catch {
          res.statusCode = 500;
          res.end("error");
        }
      });
    },
  };
}

export default defineConfig({
  // Relative paths so the built page works when opened from disk, not just
  // when served from a web root. The spec requires it to work offline.
  base: "./",
  build: { outDir: "dist", assetsDir: "assets", sourcemap: true },
  plugins: [statePlugin()],
});
