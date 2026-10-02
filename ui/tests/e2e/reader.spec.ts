// The reader, in real chromium and Playwright's webkit, against the real `dsj
// ui` and a transcript adopted into its library (#58).
import { expect, test } from "@playwright/test";

import { readerUrl, scratchDir, seed, tone } from "./seed.ts";

function sentence(start: number, speaker: number, words: string[]) {
  const tokens = words.map((w, i) => ({ t: +(start + i * 0.4).toFixed(2), w }));
  return { start, end: +(start + words.length * 0.4).toFixed(2), speaker, text: words.join(""), tokens };
}

// Two speakers, three turns. The middle sentence's `text` says something its
// tokens do not, as a chunk seam once wrote (#106): the page must draw the tokens.
function transcript(audio: string) {
  const seam = sentence(3, 1, [" Pretty", " much", " the", " the", " role."]);
  return {
    audio,
    model: "mlx-community/parakeet-tdt-0.6b-v3",
    speakers: ["SPEAKER_00", "SPEAKER_01"],
    diarization: "senko 0.1.0",
    text: "",
    unclear: [],
    sentences: [
      sentence(0, 0, [" See", " this", " col", "umn", " here."]),
      { ...seam, text: " Pretty much the role to the person." },
      sentence(6, 1, [" Yes."]),
      sentence(8, 0, [" Fine", " then."]),
    ],
  };
}

test("a transcript opened from the library reads as typeset paragraphs", async ({ page }) => {
  const dir = scratchDir();
  const seeded = seed(transcript(tone(dir, 12)), dir);
  const library = new URL(readerUrl(seeded));
  library.search = "";
  await page.goto(library.toString());

  // By its address: each browser's run seeds the same tone, so the library
  // lists both transcripts under one recording, with the same model.
  const href = `/?recording=${seeded.recording}&transcript=${seeded.transcript}`;
  const link = page.locator(`a[href="${href}"]`);
  await expect(link).toContainText("parakeet-tdt-0.6b-v3");
  await link.click();
  await expect(page).toHaveURL(new RegExp(`\\${href.slice(1)}$`));

  const article = page.getByRole("article", { name: "Transcript" });
  await expect(article.locator("p")).toHaveCount(3);
  // Exactly, leading spaces and all: no whitespace folding between the file and the page.
  expect(await article.locator("p").allTextContents()).toEqual([
    " See this column here.",
    " Pretty much the the role. Yes.",
    " Fine then.",
  ]);
  expect(await article.locator("h2").allTextContents()).toEqual([
    "Speaker 1 · 0:00",
    "Speaker 2 · 0:03",
    "Speaker 1 · 0:08",
  ]);

  const layout = await page.evaluate(async () => {
    await document.fonts.ready;
    const p = document.querySelector("article p");
    const art = document.querySelector("article");
    if (p === null || art === null) throw new Error("no transcript on the page");
    const style = getComputedStyle(p);
    // 68 zeros in the transcript's own face: what `68ch` means.
    const probe = document.createElement("span");
    probe.textContent = "0".repeat(68);
    probe.style.whiteSpace = "pre";
    art.append(probe);
    const measure = probe.getBoundingClientRect().width;
    probe.remove();
    return {
      wordElements: document.querySelectorAll("article p *").length,
      lineHeight: parseFloat(style.lineHeight) / parseFloat(style.fontSize),
      maxWidth: parseFloat(getComputedStyle(art).maxWidth),
      measure,
      align: style.textAlign,
      // Loaded, not merely asked for: a face that never arrived falls back silently.
      font: [...document.fonts].some((f) => f.family.includes("Literata") && f.status === "loaded"),
      family: style.fontFamily,
    };
  });
  expect(layout.wordElements).toBe(0);
  expect(layout.lineHeight).toBeCloseTo(1.7, 2);
  expect(Math.abs(layout.maxWidth - layout.measure)).toBeLessThan(1);
  expect(layout.align).toBe("left");
  // WebKit drops the quotes when it serialises the name; Chromium keeps them.
  expect(layout.family).toMatch(/^"?Literata Variable"?,/);
  expect(layout.font).toBe(true);

  // Select all, as Cmd+A does: the selection, which is what copy takes, holds
  // every word of every turn.
  await article.click({ position: { x: 5, y: 5 } });
  await page.keyboard.press("ControlOrMeta+a");
  const selected = await page.evaluate(() => window.getSelection()?.toString() ?? "");
  for (const words of ["See this column here.", "Pretty much the the role. Yes.", "Fine then."]) {
    expect(selected).toContain(words);
  }
});
