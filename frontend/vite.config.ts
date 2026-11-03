import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { readFileSync } from "node:fs";

// One version for the whole app: backend/app/config.py (the server reports the same number at /api/version,
// so a bundle built from this tree never shows "Sunucuda yeni sürüm var" against its own server).
const pkg = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf-8"));
let appVersion: string = pkg.version;
try {
  const cfg = readFileSync(new URL("../backend/app/config.py", import.meta.url), "utf-8");
  appVersion = /app_version:\s*str\s*=\s*"([^"]+)"/.exec(cfg)?.[1] ?? appVersion;
} catch {
  /* frontend built on its own (Docker stage without the backend) */
}

export default defineConfig({
  plugins: [react()],
  define: { __APP_VERSION__: JSON.stringify(appVersion) },
  server: {
    port: 5173,
    proxy: { "/api": { target: process.env.VITE_API_TARGET || "http://127.0.0.1:8000", changeOrigin: true } },
  },
  build: { chunkSizeWarningLimit: 2000, sourcemap: false },
});
