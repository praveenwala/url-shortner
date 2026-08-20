import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist" },
  // Without this the dev server answers /v1 with the SPA fallback — index.html
  // at HTTP 200 — and every API call silently becomes an HTML page. The proxy
  // lives here rather than in the client so the client keeps using relative
  // URLs and no host is compiled into production logic.
  server: {
    proxy: {
      "/v1": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/health": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.tsx", "tests/**/*.test.ts"],
  },
});
