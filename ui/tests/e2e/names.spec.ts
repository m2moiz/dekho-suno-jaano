// Naming a speaker in the reader (Hashiya spec, Reader; #243), in real chromium
// and Playwright's webkit against the real `dsj ui`: the name shows on every
// turn of that speaker, and survives a reload because it is in the edit list.
import { expect, test } from "@playwright/test";

import { editableTranscript } from "./editable.ts";
import { readerUrl, scratchDir, seed, tone } from "./seed.ts";

test("a speaker renamed in the margin is renamed everywhere, and stays renamed", async ({ page }, info) => {
  const dir = scratchDir();
  const seconds = 9 + info.project.name.length / 10;
  const seeded = seed(
    editableTranscript(tone(dir, seconds, `names-${info.project.name}.wav`), [
      ["alpha", "bravo"],
      ["charlie", "delta"],
      ["echo", "foxtrot"],
    ]),
    dir,
  );
  await page.goto(readerUrl(seeded));
  await page.getByRole("button", { name: "Speaker 1, rename" }).first().click();
  const field = page.getByRole("textbox", { name: "Name for Speaker 1" });
  await field.fill("Ali");
  await field.press("Enter");
  // Turns 1 and 3 are SPEAKER_00's (editableTranscript alternates speakers).
  await expect(page.getByRole("button", { name: "Ali, rename" })).toHaveCount(2);
  await page.reload();
  await expect(page.getByRole("button", { name: "Ali, rename" })).toHaveCount(2);
  await expect(page.getByRole("button", { name: "Speaker 2, rename" })).toHaveCount(1);
});

test("on a phone the nameplate and its field are 44 px targets", async ({ page }, info) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const dir = scratchDir();
  const seeded = seed(
    editableTranscript(tone(dir, 6 + info.project.name.length / 10, `names-phone-${info.project.name}.wav`), [
      ["alpha", "bravo"],
      ["charlie", "delta"],
    ]),
    dir,
  );
  await page.goto(readerUrl(seeded));
  const plate = page.getByRole("button", { name: "Speaker 1, rename" });
  expect((await plate.boundingBox())?.height).toBeGreaterThanOrEqual(44);
  await plate.click();
  const field = page.getByRole("textbox", { name: "Name for Speaker 1" });
  expect((await field.boundingBox())?.height).toBeGreaterThanOrEqual(44);
});
