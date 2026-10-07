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
  // Who and when, in the margin beside each turn (Hashiya spec, "The margin").
  expect(await article.locator(".nameplate").allTextContents()).toEqual(["Speaker 1", "Speaker 2", "Speaker 1"]);
  expect(await article.locator("[data-margin] time").allTextContents()).toEqual(["0:00", "0:03", "0:08"]);
  await expect(article.getByRole("listitem")).toHaveCount(3);

  const layout = await page.evaluate(async () => {
    await document.fonts.ready;
    const p = document.querySelector<HTMLElement>("article p");
    const turn = p?.parentElement;
    if (p === null || turn == null) throw new Error("no transcript on the page");
    const style = getComputedStyle(p);
    // 68 zeros in the turn's own face: what the text column's `68ch` means.
    // Out of flow, so the turn's grid does not squeeze it into a column.
    const probe = document.createElement("span");
    probe.textContent = "0".repeat(68);
    probe.style.whiteSpace = "pre";
    probe.style.position = "absolute";
    turn.append(probe);
    const measure = probe.getBoundingClientRect().width;
    probe.remove();
    return {
      wordElements: document.querySelectorAll("article p *").length,
      lineHeight: parseFloat(style.lineHeight) / parseFloat(style.fontSize),
      width: p.getBoundingClientRect().width,
      measure,
      align: style.textAlign,
      // Loaded, not merely asked for: a face that never arrived falls back silently.
      font: [...document.fonts].some((f) => f.family.includes("Literata") && f.status === "loaded"),
      family: style.fontFamily,
    };
  });
  expect(layout.wordElements).toBe(0);
  expect(layout.lineHeight).toBeCloseTo(1.7, 2);
  expect(Math.abs(layout.width - layout.measure)).toBeLessThan(1);
  expect(layout.align).toBe("start");
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

// Urdu as Urdu (Hashiya spec, Type), and Review Focus 1: a turn that opens in
// Urdu script is set right to left in Nastaliq at about 1.3x with 2.1
// leading, a number and an English word inside it keep their own order, a
// click on that English word still seeks to it, and a turn that opens in
// English stays left to right. The sentences are made up for this test.
test("an Urdu turn is set right to left in Nastaliq, and a mixed line keeps its words in order", async ({ page }) => {
  const dir = scratchDir();
  const seeded = seed(
    {
      audio: tone(dir, 13, "urdu.wav"),
      model: "mlx-community/whisper-large-v3-turbo",
      speakers: ["SPEAKER_00", "SPEAKER_01"],
      diarization: "senko 0.1.0",
      text: "",
      unclear: [],
      sentences: [
        sentence(0, 0, [" آج", " صبح", " ہم", " نے", " نیا", " منصوبہ", " دیکھا۔"]),
        sentence(4, 1, [" میں", " نے", " 3", " بجے", " meeting", " رکھی", " ہے۔"]),
        sentence(8, 0, [" I", " said", " کیا", " ہوا"]),
      ],
    },
    dir,
  );
  await page.goto(readerUrl(seeded));
  const paragraphs = page.getByRole("article", { name: "Transcript" }).locator("p");
  await expect(paragraphs).toHaveCount(3);

  const shape = await page.evaluate(async () => {
    await document.fonts.ready;
    const words = (p: Element, word: string) => {
      const text = p.firstChild as Text;
      const at = text.data.indexOf(word);
      const range = document.createRange();
      range.setStart(text, at);
      range.setEnd(text, at + word.length);
      return range.getBoundingClientRect();
    };
    const ps = Array.from(document.querySelectorAll("article p"));
    return {
      nastaliq: [...document.fonts].some((f) => f.family.includes("Noto Nastaliq Urdu") && f.status === "loaded"),
      turns: ps.map((p) => {
        const style = getComputedStyle(p);
        const box = p.getBoundingClientRect();
        const range = document.createRange();
        range.selectNodeContents(p);
        // A line mixing scripts comes back as one rect per bidi run, in
        // logical order, so its first rect is not its rightmost: take the extent.
        const runs = Array.from(range.getClientRects());
        const right = Math.max(...runs.map((r) => r.right));
        const left = Math.min(...runs.map((r) => r.left));
        const margin = p.parentElement?.querySelector("[data-margin]")?.getBoundingClientRect();
        return {
          // The margin's right edge against the text's leftmost ink.
          marginRight: margin?.right ?? Number.NaN,
          textLeft: left,
          lang: p.getAttribute("lang"),
          direction: style.direction,
          family: style.fontFamily,
          size: parseFloat(style.fontSize),
          leading: parseFloat(style.lineHeight) / parseFloat(style.fontSize),
          rightGap: box.right - right,
          leftGap: left - box.left,
        };
      }),
      three: words(ps[1] as Element, "3"),
      meeting: words(ps[1] as Element, "meeting"),
    };
  });
  const [urdu, mixed, english] = shape.turns;
  expect(shape.nastaliq).toBe(true);
  for (const turn of [urdu, mixed]) {
    expect(turn?.lang).toBe("ur");
    expect(turn?.direction).toBe("rtl");
    expect(turn?.family).toContain("Noto Nastaliq Urdu");
    expect(turn?.leading).toBeCloseTo(2.1, 1);
    // Set from the right edge, as Urdu is.
    expect(turn?.rightGap).toBeLessThan(2);
  }
  // The margin sits on the left of every turn, Urdu ones included (Hashiya spec, "The margin").
  for (const turn of shape.turns) expect(turn.marginRight).toBeLessThan(turn.textLeft);
  expect((urdu?.size ?? 0) / (english?.size ?? 1)).toBeCloseTo(1.3, 1);
  expect(english?.lang).toBeNull();
  expect(english?.direction).toBe("ltr");
  expect(english?.leftGap).toBeLessThan(2);
  // Right to left, "3" comes before "meeting", so it sits to its right.
  expect(shape.three.left).toBeGreaterThan(shape.meeting.right);

  // A click on "meeting" seeks to it: 4 s + 4 words x 0.4 s.
  await expect.poll(() => page.evaluate(() => document.querySelector("audio")?.readyState ?? 0)).toBeGreaterThan(0);
  const seekTo = page.evaluate(
    () =>
      new Promise<number>((resolve) => {
        const audio = document.querySelector("audio") as HTMLAudioElement;
        audio.addEventListener("seeking", () => resolve(audio.currentTime), { once: true });
      }),
  );
  await page.mouse.click(shape.meeting.left + shape.meeting.width / 2, shape.meeting.top + shape.meeting.height / 2);
  expect(await seekTo).toBeCloseTo(5.6, 2);
});

// Arabic-script punctuation decides a paragraph's direction by its bidi class,
// and ui/src/lib/script.ts must agree with the browser: the Urdu full stop
// (class AL) is strong right to left, the Arabic comma (class CS) is not.
test("a turn opening with the Urdu full stop is Urdu, one opening with the Arabic comma is not", async ({ page }) => {
  const dir = scratchDir();
  const seeded = seed(
    {
      audio: tone(dir, 9, "marks.wav"),
      model: "mlx-community/whisper-large-v3-turbo",
      speakers: ["SPEAKER_00", "SPEAKER_01"],
      diarization: "senko 0.1.0",
      text: "",
      unclear: [],
      sentences: [
        sentence(0, 0, [" \u06D4", " hello", " there"]),
        sentence(4, 1, [" \u060C", " hello", " there"]),
      ],
    },
    dir,
  );
  await page.goto(readerUrl(seeded));
  const paragraphs = page.getByRole("article", { name: "Transcript" }).locator("p");
  await expect(paragraphs).toHaveCount(2);
  const turns = await page.evaluate(() =>
    Array.from(document.querySelectorAll("article p"), (p) => ({
      lang: p.getAttribute("lang"),
      direction: getComputedStyle(p).direction,
    })),
  );
  expect(turns).toEqual([
    { lang: "ur", direction: "rtl" },
    { lang: null, direction: "ltr" },
  ]);
});
