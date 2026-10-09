// The four things v0.3.0 promises a person can do, walked end to end (#158):
// see the library, read a transcript, click a word to hear it, and keep the
// theme across a restart of `dsj ui`. In real chromium and Playwright's webkit
// (not Safari, #57 F6), against the real `dsj ui --print-url`, each run on a
// library of its own in a temporary folder: two recordings ffmpeg makes, and
// transcripts written here by hand. Nothing comes from a real recording.
import { expect, type Page, test } from "@playwright/test";

import { type Server, startUi } from "./server.ts";
import { adoptInto, recordRunInto, scratchDir, tone } from "./seed.ts";

type Word = { t: number; w: string };

function sentence(start: number, speaker: number, words: string[], step = 0.5) {
  const tokens: Word[] = words.map((w, i) => ({ t: +(start + i * step).toFixed(3), w }));
  return { start, end: +(start + words.length * step).toFixed(3), speaker, text: words.join(""), tokens };
}

// Three turns between two speakers: the reader's paragraphs are one per turn.
const STANDUP = [
  sentence(0, 0, [" See", " this", " column", " here."]),
  sentence(2, 0, [" It", " moved."]),
  sentence(3.5, 1, [" Pretty", " much", " the", " role."]),
  sentence(6, 0, [" Fine", " then."]),
];

function transcript(audio: string, model: string, extra: object = {}) {
  return { audio, model, text: "", unclear: [], sentences: STANDUP, ...extra };
}

/** A library of two recordings: one transcribed from the app, one adopted from before it. */
function twoRecordings(dir: string) {
  const library = `${dir}/library.db`;
  // From the app: the run says which engine it was.
  const standup = recordRunInto(
    library,
    transcript(tone(dir, 9, "standup.wav"), "mlx-community/parakeet-tdt-0.6b-v3", {
      speakers: ["SPEAKER_00", "SPEAKER_01"],
      diarization: "senko 0.1.0",
    }),
    dir,
    "parakeet",
  );
  // Adopted: a transcript written before the library, which names its engine itself (#172).
  // A second longer, or the library would rightly know it as the same recording.
  const review = adoptInto(
    library,
    transcript(tone(dir, 10, "review.wav"), "mlx-community/whisper-large-v3-turbo", { engine: "whisper" }),
    dir,
  );
  return { library, standup, review };
}

let server: Server;
let ids: ReturnType<typeof twoRecordings>;

test.beforeAll(async () => {
  const dir = scratchDir();
  ids = twoRecordings(dir);
  server = await startUi(ids.library);
});

test.afterAll(async () => {
  await server.stop();
});

test.describe("journey 1: see the library", () => {
  // Titled by file name without its extension: neither name holds a date.
  test("both recordings are listed by title, each with its date, engine and model under Details", async ({ page }) => {
    await page.goto(server.url);
    const rows = page.getByRole("list", { name: "Recordings" }).getByRole("listitem", { name: /^(standup|review)$/ });
    await expect(rows).toHaveCount(2);
    // A date as the reader's own clock writes it: the year, at least, and a time.
    const date = /\b20\d\d\b.*\d{1,2}:\d{2}/;
    const standup = page.getByRole("listitem", { name: "standup" });
    await expect(standup.getByRole("link", { name: "standup" })).toBeVisible();
    await expect(standup.getByRole("img", { name: "2 speakers" })).toBeVisible();
    // The model is a detail, not the row's subtitle (critique: "model repo ID as subtitle").
    await expect(standup).not.toContainText("mlx-community");
    await standup.getByRole("button", { name: "Details" }).click();
    const made = standup.locator("dt", { hasText: "Made" }).locator("+ dd");
    await expect(made).toHaveText(date);
    await expect(made).toContainText("parakeet");
    await expect(standup.locator("dt", { hasText: "Model" }).locator("+ dd")).toHaveText("mlx-community/parakeet-tdt-0.6b-v3");
    await expect(standup.locator("dt", { hasText: "Speakers" }).locator("+ dd")).toHaveText("2 speakers");
    const review = page.getByRole("listitem", { name: "review" });
    await review.getByRole("button", { name: "Details" }).click();
    await expect(review.locator("dt", { hasText: "Made" }).locator("+ dd")).toHaveText(date);
    await expect(review.locator("dt", { hasText: "Made" }).locator("+ dd")).toContainText("whisper");
    await expect(review.locator("dt", { hasText: "Model" }).locator("+ dd")).toHaveText("mlx-community/whisper-large-v3-turbo");
  });
});

/** Open the standup's transcript the way a person does: from its line in the library. */
async function openStandup(page: Page) {
  await page.goto(server.url);
  await page.getByRole("listitem", { name: "standup" }).getByRole("link", { name: "standup" }).click();
  await expect(page).toHaveURL(new RegExp(`recording=${ids.standup.recording}&transcript=${ids.standup.transcript}$`));
  await expect(page.getByRole("article", { name: "Transcript" }).locator("p")).toHaveCount(3);
}

test.describe("journey 2: open a transcript and read it", () => {
  test("it reads as one paragraph per speaker turn, with no element per word", async ({ page }) => {
    await openStandup(page);
    const article = page.getByRole("article", { name: "Transcript" });
    expect(await article.locator("p").allTextContents()).toEqual([
      " See this column here. It moved.",
      " Pretty much the role.",
      " Fine then.",
    ]);
    expect(await article.locator("p *").count()).toBe(0);
    expect(await page.locator("pre").count()).toBe(0);
  });
});

test.describe("journey 3: click a word and hear it", () => {
  test("the recording seeks to within 50 ms of the word, and the highlight sits on that word", async ({ page }) => {
    await openStandup(page);
    await expect.poll(() => page.evaluate(() => document.querySelector("audio")?.readyState ?? 0)).toBeGreaterThan(0);
    for (const [word, t] of [["role.", 5.0], ["column", 1.0], ["Fine", 6.0]] as const) {
      const box = await page.evaluate((word) => {
        for (const p of document.querySelectorAll("article p")) {
          const text = p.firstChild as Text;
          const i = text.data.indexOf(word);
          if (i < 0) continue;
          const range = document.createRange();
          range.setStart(text, i);
          range.setEnd(text, i + word.length);
          const rect = range.getBoundingClientRect();
          return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
        }
        throw new Error(`no paragraph holds ${word}`);
      }, word);
      // Where the seek was aimed, read as it starts: by `seeked` a playing
      // element has already moved on from it.
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
      expect(Math.abs((await seek) - t)).toBeLessThan(0.05);
      const painted = await page.evaluate(async () => {
        (document.querySelector("audio") as HTMLAudioElement).pause();
        await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
        return [...(CSS.highlights.get("dsj-playhead") ?? [])].map((r) => (r as Range).toString());
      });
      // Paused at once after the seek, so still inside the word clicked.
      expect(painted).toEqual([word]);
    }
  });
});

test.describe("journey 4: change the theme, quit, start again, see it kept", () => {
  // The Mac in light mode, so a dark page can only be the choice kept.
  test.use({ colorScheme: "light" });

  /** The page's own background, as lightness from 0 (black) to 1 (white). */
  async function lightness(page: Page): Promise<number> {
    return page.evaluate(() => {
      const probe = document.createElement("canvas").getContext("2d");
      if (probe === null) throw new Error("no 2d canvas");
      probe.fillStyle = getComputedStyle(document.body).backgroundColor;
      probe.fillRect(0, 0, 1, 1);
      const [r, g, b] = probe.getImageData(0, 0, 1, 1).data;
      return (0.2126 * (r ?? 0) + 0.7152 * (g ?? 0) + 0.0722 * (b ?? 0)) / 255;
    });
  }

  test("Dark, chosen before a restart of dsj ui on a new port, is still Dark after it", async ({ page }) => {
    const dir = scratchDir();
    const library = `${dir}/library.db`;
    const first = await startUi(library);
    let second: Server | null = null;
    try {
      await page.goto(first.url);
      await page.getByRole("button", { name: "Settings" }).click();
      await expect(page.getByRole("menuitemradio", { name: "Same as the Mac" })).toHaveAttribute("aria-checked", "true");
      expect(await lightness(page)).toBeGreaterThan(0.8);
      await page.getByRole("menuitemradio", { name: "Dark" }).click();
      await expect.poll(() => lightness(page)).toBeLessThan(0.2);

      // Quit it, as a person would, and start it again: a new port, a new token.
      await first.stop();
      second = await startUi(library);
      expect(new URL(second.url).port).not.toBe(new URL(first.url).port);
      await page.goto(second.url);
      await page.getByRole("button", { name: "Settings" }).click();
      await expect(page.getByRole("menuitemradio", { name: "Dark" })).toHaveAttribute("aria-checked", "true");
      expect(await page.evaluate(() => document.documentElement.style.colorScheme)).toBe("dark");
      expect(await lightness(page)).toBeLessThan(0.2);
    } finally {
      await first.stop();
      await second?.stop();
    }
  });
});
