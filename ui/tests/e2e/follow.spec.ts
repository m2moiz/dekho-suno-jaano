// While a video recording plays, the word being said stays above the player
// (#231), in real chromium and Playwright's webkit. The follow band once ran
// to 75% of the window whatever covered it, and at 800x600 the player starts
// at 45%: the word played on under the picture and nothing scrolled. The
// recording is made here by ffmpeg, never one of the owner's (#127 trap 9).
import { expect, type Page, test } from "@playwright/test";

import { readerUrl, scratchDir, screenRecording, seed } from "./seed.ts";

const SENTENCES = 40;
const WORDS = 50;
const STEP = 0.4;
// Sentence 3's first word, 60 s in: inside the 120 s recording, with three
// sentences above it to scroll past.
const WORD = "w3x0";
const AT = 3 * WORDS * STEP;
// Where the word is put before it is played: under the player at 800x600 and
// 1280x725, above it at 1512x870 (#230 measured the player's top at 273, 354
// and 448 px).
const PLACED = 400;

function transcript(audio: string) {
  const sentences = Array.from({ length: SENTENCES }, (_, s) => {
    const start = s * WORDS * STEP;
    const tokens = Array.from({ length: WORDS }, (_, i) => ({ t: +(start + i * STEP).toFixed(2), w: ` w${s}x${i}` }));
    return {
      start,
      end: +(start + WORDS * STEP).toFixed(2),
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

/** Where the word being played is drawn, and what is drawn at its middle. */
async function playing(page: Page) {
  return page.evaluate(() => {
    const painted = [...(CSS.highlights.get("dsj-playhead") ?? [])] as Range[];
    if (painted.length !== 1) throw new Error(`${painted.length} words painted as playing`);
    const box = painted[0]!.getBoundingClientRect();
    const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
    const bar = document.querySelector("video")!.closest(".sticky")!.getBoundingClientRect();
    return {
      word: painted[0]!.toString(),
      top: Math.round(box.top),
      barTop: Math.round(bar.top),
      at: hit?.tagName ?? "nothing",
      inArticle: hit?.closest("article") != null,
      scrolled: Math.round(window.scrollY),
    };
  });
}

for (const { width, height, covered } of [
  { width: 800, height: 600, covered: true },
  { width: 1280, height: 725, covered: true },
  { width: 1512, height: 870, covered: false },
]) {
  test(`a played word stays above the player at ${width}x${height}`, async ({ page }) => {
    const dir = scratchDir();
    const seeded = seed(transcript(screenRecording(dir, 120)), dir);
    await page.setViewportSize({ width, height });
    await page.goto(readerUrl(seeded));
    await expect(page.locator("article p")).not.toHaveCount(0);
    await expect
      .poll(() => page.evaluate(() => (document.querySelector("video") as HTMLVideoElement).videoWidth))
      .toBe(640);

    // The word put at PLACED, then the video seeked to it while paused: the
    // playhead paints it once and decides whether to scroll.
    const placed = await page.evaluate(
      async ({ word, at, placed }) => {
        const text = document.querySelector("article p")!.firstChild as Text;
        const i = text.data.indexOf(word);
        const range = document.createRange();
        range.setStart(text, i);
        range.setEnd(text, i + word.length);
        window.scrollBy(0, range.getBoundingClientRect().top - placed);
        const scrolled = Math.round(window.scrollY);
        const video = document.querySelector("video") as HTMLVideoElement;
        await new Promise<void>((resolve) => {
          video.addEventListener("seeked", () => resolve(), { once: true });
          video.currentTime = at + 0.05;
        });
        return { top: Math.round(range.getBoundingClientRect().top), scrolled };
      },
      { word: WORD, at: AT, placed: PLACED },
    );
    // Within a pixel: WebKit scrolls by whole pixels and the line sits at a
    // fraction of one (measured 400.83 at 800x600 under the margin grid).
    expect(Math.abs(placed.top - PLACED)).toBeLessThanOrEqual(1);
    // Long enough for a smooth scroll to finish.
    await page.waitForTimeout(1500);
    const seeked = await playing(page);
    console.log(`${width}x${height} seeked: ${JSON.stringify(seeked)}`);
    expect(seeked.word).toBe(WORD);
    expect(seeked.inArticle).toBe(true);
    // Where the word was already in sight, the view stays where it was.
    if (!covered) expect(seeked.scrolled).toBe(placed.scrolled);

    // And while it plays: two seconds, five words, then where the last one is.
    await page.evaluate(() => {
      const video = document.querySelector("video") as HTMLVideoElement;
      video.muted = true;
      return video.play();
    });
    await page.waitForTimeout(2000);
    await page.evaluate(() => (document.querySelector("video") as HTMLVideoElement).pause());
    await page.waitForTimeout(1000);
    const played = await playing(page);
    console.log(`${width}x${height} played: ${JSON.stringify(played)}`);
    expect(played.word).not.toBe(WORD);
    expect(played.inArticle).toBe(true);
  });
}
