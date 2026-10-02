// #108's frame-time method, shared by every page it is pointed at: scroll
// STEP_PX a frame for FRAMES frames and time each frame. Unchanged from #108's
// second comment; scroll.spec.ts (the plain page) and reader.spec.ts (the real
// reader) both measure through this, so their numbers compare.
import type { Page } from "@playwright/test";

export const P95_CEILING_MS = 20;
export const FRAMES = 200;
export const STEP_PX = 220;

export type Summary = { samples: number; median: number; p95: number; max: number; over16_7ms: number };

/**
 * Each frame's length in ms while `page` scrolls `frames` frames; the first
 * spans the setup, not a scroll.
 */
export function scrollFrames(page: Page, frames: number = FRAMES): Promise<number[]> {
  return page.evaluate(
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
    { frames, step: STEP_PX },
  );
}

/** Median, p95 and max of `times` in ms, to 0.1 ms. */
export function summarise(times: number[]): Summary {
  const sorted = [...times].sort((a, b) => a - b);
  const at = (q: number) => +(sorted[Math.floor(sorted.length * q)] ?? Number.NaN).toFixed(1);
  return {
    samples: sorted.length,
    median: at(0.5),
    p95: at(0.95),
    max: +(sorted.at(-1) ?? Number.NaN).toFixed(1),
    over16_7ms: sorted.filter((ms) => ms > 16.7).length,
  };
}
