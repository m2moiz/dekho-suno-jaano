// Whether a screen recording's picture is shown or folded away (#80), kept
// between launches the way the speed and the theme are.

import { readCookie, writeCookie } from "@/lib/cookie";

export const COOKIE = "dsj-video";

/** Shown unless it was folded away last time. */
export function readVideoShown(doc: Document = document): boolean {
  return readCookie(COOKIE, doc) !== "hidden";
}

export function saveVideoShown(shown: boolean, doc: Document = document): void {
  writeCookie(COOKIE, shown ? "shown" : "hidden", doc);
}
