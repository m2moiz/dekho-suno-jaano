// Review mode's model (Hashiya spec, Review mode): the sentences being
// checked, by their span of the recording; splitting and merging them; the
// two passes; which sentences are likely errors; and picking a review up
// again. Pure: no React, no fetch.
//
// A segment is a span of time, not a run of entries, because every edit
// keeps time: a correction keeps its stretch's start and end (#83), a speaker
// change moves only paragraph marks, and a split cuts at a word's start. So a
// segment saved before an edit names the same words after it, and the edit
// list stays the one home of the words.

import type { components } from "@/api/schema";
import { correction, textOf } from "@/features/edit/correct";
import type { Content, CorrectOp } from "@/lib/editOps";

export type ReviewDocument = components["schemas"]["ReviewDocument"];
export type Segment = components["schemas"]["ReviewSegment"];
export type ReviewCorrection = components["schemas"]["ReviewCorrection"];
export type Flag = Segment["flags"][number];
export type ReviewPass = ReviewDocument["review_pass"];

/**
 * The sha of the transcript as it is now, as the review route said it on
 * loading (reviewApi.ts, loadReview, the one place one is made). The only sha
 * a review is saved under: a saved document's own `transcript_sha` is a plain
 * string, so it cannot be passed to `documentOf` by mistake (Task 11 review).
 */
export type CurrentSha = string & { readonly __current: true };

export type Span = { start: number; end: number };
export type Range = { start: number; stop: number };

// Half a millisecond: dsj/hatao.py rounds times to the millisecond.
const EPS = 0.0005;

// Two spans are one sentence across a re-transcription when both ends agree
// this closely, in seconds: a choice, with no measurement behind it, set below
// one 0.08 s parakeet frame (the figure ui/src/features/transcript/document.ts
// cites for GAP_S) so a sentence that moved by a word is not taken for the old
// one. Tested at 0.03 s moved and 0.2 s moved (review-model.test.ts, "resume").
export const SAME_SPAN_S = 0.05;

// Arriving on a sentence plays it from 0.3 s before to 0.2 s after (spec,
// Review mode), and resuming after typing backs up 1.5 s (spec, Tab). Taken
// from the spec, not measured.
export const BEFORE_S = 0.3;
export const AFTER_S = 0.2;
export const RESUME_BACK_S = 1.5;

/** Each sentence of the list: from its paragraph mark's first word to its last word's end. */
export function sentenceSpans(content: Content): Span[] {
  const out: Span[] = [];
  let open: Span | null = null;
  for (const entry of content) {
    if (entry.kind === "paragraph") {
      if (open !== null) out.push(open);
      open = null;
      continue;
    }
    if (entry.text === "") continue;
    const end = entry.sourceStart + entry.length;
    if (open === null) open = { start: entry.sourceStart, end };
    else open.end = Math.max(open.end, end);
  }
  if (open !== null) out.push(open);
  return out;
}

export function freshSegments(content: Content): Segment[] {
  return sentenceSpans(content).map(({ start, end }): Segment => ({ start, end, state: "unchecked", flags: [], speaker: null, edited: false, words_hash: null }));
}

/**
 * A short hash of a sentence's words, kept with its check (#274, ruling R7):
 * 32-bit FNV-1a of the words' UTF-8 bytes, spacing aside, as eight hex
 * digits. A transcript made again keeps a sentence checked only while its
 * words still hash the same, without the review holding the words. Not a
 * guard against anyone: a one-in-four-billion chance that changed words
 * hash alike is far under any other way a check can be wrong.
 */
export function wordsHash(words: string): string {
  const text = words.trim().split(/\s+/).join(" ");
  let hash = 0x811c9dc5;
  for (const byte of new TextEncoder().encode(text)) {
    hash ^= byte;
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

/**
 * Every item with words, as its entry index and its start, in list order.
 * The list plays in order (ui/src/lib/linter.ts holds it), so the starts are
 * sorted and a segment's words are found by binary search.
 */
export type WordIndex = { at: Uint32Array; start: Float64Array };

export function wordIndex(content: Content): WordIndex {
  const at: number[] = [];
  const start: number[] = [];
  content.forEach((entry, index) => {
    if (entry.kind === "item" && entry.text !== "") {
      at.push(index);
      start.push(entry.sourceStart);
    }
  });
  return { at: Uint32Array.from(at), start: Float64Array.from(start) };
}

function firstFrom(starts: Float64Array, seconds: number): number {
  let lo = 0;
  let hi = starts.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if ((starts[mid] ?? 0) < seconds) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/** The entries holding a span's words: from its first word item to one past its last; null when it has none. */
export function entryRange(words: WordIndex, span: Span): Range | null {
  const lo = firstFrom(words.start, span.start - EPS);
  const hi = firstFrom(words.start, span.end - EPS);
  if (hi <= lo) return null;
  return { start: words.at[lo] ?? 0, stop: (words.at[hi - 1] ?? 0) + 1 };
}

/** A span's words as the box shows them, or "" when it has none. */
export function segmentText(content: Content, words: WordIndex, span: Span): string {
  const range = entryRange(words, span);
  return range === null ? "" : textOf(content, range.start, range.stop);
}

/** The segment at or after `seconds`: where a saved cursor resumes. */
export function indexAt(segments: readonly Span[], seconds: number): number {
  const found = segments.findIndex((s) => s.end > seconds + EPS);
  return found < 0 ? Math.max(0, segments.length - 1) : found;
}

export type Resumed = { segments: Segment[]; cursor: number; lost: number };

/**
 * The review to pick up: the saved one as it is when the transcript is the
 * one it was made against; else this transcript's sentences, each keeping
 * what a saved one with the same span said (Review Focus 4: a run from the
 * app with the same settings writes the same file). A check is kept only
 * when the sentence's words are still the ones it was checked with (#274,
 * ruling R7): the same span is not the same words, since a re-run can hear
 * them otherwise, and the edit list holding the corrections was put aside
 * (#249). A check from before #274 has no hash, so its words are unknown and
 * it is dropped too. `lost` counts the checks dropped, for the page to say.
 */
export function resume(saved: ReviewDocument | null, content: Content, sha: string): Resumed {
  if (saved !== null && saved.transcript_sha === sha) {
    return { segments: saved.segments, cursor: indexAt(saved.segments, saved.cursor_s), lost: 0 };
  }
  const fresh = freshSegments(content);
  if (saved === null) return { segments: fresh, cursor: 0, lost: 0 };
  const kept = new Set<number>();
  const words = wordIndex(content);
  let k = 0;
  const segments = fresh.map((segment) => {
    while (k < saved.segments.length && (saved.segments[k]?.start ?? 0) < segment.start - SAME_SPAN_S) k += 1;
    const old = saved.segments[k];
    if (old === undefined || Math.abs(old.start - segment.start) > SAME_SPAN_S || Math.abs(old.end - segment.end) > SAME_SPAN_S) {
      return segment;
    }
    const heard = { ...segment, flags: [...old.flags], speaker: old.speaker };
    if (old.state !== "checked") return heard;
    if (old.words_hash === null || old.words_hash !== wordsHash(segmentText(content, words, segment))) return heard;
    kept.add(k);
    return { ...heard, state: old.state, edited: old.edited, words_hash: old.words_hash };
  });
  const lost = saved.segments.filter((s, i) => s.state === "checked" && !kept.has(i)).length;
  return { segments, cursor: indexAt(segments, saved.cursor_s), lost };
}

export type Split = { segments: Segment[] } | { refused: string };

const BETWEEN = "Put the cursor between two words: a sentence splits where one word ends and the next begins, not at its start or its end.";

/**
 * Split segment `index` at `caret`, a place in the text the box shows
 * (spec: "time split at the matching word boundary"). A caret in the gap
 * between two words splits there; inside a word, at the nearer edge of that
 * word (Review Focus 3). An edge that is the sentence's own start or end, and
 * a one-word sentence, are refused with a sentence saying why. A word in
 * pieces (" questi" "on") is one word, as the reader reads it.
 */
export function splitAt(content: Content, segments: readonly Segment[], index: number, caret: number): Split {
  const segment = segments[index];
  const range = segment === undefined ? null : entryRange(wordIndex(content), segment);
  if (segment === undefined || range === null) return { refused: "This sentence has no words to split." };
  // Each word's first letter in the joined text, and its start in the recording.
  let raw = "";
  const opens: { at: number; time: number }[] = [];
  for (let e = range.start; e < range.stop; e += 1) {
    const entry = content[e];
    if (entry?.kind !== "item" || entry.text === "") continue;
    if (opens.length === 0 || /^\s/.test(entry.text)) {
      opens.push({ at: raw.length + (/^\s*/.exec(entry.text)?.[0].length ?? 0), time: entry.sourceStart });
    }
    raw += entry.text;
  }
  if (opens.length < 2) return { refused: "This sentence is one word, so there is nowhere to split it." };
  const lead = raw.length - raw.trimStart().length;
  const text = raw.trim();
  const begins = opens.map((o) => o.at - lead);
  const ends = begins.map((_, k) => (k + 1 < begins.length ? text.slice(0, begins[k + 1]).trimEnd().length : text.length));
  // Boundary k sits before word k; 0 and begins.length are the sentence's own ends.
  let k = -1;
  for (let b = 1; b < begins.length; b += 1) {
    if (caret >= (ends[b - 1] ?? 0) && caret <= (begins[b] ?? 0)) {
      k = b;
      break;
    }
  }
  if (k < 0) {
    const inside = begins.findIndex((b, w) => caret > b && caret < (ends[w] ?? 0));
    if (inside >= 0) k = caret - (begins[inside] ?? 0) <= (ends[inside] ?? 0) - caret ? inside : inside + 1;
    else k = caret <= (begins[0] ?? 0) ? 0 : begins.length;
  }
  if (k <= 0 || k >= begins.length) return { refused: BETWEEN };
  const at = opens[k]?.time ?? segment.start;
  // The flags, the edit and the speaker stay with the first half only, so the
  // pass's counts do not count one sentence twice (Task 11 review). Both
  // halves are to be checked again, and either can be flagged again.
  const first: Segment = { ...segment, end: at, state: "unchecked", words_hash: null };
  const second: Segment = { ...segment, start: at, state: "unchecked", flags: [], edited: false, speaker: null, words_hash: null };
  return { segments: [...segments.slice(0, index), first, second, ...segments.slice(index + 1)] };
}

/** Segment `index` joined to the one before it, to be checked again; null for the first. */
export function mergeWithPrevious(segments: readonly Segment[], index: number): Segment[] | null {
  const previous = segments[index - 1];
  const current = segments[index];
  if (index < 1 || previous === undefined || current === undefined) return null;
  const merged: Segment = {
    start: previous.start,
    end: current.end,
    state: "unchecked",
    flags: [...new Set([...previous.flags, ...current.flags])],
    speaker: previous.speaker ?? current.speaker,
    edited: previous.edited || current.edited,
    words_hash: null,
  };
  return [...segments.slice(0, index - 1), merged, ...segments.slice(index + 1)];
}

export function toggleFlag(segment: Segment, flag: Flag): Segment {
  const flags = segment.flags.includes(flag) ? segment.flags.filter((f) => f !== flag) : [...segment.flags, flag];
  return { ...segment, flags };
}

/**
 * The likely errors (spec, "Passes"): a sentence with an unsure word (under
 * the engine's cut-off, ui/src/features/transcript/confidence.ts), a flag, or
 * a disagreement with the second opinion. One walk over each span's entries.
 */
export function likelyErrors(
  content: Content,
  words: WordIndex,
  segments: readonly Segment[],
  cutoff: number | null,
  disagree: ReadonlySet<number>,
): number[] {
  const out: number[] = [];
  segments.forEach((segment, index) => {
    if (segment.flags.length > 0 || disagree.has(index)) {
      out.push(index);
      return;
    }
    const range = cutoff === null ? null : entryRange(words, segment);
    if (range === null || cutoff === null) return;
    for (let e = range.start; e < range.stop; e += 1) {
      const entry = content[e];
      if (entry?.kind === "item" && entry.text !== "" && entry.confidence !== null && entry.confidence < cutoff) {
        out.push(index);
        return;
      }
    }
  });
  return out;
}

/** The segments a pass visits, in order. */
export function passOrder(count: number, pass: ReviewPass, likely: readonly number[]): number[] {
  return pass === "likely" ? [...likely] : Array.from({ length: count }, (_, i) => i);
}

/** The next (or previous) segment of `order` after (or before) `current`, or null at the end. */
export function step(order: readonly number[], current: number, by: 1 | -1): number | null {
  if (by > 0) return order.find((i) => i > current) ?? null;
  return [...order].reverse().find((i) => i < current) ?? null;
}

export type Counts = { checked: number; total: number; edited: number; flagged: number; reassigned: number };

/** What the pass did, for its end (spec, "Finishing"). */
export function counts(segments: readonly Segment[]): Counts {
  return {
    checked: segments.filter((s) => s.state === "checked").length,
    total: segments.length,
    edited: segments.filter((s) => s.edited).length,
    flagged: segments.filter((s) => s.flags.length > 0).length,
    reassigned: segments.filter((s) => s.speaker !== null).length,
  };
}

/**
 * Time left at the current pace (spec, top bar): the median gap between this
 * session's checks, so one long pause does not double the estimate. Nothing
 * until three checks make a pace.
 */
export function timeLeft(checkedAtMs: readonly number[], remaining: number): string | null {
  if (checkedAtMs.length < 3 || remaining <= 0) return null;
  const gaps = checkedAtMs
    .slice(1)
    .map((t, k) => t - (checkedAtMs[k] ?? t))
    .sort((a, b) => a - b);
  const median = gaps[gaps.length >> 1] ?? 0;
  const minutes = Math.round((median * remaining) / 60_000);
  if (minutes < 1) return "under a minute left";
  if (minutes < 60) return `about ${minutes} min left`;
  return `about ${Math.floor(minutes / 60)} h ${minutes % 60} min left`;
}

/** The document the page saves. */
export function documentOf(fields: {
  sha: CurrentSha;
  pass: ReviewPass;
  cursorS: number;
  startedAt: string;
  segments: readonly Segment[];
  corrections: readonly ReviewCorrection[];
}): ReviewDocument {
  return {
    version: 1,
    transcript_sha: fields.sha,
    review_pass: fields.pass,
    cursor_s: fields.cursorS,
    started_at: fields.startedAt,
    updated_at: new Date().toISOString(),
    segments: [...fields.segments],
    corrections: [...fields.corrections],
  };
}

/** A change of words made in Review: the edit, and what it changed, for sub-project C. */
export type WordFix = { op: CorrectOp; correction: Omit<ReviewCorrection, "at"> };

/**
 * The edit that makes entries [range) say `text`, changing only the words
 * that differ (F4): the common words at either end are left as they are,
 * times and all, so a one-word fix keeps every other word's link to the audio
 * and the reader's margin strikes through only what changed. Null when the
 * words are the same, spacing aside, so checking a sentence again applies
 * nothing twice (Review Focus 2). A word added with nothing to replace takes
 * the time of the word beside it, retyped with it; a word in pieces
 * (" questi" "on") is retyped whole.
 */
export function wordCorrection(content: Content, range: Range, text: string): WordFix | null {
  // The words as the reader reads them: an item opening with a space starts one.
  const groups: { first: number; last: number; text: string }[] = [];
  for (let e = range.start; e < range.stop; e += 1) {
    const entry = content[e];
    if (entry?.kind !== "item" || entry.text === "") continue;
    const open = groups.at(-1);
    if (open === undefined || /^\s/.test(entry.text)) groups.push({ first: e, last: e, text: entry.text });
    else {
      open.last = e;
      open.text += entry.text;
    }
  }
  // Compared as the box shows them, a word between spaces, each knowing the entries holding it.
  const mine: { word: string; group: number }[] = [];
  groups.forEach((g, k) => {
    for (const word of g.text.trim().split(/\s+/)) if (word !== "") mine.push({ word, group: k });
  });
  const typed = text.trim().split(/\s+/).filter((w) => w !== "");
  if (mine.length === 0) return null;
  let p = 0;
  while (p < mine.length && p < typed.length && mine[p]?.word === typed[p]) p += 1;
  let s = 0;
  while (s < mine.length - p && s < typed.length - p && mine[mine.length - 1 - s]?.word === typed[typed.length - 1 - s]) s += 1;
  if (mine.length - p - s === 0 && typed.length - p - s === 0) return null;
  // Only words added: retype the word before them with them, or at the start the word after.
  if (mine.length - p - s === 0) {
    if (p > 0) p -= 1;
    else s -= 1;
  }
  // An edit replaces whole entries, so a changed word in pieces is retyped whole.
  const firstGroup = mine[p]?.group ?? 0;
  const lastGroup = mine[mine.length - 1 - s]?.group ?? firstGroup;
  while (p > 0 && mine[p - 1]?.group === firstGroup) p -= 1;
  while (s > 0 && mine[mine.length - s]?.group === lastGroup) s -= 1;
  const start = groups[firstGroup]?.first ?? range.start;
  const stop = (groups[lastGroup]?.last ?? range.stop - 1) + 1;
  const after = typed.slice(p, typed.length - s).join(" ");
  const before = mine
    .slice(p, mine.length - s)
    .map((w) => w.word)
    .join(" ");
  let from = Number.POSITIVE_INFINITY;
  let to = 0;
  for (let e = start; e < stop; e += 1) {
    const entry = content[e];
    if (entry?.kind !== "item") continue;
    from = Math.min(from, entry.sourceStart);
    to = Math.max(to, entry.sourceStart + entry.length);
  }
  return { op: correction(content, start, stop, after), correction: { start: from, end: to, before, after } };
}

/**
 * Where `caret`, a place in the box's text, falls in the list's text of the
 * same words (Task 11 review): the box may be spaced otherwise (two spaces, a
 * line break), so the place is found word by word. Inside or at the edge of
 * a word, the same place in that word; in a gap, the end of the word before
 * it. Null when the two do not hold the same number of words.
 */
export function caretInList(box: string, caret: number, list: string): number | null {
  const tokens = (text: string) => [...text.matchAll(/\S+/g)].map((m) => ({ at: m.index, end: m.index + m[0].length }));
  const mine = tokens(box);
  const theirs = tokens(list);
  if (mine.length !== theirs.length) return null;
  for (let k = 0; k < mine.length; k += 1) {
    const word = mine[k];
    const same = theirs[k];
    if (word === undefined || same === undefined) break;
    if (caret < word.at) return k === 0 ? 0 : (theirs[k - 1]?.end ?? 0);
    if (caret <= word.end) return same.at + (caret - word.at);
  }
  return list.length;
}
