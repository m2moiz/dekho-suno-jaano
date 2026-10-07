// Undo and redo over the edit list (#66), in real chromium and Playwright's
// webkit, against the real `dsj ui`: Cmd+Z steps back through edits only.
import { expect, test } from "@playwright/test";

import { editableTranscript, painted, selectWord } from "./editable.ts";
import { readerUrl, scratchDir, seed, tone } from "./seed.ts";

test("Cmd+Z undoes a mute and nothing else; the mute is saved and its undo is not", async ({ page }) => {
  const dir = scratchDir();
  const seeded = seed(
    editableTranscript(tone(dir, 8), [
      ["alpha", "bravo", "charlie", "delta"],
      ["echo", "foxtrot", "golf", "hotel"],
    ]),
    dir,
  );
  await page.goto(readerUrl(seeded));
  const bar = page.getByRole("toolbar", { name: "Edit" });
  await expect(bar.getByRole("button", { name: "Undo" })).toBeDisabled();

  await selectWord(page, "charlie");
  await page.getByRole("toolbar", { name: "Selection" }).getByRole("button", { name: "Mute", exact: true }).click();
  await expect.poll(() => painted(page, "dsj-muted")).toEqual(["charlie"]);
  await expect(bar.getByRole("status")).toHaveText("Saved");

  // A caret move and a seek, a scroll and some playback: none is an edit.
  await page.getByText("golf").click();
  await page.mouse.wheel(0, 300);
  await expect.poll(() => page.evaluate(() => document.querySelector("audio")?.currentTime ?? 0)).toBeGreaterThan(3);
  await page.evaluate(() => document.querySelector("audio")?.pause());

  await page.keyboard.press("ControlOrMeta+z");
  await expect.poll(() => painted(page, "dsj-muted")).toEqual([]);
  await expect(bar.getByRole("button", { name: "Undo" })).toBeDisabled();
  await page.keyboard.press("ControlOrMeta+Shift+z");
  await expect.poll(() => painted(page, "dsj-muted")).toEqual(["charlie"]);
  await expect(bar.getByRole("status")).toHaveText("Saved");

  await page.reload();
  await expect.poll(() => painted(page, "dsj-muted")).toEqual(["charlie"]);
  await expect(bar.getByRole("button", { name: "Undo" })).toBeDisabled();
  // The key sheet behind `?` says so.
  await page.keyboard.press("Shift+Slash");
  await expect(page.getByRole("dialog")).toContainText("forgets their undo");
});

test("on a phone the key sheet's close button is 44 px", async ({ page }, info) => {
  const dir = scratchDir();
  const seeded = seed(editableTranscript(tone(dir, 9.3 + info.project.name.length / 100, `sheet-${info.project.name}.wav`), [["alpha", "bravo"]]), dir);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(readerUrl(seeded));
  await expect(page.locator("article p").first()).toHaveText(" alpha bravo");
  await page.keyboard.press("Shift+Slash");
  const close = page.getByRole("dialog").getByRole("button", { name: "Close" });
  // Its laid-out size: the sheet zooms in from 95% as it opens, which a bounding box would catch mid-way.
  const size = await close.evaluate((el) => [(el as HTMLElement).offsetWidth, (el as HTMLElement).offsetHeight]);
  expect(Math.min(...size)).toBeGreaterThanOrEqual(44);
  await close.click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
});
