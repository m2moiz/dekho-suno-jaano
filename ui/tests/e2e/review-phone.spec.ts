// Review mode on a phone and a tablet (Hashiya spec, "Phone and tablet,
// touch-first"), in a real browser against the real `dsj ui`: the card below
// 768 px or on a touch screen, every target on it 44 px or more (F15), the
// desk's keys on it when a keyboard is there (F14), and the swipes.
import { type CDPSession, expect, type Page, test } from "@playwright/test";

import { editableTranscript } from "./editable.ts";
import { readerUrl, scratchDir, seed, tone } from "./seed.ts";

const PHONE = { width: 390, height: 844 };
const TABLET = { width: 820, height: 1180 };
const LEAST = 44;

/** Open Review on a made-up transcript of three sentences, at its pass chooser. */
async function openReview(page: Page, name: string, seconds: number): Promise<string> {
  const dir = scratchDir();
  const seeded = seed(
    // A length of its own, per test and per browser: two tones of one length are
    // one recording to the library, and another test's transcript would be this
    // one's second opinion.
    editableTranscript(tone(dir, seconds, `${name}.wav`), [
      ["alpha", "bravo", "charlie"],
      ["delta", "echo"],
      ["foxtrot", "golf"],
    ]),
    dir,
  );
  const reader = readerUrl(seeded);
  const review = new URL(reader);
  review.searchParams.set("review", "1");
  await page.goto(review.toString());
  await expect(page.getByRole("heading", { name: "Which sentences?" })).toBeVisible();
  return new URL(reader).search;
}

/**
 * Every control in sight smaller than LEAST px either way, or reaching past
 * the window's sides, by its measured box. jsdom lays nothing out, so only
 * a real browser can say (correction.spec.ts, player.spec.ts).
 */
function undersized(page: Page): Promise<string[]> {
  return page.evaluate((least) => {
    const controls = document.querySelectorAll<HTMLElement>(
      "a[href], button, textarea, input, select, [role=button], [role=slider], [role=combobox], [role=option], [role=menuitem], [role=menuitemcheckbox], [role=menuitemradio], [tabindex='0']",
    );
    const out: string[] = [];
    for (const el of controls) {
      const box = el.getBoundingClientRect();
      // Not drawn: hidden, or the screen reader's own.
      if (box.width === 0 || box.height === 0 || el.closest("[aria-hidden=true], .sr-only, [hidden]")) continue;
      const name = (el.getAttribute("aria-label") ?? el.textContent ?? el.tagName).trim().slice(0, 40);
      // Its laid-out size, not its box: a menu opens from 95 % scale, and a box
      // measured mid-animation is that much smaller.
      const [width, height] = [el.offsetWidth, el.offsetHeight];
      if (height < least || width < least) out.push(`${name}: ${width}x${height}`);
      if (box.left < 0 || box.right > window.innerWidth) out.push(`${name}: outside the window`);
    }
    return out;
  }, LEAST);
}

/**
 * A finger's drag of `dx` by `dy` px from `at`, through the DevTools protocol:
 * Playwright's touchscreen only taps, so a real touch drag needs chromium.
 */
async function swipe(cdp: CDPSession, at: { x: number; y: number }, dx: number, dy = 8): Promise<void> {
  const { x, y } = at;
  await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x, y }] });
  await cdp.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [{ x: x + dx / 2, y: y + dy / 2 }] });
  await cdp.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [{ x: x + dx, y: y + dy }] });
  await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
}

test.describe("on a phone, 390 px wide, with a keyboard", () => {
  test.use({ viewport: PHONE });

  test("every target is 44 px or more: chooser, card, flag menu, settings menu, done panel (F15)", async ({ page }, info) => {
    await openReview(page, `review-phone-targets-${info.project.name}`, 8.6 + info.project.name.length / 1000);
    expect(await undersized(page)).toEqual([]);
    await page.getByRole("button", { name: /^Every sentence/ }).click();
    const card = page.getByRole("article", { name: "Sentence being checked" });
    await expect(card).toBeVisible();
    // One sentence, not the desk's five.
    await expect(page.getByText("delta echo")).toHaveCount(0);
    expect(await undersized(page)).toEqual([]);

    // Back and Checked, next sit above the player rail, nothing behind it.
    const rail = await page.getByRole("region", { name: "Player" }).boundingBox();
    const next = await page.getByRole("button", { name: "Checked, next" }).boundingBox();
    if (rail === null || next === null) throw new Error("the rail or Checked, next is not on the page");
    expect(next.y + next.height).toBeLessThanOrEqual(rail.y + 0.5);
    expect(next.height).toBeGreaterThanOrEqual(48);

    await page.getByRole("button", { name: "Flag" }).click();
    await expect(page.getByRole("menu")).toBeVisible();
    expect(await undersized(page)).toEqual([]);
    await page.getByRole("menuitemcheckbox", { name: "Not speech" }).click();
    await expect(page.getByRole("menu")).toBeHidden();
    await expect(card.getByText("Not speech")).toBeVisible();

    await page.getByRole("combobox", { name: "Playback speed" }).click();
    await expect(page.getByRole("listbox")).toBeVisible();
    expect(await undersized(page)).toEqual([]);
    await page.keyboard.press("Escape");
    await expect(page.getByRole("listbox")).toBeHidden();

    await page.getByRole("button", { name: "Settings" }).click();
    await expect(page.getByRole("menu")).toBeVisible();
    expect(await undersized(page)).toEqual([]);
    // And the key sheet it opens.
    await page.getByRole("menuitem", { name: /^Keys/ }).click();
    await expect(page.getByRole("dialog", { name: "Keys in Review" })).toBeVisible();
    expect(await undersized(page)).toEqual([]);
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toBeHidden();

    for (let i = 0; i < 3; i += 1) await page.getByRole("button", { name: "Checked, next" }).click();
    await expect(page.getByRole("heading", { name: "This pass is done" })).toBeVisible();
    expect(await undersized(page)).toEqual([]);
  });

  test("the desk's keys work on the card when a keyboard is there (F14)", async ({ page }, info) => {
    const reader = await openReview(page, `review-phone-keys-${info.project.name}`, 8.7 + info.project.name.length / 1000);
    await page.keyboard.press("Enter");
    const box = page.getByRole("textbox", { name: "What was said" });
    await expect(page.getByRole("article", { name: "Sentence being checked" })).toBeVisible();
    await expect(box).toBeFocused();
    await expect(box).toHaveValue("alpha bravo charlie");
    await page.keyboard.press("Enter");
    await expect(box).toHaveValue("delta echo");
    await expect(page.getByText("1 of 3 checked")).toBeVisible();
    await page.keyboard.press("Shift+Enter");
    await expect(box).toHaveValue("alpha bravo charlie");
    // A correction typed on the card, then Ctrl+2: the words are kept and the speaker changes.
    await box.fill("alpha bravo charles");
    await page.keyboard.press("Control+2");
    await expect(page.getByRole("button", { name: "Speaker 2" })).toHaveAttribute("aria-pressed", "true");
    await page.keyboard.press("Control+f");
    await expect(page.getByRole("menu")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("menu")).toBeHidden();
    await expect(box).toBeFocused();
    // Esc leaves for the reader, once everything is saved, and the correction is there.
    await page.keyboard.press("Escape");
    await expect(page).toHaveURL((url) => url.search === reader);
    // Speaker 2 now says it, as the sentence after it: the reader draws one turn of the two.
    await expect(page.locator("article p").first()).toHaveText(/^ alpha bravo charles delta echo$/);
  });
});

test("in a narrow window, a mouse drag across the card selects words and checks nothing (Task 14 review, I1)", async ({ page }, info) => {
  await page.setViewportSize(PHONE);
  await openReview(page, `review-phone-mouse-${info.project.name}`, 8.9 + info.project.name.length / 1000);
  await page.getByRole("button", { name: /^Every sentence/ }).click();
  const card = page.getByRole("article", { name: "Sentence being checked" });
  const box = page.getByRole("textbox", { name: "What was said" });
  await expect(box).toHaveValue("alpha bravo charlie");
  const line = await card.getByText("Not checked yet").boundingBox();
  if (line === null) throw new Error("the card's margin line is not on the page");
  // Right to left across the margin line, 200 px, as selecting its words would.
  const y = line.y + line.height / 2;
  await page.mouse.move(line.x + line.width, y);
  await page.mouse.down();
  await page.mouse.move(line.x + line.width - 100, y + 2);
  await page.mouse.move(line.x + line.width - 200, y + 4);
  await page.mouse.up();
  await page.waitForTimeout(300);
  await expect(box).toHaveValue("alpha bravo charlie");
  await expect(page.getByText("0 of 3 checked")).toBeVisible();
});

test("words typed on the card and then hidden stay out of the list, and come back on reopening (Task 14 fix round 4)", async ({ page }, info) => {
  await page.setViewportSize(PHONE);
  const reader = await openReview(page, `review-phone-hide-${info.project.name}`, 9.1 + info.project.name.length / 1000);
  const review = page.url();
  await page.getByRole("button", { name: /^Every sentence/ }).click();
  const box = page.getByRole("textbox", { name: "What was said" });
  await box.fill("alpha bravo charl");
  // An app switch on a phone: hidden, and never shown again. No key, no button, no beforeunload.
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "hidden" });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await page.waitForTimeout(500);
  // Half a word is not a correction: the reader still says what it said.
  await page.goto(review.replace("&review=1", ""));
  expect(new URL(page.url()).search).toBe(reader);
  await expect(page.locator("article p").first()).toHaveText(/charlie/);
  // The tab opened again later: Review puts the words back in their box.
  await page.goto(review);
  await page.getByRole("button", { name: /^Every sentence/ }).click();
  await expect(box).toHaveValue("alpha bravo charl");
  await expect(page.getByText("Restored words typed before the page closed")).toBeVisible();
});

test("words typed on the card come back when the page was killed before any save could land (Task 14 fix round 3)", async ({ page, context, browserName }, info) => {
  test.skip(browserName !== "chromium", "the tab is killed through the DevTools protocol, which only chromium has");
  await page.setViewportSize(PHONE);
  await openReview(page, `review-phone-draft-${info.project.name}`, 9.2 + info.project.name.length / 1000);
  const token = await page.evaluate(() => sessionStorage.getItem("dsj-token"));
  const review = `${page.url()}#t=${token}`;
  await page.getByRole("button", { name: /^Every sentence/ }).click();
  await page.getByRole("textbox", { name: "What was said" }).fill("alpha bravo charles");
  // The tab killed outright, as a phone kills one: no pagehide, no
  // visibilitychange, so no save of any kind is sent. The browser's copy is
  // all that is left. (CDP, chromium only; the webkit run skips this test.)
  const cdp = await context.newCDPSession(page);
  void cdp.send("Page.crash").catch(() => undefined);
  await page.waitForEvent("crash");
  await page.close();

  const again = await context.newPage();
  await again.setViewportSize(PHONE);
  await again.goto(review);
  await again.getByRole("button", { name: /^Every sentence/ }).click();
  const box = again.getByRole("textbox", { name: "What was said" });
  await expect(box).toHaveValue("alpha bravo charles");
  await expect(again.getByText("Restored words typed before the page closed")).toBeVisible();
  // Checked, next commits it and the save lands: the copy is gone.
  await again.getByRole("button", { name: "Checked, next" }).click();
  await expect(box).toHaveValue("delta echo");
  await expect.poll(() => again.evaluate(() => Object.keys(localStorage).filter((k) => k.startsWith("dsj-review-draft-")))).toEqual([]);
});

test("a sentence committed one second before the page is killed is kept, on a slow upload (#251)", async ({ page, context, browserName }) => {
  test.skip(browserName !== "chromium", "the tab is killed and the upload slowed through the DevTools protocol, which only chromium has");
  test.slow();
  await page.setViewportSize(PHONE);
  // 300 sentences of ten words: its whole edit list is about 0.7 MB, which the
  // slowed upload below needs about ten seconds for; one change is a few
  // hundred bytes. No recording: Review checks the words, not the sound.
  const dir = scratchDir();
  const sentences = Array.from({ length: 300 }, (_, i) => Array.from({ length: 10 }, (_, k) => `s${i}w${k}`));
  const seeded = seed(editableTranscript(`${dir}/none.wav`, sentences), dir);
  const reader = readerUrl(seeded);
  await page.goto(reader.replace("#", "&review=1#"));
  await page.getByRole("button", { name: /^Every sentence/ }).click();
  const box = page.getByRole("textbox", { name: "What was said" });
  await expect(box).toHaveValue(sentences[0]?.join(" ") ?? "");
  await expect(page.locator("header").getByText("Saved")).toBeVisible();
  // Phone data, slow to send: 64 KiB a second up, 50 ms each way.
  const cdp = await context.newCDPSession(page);
  await cdp.send("Network.enable");
  await cdp.send("Network.emulateNetworkConditions", { offline: false, latency: 50, downloadThroughput: -1, uploadThroughput: 65_536 });
  await box.fill(`${sentences[0]?.slice(0, 9).join(" ")} Charles`);
  await page.getByRole("button", { name: "Checked, next" }).click();
  await expect(box).toHaveValue(sentences[1]?.join(" ") ?? "");
  await page.waitForTimeout(1000);
  // Killed, as a phone kills a tab: no pagehide, no visibilitychange. Only a
  // request already sent with keepalive outlives it.
  void cdp.send("Page.crash").catch(() => undefined);
  await page.waitForEvent("crash");
  await page.close();

  const again = await context.newPage();
  await again.setViewportSize(PHONE);
  await again.goto(reader);
  await expect(again.locator("article p").first()).toContainText("s0w8 Charles");
  await again.goto(reader.replace("#", "&review=1#"));
  await expect(again.getByText(/1 of 300 checked/)).toBeVisible();
});

test.describe("on a tablet, a touch screen 820 px wide", () => {
  test.use({ viewport: TABLET, hasTouch: true });

  test("the card is used, its targets are 44 px or more, and a swipe of a finger checks or goes back", async ({ page, browserName }, info) => {
    await openReview(page, `review-tablet-${info.project.name}`, 8.8 + info.project.name.length / 1000);
    expect(await page.evaluate(() => matchMedia("(pointer: coarse)").matches)).toBe(true);
    await page.getByRole("button", { name: /^Every sentence/ }).tap();
    const card = page.getByRole("article", { name: "Sentence being checked" });
    await expect(card).toBeVisible();
    const box = page.getByRole("textbox", { name: "What was said" });
    // Nothing takes the focus, so the screen's keyboard stays down.
    await expect(box).not.toBeFocused();
    expect(await undersized(page)).toEqual([]);
    await page.getByRole("button", { name: "Checked, next" }).tap();
    await expect(box).toHaveValue("delta echo");
    await page.getByRole("button", { name: "Back" }).tap();
    await expect(box).toHaveValue("alpha bravo charlie");

    // Real touch input: Playwright's touchscreen only taps, so the finger's
    // drag goes through the DevTools protocol, which only chromium speaks.
    // WebKit's run still measures the targets and taps above.
    if (browserName !== "chromium") return;
    // From the card's margin line, not the text box.
    const from = await card.locator("p").first().boundingBox();
    if (from === null) throw new Error("the card's margin line is not on the page");
    const at = { x: from.x + 200, y: from.y + from.height / 2 };
    const cdp = await page.context().newCDPSession(page);
    await swipe(cdp, at, -160);
    await expect(box).toHaveValue("delta echo");
    await expect(page.getByText("1 of 3 checked")).toBeVisible();
    await swipe(cdp, at, 160);
    await expect(box).toHaveValue("alpha bravo charlie");
    // A steep drag is a scroll, not a swipe.
    await swipe(cdp, at, -100, 90);
    await page.waitForTimeout(300);
    await expect(box).toHaveValue("alpha bravo charlie");
    await cdp.detach();
  });
});

test.describe("on a phone, 390 px wide, a touch screen", () => {
  test.use({ viewport: PHONE, hasTouch: true });

  test("a swipe left checks and goes on, a swipe right goes back, a speaker chip reassigns, every target 44 px (Task 15)", async ({ page, browserName }, info) => {
    await openReview(page, `review-phone-touch-${info.project.name}`, 9.3 + info.project.name.length / 1000);
    await page.getByRole("button", { name: /^Every sentence/ }).tap();
    const card = page.getByRole("article", { name: "Sentence being checked" });
    const box = page.getByRole("textbox", { name: "What was said" });
    await expect(box).toHaveValue("alpha bravo charlie");
    // Nothing takes the focus, so the screen's keyboard stays down.
    await expect(box).not.toBeFocused();
    expect(await undersized(page)).toEqual([]);

    if (browserName === "chromium") {
      // A finger's drag goes through the DevTools protocol, which only chromium
      // speaks; webkit taps on and still measures the targets and the chip.
      // From the card's margin line, not the text box, which keeps drags for selecting words.
      const from = await card.locator("p").first().boundingBox();
      if (from === null) throw new Error("the card's margin line is not on the page");
      const at = { x: from.x + from.width / 2, y: from.y + from.height / 2 };
      const cdp = await page.context().newCDPSession(page);
      await swipe(cdp, at, -160);
      await expect(box).toHaveValue("delta echo");
      await expect(page.getByText("1 of 3 checked")).toBeVisible();
      await swipe(cdp, at, 160);
      await expect(box).toHaveValue("alpha bravo charlie");
      await swipe(cdp, at, -160);
      await cdp.detach();
    } else {
      await page.getByRole("button", { name: "Checked, next" }).tap();
    }
    await expect(box).toHaveValue("delta echo");

    // "delta echo" is the second speaker's (editableTranscript alternates them); a tap on the first's chip reassigns it.
    const chips = page.getByRole("group", { name: "Who said it" });
    await expect(chips.getByRole("button", { name: "Speaker 2" })).toHaveAttribute("aria-pressed", "true");
    await chips.getByRole("button", { name: "Speaker 1" }).tap();
    await expect(page.getByText("Said by Speaker 1")).toBeVisible();
    await expect(chips.getByRole("button", { name: "Speaker 1" })).toHaveAttribute("aria-pressed", "true");
    expect(await undersized(page)).toEqual([]);
  });

  test("the card's gold Checked, next stands 12 px or more clear of the rail, whose play is not gold (critique P1-2)", async ({ page }, info) => {
    await openReview(page, `review-phone-gap-${info.project.name}`, 9.4 + info.project.name.length / 1000);
    await page.getByRole("button", { name: /^Every sentence/ }).tap();
    const checked = await page.getByRole("button", { name: "Checked, next" }).boundingBox();
    const rail = await page.getByRole("region", { name: "Player" }).boundingBox();
    if (checked === null || rail === null) throw new Error("Checked, next or the rail is not on the page");
    expect(rail.y - (checked.y + checked.height)).toBeGreaterThanOrEqual(12);
    const gold = (name: string | RegExp) => page.getByRole("button", { name }).evaluate((element) => getComputedStyle(element).backgroundColor === "rgb(200, 162, 74)");
    expect(await gold("Checked, next")).toBe(true);
    // Arriving plays the sentence, so the rail's button may read Pause.
    expect(await gold(/^(Play|Pause)$/)).toBe(false);
  });
});
