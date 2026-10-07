// Review mode's desk by keyboard alone (Hashiya spec, "Keyboard-complete on
// the Mac"), in a real browser against the real `dsj ui`: entering from the
// reader with R, picking the pass with Enter (F13), the Ctrl+F flag menu
// (F12), and Option+Tab out of the box to the bar's pass switch.
import { expect, type Page, test } from "@playwright/test";

import { editableTranscript } from "./editable.ts";
import { readerUrl, scratchDir, seed, tone } from "./seed.ts";

async function openReview(page: Page, name: string): Promise<void> {
  const dir = scratchDir();
  const seeded = seed(
    editableTranscript(tone(dir, 8, `${name}.wav`), [
      ["alpha", "bravo", "charlie"],
      ["delta", "echo"],
      ["foxtrot", "golf"],
    ]),
    dir,
  );
  await page.goto(readerUrl(seeded));
  await expect(page.getByRole("link", { name: "Review", exact: true })).toBeVisible();
  // R in the reader opens Review (keys.ts, READER_SHEET).
  await page.locator("body").press("r");
  await expect(page.getByRole("heading", { name: "Which sentences?" })).toBeVisible();
}

test("enters by R, picks the pass with Enter, and the flag menu works by keyboard (F12, F13)", async ({ page }, info) => {
  await openReview(page, `review-flags-${info.project.name}`);
  // The chooser's first choice holds focus: Enter takes it.
  await expect(page.getByRole("button", { name: /^Every sentence/ })).toBeFocused();
  await page.keyboard.press("Enter");
  const box = page.getByRole("textbox", { name: "What was said" });
  await expect(box).toBeFocused();
  await expect(box).toHaveValue("alpha bravo charlie");

  await page.keyboard.press("Control+f");
  const menu = page.getByRole("menu");
  await expect(menu).toBeVisible();
  // Focus is in the menu, not the box.
  await expect(box).not.toBeFocused();
  // Focus is on the menu itself; the first arrow lands on its first item.
  for (let i = 0; i < 3; i += 1) await page.keyboard.press("ArrowDown");
  await expect(page.getByRole("menuitemcheckbox", { name: "Overlapping talk" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(menu).toBeHidden();
  await expect(box).toBeFocused();
  await expect(page.getByLabel("Sentence being checked").getByText("Overlapping talk")).toBeVisible();

  // Esc closes the menu without a flag, and focus goes back to the box.
  await page.keyboard.press("Control+f");
  await expect(menu).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(menu).toBeHidden();
  await expect(box).toBeFocused();
  // That Esc closed the menu; it did not leave Review.
  await expect(page.getByRole("heading", { name: /^Review/ })).toBeVisible();
});

test("Option+Tab reaches the bar's pass switch, and the switch works by keyboard (F13)", async ({ page }, info) => {
  await openReview(page, `review-pass-${info.project.name}`);
  await page.keyboard.press("Enter");
  const box = page.getByRole("textbox", { name: "What was said" });
  await expect(box).toBeFocused();
  const every = page.getByRole("button", { name: "Every sentence", exact: true });
  const likely = page.getByRole("button", { name: /^Likely errors/ });
  // Backwards out of the box, through the page's controls, to the bar. The
  // switch is one stop (a roving tabindex): Tab lands on the pass in use.
  for (let i = 0; i < 12 && !(await every.evaluate((el) => el === document.activeElement)); i += 1) {
    await page.keyboard.press("Alt+Shift+Tab");
  }
  await expect(every).toBeFocused();
  await page.keyboard.press("ArrowRight");
  await expect(likely).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(likely).toHaveAttribute("aria-pressed", "true");
});
