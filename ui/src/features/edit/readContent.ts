// The reader's paragraphs and word table, made from the edit list (#66)
// rather than from the transcript, so a word retyped (#83) or re-timed (#85)
// reads, plays and highlights as edited. The paragraphs and words come out of
// the same `read` the plain reader uses, so both break text the same way.
//
// Each word also gets the entries it spans in the list, [first, stop), which
// is what an edit of that word changes. A word is one entry or several: a
// recogniser writes " questi" and "on" as two tokens, and between them may sit
// an entry with no text that the word also spans (dsj/hatao.py, `_words`).

import type { Content } from "@/lib/editOps";
import { read, type Reading, type Sentence, type TranscriptDoc } from "@/features/transcript/document";

export type EditReading = {
  reading: Reading;
  /** Each word's first entry in the list. */
  first: Uint32Array;
  /** One past each word's last entry. */
  stop: Uint32Array;
};

/**
 * The transcript's legend, then any label the list uses that the legend
 * lacks, in order of first use: a speaker a person added in Review (Ctrl+3 on
 * a two-speaker call) reads as "Speaker 3". Undefined when neither has a label,
 * so an unlabelled transcript still breaks paragraphs at pauses (document.ts GAP_S).
 */
export function speakerLabels(content: Content, legend: readonly string[] | undefined): string[] | undefined {
  const labels = [...(legend ?? [])];
  const known = new Set(labels);
  for (const entry of content) {
    if (entry.kind === "paragraph" && entry.speaker !== null && !known.has(entry.speaker)) {
      known.add(entry.speaker);
      labels.push(entry.speaker);
    }
  }
  return legend === undefined && labels.length === 0 ? undefined : labels;
}

/** The reading of `content`, with `legend` (the transcript's speakers, then any the list adds) naming its paragraphs. */
export function readContent(content: Content, legend: string[] | undefined): EditReading {
  const speakers = speakerLabels(content, legend);
  const sentences: Sentence[] = [];
  const entryOf: number[][] = [];
  let sentence: Sentence | null = null;
  let entries: number[] = [];
  const close = () => {
    if (sentence !== null && sentence.tokens.length > 0) {
      sentences.push(sentence);
      entryOf.push(entries);
    }
  };
  content.forEach((entry, index) => {
    if (entry.kind === "paragraph") {
      close();
      const label = entry.speaker === null ? -1 : (speakers?.indexOf(entry.speaker) ?? -1);
      sentence = { start: 0, end: 0, text: "", tokens: [], ...(speakers ? { speaker: label < 0 ? null : label } : {}) };
      entries = [];
      return;
    }
    if (sentence === null || entry.text === "") return;
    const end = entry.sourceStart + entry.length;
    if (sentence.tokens.length === 0) sentence.start = entry.sourceStart;
    sentence.end = Math.max(sentence.end, end);
    sentence.text += entry.text;
    sentence.tokens.push({
      t: entry.sourceStart,
      w: entry.text,
      e: end,
      ...(entry.confidence === null ? {} : { c: entry.confidence }),
    });
    entries.push(index);
  });
  close();
  const doc: TranscriptDoc = { audio: "", model: "", sentences, ...(speakers ? { speakers } : {}) };
  const reading = read(doc);

  // The same rule `read` opens a word by: a sentence's first token, and every
  // token that starts with whitespace.
  const first: number[] = [];
  const stop: number[] = [];
  sentences.forEach((s, i) => {
    const indexes = entryOf[i] ?? [];
    s.tokens.forEach((token, k) => {
      const at = indexes[k] ?? 0;
      if (k === 0 || /^\s/.test(token.w)) {
        first.push(at);
        stop.push(at + 1);
      } else {
        stop[stop.length - 1] = at + 1;
      }
    });
  });
  if (first.length !== reading.words.start.length) {
    throw new Error(`the edit list read as ${reading.words.start.length} words but mapped ${first.length}`);
  }
  return { reading, first: Uint32Array.from(first), stop: Uint32Array.from(stop) };
}

function same<T extends ArrayLike<number>>(a: T, b: T): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i += 1) {
    const x = a[i] ?? 0;
    const y = b[i] ?? 0;
    // NaN, a word with no confidence, is the same as NaN.
    if (x !== y && !(Number.isNaN(x) && Number.isNaN(y))) return false;
  }
  return true;
}

/**
 * `next`, keeping `previous`'s Reading when the two draw the same words at the
 * same times: a mute changes neither, and a new Reading would rebuild the
 * paragraphs' highlights and the playhead for nothing.
 */
export function keepReading(previous: EditReading | null, next: EditReading): EditReading {
  if (previous === null) return next;
  const a = previous.reading;
  const b = next.reading;
  const unchanged =
    a.turns.length === b.turns.length &&
    a.turns.every((turn, i) => {
      const other = b.turns[i];
      return other !== undefined && turn.text === other.text && turn.speaker === other.speaker && turn.start === other.start;
    }) &&
    same(a.words.start, b.words.start) &&
    same(a.words.end, b.words.end) &&
    same(a.words.confidence, b.words.confidence);
  return unchanged ? { ...next, reading: a } : next;
}
