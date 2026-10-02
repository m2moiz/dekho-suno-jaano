// Browser tests (#157), run by `just verify` and never by `just check`:
// browsers are slow, and a gate that gets slow is a gate agents skip (#96).
//
// What this deliberately does NOT test, so nobody reads a green run as more:
//
// 1. Real Safari. The `webkit` project is Playwright's own WebKit build, a
//    stand-in that catches WebKit-against-Blink differences, not the browser
//    `dsj ui` opens on this Mac (#57 first comment, F6). Real Safari is checked
//    by hand, once per milestone, and labelled as a manual step (#127 step 8).
// 2. Frame times in CI. The scroll check (#108) runs here on this Mac, where a
//    frame time means something; on a shared CI runner it would be flaky, and
//    a flaky gate gets switched off (#57 F8). CI runs `just check` only.
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  globalSetup: "./tests/e2e/global-setup.ts",
  // A failure is a failure: no retries that turn a flaky page green.
  retries: 0,
  forbidOnly: true,
  reporter: "list",
  projects: [
    { name: "chromium", testDir: "tests/e2e", use: { ...devices["Desktop Chrome"] } },
    { name: "webkit", testDir: "tests/e2e", use: { ...devices["Desktop Safari"] } },
    // Chromium only: the 16.7 ms baseline it is compared with was measured there.
    { name: "perf", testDir: "tests/perf", use: { ...devices["Desktop Chrome"] } },
  ],
});
