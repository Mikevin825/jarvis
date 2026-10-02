import { defineConfig } from "vite";

export default defineConfig({
  // Relative paths so the built page works when opened from disk, not just
  // when served from a web root. The spec requires it to work offline.
  base: "./",
  build: { outDir: "dist", assetsDir: "assets", sourcemap: true },
});
