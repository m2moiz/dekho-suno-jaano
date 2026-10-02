// The 60fps claim as a check (#108): the synthetic 1,038-sentence transcript
// rendered the way the original 16.7 ms measurement rendered the private one,
// one <span data-w> per token inside one <p> per speaker turn, then scrolled
// 220 px per frame for 200 frames while frame times are sampled. The method
// is #108's second comment, unchanged.
//
// Gated on p95, not median: the median is pinned to the display's 16.7 ms and
// cannot move until a regression is catastrophic. 20 ms is the baseline p95
// (17.5 ms on 2026-09-22) plus headroom. Runs in `just ui-perf`, part of
// `just verify`, on this Mac; never in `just check` or CI, where a frame-time
// gate is a flaky gate (#57 F8).
import { expect, test } from "@playwright/test";

import { SHAPE, syntheticTranscript, type Transcript } from "./fixture.ts";

const P95_CEILING_MS = 20;
const FRAMES = 200;
const STEP_PX = 220;

function escape(text: string): string {
  return text.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

// Sized to match the page the baseline came from, because the frame time
// depends on the page's size, not its look. That page had 21,847 spans, 23,934
// nodes and a 51,106 px scroll height (#108's second comment). This one: a
// <section> per turn holding a label, a <p>, and a <span> per sentence around
// its tokens, which is 23,841 nodes; and 22px type at 48ch, which is 50,552 px
// in a 1280x720 chromium (measured 2026-10-02).
function page(transcript: Transcript): string {
  const turns: { speaker: number; sentences: string[] }[] = [];
  for (const sentence of transcript.sentences) {
    let turn = turns.at(-1);
    if (turn === undefined || turn.speaker !== sentence.speaker) {
      turn = { speaker: sentence.speaker, sentences: [] };
      turns.push(turn);
    }
    const spans = sentence.tokens.map((token) => `<span data-w>${escape(token.w)}</span>`);
    turn.sentences.push(`<span>${spans.join("")}</span>`);
  }
  const body = turns
    .map((turn) => {
      const label = `${transcript.speakers[turn.speaker] ?? ""} <time>00:00</time>`;
      return `<section><h2>${label}</h2><p>${turn.sentences.join("")}</p></section>`;
    })
    .join("\n");
  return `<!doctype html><html><head><meta charset="utf-8"><style>
    body { max-width: 48ch; margin: 0 auto; padding: 2rem; font: 22px/1.7 Georgia, serif; }
    h2 { font: 600 13px system-ui, sans-serif; margin: 1.25em 0 0; color: #666; }
    p { margin: 0; }
  </style></head><body>${body}</body></html>`;
}

test("scrolling the 1,038-sentence transcript keeps p95 frame time under 20 ms", async ({ page: tab }) => {
  await tab.setContent(page(syntheticTranscript()));

  const dom = await tab.evaluate(() => ({
    spans: document.querySelectorAll("[data-w]").length,
    turns: document.querySelectorAll("section").length,
    allNodes: document.getElementsByTagName("*").length,
    scrollHeight: document.documentElement.scrollHeight,
    viewport: window.innerHeight,
  }));
  // The page is the size the claim is about, and tall enough that every one
  // of the 200 frames really scrolls; at the bottom a frame is free.
  expect(dom.spans).toBe(SHAPE.tokens);
  expect(dom.turns).toBe(SHAPE.turns);
  expect(dom.scrollHeight).toBeGreaterThan(FRAMES * STEP_PX + dom.viewport);

  const frames = await tab.evaluate(
    ({ frames, step }) =>
      new Promise<number[]>((resolve) => {
        const times: number[] = [];
        let last = performance.now();
        let n = 0;
        const tick = () => {
          const now = performance.now();
          times.push(now - last);
          last = now;
          window.scrollBy(0, step);
          if (++n < frames) requestAnimationFrame(tick);
          else resolve(times);
        };
        requestAnimationFrame(tick);
      }),
    { frames: FRAMES, step: STEP_PX },
  );
  // The first sample spans setContent to the first frame, not a scroll.
  const sorted = frames.slice(1).sort((a, b) => a - b);
  const at = (q: number) => +(sorted[Math.floor(sorted.length * q)] ?? Number.NaN).toFixed(1);
  const result = {
    ...dom,
    samples: sorted.length,
    median: at(0.5),
    p95: at(0.95),
    max: +(sorted.at(-1) ?? Number.NaN).toFixed(1),
    over16_7ms: sorted.filter((ms) => ms > 16.7).length,
  };
  console.log(`frame times: ${JSON.stringify(result)}`);

  expect(result.samples).toBe(FRAMES - 1);
  expect(result.p95).toBeLessThanOrEqual(P95_CEILING_MS);
});
