// Click a word to hear it; the word being said is highlighted (#60). In real
// chromium and Playwright's webkit, against the real `dsj ui`, with a real
// recording served through the media route (#59).
import { expect, type Page, test } from "@playwright/test";
import { spawnSync } from "node:child_process";
import path from "node:path";

import { readerUrl, scratchDir, seed } from "./seed.ts";

type Word = { t: number; w: string };

function sentence(start: number, speaker: number, words: string[], step = 0.5) {
  const tokens: Word[] = words.map((w, i) => ({ t: +(start + i * step).toFixed(3), w }));
  return { start, end: +(start + words.length * step).toFixed(3), speaker, text: words.join(""), tokens };
}

function transcript(audio: string, sentences: ReturnType<typeof sentence>[]) {
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

/** Silence of `seconds`, small: 8 kHz mono. Its own name, so each test is its own recording. */
function silence(dir: string, seconds: number, name: string): string {
  const file = path.join(dir, name);
  const run = spawnSync(
    "ffmpeg",
    ["-y", "-loglevel", "error", "-f", "lavfi", "-i", `anullsrc=r=8000:cl=mono`, "-t", String(seconds), file],
    { encoding: "utf8" },
  );
  if (run.status !== 0) throw new Error(`ffmpeg could not write ${file}: ${run.stderr}`);
  return file;
}

/** The middle of `word`'s first box, found in the paragraph text that holds it. */
async function wordBox(page: Page, word: string, at: "middle" | "last-letter" = "middle") {
  return page.evaluate(
    ({ word, at }) => {
      for (const p of document.querySelectorAll("article p")) {
        const text = p.firstChild as Text;
        const i = text.data.indexOf(word);
        if (i < 0) continue;
        const range = document.createRange();
        if (at === "middle") {
          range.setStart(text, i);
          range.setEnd(text, i + word.length);
        } else {
          range.setStart(text, i + word.length - 1);
          range.setEnd(text, i + word.length);
        }
        const box = range.getClientRects()[0];
        if (box === undefined) break;
        // For the last letter, its right quarter: the caret rounds to the gap after it.
        const x = at === "middle" ? box.left + box.width / 2 : box.right - box.width / 4;
        return { x, y: box.top + box.height / 2 };
      }
      throw new Error(`no paragraph holds ${JSON.stringify(word)}`);
    },
    { word, at },
  );
}

/**
 * Click `word` and say where the seek went: the position as the seek starts,
 * which is what the click asked for. The seek must also finish. Read at
 * `seeked`, a playing element has already moved on from it (66 ms once in
 * webkit), which is playback, not aim.
 */
async function clickWord(page: Page, word: string, at: "middle" | "last-letter" = "middle") {
  const box = await wordBox(page, word, at);
  const seek = page.evaluate(
    () =>
      new Promise<number>((resolve) => {
        const audio = document.querySelector("audio") as HTMLAudioElement;
        let target = Number.NaN;
        audio.addEventListener("seeking", () => (target = audio.currentTime), { once: true });
        audio.addEventListener("seeked", () => resolve(target), { once: true });
      }),
  );
  await page.mouse.click(box.x, box.y);
  return seek;
}

/** Pause, let the playhead paint where it stopped, and say what it painted and when. */
async function pausedAt(page: Page) {
  return page.evaluate(async () => {
    const audio = document.querySelector("audio") as HTMLAudioElement;
    audio.pause();
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    const ranges = [...(CSS.highlights.get("dsj-playhead") ?? [])] as Range[];
    return { time: audio.currentTime, painted: ranges.map((r) => r.toString()) };
  });
}

function wordAt(sentences: ReturnType<typeof sentence>[], seconds: number): string | null {
  for (const s of sentences) {
    for (const [i, token] of s.tokens.entries()) {
      const end = s.tokens[i + 1]?.t ?? s.end;
      if (seconds >= token.t && seconds < end) return token.w.trim();
    }
  }
  return null;
}

test("clicking a word seeks to it within 50 ms and highlights that word", async ({ page }) => {
  const dir = scratchDir();
  const sentences = [
    sentence(0, 0, [" See", " this", " col", "umn", " here."]),
    sentence(2.5, 1, [" Pretty", " much", " the", " role."]),
  ];
  const seeded = seed(transcript(silence(dir, 8, "click.wav"), sentences), dir);
  await page.goto(readerUrl(seeded));
  await expect(page.locator("article p")).toHaveCount(2);
  await expect.poll(() => page.evaluate(() => document.querySelector("audio")?.readyState ?? 0)).toBeGreaterThan(0);

  // " column" is two tokens; the word starts at " col", t = 1.0.
  expect(Math.abs((await clickWord(page, "column")) - 1.0)).toBeLessThan(0.05);
  // The right edge of a word's last letter is still that word, not the next one.
  expect(Math.abs((await clickWord(page, "much", "last-letter")) - 3.0)).toBeLessThan(0.05);
  expect(Math.abs((await clickWord(page, "role.")) - 4.0)).toBeLessThan(0.05);
  const { time, painted } = await pausedAt(page);
  expect(painted).toEqual([wordAt(sentences, time)]);

  // Still plain text: the highlight added no element.
  expect(await page.locator("article p *").count()).toBe(0);
});

test("an hour in, the highlight is on the word the recording is saying", async ({ page }) => {
  test.slow();
  const dir = scratchDir();
  const sentences = [
    sentence(0, 0, [" Start."]),
    ...Array.from({ length: 6 }, (_, k) =>
      sentence(3598 + k * 2, (k + 1) % 2, [` w${3598 + k * 2}a`, ` w${3598 + k * 2}b`, ` w${3598 + k * 2}c`, ` w${3598 + k * 2}d.`]),
    ),
  ];
  const seeded = seed(transcript(silence(dir, 3612, "hour.wav"), sentences), dir);
  await page.goto(readerUrl(seeded));
  await expect(page.locator("article p")).toHaveCount(7);

  expect(Math.abs((await clickWord(page, "w3600a")) - 3600)).toBeLessThan(0.05);
  // Let it play across several words, then check where it stopped.
  await page.waitForTimeout(1300);
  const { time, painted } = await pausedAt(page);
  expect(time).toBeGreaterThan(3600.5);
  expect(painted).toEqual([wordAt(sentences, time)]);
});

test("the view follows the playhead until the reader scrolls away", async ({ page }) => {
  const dir = scratchDir();
  // 120 turns of 4 s each, alternating speakers: a page several screens tall.
  const sentences = Array.from({ length: 120 }, (_, k) =>
    sentence(k * 4, k % 2, Array.from({ length: 8 }, (_, i) => ` t${k}w${i}`)),
  );
  const seeded = seed(transcript(silence(dir, 485, "follow.wav"), sentences), dir);
  await page.goto(readerUrl(seeded));
  await expect(page.locator("article p")).toHaveCount(120);

  await clickWord(page, "t0w1");
  // Which turn the painted word is in, and whether it is on screen, read in one frame.
  const shown = () =>
    page.evaluate(() => {
      const range = [...(CSS.highlights.get("dsj-playhead") ?? [])][0] as Range | undefined;
      const box = range?.getBoundingClientRect();
      const turn = Number(/^t(\d+)w/.exec(range?.toString() ?? "")?.[1] ?? -1);
      return { turn, inView: box !== undefined && box.top >= 0 && box.bottom <= window.innerHeight };
    });
  const jump = (seconds: number) =>
    page.evaluate((s) => {
      (document.querySelector("audio") as HTMLAudioElement).currentTime = s;
    }, seconds);
  // Playing on while the check runs, so a turn or two past the jump counts.
  const near = (turn: number, inView: boolean) => (seen: { turn: number; inView: boolean }) =>
    seen.turn >= turn && seen.turn <= turn + 2 && seen.inView === inView;

  // Far down the page (turn 100 starts at 400 s): followed there.
  await jump(400);
  await expect.poll(async () => near(100, true)(await shown())).toBe(true);
  expect(await page.evaluate(() => window.scrollY)).toBeGreaterThan(1000);

  // A wheel turn means the reader is looking elsewhere: the view stays put.
  await page.mouse.wheel(0, -600);
  await expect(page.getByRole("button", { name: "Follow playback" })).toBeVisible();
  await jump(200);
  await expect.poll(async () => near(50, false)(await shown())).toBe(true);
  await page.waitForTimeout(600);
  expect(near(50, false)(await shown())).toBe(true);

  // Asked to, it follows again.
  await page.getByRole("button", { name: "Follow playback" }).click();
  await expect.poll(async () => near(50, true)(await shown())).toBe(true);
  await expect(page.getByRole("button", { name: "Follow playback" })).toHaveCount(0);
});

test("at half speed and at double speed the highlight keeps time with the recording", async ({ page }) => {
  const dir = scratchDir();
  const sentences = Array.from({ length: 6 }, (_, k) =>
    sentence(k * 4, k % 2, Array.from({ length: 8 }, (_, i) => ` s${k}w${i}`)),
  );
  const seeded = seed(transcript(silence(dir, 26, "speed.wav"), sentences), dir);
  await page.goto(readerUrl(seeded));
  await expect(page.locator("article p")).toHaveCount(6);
  await expect.poll(() => page.evaluate(() => document.querySelector("audio")?.readyState ?? 0)).toBeGreaterThan(0);

  for (const [speed, label] of [[0.5, "0.5×"], [2, "2×"]] as const) {
    await page.getByRole("combobox", { name: "Playback speed" }).click();
    await page.getByRole("option", { name: label }).click();
    expect(await page.evaluate(() => (document.querySelector("audio") as HTMLAudioElement).playbackRate)).toBe(speed);
    await clickWord(page, "s1w0");
    await page.waitForTimeout(1500);
    const { time, painted } = await pausedAt(page);
    // It played, at the rate picked. How far it got is not asserted: headless
    // Playwright WebKit plays 2x at about 1.6x of wall time (measured
    // 2026-10-02, with and without preservesPitch; chromium plays 2.0x), and
    // what matters here is that the highlight follows wherever the clock is.
    expect(time).toBeGreaterThan(4.2);
    expect(await page.evaluate(() => (document.querySelector("audio") as HTMLAudioElement).playbackRate)).toBe(speed);
    expect(painted).toEqual([wordAt(sentences, time)]);
  }
});

test("clicking the waveform moves the same playhead a word does, and the page never fetches the audio", async ({ page }) => {
  // The page's own requests go through the API client, which always sends the
  // token as a header; the <audio> element's carry it in the query instead.
  // (resourceType cannot tell them apart: WebKit does not call the element's
  // requests "media".)
  const fetched: string[] = [];
  page.on("request", (request) => {
    if (request.headers()["authorization"] !== undefined) fetched.push(new URL(request.url()).pathname);
  });
  const dir = scratchDir();
  const sentences = Array.from({ length: 10 }, (_, k) =>
    sentence(k * 4, k % 2, Array.from({ length: 8 }, (_, i) => ` v${k}w${i}`)),
  );
  const seeded = seed(transcript(silence(dir, 40, "wave.wav"), sentences), dir);
  await page.goto(readerUrl(seeded));
  await expect(page.locator("article p")).toHaveCount(10);
  await expect.poll(() => page.evaluate(() => document.querySelector("audio")?.readyState ?? 0)).toBeGreaterThan(0);

  const canvas = page.getByLabel("Waveform");
  const box = await canvas.boundingBox();
  if (box === null) throw new Error("the waveform is not on the page");
  const seek = page.evaluate(
    () =>
      new Promise<number>((resolve) => {
        const audio = document.querySelector("audio") as HTMLAudioElement;
        audio.addEventListener("seeking", () => resolve(audio.currentTime), { once: true });
      }),
  );
  // A quarter of the way along 40 s.
  await page.mouse.click(box.x + box.width / 4, box.y + box.height / 2);
  expect(Math.abs((await seek) - 10)).toBeLessThan(0.5);
  const { time, painted } = await pausedAt(page);
  expect(painted).toEqual([wordAt(sentences, time)]);
  const cursorX = await page.evaluate(() => {
    const cursor = document.querySelector('[aria-label="Waveform"] + div') as HTMLElement;
    return new DOMMatrixReadOnly(getComputedStyle(cursor).transform).m41;
  });
  expect(Math.abs(cursorX - (time / 40) * box.width)).toBeLessThan(2);

  // What the page itself asked for: the envelope, never the recording.
  const route = `/api/recording/${seeded.recording}`;
  expect(fetched).toContain(`${route}/waveform`);
  expect(fetched.filter((p) => p.startsWith(`${route}/media`))).toEqual([]);
});

// The rail's controls are 44 px tall on a phone and never under 36 on a laptop.
// The Select primitive's own `data-[size=sm]:h-7` once beat the rail's h-11, and
// only a measured box shows that (jsdom lays nothing out).
for (const [label, viewport, least] of [
  ["a phone", { width: 390, height: 844 }, 44],
  ["a laptop", { width: 1440, height: 900 }, 36],
] as const) {
  test(`on ${label} the speed select and the play button are at least ${least} px tall`, async ({ page }) => {
    await page.setViewportSize(viewport);
    const dir = scratchDir();
    const seeded = seed(transcript(silence(dir, 8, "rail.wav"), [sentence(0, 0, [" One", " two."])]), dir);
    await page.goto(readerUrl(seeded));
    for (const control of [page.getByRole("combobox", { name: "Playback speed" }), page.getByRole("button", { name: "Play" })]) {
      const box = await control.boundingBox();
      if (box === null) throw new Error("a rail control is not on the page");
      expect(box.height).toBeGreaterThanOrEqual(least);
    }
  });
}

// One gold action per screen (DESIGN.md, The One Gold Rule; Task 16a review I2;
// critique 7 Oct P1-2): the rail's play is a control, outlined on the field, so
// the screen's gold action (Review, Checked next) is the only gold button. And
// the phone shows the time too (critique P2-9), which `hidden sm:inline` hid.
for (const viewport of [{ width: 390, height: 844 }, { width: 1440, height: 900 }]) {
  test(`at ${viewport.width} px the rail's play is not gold, and the time shows`, async ({ page }) => {
    await page.setViewportSize(viewport);
    const dir = scratchDir();
    const seeded = seed(transcript(silence(dir, 8, `rail-gold-${viewport.width}.wav`), [sentence(0, 0, [" One", " two."])]), dir);
    await page.goto(readerUrl(seeded));
    const play = page.getByRole("button", { name: "Play" });
    const fill = await play.evaluate((element) => getComputedStyle(element).backgroundColor);
    expect(fill).not.toBe("rgb(200, 162, 74)");
    const rail = page.getByRole("region", { name: "Player" });
    await expect(rail.getByText(/^0:00 \/ 0:0\d$/)).toBeVisible();
  });
}
