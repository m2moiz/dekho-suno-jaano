import path from "node:path";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// `just ui-dev` runs uvicorn on this port; the dev server hands it every
// request the Python side answers, so the page talks to one origin in dev
// exactly as it does when dsj ui serves the built files.
const API = "http://127.0.0.1:8721";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": path.resolve(import.meta.dirname, "src") },
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: { "/api": API, "/media": API },
  },
  build: {
    // Committed, and inside the Python package, so `uv tool install` ships the
    // page with no Node on the machine (#57 body, correction 2).
    outDir: path.resolve(import.meta.dirname, "../dsj/ui/static"),
    emptyOutDir: true,
  },
});
