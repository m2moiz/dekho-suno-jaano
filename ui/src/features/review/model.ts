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
import { textOf } from "@/features/edit/correct";
import type { Content } from "@/lib/editOps";

export type ReviewDocument = components["schemas"]["ReviewDocument"];
export type Segment = components["schemas"]["ReviewSegment"];
export type ReviewCorrection = components["schemas"]["ReviewCorrection"];
export type Flag = Segment["flags"][number];
export type ReviewPass = ReviewDocument["review_pass"];

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
  return sentenceSpans(content).map(({ start, end }): Segment => ({ start, end, state: "unchecked", flags: [], speaker: null, edited: false }));
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
 * app with the same settings writes the same file). `lost` counts the checked
 * sentences that no longer match, for the page to say.
 */
export function resume(saved: ReviewDocument | null, content: Content, sha: string): Resumed {
  if (saved !== null && saved.transcript_sha === sha) {
    return { segments: saved.segments, cursor: indexAt(saved.segments, saved.cursor_s), lost: 0 };
  }
  const fresh = freshSegments(content);
  if (saved === null) return { segments: fresh, cursor: 0, lost: 0 };
  const used = new Set<number>();
  let k = 0;
  const segments = fresh.map((segment) => {
    while (k < saved.segments.length && (saved.segments[k]?.start ?? 0) < segment.start - SAME_SPAN_S) k += 1;
    const old = saved.segments[k];
    if (old === undefined || Math.abs(old.start - segment.start) > SAME_SPAN_S || Math.abs(old.end - segment.end) > SAME_SPAN_S) {
      return segment;
    }
    used.add(k);
    return { ...segment, state: old.state, flags: [...old.flags], speaker: old.speaker, edited: old.edited };
  });
  const lost = saved.segments.filter((s, i) => s.state === "checked" && !used.has(i)).length;
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
  const first: Segment = { ...segment, end: at, state: "unchecked" };
  const second: Segment = { ...segment, start: at, state: "unchecked" };
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
  sha: string;
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
