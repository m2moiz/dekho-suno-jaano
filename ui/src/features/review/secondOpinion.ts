// The second opinion (Hashiya spec, Review mode): "when another transcript of
// the same recording exists, its reading of the same time span appears in
// grey as a second opinion; where both are in the same script, the words that
// differ are underlined." It also feeds the "Likely errors" pass.
//
// Aligned by time, not by text: two engines cut sentences in different
// places, but a word said at 12.3 s is at 12.3 s in both. A word of the other
// reading belongs to the span its middle falls in, so a word across a boundary
// is counted once. The other transcript is loaded by the routes the reader
// already uses; nothing new is asked of the server.

import { api } from "@/api/client";
import { ApiError, fromBody } from "@/features/errors/appError";
import type { RecordingRow, TranscriptRow } from "@/features/library/types";
import { parseTranscript, read, type Reading } from "@/features/transcript/document";
import { fold } from "@/lib/fold";
import { firstStrong } from "@/lib/script";
import type { Span } from "./model";

export type Opinions = {
  /** The other reading's words, one list a span. */
  words: string[][];
  /** Which of those words differ from this transcript's, or null where the scripts differ. */
  differs: (boolean[] | null)[];
  /** The spans where the two disagree on a word, either side's: likely errors. */
  disagree: Set<number>;
};

// How far before the first span, or after the last, a word of the other
// reading may sit (its middle from the span's edge, in seconds) and still be
// given to that span, so Ctrl+G at either end of a transcript keeps it (Task
// 12 review, M9). A choice, with no measurement behind it: about one long
// edge word (parakeet's first word in scratch/eval/arm_a_transcript.json runs
// 0.32 to 1.36 s, as that review read it), short enough that a stretch only
// the other engine transcribed is not poured into one sentence. Tested at 0.1
// and 0.7 s in, 1.1 and 1.7 s out (second-opinion.test.ts).
export const EDGE_S = 1.0;

/** The other reading's words for each span, in one walk (both are in time order). */
export function opinionWords(other: Reading, spans: readonly Span[]): string[][] {
  const { start, end, turn, offset, length } = other.words;
  const out: string[][] = spans.map(() => []);
  let k = 0;
  for (let w = 0; w < start.length; w += 1) {
    const middle = ((start[w] ?? 0) + (end[w] ?? 0)) / 2;
    while (k < spans.length && middle >= (spans[k]?.end ?? 0)) k += 1;
    let place = k;
    if (k === spans.length) {
      // After the last span: it takes a word close behind it.
      const last = spans[k - 1];
      if (last === undefined || middle - last.end > EDGE_S) continue;
      place = k - 1;
    } else if (middle < (spans[k]?.start ?? 0)) {
      // In a pause between two spans (an engine stretches a sentence's last word
      // into the silence after it): the nearer span takes the word, so the grey
      // line never loses one. Before the first span, the first takes a word close in front of it.
      const before = spans[k - 1];
      if (before === undefined) {
        if ((spans[k]?.start ?? 0) - middle > EDGE_S) continue;
      } else if (middle - before.end <= (spans[k]?.start ?? 0) - middle) {
        place = k - 1;
      }
    }
    const from = offset[w] ?? 0;
    const text = other.turns[turn[w] ?? 0]?.text.slice(from, from + (length[w] ?? 0)).trim();
    if (text) out[place]?.push(text);
  }
  return out;
}

/**
 * A word as compared: the library search's fold (`@/lib/fold`: case, short
 * vowels, one form of each Urdu letter) with punctuation dropped too, so one
 * word in two spellings or with a comma after it is the same word.
 */
export function normalize(word: string): string {
  return fold(word.normalize("NFC")).replace(/[\p{P}\p{S}]/gu, "");
}

/** Which of `theirs` are not in the longest common run of equal words with `mine`. */
export function differing(mine: readonly string[], theirs: readonly string[]): boolean[] {
  const a = mine.map(normalize);
  const b = theirs.map(normalize);
  const n = a.length;
  const m = b.length;
  // A table is fine: two lists of 412 words, the longest sentence tests/perf/fixture.ts
  // allows, took 1.56 ms a call (mean of 20 calls to this function, timed in a
  // throwaway unit test run with `npx vitest run` from ui/, 7 Oct 2026).
  const table = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
  for (let i = n - 1; i >= 0; i -= 1) {
    const row = table[i] as Uint16Array;
    const below = table[i + 1] as Uint16Array;
    for (let j = m - 1; j >= 0; j -= 1) {
      row[j] = a[i] === b[j] ? (below[j + 1] ?? 0) + 1 : Math.max(below[j] ?? 0, row[j + 1] ?? 0);
    }
  }
  const same = new Array<boolean>(m).fill(false);
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      same[j] = true;
      i += 1;
      j += 1;
    } else if ((table[i + 1]?.[j] ?? 0) >= (table[i]?.[j + 1] ?? 0)) {
      i += 1;
    } else {
      j += 1;
    }
  }
  return same.map((s, k) => !s && b[k] !== "");
}

/** Both readings open in the same script: only then is a word-by-word comparison meaningful. */
export function sameScript(a: string, b: string): boolean {
  const script = firstStrong(a);
  return script !== "none" && script === firstStrong(b);
}

/** One span's comparison: which of `theirs` differ (null where the scripts differ or they have none), and whether the two disagree. */
function compare(own: string, theirs: readonly string[]): { marks: boolean[] | null; disagrees: boolean } {
  const ownWords = own.split(/\s+/).filter(Boolean);
  const ownCount = ownWords.filter((w) => normalize(w) !== "").length;
  // The other reading has nothing here but the draft has words: the engine
  // invented them or the other one missed them. Either way the two disagree,
  // and that needs no script to see.
  if (theirs.length === 0) return { marks: null, disagrees: ownCount > 0 };
  if (!sameScript(own, theirs.join(" "))) return { marks: null, disagrees: false };
  const marks = differing(ownWords, theirs);
  // Words in the common run are the unmarked ones of theirs; any draft word
  // beyond them is the draft's own (a repetition, an invented word).
  const common = theirs.filter((w, j) => !marks[j] && normalize(w) !== "").length;
  return { marks, disagrees: marks.some(Boolean) || ownCount > common };
}

const NONE = (spans: readonly Span[]): Opinions => ({ words: spans.map(() => []), differs: spans.map(() => null), disagree: new Set() });

/** The second opinion for every span, given this transcript's text of each. */
export function secondOpinion(other: Reading | null, spans: readonly Span[], mine: readonly string[]): Opinions {
  if (other === null) return NONE(spans);
  const words = opinionWords(other, spans);
  const disagree = new Set<number>();
  const differs = words.map((theirs, k) => {
    const { marks, disagrees } = compare(mine[k] ?? "", theirs);
    if (disagrees) disagree.add(k);
    return marks;
  });
  return { words, differs, disagree };
}

/**
 * `secondOpinion`, remembering its last answer, for Review's every edit. An
 * edit changes one sentence's words, so only that span is compared again;
 * the other reading's words are placed again only when the spans change (a
 * split or a merge) or the other reading does. On the 1,500-sentence fixture
 * comparing every span again made a correction's frame 57 ms at the median,
 * against 17 ms with no second opinion; remembered, 16.6 ms (Task 15, one run
 * each, medians, `cd ui && npx playwright test tests/perf/long.spec.ts
 * --project=perf`).
 */
export function rememberedOpinion(): (other: Reading | null, spans: readonly Span[], mine: readonly string[]) => Opinions {
  let placed: { other: Reading; spans: readonly Span[]; words: string[][] } | null = null;
  let compared: { theirs: readonly string[]; own: string; marks: boolean[] | null; disagrees: boolean }[] = [];
  return (other, spans, mine) => {
    if (other === null) return NONE(spans);
    if (placed?.other !== other || placed.spans !== spans) {
      placed = { other, spans, words: opinionWords(other, spans) };
      compared = [];
    }
    const disagree = new Set<number>();
    const differs = placed.words.map((theirs, k) => {
      const own = mine[k] ?? "";
      let last = compared[k];
      if (last?.theirs !== theirs || last.own !== own) {
        last = { theirs, own, ...compare(own, theirs) };
        compared[k] = last;
      }
      if (last.disagrees) disagree.add(k);
      return last.marks;
    });
    return { words: placed.words, differs, disagree };
  };
}

/** The newest other transcript of the same recording, or null (the library lists them newest first). */
export function otherTranscript(recording: RecordingRow, transcriptId: number): TranscriptRow | null {
  return recording.transcripts.find((t) => t.id !== transcriptId) ?? null;
}

/** Another transcript's words, read as the reader reads them. Throws ApiError in the server's words. */
export async function loadReading(transcriptId: number): Promise<Reading> {
  const route = `/api/transcripts/${transcriptId}`;
  const { data, error, response } = await api.GET("/api/transcripts/{transcript_id}", {
    params: { path: { transcript_id: String(transcriptId) } },
  });
  if (data === undefined) throw new ApiError(fromBody(error, response, route));
  return read(parseTranscript(data));
}
