import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The dev server and preview listen on 127.0.0.1 only and proxy /api to the
// loopback-only FastAPI backend, so the browser talks to a single local origin.
const api = { "/api": { target: "http://127.0.0.1:8000", changeOrigin: false } };

export default defineConfig({
  plugins: [react()],
  server: { host: "127.0.0.1", port: 5173, strictPort: true, proxy: api },
  preview: { host: "127.0.0.1", port: 4173, strictPort: true, proxy: api },
  test: { environment: "node", include: ["src/**/*.test.{ts,tsx}"] },
});
