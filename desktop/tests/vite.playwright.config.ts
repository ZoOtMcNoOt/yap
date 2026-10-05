import path from "node:path";
import { defineConfig, mergeConfig } from "vite";
import desktopConfig from "../vite.config.ts";

// Browser journeys use their own artifact. The shipped build keeps its normal
// entries and production-only preview guard.
export default defineConfig(async (environment) =>
  mergeConfig(await desktopConfig(environment), {
    define: { "import.meta.env.DEV": "true" },
    build: {
      outDir: "tests/results/playwright-app",
      emptyOutDir: true,
      rolldownOptions: {
        input: [
          path.resolve(import.meta.dirname, "../index.html"),
          path.resolve(
            import.meta.dirname,
            "fixtures/archivist-ingestion-owner.html",
          ),
          path.resolve(
            import.meta.dirname,
            "fixtures/transcript-correction-owner.html",
          ),
        ],
      },
    },
  }),
);
