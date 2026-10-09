// Retyping a misheard word in the app (#83), in real chromium and Playwright's
// webkit, against the real `dsj ui`: the reader shows it, its unsure tint goes,
// one undo takes it back, and the library says the transcript was edited.
import { expect, test } from "@playwright/test";

import { editableTranscript, painted, selectWord } from "./editable.ts";
import { readerUrl, scratchDir, seed, tone } from "./seed.ts";

test("a retyped word reads as retyped, loses its tint, undoes in one step and is kept", async ({ page }, info) => {
  const dir = scratchDir();
  // Its own recording, so this browser's row is told apart from the other's
  // in the run's one library: a length of its own, since the library knows a
  // recording by its contents and would file two equal tones as one.
  const name = `correct-${info.project.name}.wav`;
  const seconds = 8 + info.project.name.length / 10;
  const seeded = seed(
    editableTranscript(
      tone(dir, seconds, name),
      [
        ["alpha", "bravo", "charlie", "delta"],
        ["echo", "foxtrot", "golf", "hotel"],
      ],
      ["charlie"],
    ),
    dir,
  );
  await page.goto(readerUrl(seeded));
  const first = page.locator("article p").first();
  await expect(first).toHaveText(" alpha bravo charlie delta");
  await expect(page.getByRole("group", { name: "Unsure words", exact: true })).toContainText("1");
  await page.getByRole("switch", { name: "Unsure words" }).click();
  await expect.poll(() => painted(page, "dsj-unsure")).toEqual(["charlie"]);

  await selectWord(page, "charlie");
  await page.getByRole("toolbar", { name: "Selection" }).getByRole("button", { name: "Correct" }).click();
  const field = page.getByRole("textbox", { name: "What was said" });
  await expect(field).toHaveValue("charlie");
  await field.fill("Charles Darwin");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(first).toHaveText(" alpha bravo Charles Darwin delta");
  await expect(page.getByRole("group", { name: "Unsure words", exact: true })).toContainText("0");
  // What the recogniser had, struck through in the margin beside the turn.
  await expect(page.locator("article li").first().locator("[data-margin] del")).toHaveText("charlie");
  await expect(page.getByRole("toolbar", { name: "Edit" }).getByRole("status")).toHaveText("Saved");

  await page.keyboard.press("ControlOrMeta+z");
  await expect(first).toHaveText(" alpha bravo charlie delta");
  await page.keyboard.press("ControlOrMeta+Shift+z");
  await expect(first).toHaveText(" alpha bravo Charles Darwin delta");
  await expect(page.getByRole("toolbar", { name: "Edit" }).getByRole("status")).toHaveText("Saved");

  await page.reload();
  await expect(page.locator("article p").first()).toHaveText(" alpha bravo Charles Darwin delta");
  await page.getByRole("link", { name: "Library" }).click();
  // Its row is titled by the file's name without the extension.
  const recording = page.getByRole("listitem", { name: name.replace(/\.wav$/, "") });
  await recording.getByRole("button", { name: "Details" }).click();
  await expect(recording.locator("dt", { hasText: "Edited" }).locator("+ dd")).toHaveText(/\d{1,2}:\d{2}/);
});

for (const { width, height, least } of [
  { width: 390, height: 844, least: 44 },
  { width: 1440, height: 900, least: 36 },
]) {
  test(`at ${width}x${height} the selection's tools and Correct in place are in sight, ${least} px tall or more`, async ({ page }, info) => {
    const dir = scratchDir();
    const seeded = seed(
      editableTranscript(tone(dir, 6 + width / 1000 + info.project.name.length / 100, `tools-${width}-${info.project.name}.wav`), [
        ["alpha", "bravo", "charlie", "delta"],
        ["echo", "foxtrot", "golf", "hotel"],
      ]),
      dir,
    );
    await page.setViewportSize({ width, height });
    await page.goto(readerUrl(seeded));
    await expect(page.locator("article p").first()).toHaveText(" alpha bravo charlie delta");
    await selectWord(page, "hotel");
    const tools = page.getByRole("toolbar", { name: "Selection" });
    for (const name of ["Correct", "Hear", "Timing", "Mute"]) {
      const box = await tools.getByRole("button", { name, exact: true }).boundingBox();
      expect(box?.height ?? 0).toBeGreaterThanOrEqual(least);
      // Inside the window, clear of its sides.
      expect(box?.x ?? -1).toBeGreaterThanOrEqual(0);
      expect((box?.x ?? 0) + (box?.width ?? 0)).toBeLessThanOrEqual(width);
    }
    await tools.getByRole("button", { name: "Correct" }).click();
    const form = page.getByRole("form", { name: "Correct" });
    await expect(form.getByRole("textbox", { name: "What was said" })).toHaveValue("hotel");
    for (const name of ["Hear", "Cancel", "Save"]) {
      const box = await form.getByRole("button", { name }).boundingBox();
      expect(box?.height ?? 0).toBeGreaterThanOrEqual(least);
      expect((box?.x ?? 0) + (box?.width ?? 0)).toBeLessThanOrEqual(width);
    }
    await page.keyboard.press("Escape");
    await expect(form).toHaveCount(0);

    // Timing's dock, the same rule.
    await selectWord(page, "hotel");
    await tools.getByRole("button", { name: "Timing" }).click();
    const strip = page.getByRole("region", { name: "Word timing" });
    for (const name of ["Hear", "Done"]) {
      const box = await strip.getByRole("button", { name }).boundingBox();
      expect(box?.height ?? 0).toBeGreaterThanOrEqual(least === 44 ? 44 : 28);
      expect((box?.x ?? 0) + (box?.width ?? 0)).toBeLessThanOrEqual(width);
    }
  });
}

test("from the keyboard alone: ] selects the unsure word with focus on Correct, Esc goes back to the text, Enter saves back to it", async ({ page }, info) => {
  const dir = scratchDir();
  const seeded = seed(
    editableTranscript(
      tone(dir, 7 + info.project.name.length / 100, `keys-${info.project.name}.wav`),
      [
        ["alpha", "bravo", "charlie", "delta"],
        ["echo", "foxtrot", "golf", "hotel"],
      ],
      ["charlie"],
    ),
    dir,
  );
  await page.goto(readerUrl(seeded));
  await expect(page.locator("article p").first()).toHaveText(" alpha bravo charlie delta");
  const tools = page.getByRole("toolbar", { name: "Selection" });
  const selection = () => page.evaluate(() => window.getSelection()?.toString() ?? "");
  const focused = () => page.evaluate(() => document.activeElement?.tagName ?? "");

  await page.keyboard.press("]");
  await expect(tools.getByRole("button", { name: "Correct" })).toBeFocused();
  expect(await selection()).toBe("charlie");

  await page.keyboard.press("Escape");
  await expect(tools).toHaveCount(0);
  expect(await focused()).toBe("P");
  expect(await selection()).toBe("");

  await page.keyboard.press("]");
  await expect(tools.getByRole("button", { name: "Correct" })).toBeFocused();
  await page.keyboard.press("Enter");
  const field = page.getByRole("textbox", { name: "What was said" });
  await expect(field).toBeFocused();
  await field.fill("Charles Darwin");
  await page.keyboard.press("Enter");
  await expect(page.locator("article p").first()).toHaveText(" alpha bravo Charles Darwin delta");
  await expect.poll(selection).toBe("Charles Darwin");
  expect(await focused()).toBe("P");
});
