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
  await page.getByRole("button", { name: "Unsure words (1)" }).click();
  await expect.poll(() => painted(page, "dsj-unsure")).toEqual(["charlie"]);

  await selectWord(page, "charlie");
  await page.getByRole("button", { name: "Correct…" }).click();
  const field = page.getByRole("textbox", { name: "What was said" });
  await expect(field).toHaveValue("charlie");
  await field.fill("Charles Darwin");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(first).toHaveText(" alpha bravo Charles Darwin delta");
  await expect(page.getByRole("button", { name: "Unsure words (0)" })).toBeVisible();
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
