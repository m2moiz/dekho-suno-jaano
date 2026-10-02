// Unit tests (#157): Vitest with React Testing Library, run by `just check`.
// Built on vite.config.ts so a test resolves `@/` and transforms JSX exactly
// as the build does. Only tests/unit: the Playwright specs under tests/e2e
// and tests/perf run in `just verify`, in real browsers.
import { defineConfig, mergeConfig } from "vitest/config";

import viteConfig from "./vite.config.ts";

export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: "jsdom",
      include: ["tests/unit/**/*.test.{ts,tsx}"],
    },
  }),
);
