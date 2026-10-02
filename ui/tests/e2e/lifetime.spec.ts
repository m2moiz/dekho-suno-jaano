// How long `dsj ui` outlives its page (#206): a closed page says goodbye, and the
// server stops about BYE_S (10 s, dsj/ui/server.py) later, inside the 60 s #57 asks
// for. Its own server, because this one is meant to stop.
import { expect, test } from "@playwright/test";

import { startUi } from "./server.ts";
import { scratchDir } from "./seed.ts";

test("closing the page stops dsj ui within 60 s", async ({ browser }) => {
  // Room to wait out the whole minute, so a server that outlives it fails on
  // the line that says so rather than on the default 30 s test timeout.
  test.setTimeout(90_000);
  const server = await startUi(`${scratchDir()}/library.db`);
  try {
    const page = await (await browser.newContext()).newPage();
    await page.goto(server.url);
    await expect(page.getByRole("main")).toBeVisible();

    const closed = Date.now();
    await page.close();
    const stopped = await Promise.race([
      server.exited.then(() => true),
      new Promise<false>((resolve) => setTimeout(() => resolve(false), 60_000)),
    ]);
    expect(stopped, "dsj ui was still running 60 s after its page closed").toBe(true);
    // Well inside the minute: the goodbye stopped it, not three minutes of silence.
    expect(Date.now() - closed).toBeLessThan(30_000);
  } finally {
    await server.stop();
  }
});
