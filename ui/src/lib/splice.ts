// One change, not the whole list (#251). A 2.5 h transcript's edit list is
// about 3.5 MB, and every correction in Review sent all of it (measured in
// Task 15). The server takes a splice instead, `delete` entries at `start`
// replaced by `insert` (PATCH .../edits and .../review), and this file works
// one out from the list as the server holds it and the list now.
//
// Relative imports only, so the unit test can hand this file to the
// TypeScript compiler on its own, as editOps.ts.

import type { Entry } from "./editOps";

/** Put `insert` in place of `delete` entries at `start`. */
export type Splice<T> = { start: number; delete: number; insert: T[] };

/**
 * The splice that turns `before` into `after`: everything between their
 * longest common prefix and their longest common suffix, compared with
 * `same`. Null when the two are equal, so nothing is sent. The suffix never
 * reaches back into the prefix, so taking one of three equal entries out is
 * one entry deleted, not a negative count.
 */
export function spliceOf<T>(before: readonly T[], after: readonly T[], same: (a: T, b: T) => boolean): Splice<T> | null {
  const shorter = Math.min(before.length, after.length);
  let start = 0;
  while (start < shorter && same(before[start] as T, after[start] as T)) start += 1;
  if (start === before.length && start === after.length) return null;
  let tail = 0;
  while (tail < shorter - start && same(before[before.length - 1 - tail] as T, after[after.length - 1 - tail] as T)) tail += 1;
  return { start, delete: before.length - start - tail, insert: after.slice(start, after.length - tail) };
}

/** `list` with `change` made, as the server makes it. */
export function spliced<T>(list: readonly T[], change: Splice<T>): T[] {
  return [...list.slice(0, change.start), ...change.insert, ...list.slice(change.start + change.delete)];
}

/**
 * Two entries of an edit list are the same entry when every field the file
 * holds is equal. `confidence` is left out: it is not in the file, and the
 * server works it out again on every read (dsj/ui/edits.py, _confidences).
 * An unchanged entry is the same object (editOps.ts keeps them), checked first.
 */
export function sameEntry(a: Entry, b: Entry): boolean {
  if (a === b) return true;
  if (a.kind === "paragraph" || b.kind === "paragraph") {
    return a.kind === "paragraph" && b.kind === "paragraph" && a.speaker === b.speaker && a.language === b.language;
  }
  return a.source === b.source && a.sourceStart === b.sourceStart && a.length === b.length && a.text === b.text && a.muted === b.muted;
}
