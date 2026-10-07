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
  await page.getByRole("button", { name: "1 unsure" }).click();
  await expect.poll(() => painted(page, "dsj-unsure")).toEqual(["charlie"]);

  await selectWord(page, "charlie");
  await page.getByRole("toolbar", { name: "Selection" }).getByRole("button", { name: "Correct" }).click();
  const field = page.getByRole("textbox", { name: "What was said" });
  await expect(field).toHaveValue("charlie");
  await field.fill("Charles Darwin");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(first).toHaveText(" alpha bravo Charles Darwin delta");
  await expect(page.getByRole("button", { name: "0 unsure" })).toBeVisible();
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
  const recording = page.getByRole("listitem", { name });
  await expect(recording.getByRole("link", { name: /parakeet-tdt-0\.6b-v3/ })).toContainText("edited");
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
  });
}
