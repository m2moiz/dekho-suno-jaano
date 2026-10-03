// The edit list checked after every edit, undo and redo, in development
// builds, so a change that breaks it fails at the edit that broke it, not at a
// save much later (#86, after audapolis's document_linter, rewritten for
// dsj's entries rather than copied).
//
// The rules are dsj/hatao.py's `validate` and `loads`, the ones the server
// refuses a save by, so a list the page accepts is a list the server accepts.
// One more is the render's (`spans_to_mute`): the app only mutes, retypes and
// re-times words, so its list must still play the recording from the start,
// in order, with no stretch left out, or a render would refuse it.
//
// Relative imports only, as editOps.ts.

import type { Content, Entry } from "./editOps";

/** The list is broken. The message names the entry and what is wrong with it. */
export class InvalidContent extends Error {
  constructor(message: string) {
    super(message);
    this.name = "InvalidContent";
  }
}

// dsj/hatao.py `_LANGUAGE`: a BCP 47 tag's shape, loosely ("ur", "pa-Guru", "en-GB").
const LANGUAGE = /^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{1,8})*$/;

// dsj/hatao.py `_TOUCH_S`: two items closer than this are one stretch, not a cut.
const TOUCH_S = 0.002;

function where(index: number, entry: Entry): string {
  return entry.kind === "paragraph"
    ? `entry ${index} (paragraph, speaker ${JSON.stringify(entry.speaker)})`
    : `entry ${index} (item ${JSON.stringify(entry.text)} at ${entry.sourceStart} s of source ${JSON.stringify(entry.source)})`;
}

/**
 * Return nothing, or throw naming the first entry that is wrong. `sources` are
 * the source ids the server gave the page; an item naming any other is broken.
 */
export function lint(content: Content, sources: ReadonlySet<string>): void {
  let previous = 0;
  let reached = 0;
  content.forEach((entry, index) => {
    if (entry.kind === "paragraph") {
      if (entry.language !== null && !LANGUAGE.test(entry.language)) {
        throw new InvalidContent(`${where(index, entry)}: language ${JSON.stringify(entry.language)} is not a language tag`);
      }
      return;
    }
    if (entry.kind !== "item") {
      throw new InvalidContent(`entry ${index} has kind ${JSON.stringify((entry as { kind: unknown }).kind)}`);
    }
    if (index === 0) throw new InvalidContent(`${where(index, entry)}: the list must open with a paragraph`);
    if (!sources.has(entry.source)) {
      throw new InvalidContent(`${where(index, entry)}: no such source; the list has ${[...sources].join(", ")}`);
    }
    for (const [name, value] of [["start", entry.sourceStart], ["length", entry.length]] as const) {
      if (typeof value !== "number" || !Number.isFinite(value) || value < 0) {
        throw new InvalidContent(`${where(index, entry)}: ${name} is ${value}; it must be a finite number of seconds, 0 or more`);
      }
    }
    if (typeof entry.text !== "string") throw new InvalidContent(`${where(index, entry)}: its text is not a string`);
    if (typeof entry.muted !== "boolean") {
      throw new InvalidContent(`${where(index, entry)}: muted is ${JSON.stringify(entry.muted)}, not true or false`);
    }
    if (entry.sourceStart < previous || entry.sourceStart > reached + TOUCH_S) {
      throw new InvalidContent(
        `${where(index, entry)}: does not follow the entry before it in the recording ` +
          `(the list reached ${reached} s), so it would not play, or render, in order`,
      );
    }
    previous = entry.sourceStart;
    reached = Math.max(reached, entry.sourceStart + entry.length);
  });
}

/** The check an Editor runs: `lint` in development builds, nothing in the one a person runs. */
export function devCheck(content: Content): ((next: Content) => void) | undefined {
  if (!import.meta.env.DEV) return undefined;
  const sources = new Set(content.flatMap((e) => (e.kind === "item" ? [e.source] : [])));
  return (next) => lint(next, sources);
}
