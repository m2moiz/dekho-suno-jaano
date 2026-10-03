// Reviewing the words to bleep in the app (#84), in real chromium and
// Playwright's webkit, against the real `dsj ui`: a word added from the app
// lands in the user's list (a temp file, global-setup.ts), the next pass
// matches it, and playing over it is silent exactly where a render would be.
import { readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

import { editableTranscript, painted } from "./editable.ts";
import { readerUrl, scratchDir, seed, tone } from "./seed.ts";

// Where "foxtrot" is in the transcript below (editable.ts spaces the words),
// and the span dsj.hatao.spans_to_mute makes of it: 0.1 s either side.
const FOXTROT = { start: 3.2, end: 3.55 };
const SPAN = { start: 3.1, end: 3.65 };
// One frame at 60 Hz, the most the live mute may run late or early by.
const FRAME_S = 1 / 60;

test("a word added from the app is matched, muted live where a render mutes, and undone", async ({ page }, info) => {
  // The run's one word list is shared by every browser's run of this test, so
  // each adds a word of its own, which no other transcript holds.
  const word = `foxtrot${info.project.name}`;
  const dir = scratchDir();
  const seeded = seed(
    editableTranscript(tone(dir, 8), [
      ["alpha", "bravo", "charlie", "delta"],
      ["echo", word, "golf", "hotel"],
    ]),
    dir,
  );
  await page.goto(readerUrl(seeded));
  const panel = page.getByRole("region", { name: "Words to bleep" });
  await expect(panel.getByRole("status")).toContainText("No word matched: 8 words searched");

  await panel.getByRole("textbox", { name: "A word to add to your list" }).fill(word);
  await panel.getByRole("button", { name: "Add" }).click();
  const row = panel.getByRole("listitem", { name: word });
  await expect(row).toContainText("0:03.2");
  await expect(row).toContainText(`user:${word}`);
  await expect(row).toContainText("muted");
  await expect.poll(() => painted(page, "dsj-muted")).toEqual([word]);
  expect(readFileSync(process.env["DSJ_WORDS"] ?? "", "utf8")).toContain(`roman = ["${word}"]`);
  await expect(page.getByRole("toolbar", { name: "Edit" }).getByRole("status")).toHaveText("Saved");

  // Every frame, the time and whether the sound is off, while the match is auditioned.
  await page.evaluate(() => {
    const audio = document.querySelector("audio") as HTMLAudioElement;
    const samples: [number, boolean][] = [];
    (window as unknown as { samples: typeof samples }).samples = samples;
    const look = () => {
      if (!audio.paused) samples.push([audio.currentTime, audio.muted]);
      requestAnimationFrame(look);
    };
    requestAnimationFrame(look);
  });
  await row.getByRole("button", { name: "Hear" }).click();
  // Played from a second before the word, and stopped a second after it.
  await expect
    .poll(() => page.evaluate(() => (document.querySelector("audio") as HTMLAudioElement).paused), { timeout: 8000 })
    .toBe(true);
  const samples = await page.evaluate(() => (window as unknown as { samples: [number, boolean][] }).samples);
  const stoppedAt = await page.evaluate(() => (document.querySelector("audio") as HTMLAudioElement).currentTime);
  expect(stoppedAt).toBeGreaterThanOrEqual(FOXTROT.end + 1);
  expect(stoppedAt).toBeLessThan(FOXTROT.end + 1.2);
  expect(samples[0]?.[0] ?? 0).toBeLessThan(FOXTROT.start - 0.9);
  const silent = samples.filter(([, muted]) => muted).map(([t]) => t);
  console.log(
    `${info.project.name}: ${samples.length} frames, silent from ${Math.min(...silent).toFixed(3)} to ` +
      `${Math.max(...silent).toFixed(3)} s against the span ${SPAN.start} to ${SPAN.end} s; stopped at ${stoppedAt.toFixed(3)} s`,
  );
  const inside = samples.filter(([t]) => t > SPAN.start + FRAME_S && t < SPAN.end - FRAME_S);
  const outside = samples.filter(([t]) => t < SPAN.start - 2 * FRAME_S || t > SPAN.end + 2 * FRAME_S);
  expect(inside.length).toBeGreaterThan(10);
  expect(inside.every(([, muted]) => muted)).toBe(true);
  expect(outside.length).toBeGreaterThan(60);
  expect(outside.every(([, muted]) => !muted)).toBe(true);

  // Dismissed, it plays; one undo mutes it again.
  await row.getByRole("button", { name: "Dismiss" }).click();
  await expect(row).toContainText("dismissed");
  await expect.poll(() => painted(page, "dsj-muted")).toEqual([]);
  await page.keyboard.press("ControlOrMeta+z");
  await expect(row).toContainText("muted");
  await expect.poll(() => painted(page, "dsj-muted")).toEqual([word]);
});
