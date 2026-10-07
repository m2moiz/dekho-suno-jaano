// Which words a person corrected (#83), and what the recogniser had written
// there, for the margin (Hashiya spec, "The margin": "corrections with the
// original struck through in red").
//
// The words on the page are paired with the transcript's own words: a word
// pairs with the first unpaired word of the transcript that overlaps it in
// time and reads the same. A word left as it was pairs, and so does one whose
// edges alone were dragged (#85), even though both read back with
// confidence 1 (correct.ts and bounds.ts give it, and dsj/ui/edits.py
// `_confidences` gives 1 to any item that matches no token exactly). What is
// left unpaired is a correction: confidence-1 words with no counterpart, the
// transcript's words with none, or both, grouped where they meet in time. A
// transcript word left unpaired with no word over it was deleted ("the the"
// retyped as "the", or a stretch emptied), and shows struck through too.

import { read, type Reading, type TranscriptDoc } from "@/features/transcript/document";

export type Correction = {
  /** The paragraph it is in. */
  turn: number;
  /**
   * Its first and last word, as indexes into the reading's words. A deletion
   * has none: `last` is `first - 1`, and `first` is where the words were.
   */
  first: number;
  last: number;
  /** What the transcript had over the same stretch of time, and what it says now ("" when deleted). */
  original: string;
  now: string;
};

/**
 * The transcript's own words, in time order, made once per transcript: each
 * one's start, end and text, trimmed. They are `read`'s words, so sub-word
 * pieces (" questi" and "on") are one word by the same rule the reader uses.
 */
export type Tokens = { t: Float64Array; e: Float64Array; w: readonly string[] };

// Half a millisecond: dsj/hatao.py rounds times to the millisecond.
const EPS = 0.0005;

/** Words [first, last] of `reading` as one string, as the page shows them, trimmed. */
function wordsText(reading: Reading, first: number, last: number): string {
  const { turn, offset, length } = reading.words;
  const text = reading.turns[turn[first] ?? 0]?.text ?? "";
  return text.slice(offset[first] ?? 0, (offset[last] ?? 0) + (length[last] ?? 0)).trim();
}

export function tokensOf(doc: TranscriptDoc): Tokens {
  const reading = read(doc);
  const { start, end } = reading.words;
  return { t: start, e: end, w: Array.from(start, (_, i) => wordsText(reading, i, i)) };
}

/** The first index whose value is at or after `seconds`. */
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

/** The transcript's words that overlap [from, to), in order. */
function* overlapping(tokens: Tokens, from: number, to: number): Generator<number> {
  // A word that starts before `from` can still reach past it.
  let i = firstFrom(tokens.t, from - EPS);
  while (i > 0 && (tokens.e[i - 1] ?? 0) > from + EPS) i -= 1;
  for (; i < tokens.t.length && (tokens.t[i] ?? 0) < to - EPS; i += 1) {
    if ((tokens.e[i] ?? 0) > from + EPS || (tokens.t[i] ?? 0) >= from - EPS) yield i;
  }
}

/** The transcript's own words whose middle falls in [from, to), joined by spaces. */
export function originalText(tokens: Tokens, from: number, to: number): string {
  const said: string[] = [];
  for (const i of overlapping(tokens, from, to)) {
    const middle = ((tokens.t[i] ?? 0) + (tokens.e[i] ?? 0)) / 2;
    if (middle >= from - EPS && middle < to - EPS && tokens.w[i] !== "") said.push(tokens.w[i] ?? "");
  }
  return said.join(" ");
}

type Loose = { from: number; to: number; original?: number; word?: number };
type Group = { from: number; to: number; originals: number[]; words: number[] };

/** Every corrected stretch, in time order: retyped words, deleted words, or both. */
export function corrections(reading: Reading, tokens: Tokens): Correction[] {
  const { start, end, confidence, turn } = reading.words;
  const paired = new Uint8Array(tokens.t.length);
  const loose: Loose[] = [];
  for (let w = 0; w < start.length; w += 1) {
    const text = wordsText(reading, w, w);
    let pair = -1;
    for (const i of overlapping(tokens, start[w] ?? 0, end[w] ?? 0)) {
      if (paired[i] === 0 && tokens.w[i] === text) {
        pair = i;
        break;
      }
    }
    if (pair >= 0) paired[pair] = 1;
    else if (confidence[w] === 1) loose.push({ from: start[w] ?? 0, to: end[w] ?? 0, word: w });
  }
  for (let i = 0; i < tokens.t.length; i += 1) {
    if (paired[i] === 0 && tokens.w[i] !== "") loose.push({ from: tokens.t[i] ?? 0, to: tokens.e[i] ?? 0, original: i });
  }
  loose.sort((a, b) => a.from - b.from);

  // Loose ends that meet in time are one correction, inside one paragraph.
  const groups: Group[] = [];
  for (const x of loose) {
    const group = groups.at(-1);
    const lastWord = group?.words.at(-1);
    const meets = group !== undefined && x.from <= group.to + EPS;
    const sameTurn = x.word === undefined || lastWord === undefined || (turn[x.word] === turn[lastWord] && x.word === lastWord + 1);
    if (group !== undefined && meets && sameTurn) {
      group.to = Math.max(group.to, x.to);
      if (x.word !== undefined) group.words.push(x.word);
      if (x.original !== undefined) group.originals.push(x.original);
    } else {
      groups.push({ from: x.from, to: x.to, words: x.word === undefined ? [] : [x.word], originals: x.original === undefined ? [] : [x.original] });
    }
  }

  const out: Correction[] = [];
  for (const group of groups) {
    const original = group.originals.map((i) => tokens.w[i] ?? "").join(" ");
    const first = group.words[0];
    const last = group.words.at(-1);
    if (first !== undefined && last !== undefined) {
      const now = wordsText(reading, first, last);
      if (now !== original) out.push({ turn: turn[first] ?? 0, first, last, original, now });
      continue;
    }
    // Deleted: shown beside the nearer of the words either side of where it was.
    const after = firstFrom(start, group.from - EPS);
    const before = after - 1;
    const nearer =
      before < 0 ? after : after >= start.length ? before : group.from - (end[before] ?? 0) <= (start[after] ?? 0) - group.to ? before : after;
    if (nearer < 0 || nearer >= start.length) continue;
    out.push({ turn: turn[nearer] ?? 0, first: before + 1, last: before, original, now: "" });
  }
  return out;
}
