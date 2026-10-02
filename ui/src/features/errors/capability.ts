// The two browser features the reader leans on, checked before anything
// renders (#107). Neither throws when it is missing: the page loads, the words
// show, and nothing follows the audio or answers a click. That silent shape is
// the one this app exists to avoid, so a browser without them is told so.
//
// Floors from @mdn/browser-compat-data 8.1.2, read 2026-09-22: Highlight and
// CSS.highlights are Safari 17.2, Chrome 105, Firefox 140. Click-to-word never
// sets the floor, because every engine ships one of its two spellings
// (caretPositionFromPoint: Safari 26.2, Chrome 128, Firefox 20;
// caretRangeFromPoint, the fallback: Safari 5, Chrome 4, Firefox 150; the
// issue said "no Firefox", which 8.1.2 itself no longer says).

import type { AppError } from "./appError";

export const FLOOR = "Safari 17.2, Chrome 105 or Firefox 140";

type Probe = {
  Highlight?: unknown;
  CSS?: { highlights?: unknown };
  document: { caretPositionFromPoint?: unknown; caretRangeFromPoint?: unknown };
  navigator: { userAgent: string };
};

/** The features this browser lacks, by the names a person could search for. */
export function missingFeatures(win: Probe): string[] {
  const missing: string[] = [];
  if (typeof win.Highlight !== "function" || win.CSS?.highlights == null) {
    missing.push("the CSS Custom Highlight API (Highlight and CSS.highlights)");
  }
  const doc = win.document;
  if (
    typeof doc.caretPositionFromPoint !== "function" &&
    typeof doc.caretRangeFromPoint !== "function"
  ) {
    missing.push("document.caretPositionFromPoint (or its older spelling, caretRangeFromPoint)");
  }
  return missing;
}

/** "Safari 17.1", "Chrome 104", "Firefox 139", or the user agent when none of those. */
export function browserName(userAgent: string): string {
  const patterns: [string, RegExp][] = [
    ["Edge", /Edg\/(\d+(?:\.\d+)?)/],
    ["Firefox", /Firefox\/(\d+(?:\.\d+)?)/],
    ["Chrome", /Chrome\/(\d+(?:\.\d+)?)/],
    ["Safari", /Version\/(\d+(?:\.\d+)?).*Safari\//],
  ];
  for (const [name, pattern] of patterns) {
    const found = pattern.exec(userAgent);
    if (found?.[1] !== undefined) return `${name} ${found[1]}`;
  }
  return `this browser (${userAgent})`;
}

/** The error to show instead of the app, or null when this browser can run it. */
export function capabilityError(win: Probe): AppError | null {
  const missing = missingFeatures(win);
  if (missing.length === 0) return null;
  return {
    error: "UnsupportedBrowser",
    message:
      `${browserName(win.navigator.userAgent)} cannot run dsj's reader: it lacks ` +
      `${missing.join(", and ")}. Open the same address in ${FLOOR}, or newer.`,
    request: null,
  };
}
