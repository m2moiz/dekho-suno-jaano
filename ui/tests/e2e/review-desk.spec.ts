// Review mode's desk by keyboard alone (Hashiya spec, "Keyboard-complete on
// the Mac"), in a real browser against the real `dsj ui`: entering from the
// reader with R, picking the pass with Enter (F13), the Ctrl+F flag menu
// (F12), Option+Tab out of the box to the bar's pass switch, and a whole
// review start to finish, saved as an answer key (Hashiya spec, Testing).
import { existsSync, readFileSync } from "node:fs";

import { expect, type Page, test } from "@playwright/test";

import { editableTranscript, selectWord } from "./editable.ts";
import { readerUrl, type Seeded, scratchDir, seed, tone } from "./seed.ts";

/**
 * Open Review from the reader with R, on a made-up transcript of three
 * sentences over a tone of `seconds`, at its pass chooser. Two tones of one
 * length are one recording to the library, and the other's transcript would
 * be this one's second opinion: a test that minds gives a length of its own.
 */
async function openReview(page: Page, name: string, seconds = 8): Promise<Seeded> {
  const dir = scratchDir();
  const seeded = seed(
    editableTranscript(tone(dir, seconds, `${name}.wav`), [
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
  return seeded;
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

test("Ctrl+/ then an Esc at once closes only the key sheet, ten times over (UAT 8 Oct, finding 4)", async ({ page }, info) => {
  await openReview(page, `review-sheet-${info.project.name}`, 9);
  await page.keyboard.press("Enter");
  const box = page.getByRole("textbox", { name: "What was said" });
  await expect(box).toBeFocused();
  const sheet = page.getByRole("dialog", { name: "Keys in Review" });
  // The UAT saw it after a key that changes the page first (Ctrl+G, Ctrl+J, Tab): 1 in 3 in Chromium.
  for (let i = 0; i < 10; i += 1) {
    await page.keyboard.press(["Control+g", "Control+j", "Tab"][i % 3] ?? "Control+g");
    await page.keyboard.press("Control+/");
    await page.keyboard.press("Escape");
    await expect(sheet).toBeHidden();
    await expect(page.getByRole("heading", { name: /^Review/ })).toBeVisible();
    await expect(box).toBeFocused();
  }
  expect(new URL(page.url()).searchParams.get("review")).toBe("1");
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

// Tab plays in the box (spec), so the box names its ways out and both work
// (critique 7 Oct round 2, P1-1): Option+Tab, where the browser moves focus
// with it, and F6, which steps through the regions on every keyboard: box,
// the controls row, the bar, the rail, and round again. Runs on webkit too in
// the full verify.
test("leaves the Review box by Option+Tab and by F6, and F6 steps box, controls, bar, rail", async ({ page }, info) => {
  await openReview(page, `review-regions-${info.project.name}`, 8.7);
  await page.keyboard.press("Enter");
  const box = page.getByRole("textbox", { name: "What was said" });
  await expect(box).toBeFocused();
  await expect(box).toHaveAccessibleDescription("Tab plays. F6 or Option+Tab moves to the other controls.");

  await page.keyboard.press("Alt+Tab");
  await expect(box).not.toBeFocused();

  await box.focus();
  const inside = (name: string) =>
    page.evaluate((name) => {
      const active = document.activeElement;
      if (name === "row") return active?.closest('[role="toolbar"][aria-label="Sentence controls"]') !== null;
      if (name === "bar") return active?.closest("header") !== null;
      return active?.closest('[role="region"][aria-label="Player"]') !== null;
    }, name);
  await page.keyboard.press("F6");
  expect(await inside("row")).toBe(true);
  await page.keyboard.press("F6");
  expect(await inside("bar")).toBe(true);
  await page.keyboard.press("F6");
  expect(await inside("rail")).toBe(true);
  await page.keyboard.press("F6");
  await expect(box).toBeFocused();
  await page.keyboard.press("Shift+F6");
  expect(await inside("rail")).toBe(true);
});

test("Review opens from the reader only once a slow save of a correction has landed (Task 13 re-review)", async ({ page }, info) => {
  const dir = scratchDir();
  const seeded = seed(
    editableTranscript(tone(dir, 7.5, `review-slow-${info.project.name}.wav`), [
      ["alpha", "bravo", "charlie"],
      ["delta", "echo"],
    ]),
    dir,
  );
  // The reader's save held 1.5 s, as a busy server would.
  await page.route("**/api/transcripts/*/edits", async (route) => {
    if (["PUT", "PATCH"].includes(route.request().method())) await new Promise((resolve) => setTimeout(resolve, 1500));
    await route.continue();
  });
  const dialogs: string[] = [];
  page.on("dialog", (dialog) => {
    dialogs.push(dialog.type());
    void dialog.accept();
  });
  await page.goto(readerUrl(seeded));
  await expect(page.locator("article p").first()).toHaveText(" alpha bravo charlie");
  await selectWord(page, "charlie");
  await page.getByRole("toolbar", { name: "Selection" }).getByRole("button", { name: "Correct" }).click();
  await page.getByRole("textbox", { name: "What was said" }).fill("Charles");
  await page.getByRole("button", { name: "Save" }).click();
  await page.getByRole("link", { name: "Review", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Which sentences?" })).toBeVisible({ timeout: 10_000 });
  await page.keyboard.press("Enter");
  await expect(page.getByRole("textbox", { name: "What was said" })).toHaveValue("alpha bravo Charles");
  // No "Leave site?" on the way: the page left with nothing unsaved.
  expect(dialogs).toEqual([]);
});

test("a transcript is reviewed by keyboard from R to the answer key, and the reader shows the correction (Task 15)", async ({ page }, info) => {
  const seeded = await openReview(page, `review-journey-${info.project.name}`, 8.3 + info.project.name.length / 1000);
  await page.keyboard.press("Enter");
  const box = page.getByRole("textbox", { name: "What was said" });
  await expect(box).toBeFocused();
  await expect(box).toHaveValue("alpha bravo charlie");

  // A correction: "charlie" was "Charles".
  await box.fill("alpha bravo Charles");
  await box.press("Enter");
  await expect(box).toHaveValue("delta echo");
  await expect(page.getByText("1 of 3 checked")).toBeVisible();

  // Said by the first speaker, not the second (editableTranscript alternates them).
  await box.press("Control+1");
  await expect(page.getByText("Said by Speaker 1")).toBeVisible();

  // Split after "delta", check the first half, and merge the second back into it.
  await box.evaluate((el: HTMLTextAreaElement) => el.setSelectionRange(5, 5));
  await box.press("Control+s");
  await expect(box).toHaveValue("delta");
  await expect(page.getByText("1 of 4 checked")).toBeVisible();
  await box.press("Enter");
  await expect(box).toHaveValue("echo");
  await box.press("Control+m");
  await expect(box).toHaveValue("delta echo");
  await expect(page.getByText(/of 3 checked$/)).toBeVisible();
  await box.press("Enter");

  // Can't make it out.
  await expect(box).toHaveValue("foxtrot golf");
  await box.press("Control+u");
  await box.press("Enter");

  await expect(page.getByRole("heading", { name: "This pass is done" })).toBeVisible();
  await page.getByRole("button", { name: "Save as answer key" }).click();
  await expect(page.getByRole("status").filter({ hasText: "beside the transcript" })).toBeVisible();
  const keyFile = seeded.transcriptPath.replace(/\.json$/, ".reference.json");
  expect(existsSync(keyFile)).toBe(true);
  expect(existsSync(keyFile.replace(/\.json$/, ".txt"))).toBe(true);
  const key = JSON.parse(readFileSync(keyFile, "utf8")) as {
    complete: boolean;
    segments: { text: string; speaker: string; flags: string[] }[];
  };
  expect(key.complete).toBe(true);
  expect(key.segments.map((s) => s.text)).toEqual(["alpha bravo Charles", "delta echo", "foxtrot golf"]);
  // By name: the second sentence was Speaker 2's until Ctrl+1.
  expect(key.segments.map((s) => s.speaker)).toEqual(["Speaker 1", "Speaker 1", "Speaker 1"]);
  expect(key.segments[2]?.flags).toEqual(["unclear"]);

  // Back in the reader the correction shows, and the margin strikes through
  // only the word it replaced, not the sentence (F4).
  await page.getByRole("link", { name: "Back to the transcript" }).last().click();
  await expect(page.locator("article p").first()).toContainText("alpha bravo Charles");
  await expect(page.locator("article li [data-margin] del")).toHaveText(["charlie"]);
});

// The owner's ruling of 8 Oct (critique 7 Oct, P1-1): the margin stays on the
// left, and a right-to-left sentence takes a narrower measure so its start,
// on the right, sits near it. The box and the context lines share that
// measure, so the context's start lines up with the box text's (it overshot
// by about 18 px, the box's padding and edge, before).
test("an Urdu sentence on the desk takes the narrow measure, its context lined up with it", async ({ page }, info) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const dir = scratchDir();
  const seeded = seed(
    editableTranscript(tone(dir, 8.6 + info.project.name.length / 1000, `review-urdu-measure-${info.project.name}.wav`), [
      ["آج", "صبح", "ہم", "نے", "نیا", "منصوبہ", "دیکھا۔"],
      ["میں", "نے", "3", "بجے", "meeting", "رکھی", "ہے۔"],
      ["یہ", "بات", "ٹھیک", "ہے۔"],
    ]),
    dir,
  );
  await page.goto(readerUrl(seeded));
  // R reaches the page once the reader is up, as openReview waits for.
  await expect(page.getByRole("link", { name: "Review", exact: true })).toBeVisible();
  await page.locator("body").press("r");
  await page.getByRole("button", { name: /^Every sentence/ }).click();
  const box = page.getByRole("textbox", { name: "What was said" });
  await expect(box).toHaveAttribute("lang", "ur");
  const shape = await page.evaluate(() => {
    const textarea = document.querySelector("textarea") as HTMLTextAreaElement;
    const style = getComputedStyle(textarea);
    const inset = parseFloat(style.paddingRight) + parseFloat(style.borderRightWidth);
    const context = document.querySelector(".review-context:lang(ur)") as HTMLElement;
    const margin = document.querySelector(".review-margin") as HTMLElement;
    return {
      boxTextRight: textarea.getBoundingClientRect().right - inset,
      contextRight: context.getBoundingClientRect().right,
      marginRight: margin.getBoundingClientRect().right,
    };
  });
  // Near the margin: the text's start within 600 px of it (it was about 850 at 1440).
  expect(shape.boxTextRight - shape.marginRight).toBeLessThan(600);
  expect(Math.abs(shape.contextRight - shape.boxTextRight)).toBeLessThanOrEqual(2);
});
