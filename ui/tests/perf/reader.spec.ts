// #108's frame-time check pointed at the real reader (#58): the synthetic
// 1,038-sentence transcript adopted into the run's library, opened in the page
// `dsj ui` serves, and scrolled the way scroll.spec.ts scrolls the plain page.
// The plain page stays as the baseline the 16.7 ms number came from; this is
// the view a person reads.
import { expect, test } from "@playwright/test";

import { readerUrl, scratchDir, seed } from "../e2e/seed.ts";
import { SHAPE, syntheticTranscript } from "./fixture.ts";
import { FRAMES, P95_CEILING_MS, STEP_PX, scrollFrames, summarise } from "./sample.ts";

test("scrolling the reader over the 1,038-sentence fixture keeps p95 under 20 ms", async ({ page }) => {
  const dir = scratchDir();
  // No recording: the reader is measured as text alone, the case #58 is about.
  const seeded = seed({ ...syntheticTranscript(), audio: `${dir}/no-such-recording.wav` }, dir);
  await page.goto(readerUrl(seeded));
  await expect(page.locator("article p")).toHaveCount(SHAPE.turns);

  const dom = await page.evaluate(async () => {
    await document.fonts.ready;
    return {
      paragraphs: document.querySelectorAll("article p").length,
      wordElements: document.querySelectorAll("article p *").length,
      allNodes: document.getElementsByTagName("*").length,
      scrollHeight: document.documentElement.scrollHeight,
      viewport: window.innerHeight,
    };
  });
  expect(dom.wordElements).toBe(0);
  // The same 220 px a frame, for as many frames as the page has room for: at
  // the bottom a frame scrolls nothing and is free, which would flatter p95.
  // The reader is set tighter than the plain page (38,609 px against 50,552 on
  // 2026-10-02), so it holds about 170 of the 200; fewer than 150 would mean
  // the page shrank and the number no longer compares.
  const frames = Math.min(FRAMES, Math.floor((dom.scrollHeight - dom.viewport) / STEP_PX));
  expect(frames).toBeGreaterThanOrEqual(150);

  const result = { ...dom, frames, ...summarise((await scrollFrames(page, frames)).slice(1)) };
  console.log(`reader frame times: ${JSON.stringify(result)}`);
  expect(result.samples).toBe(frames - 1);
  expect(result.p95).toBeLessThanOrEqual(P95_CEILING_MS);
});
