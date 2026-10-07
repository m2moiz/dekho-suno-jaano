// Which words a person corrected (#83), and what the recogniser had written
// there, for the margin (Hashiya spec, "The margin": "corrections with the
// original struck through in red").
//
// A corrected word reads back with confidence 1: correct.ts gives every new
// word 1, and dsj/ui/edits.py `_confidences` gives 1 to any item that matches
// no token of the transcript. So does a word whose edges alone were dragged
// (#85, bounds.ts gives it 1 too), a word a correction took in and left as it
// was, and now and then a word the recogniser was fully sure of. So a
// confidence-1 word counts as corrected only when no word of the transcript's
// own over the same stretch of time reads the same; a run of such words in one
// paragraph is one correction.

import type { Reading, TranscriptDoc } from "@/features/transcript/document";

export type Correction = {
  /** The paragraph it is in. */
  turn: number;
  /** Its first and last word, as indexes into the reading's words. */
  first: number;
  last: number;
  /** What the transcript had over the same stretch of time, and what it says now. */
  original: string;
  now: string;
};

/**
 * The transcript's own words, in time order, made once per transcript: each
 * one's start, end and text, trimmed. A word is a token that opens with
 * whitespace (or a sentence) plus the pieces after it, the rule `read` uses,
 * so " questi" and "on" compare as "question".
 */
export type Tokens = { t: Float64Array; e: Float64Array; w: readonly string[] };

// Half a millisecond: dsj/hatao.py rounds times to the millisecond.
const EPS = 0.0005;

export function tokensOf(doc: TranscriptDoc): Tokens {
  const t: number[] = [];
  const e: number[] = [];
  const w: string[] = [];
  for (const sentence of doc.sentences) {
    sentence.tokens.forEach((token, k) => {
      const end = token.e ?? token.t;
      const last = w.length - 1;
      if (k === 0 || /^\s/.test(token.w) || last < 0) {
        t.push(token.t);
        e.push(end);
        w.push(token.w);
      } else {
        e[last] = Math.max(e[last] ?? end, end);
        w[last] += token.w;
      }
    });
  }
  return { t: Float64Array.from(t), e: Float64Array.from(e), w: w.map((word) => word.trim()) };
}

/** The first word starting at or after `seconds`. */
function firstFrom(times: Float64Array, seconds: number): number {
  let lo = 0;
  let hi = times.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if ((times[mid] ?? 0) < seconds) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/** The transcript's own words whose middle falls in [from, to), joined by spaces. */
export function originalText(tokens: Tokens, from: number, to: number): string {
  const said: string[] = [];
  // A word that starts before `from` can still have its middle after it.
  let i = firstFrom(tokens.t, from - EPS);
  while (i > 0 && (tokens.e[i - 1] ?? 0) > from + EPS) i -= 1;
  for (; i < tokens.t.length && (tokens.t[i] ?? 0) < to - EPS; i += 1) {
    const middle = ((tokens.t[i] ?? 0) + (tokens.e[i] ?? 0)) / 2;
    if (middle >= from - EPS && middle < to - EPS) said.push(tokens.w[i] ?? "");
  }
  return said.filter((word) => word !== "").join(" ");
}

/** Whether a word of the transcript's own reading `text` overlaps [from, to) in time. */
function saidThere(tokens: Tokens, from: number, to: number, text: string): boolean {
  let i = firstFrom(tokens.t, from - EPS);
  while (i > 0 && (tokens.e[i - 1] ?? 0) > from + EPS) i -= 1;
  for (; i < tokens.t.length && (tokens.t[i] ?? 0) < to - EPS; i += 1) {
    if (tokens.w[i] === text) return true;
  }
  return false;
}

/** Every corrected stretch: one per run of retyped words inside one paragraph. */
export function corrections(reading: Reading, tokens: Tokens): Correction[] {
  const { start, end, confidence, turn, offset, length } = reading.words;
  const textOf = (first: number, last: number) =>
    (reading.turns[turn[first] ?? 0]?.text ?? "").slice(offset[first] ?? 0, (offset[last] ?? 0) + (length[last] ?? 0)).trim();
  const retyped = (w: number) =>
    confidence[w] === 1 && !saidThere(tokens, start[w] ?? 0, end[w] ?? 0, textOf(w, w));
  const out: Correction[] = [];
  let w = 0;
  while (w < start.length) {
    if (!retyped(w)) {
      w += 1;
      continue;
    }
    let last = w;
    while (last + 1 < start.length && turn[last + 1] === turn[w] && retyped(last + 1)) last += 1;
    const original = originalText(tokens, start[w] ?? 0, end[last] ?? 0);
    out.push({ turn: turn[w] ?? 0, first: w, last, original, now: textOf(w, last) });
    w = last + 1;
  }
  return out;
}
