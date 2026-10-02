// #108's frame-time check pointed at the real reader (#58): the synthetic
// 1,038-sentence transcript adopted into the run's library, opened in the page
// `dsj ui` serves, and scrolled the way scroll.spec.ts scrolls the plain page.
// The plain page stays as the baseline the 16.7 ms number came from; this is
// the view a person reads. The second test times the playhead's own tick
// (#60), against the 5 ms p95 #57 section 12 set for it.
import { expect, test } from "@playwright/test";
import { spawnSync } from "node:child_process";
import path from "node:path";

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

// #57 section 12: "playhead tick p95 > 5 ms" fails the perf check.
const TICK_P95_CEILING_MS = 5;

test("the playhead's tick stays under 5 ms at p95 while it follows the fixture", async ({ page }) => {
  test.slow();
  const dir = scratchDir();
  // Silence as long as the fixture (6,305 s), 8 kHz mono so it is 100 MB, not 600.
  const audio = path.join(dir, "fixture.wav");
  const made = spawnSync("ffmpeg", ["-y", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono", "-t", "6310", audio]);
  expect(made.status).toBe(0);
  const seeded = seed({ ...syntheticTranscript(), audio }, dir);
  await page.goto(readerUrl(seeded));
  await expect(page.locator("article p")).toHaveCount(SHAPE.turns);
  await expect.poll(() => page.evaluate(() => document.querySelector("audio")?.readyState ?? 0)).toBeGreaterThan(0);

  // Start it the way a person does, by clicking a word, then make the
  // playhead work: 4x speed, and a jump to a far part of the transcript every
  // half second, each of which the view follows.
  const box = await page.evaluate(() => {
    const range = document.createRange();
    const text = document.querySelector("article p")?.firstChild as Text;
    range.setStart(text, 1);
    range.setEnd(text, 3);
    const rect = range.getBoundingClientRect();
    return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
  });
  await page.mouse.click(box.x, box.y);
  const frames = await page.evaluate(
    () =>
      new Promise<number[]>((resolve) => {
        const audio = document.querySelector("audio") as HTMLAudioElement;
        audio.muted = true;
        audio.playbackRate = 4;
        const times: number[] = [];
        let last = performance.now();
        let jumps = 0;
        const jumper = setInterval(() => {
          audio.currentTime = ((jumps * 1777) % 6200) + 30;
          jumps += 1;
        }, 500);
        const frame = () => {
          const now = performance.now();
          times.push(now - last);
          last = now;
          if (times.length < 300) requestAnimationFrame(frame);
          else {
            clearInterval(jumper);
            audio.pause();
            resolve(times.slice(1));
          }
        };
        requestAnimationFrame(frame);
      }),
  );
  const ticks = await page.evaluate(() => window.dsjPlayheadTicks?.() ?? []);
  const tick = summarise(ticks);
  console.log(`playhead tick ms: ${JSON.stringify(tick)}; frames while playing: ${JSON.stringify(summarise(frames))}`);
  expect(tick.samples).toBeGreaterThan(200);
  expect(tick.p95).toBeLessThanOrEqual(TICK_P95_CEILING_MS);
});

test("switching the unsure-word tint on keeps scroll p95 under 20 ms", async ({ page }) => {
  const dir = scratchDir();
  // The fixture with a confidence on every token, one token in ten under
  // whisper's cut-off, so about a tenth of the words are tinted, as on the real
  // transcript the cut-off was measured on (#62).
  const fixture = syntheticTranscript();
  let n = 0;
  const sentences = fixture.sentences.map((s) => ({
    ...s,
    tokens: s.tokens.map((t) => ({ ...t, c: n++ % 10 === 0 ? 0.3 : 0.95 })),
  }));
  const seeded = seed(
    { ...fixture, model: "mlx-community/whisper-large-v3-turbo", sentences, audio: `${dir}/none.wav` },
    dir,
  );
  await page.goto(readerUrl(seeded));
  await expect(page.locator("article p")).toHaveCount(SHAPE.turns);
  await page.getByRole("button", { name: /^Unsure words/ }).click();
  const tinted = await page.evaluate(async () => {
    await document.fonts.ready;
    return {
      ranges: CSS.highlights.get("dsj-unsure")?.size ?? 0,
      scrollHeight: document.documentElement.scrollHeight,
      viewport: window.innerHeight,
    };
  });
  expect(tinted.ranges).toBeGreaterThan(1000);
  const frames = Math.min(FRAMES, Math.floor((tinted.scrollHeight - tinted.viewport) / STEP_PX));
  expect(frames).toBeGreaterThanOrEqual(150);
  const result = { ...tinted, frames, ...summarise((await scrollFrames(page, frames)).slice(1)) };
  console.log(`tinted reader frame times: ${JSON.stringify(result)}`);
  expect(result.p95).toBeLessThanOrEqual(P95_CEILING_MS);
});
