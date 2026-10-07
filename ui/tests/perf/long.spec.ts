// Review Focus 5 and the spec's "Long recordings": a 2.5 h call, 1,500
// sentences between four speakers, keeps the 20 ms p95 frame budget in the
// reader's scroll and in Review's step from sentence to sentence. Synthetic
// (fixture.ts), no audio: the frames are measured as text and layout alone.
// The last two tests measure what an edit costs on it: the frame a correction
// lands in, with and without a second opinion to work out again (Task 13's
// estimate, about 30 ms), and the bytes and time of the saves a commit sends
// (#251).
import { expect, type Page, type Request, test } from "@playwright/test";

import { readerUrl, type Seeded, scratchDir, seed } from "../e2e/seed.ts";
import { LONG_SHAPE, syntheticTranscript, type Transcript } from "./fixture.ts";
import { FRAMES, P95_CEILING_MS, STEP_PX, type Summary, scrollFrames, summarise } from "./sample.ts";

// A correction's frame, second opinion worked out again included: the
// ceiling Task 15's dispatch set for changing the code (p95 per edit over 50
// ms). Measured 2026-10-07 on this Mac, `cd ui && npx playwright test
// tests/perf/long.spec.ts --project=perf`: see task-15-report.md.
const EDIT_P95_CEILING_MS = 50;

/** The long fixture in the run's library, with no recording; and, given `other`, a second transcript of the same "recording". */
function seedLong(other?: (t: Transcript) => Transcript): Seeded {
  const dir = scratchDir();
  // One path for both: a missing recording is matched by its path (store.py, _recording_for).
  const audio = `${dir}/none.wav`;
  if (other !== undefined) seed(other({ ...syntheticTranscript(LONG_SHAPE), audio }), dir);
  return seed({ ...syntheticTranscript(LONG_SHAPE), audio }, dir);
}

/** Another engine's reading: every seventh piece heard differently, so the two disagree throughout. */
function otherEngine(t: Transcript): Transcript {
  let k = 0;
  const sentences = t.sentences.map((s) => {
    const tokens = s.tokens.map((token) => ((k += 1) % 7 === 0 ? { ...token, w: token.w.startsWith(" ") ? " zo" : "zo" } : token));
    return { ...s, tokens, text: tokens.map((token) => token.w).join("") };
  });
  return { ...t, model: "synthetic-other", sentences, text: sentences.map((s) => s.text).join("") };
}

/** Open Review on `seeded` and take the pass chooser's first choice, Every sentence. */
async function openReview(page: Page, seeded: Seeded): Promise<void> {
  await page.goto(readerUrl(seeded).replace("#", "&review=1#"));
  await expect(page.getByRole("heading", { name: "Which sentences?" })).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("textbox", { name: "What was said" })).toBeFocused();
}

test("scrolling the reader over 1,500 sentences keeps p95 under 20 ms", async ({ page }) => {
  const seeded = seedLong();
  await page.goto(readerUrl(seeded));
  await expect(page.locator("article p")).toHaveCount(LONG_SHAPE.turns);
  const dom = await page.evaluate(async () => {
    await document.fonts.ready;
    return { scrollHeight: document.documentElement.scrollHeight, viewport: window.innerHeight };
  });
  const frames = Math.min(FRAMES, Math.floor((dom.scrollHeight - dom.viewport) / STEP_PX));
  expect(frames).toBeGreaterThanOrEqual(150);
  const result = { ...dom, frames, ...summarise((await scrollFrames(page, frames)).slice(1)) };
  console.log(`long reader frame times: ${JSON.stringify(result)}`);
  expect(result.p95).toBeLessThanOrEqual(P95_CEILING_MS);
});

test("stepping through 300 of 1,500 sentences in Review keeps p95 under 20 ms, five sentences drawn", async ({ page }) => {
  await openReview(page, seedLong());
  // The one in hand and two either side, never the transcript.
  expect(await page.locator("main .review-row").count()).toBeLessThanOrEqual(5);
  const times = await page.evaluate(
    () =>
      new Promise<number[]>((resolve) => {
        const field = document.querySelector("textarea") as HTMLTextAreaElement;
        const out: number[] = [];
        let last = performance.now();
        let n = 0;
        const frame = () => {
          const now = performance.now();
          out.push(now - last);
          last = now;
          field.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", code: "Enter", bubbles: true, cancelable: true }));
          if (++n < 300) requestAnimationFrame(frame);
          else resolve(out.slice(1));
        };
        requestAnimationFrame(frame);
      }),
  );
  const result = summarise(times);
  console.log(`review step frame times: ${JSON.stringify(result)}`);
  await expect(page.getByText(/^(299|300) of 1,500 checked$/)).toBeVisible();
  expect(result.p95).toBeLessThanOrEqual(P95_CEILING_MS);
});

/**
 * Count the edit list's saves as the page starts them: the body is made into
 * JSON just before `fetch` is called, in the same frame, so a frame that
 * started one carries #251's cost, not the edit's. Before the page loads.
 */
async function countSaves(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const started: number[] = [];
    Object.assign(window, { dsjSaves: started });
    const fetch = window.fetch.bind(window);
    window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
      const request = input instanceof Request ? input : null;
      const url = request?.url ?? String(input);
      if ((init?.method ?? request?.method) === "PUT" && url.endsWith("/edits")) started.push(performance.now());
      return fetch(input, init);
    };
  });
}

type Frames = { keystroke: number[]; edit: number[]; saving: number[] };

/**
 * Alternate frames of one keystroke in the box and one Enter, `edits` times:
 * each Enter commits a one-word correction. The frame after each is that
 * action's cost; one in which an edit-list save started is kept apart, in
 * `saving` (countSaves).
 */
function typeAndCommit(page: Page, edits: number): Promise<Frames> {
  return page.evaluate(
    (edits) =>
      new Promise<Frames>((resolve) => {
        const field = document.querySelector("textarea") as HTMLTextAreaElement;
        const saves = (window as unknown as { dsjSaves: number[] }).dsjSaves;
        // React reads a typed value through the element's own setter, not the instance's.
        const setValue = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
        if (setValue === undefined) throw new Error("no value setter");
        const out: Frames = { keystroke: [], edit: [], saving: [] };
        let last = performance.now();
        let n = 0;
        const frame = () => {
          const now = performance.now();
          const saved = saves.some((at) => at >= last && at < now);
          // n odd: the frame before dispatched a keystroke; n even (from 2): an Enter.
          if (n > 0) (saved ? out.saving : n % 2 === 1 ? out.keystroke : out.edit).push(now - last);
          last = now;
          if (n === 2 * edits) {
            resolve(out);
            return;
          }
          if (n % 2 === 0) {
            setValue.call(field, `${field.value}q`);
            field.dispatchEvent(new Event("input", { bubbles: true }));
          } else {
            field.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", code: "Enter", bubbles: true, cancelable: true }));
          }
          n += 1;
          requestAnimationFrame(frame);
        };
        requestAnimationFrame(frame);
      }),
    edits,
  );
}

test("a correction on 1,500 sentences lands inside 50 ms at p95, second opinion worked out again included", async ({ page }) => {
  test.slow();
  await countSaves(page);
  const results: Record<string, { keystroke: Summary; edit: Summary; saving: Summary }> = {};
  for (const [name, seeded] of [
    ["alone", seedLong()],
    ["with a second opinion", seedLong(otherEngine)],
  ] as const) {
    await openReview(page, seeded);
    // With one, the grey line is there, so every edit works it out again; alone, it is not.
    await expect(page.locator("main .sr-only", { hasText: "Second opinion" })).toHaveCount(name === "alone" ? 0 : 1);
    const frames = await typeAndCommit(page, 60);
    await expect(page.getByText("60 of 1,500 checked")).toBeVisible();
    // Each commit was a change of words, so the edit list was saved.
    await expect(page.locator("header").getByText("Saved")).toBeVisible({ timeout: 30_000 });
    expect(frames.saving.length).toBeGreaterThan(0);
    results[name] = { keystroke: summarise(frames.keystroke), edit: summarise(frames.edit), saving: summarise(frames.saving) };
  }
  console.log(`review edit frame times: ${JSON.stringify(results)}`);
  for (const result of Object.values(results)) {
    expect(result.keystroke.p95).toBeLessThanOrEqual(P95_CEILING_MS);
    expect(result.edit.p95).toBeLessThanOrEqual(EDIT_P95_CEILING_MS);
  }
});

test("what a commit in Review sends on 1,500 sentences, in bytes and time (#251)", async ({ page }) => {
  test.slow();
  await openReview(page, seedLong());
  const sent: { route: string; bytes: number; ms: number }[] = [];
  const timed = async (request: Request) => {
    if (request.method() !== "PUT") return;
    const route = new URL(request.url()).pathname.split("/").at(-1) ?? "";
    const bytes = request.postDataBuffer()?.length ?? 0;
    const response = await request.response();
    await response?.finished();
    expect(response?.status()).toBe(200);
    sent.push({ route, bytes, ms: +request.timing().responseEnd.toFixed(1) });
  };
  const pending: Promise<void>[] = [];
  page.on("request", (request) => pending.push(timed(request)));
  const box = page.getByRole("textbox", { name: "What was said" });
  const saved = page.locator("header").getByText("Saved");
  const commits: { kind: string; frame: number; sends: typeof sent }[] = [];
  // Five checks with a correction, then five with none, each let settle before the next.
  for (const kind of [...Array(5).fill("corrected"), ...Array(5).fill("checked only")] as string[]) {
    const from = sent.length;
    if (kind === "corrected") await box.fill(`${await box.inputValue()} q`);
    // Enter, at the start of a frame, and the length of that frame: the commit and what it starts.
    const frame = await page.evaluate(
      () =>
        new Promise<number>((resolve) => {
          const field = document.querySelector("textarea") as HTMLTextAreaElement;
          requestAnimationFrame(() => {
            const began = performance.now();
            field.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", code: "Enter", bubbles: true, cancelable: true }));
            requestAnimationFrame(() => resolve(+(performance.now() - began).toFixed(1)));
          });
        }),
    );
    // Past the review's 400 ms wait (reviewApi.ts SAVE_AFTER_MS), then until both saves are in.
    await page.waitForTimeout(600);
    await expect(saved).toBeVisible({ timeout: 30_000 });
    await Promise.all(pending);
    commits.push({ kind, frame, sends: sent.slice(from) });
  }
  console.log(`review commit saves: ${JSON.stringify(commits)}`);
  // A correction sends the edit list; every commit sends the review.
  for (const commit of commits) {
    expect(commit.sends.some((s) => s.route === "review")).toBe(true);
    expect(commit.sends.some((s) => s.route === "edits")).toBe(commit.kind === "corrected");
  }
});
