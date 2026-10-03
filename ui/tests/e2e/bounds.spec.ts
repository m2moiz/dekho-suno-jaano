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
  await page.getByRole("button", { name: "Timing…" }).click();
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
