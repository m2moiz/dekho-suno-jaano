// The capability gate (#107), in real chromium and Playwright's webkit, against
// the real `dsj ui`: a browser without the CSS Custom Highlight API is told so
// and never shown a transcript it cannot follow. The unit tests
// (tests/unit/capability.test.ts) hand the gate a fake window; this deletes the
// feature from a real one before the page's own script runs, so it also proves
// main.tsx puts the gate in front of the app.
import { expect, type Page, test } from "@playwright/test";

import { readerUrl, scratchDir, seed, tone } from "./seed.ts";

const WORDS = [" Only", " a", " browser", " with", " highlights."];
const TEXT = WORDS.join("");

function transcript(audio: string) {
  const tokens = WORDS.map((w, i) => ({ t: +(i * 0.4).toFixed(2), w }));
  return {
    audio,
    model: "mlx-community/parakeet-tdt-0.6b-v3",
    text: TEXT,
    unclear: [],
    sentences: [{ start: 0, end: 2, text: TEXT, tokens }],
  };
}

/** Open a seeded transcript's page, and list every transcript the page asked the server for. */
async function openTranscript(page: Page): Promise<string[]> {
  const dir = scratchDir();
  const asked: string[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.startsWith("/api/transcripts/")) asked.push(request.url());
  });
  await page.goto(readerUrl(seed(transcript(tone(dir, 3)), dir)));
  return asked;
}

test("with CSS.highlights, the same page renders the transcript and no dialog", async ({ page }) => {
  const asked = await openTranscript(page);

  await expect(page.getByRole("article", { name: "Transcript" }).locator("p")).toHaveText(TEXT);
  expect(asked).toHaveLength(1);
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("without CSS.highlights, the unsupported browser dialog shows and no transcript renders", async ({ page }) => {
  // Before any of the page's own script: the gate runs in the first render.
  await page.addInitScript(() => {
    delete (CSS as { highlights?: unknown }).highlights;
  });

  const asked = await openTranscript(page);

  // The deletion took, or every assertion below would pass for another reason.
  expect(await page.evaluate(() => "highlights" in CSS)).toBe(false);
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("cannot run dsj's reader");
  await expect(dialog).toContainText("the CSS Custom Highlight API (Highlight and CSS.highlights)");
  await expect(dialog).toContainText("Safari 17.2, Chrome 105 or Firefox 140");
  await expect(dialog).toContainText("UnsupportedBrowser");

  // Long enough for the page to have fetched and drawn the transcript, as the
  // test above shows it does: the app never mounted, so it never asked.
  await page.waitForLoadState("networkidle");
  expect(asked).toEqual([]);
  await expect(page.getByRole("article", { name: "Transcript" })).toHaveCount(0);
  await expect(page.getByText(TEXT.trim())).toHaveCount(0);
});
