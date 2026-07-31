import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import path from "node:path";
import process from "node:process";
import type { InlineConfig } from "vitest";

const host = process.env.TAURI_DEV_HOST;

// https://vite.dev/config/
export default defineConfig(async () => ({
  plugins: [react(), tailwindcss()],
  test: {
    // private-server-ssh-profile spawns Windows PowerShell once per file it
    // validates, roughly thirteen times. That is a few seconds on a
    // workstation and over two minutes on a hosted runner, where it timed out
    // at 120 s while taking 313 s for the file. It measures the runner, not the
    // code, so it runs through `pnpm test:local` before pushing instead. Same
    // split as the release contracts.
    exclude: [
      "tests/e2e/**",
      "tests/wdio/**",
      "tests/results/**",
      "node_modules/**",
      "dist/**",
      ...(process.env.YAP_RUN_LOCAL_ONLY_TESTS === "1"
        ? []
        : ["tests/unit/private-server-ssh-profile.test.js"]),
    ],
  } satisfies InlineConfig,
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  build: {
    // Desktop shell is one app surface; split further when startup profiling says it matters.
    chunkSizeWarningLimit: 800,
    rolldownOptions: {
      checks: {
        pluginTimings: false,
      },
    },
  },

  // Vite options tailored for Tauri development and only applied in `tauri dev` or `tauri build`
  //
  // 1. prevent Vite from obscuring rust errors
  clearScreen: false,
  // 2. tauri expects a fixed port, fail if that port is not available
  server: {
    port: 1420,
    strictPort: true,
    host: host || false,
    hmr: host
      ? {
          protocol: "ws",
          host,
          port: 1421,
        }
      : undefined,
    watch: {
      // 3. tell Vite to ignore watching `src-tauri`
      ignored: ["**/src-tauri/**"],
    },
  },
}));
