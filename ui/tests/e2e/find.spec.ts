// A word found with the browser's find must not land behind the player (#230),
// in real chromium and Playwright's webkit. `window.find()` stands in for
// Cmd+F, whose bar no test can open; it scrolls the match into view the way
// the bar does in both engines, as far as #230 measured. The recording is made
// here by ffmpeg, never one of the owner's (#127 trap 9).
import { expect, type Page, test } from "@playwright/test";

import { readerUrl, scratchDir, screenRecording, seed } from "./seed.ts";

// Not in TypeScript's DOM types: it was never standardised, but chromium and
// WebKit both ship it.
declare global {
  interface Window {
    find(text: string): boolean;
  }
}

// The one word to find, in sentence FOUND of SENTENCES: near the end, as in
// #230's 9,984-word transcript, so find has to scroll a long way to it.
const NEEDLE = "zanzibar";
const SENTENCES = 200;
const WORDS = 50;
const FOUND = 190;

function transcript(audio: string) {
  const sentences = Array.from({ length: SENTENCES }, (_, s) => {
    const start = s * WORDS * 0.4;
    const tokens = Array.from({ length: WORDS }, (_, i) => ({
      t: +(start + i * 0.4).toFixed(2),
      w: s === FOUND && i === WORDS / 2 ? ` ${NEEDLE}` : ` w${s}x${i}`,
    }));
    return {
      start,
      end: +(start + WORDS * 0.4).toFixed(2),
      speaker: Math.floor(s / 4) % 2,
      text: tokens.map((t) => t.w).join(""),
      tokens,
    };
  });
  return {
    audio,
    model: "mlx-community/parakeet-tdt-0.6b-v3",
    speakers: ["SPEAKER_00", "SPEAKER_01"],
    diarization: "senko 0.1.0",
    text: "",
    unclear: [],
    sentences,
  };
}

/** Find `word` from the top of the page, then say what is drawn at the middle of the match. */
async function find(page: Page, word: string) {
  return page.evaluate((word) => {
    window.scrollTo(0, 0);
    window.getSelection()?.removeAllRanges();
    if (!window.find(word)) throw new Error(`window.find did not find ${word}`);
    const box = window.getSelection()!.getRangeAt(0).getBoundingClientRect();
    const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
    const video = document.querySelector("video")!.getBoundingClientRect();
    return {
      wordTop: Math.round(box.top),
      videoTop: Math.round(video.top),
      at: hit?.tagName ?? "nothing",
      inArticle: hit?.closest("article") != null,
      scrolled: window.scrollY,
    };
  }, word);
}

// #230's three windows: two where the match landed behind the picture, and the
// 1512x870 one where it already showed.
for (const viewport of [
  { width: 800, height: 600 },
  { width: 1280, height: 725 },
  { width: 1512, height: 870 },
]) {
  test(`a word found in a video recording shows above the player at ${viewport.width}x${viewport.height}`, async ({
    page,
  }) => {
    const dir = scratchDir();
    const seeded = seed(transcript(screenRecording(dir, 4)), dir);
    await page.setViewportSize(viewport);
    await page.goto(readerUrl(seeded));
    await expect(page.locator("article p")).not.toHaveCount(0);
    // The picture shown and sized, as a person sees it before they search.
    await expect
      .poll(() => page.evaluate(() => (document.querySelector("video") as HTMLVideoElement).videoWidth))
      .toBe(640);
    await expect(page.locator("video")).toBeVisible();

    const found = await find(page, NEEDLE);
    console.log(`${viewport.width}x${viewport.height}: ${JSON.stringify(found)}`);
    expect(found.scrolled).toBeGreaterThan(0);
    expect(found.at).toBe("P");
    expect(found.inArticle).toBe(true);
  });
}
