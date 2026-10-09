// Dragging a word's edge (#85), in real chromium and Playwright's webkit,
// against the real `dsj ui`: a pointer drag, saved, one undo step.
import { expect, type Page, test } from "@playwright/test";

import { editableTranscript, selectWord } from "./editable.ts";
import { readerUrl, scratchDir, seed, tone } from "./seed.ts";

// editable.ts spaces the words: "charlie" is 1.3 to 1.65 s, "delta" 1.8 to 2.15 s.
const CHARLIE_END = 1.65;
const TARGET = 1.95;

async function openTiming(page: Page, word: string) {
  await expect(page.locator("article")).toContainText(word);
  await selectWord(page, word);
  await page.getByRole("toolbar", { name: "Selection" }).getByRole("button", { name: "Timing" }).click();
  return page.getByRole("region", { name: "Word timing" });
}

const valueOf = async (page: Page, name: string) =>
  Number(await page.getByRole("slider", { name }).getAttribute("aria-valuenow"));

test("dragging a word's end is one undo step, takes time from the next word, and is kept", async ({ page }, info) => {
  const dir = scratchDir();
  const seeded = seed(
    // A length no other spec uses: the run's one library files equal tones as one recording.
    editableTranscript(tone(dir, 10 + info.project.name.length / 10, `bounds-${info.project.name}.wav`), [
      ["alpha", "bravo", "charlie", "delta"],
      ["echo", "foxtrot", "golf", "hotel"],
    ]),
    dir,
  );
  await page.goto(readerUrl(seeded));
  const strip = await openTiming(page, "charlie");
  const handle = strip.getByRole("slider", { name: "End of charlie" });
  expect(await valueOf(page, "End of charlie")).toBeCloseTo(CHARLIE_END, 3);

  // Where TARGET seconds is on the strip, from the slider's own range.
  const box = await strip.locator("div.relative").boundingBox();
  const from = Number(await handle.getAttribute("aria-valuemin"));
  const to = Number(await handle.getAttribute("aria-valuemax"));
  const at = await handle.boundingBox();
  if (box === null || at === null) throw new Error("the strip is not on screen");
  const x = box.x + ((TARGET - from) / (to - from)) * box.width;
  await page.mouse.move(at.x + at.width / 2, at.y + at.height / 2);
  await page.mouse.down();
  await page.mouse.move(x, at.y + at.height / 2, { steps: 12 });
  await page.mouse.up();

  expect(await valueOf(page, "End of charlie")).toBeCloseTo(TARGET, 1);
  await expect(page.getByRole("toolbar", { name: "Edit" }).getByRole("status")).toHaveText("Saved");

  // Twelve pointer moves, one step back.
  await page.keyboard.press("ControlOrMeta+z");
  expect(await valueOf(page, "End of charlie")).toBeCloseTo(CHARLIE_END, 3);
  await expect(page.getByRole("button", { name: "Undo" })).toBeDisabled();
  await page.keyboard.press("ControlOrMeta+Shift+z");
  const dragged = await valueOf(page, "End of charlie");
  expect(dragged).toBeCloseTo(TARGET, 1);
  await expect(page.getByRole("toolbar", { name: "Edit" }).getByRole("status")).toHaveText("Saved");

  // Kept: the next word gave up what the edge moved into, and both survive a reload.
  await page.reload();
  await openTiming(page, "charlie");
  expect(await valueOf(page, "End of charlie")).toBe(dragged);
  await page.getByRole("button", { name: "Done" }).click();
  await openTiming(page, "delta");
  expect(await valueOf(page, "Start of delta")).toBe(dragged);
});

/** The word's box on screen, from its text. */
function wordBox(page: Page, word: string) {
  return page.evaluate((word) => {
    for (const p of document.querySelectorAll("article p")) {
      const text = p.firstChild as Text;
      const at = text.data.indexOf(` ${word}`);
      if (at < 0) continue;
      const range = document.createRange();
      range.setStart(text, at + 1);
      range.setEnd(text, at + 1 + word.length);
      const box = range.getBoundingClientRect();
      return { top: box.top, bottom: box.bottom };
    }
    throw new Error(`no paragraph holds ${word}`);
  }, word);
}

for (const { width, height } of [
  { width: 1440, height: 900 },
  { width: 390, height: 844 },
]) {
  test(`at ${width}x${height} Timing scrolls its word clear of the dock: one at the window's bottom, one far down, the last`, async ({ page }, info) => {
    const dir = scratchDir();
    // Forty turns of eight words: the last is several screens below the first.
    const turns = Array.from({ length: 40 }, (_, t) => Array.from({ length: 8 }, (_, w) => `t${t}w${w}`));
    const seconds = Math.ceil(40 * (8 * 0.5 + 0.4)) + 2 + width / 10000 + info.project.name.length / 10;
    const seeded = seed(editableTranscript(tone(dir, seconds, `bounds-long-${width}-${info.project.name}.wav`), turns), dir);
    await page.setViewportSize({ width, height });
    await page.goto(readerUrl(seeded));
    await expect(page.locator("article p")).toHaveCount(40);
    const rail = await page.getByRole("region", { name: "Player" }).boundingBox();
    if (rail === null) throw new Error("no player on screen");
    // The lowest word wholly above the rail, as the page first draws: no scrolling first.
    const bottom = await page.evaluate((railTop) => {
      let best = "";
      let lowest = -1;
      for (const p of document.querySelectorAll("article p")) {
        const text = p.firstChild as Text;
        for (const match of text.data.matchAll(/t\d+w\d+/g)) {
          const range = document.createRange();
          range.setStart(text, match.index);
          range.setEnd(text, match.index + match[0].length);
          const box = range.getBoundingClientRect();
          if (box.bottom < railTop - 2 && box.bottom > lowest) {
            lowest = box.bottom;
            best = match[0];
          }
        }
      }
      return best;
    }, rail.y);
    expect(bottom).not.toBe("");
    const bar = await page.getByRole("banner").boundingBox();
    for (const word of [bottom, "t30w3", "t39w7"]) {
      const strip = await openTiming(page, word);
      await expect(strip.getByRole("slider", { name: `Start of ${word}` })).toBeFocused();
      const dock = await strip.boundingBox();
      if (dock === null || bar === null) throw new Error("no strip or no bar on screen");
      const box = await wordBox(page, word);
      // Above the dock's top, below the bar: in sight while its edges are dragged.
      expect(box.bottom).toBeLessThanOrEqual(dock.y);
      expect(box.top).toBeGreaterThanOrEqual(bar.y + bar.height);
      // On the phone the dock's buttons are 44 px tall (F15).
      if (width <= 767) {
        for (const name of ["Hear", "Done"]) {
          const button = await strip.getByRole("button", { name }).boundingBox();
          expect(button?.height ?? 0).toBeGreaterThanOrEqual(44);
        }
      }
      // Esc closes it and puts focus back on the word's paragraph, with the word selected.
      await page.keyboard.press("Escape");
      await expect(strip).toHaveCount(0);
      expect(await page.evaluate(() => [document.activeElement?.tagName, window.getSelection()?.toString()])).toEqual(["P", word]);
    }
  });
}

test("the reader's menu opens Timing for the one selected word, and says why it is off otherwise", async ({ page }, info) => {
  const dir = scratchDir();
  const seeded = seed(
    editableTranscript(tone(dir, 11 + info.project.name.length / 10, `menu-${info.project.name}.wav`), [
      ["alpha", "bravo", "charlie", "delta"],
    ]),
    dir,
  );
  await page.goto(readerUrl(seeded));
  await expect(page.locator("article")).toContainText("charlie");
  await page.getByRole("button", { name: "More" }).click();
  await expect(page.getByRole("menuitem", { name: /^Timing/ })).toContainText("select one word");
  await expect(page.getByRole("menuitem", { name: /^Timing/ })).toBeDisabled();
  await page.keyboard.press("Escape");

  await selectWord(page, "charlie");
  await page.getByRole("button", { name: "More" }).click();
  await page.getByRole("menuitem", { name: /^Timing/ }).click();
  await expect(page.getByRole("region", { name: "Word timing" })).toBeVisible();
  await expect(page.getByRole("slider", { name: "Start of charlie" })).toBeFocused();
});
