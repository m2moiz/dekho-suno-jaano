// Retyping a stretch of words the recogniser got wrong, keeping it bound to
// the same audio (#83).
//
// The stretch keeps its start and its end, so no neighbouring word moves.
// Inside it, the new words share the time in proportion to their length in
// characters, the arithmetic wassgha/rescript uses (reimplemented, not
// copied: its licence is noncommercial); a longer word takes longer to say,
// and without timings for words nobody said, that is the best guess there is.
// A person who hears it is off drags the edge (#85).
//
// Each new word is sure (`confidence` 1): a person checked it, so its
// low-confidence tint (#62) goes, and the server reads it back the same way
// (dsj/ui/edits.py, `_confidences`). A stretch that was muted stays muted:
// retyping a bleeped word must not bring its sound back.

import type { Content, CorrectOp, Entry, Item } from "@/lib/editOps";

// The file's own precision: dsj/hatao.py rounds lengths to the millisecond.
function ms(seconds: number): number {
  return Math.round(seconds * 1000) / 1000;
}

/**
 * The edit that puts `text` in place of entries [start, stop), which must
 * open on an item that has words. An empty `text` leaves the stretch as audio
 * with no words in it, as a pause is.
 */
export function correction(content: Content, start: number, stop: number, text: string): CorrectOp {
  const items = content.slice(start, stop).filter((e): e is Item => e.kind === "item");
  const first = items.find((e) => e.text !== "");
  if (first === undefined) throw new RangeError(`entries [${start}, ${stop}) hold no words to correct`);
  const from = items[0]?.sourceStart ?? first.sourceStart;
  const to = Math.max(...items.map((e) => e.sourceStart + e.length));
  const muted = items.some((e) => e.text !== "" && e.muted);
  const words = text.trim().split(/\s+/).filter((w) => w !== "");
  const base = { kind: "item" as const, source: first.source, muted };
  if (words.length === 0) {
    return { kind: "correct", start, stop, entries: [{ ...base, sourceStart: from, length: ms(to - from), text: "", confidence: null }] };
  }
  // The space in front of the first word is the stretch's own (" Hello"),
  // so it reads as a new word or as the rest of one, as it did.
  const lead = /^\s*/.exec(first.text)?.[0] ?? "";
  const total = words.reduce((sum, w) => sum + w.length, 0);
  const edges = [from];
  let said = 0;
  for (const word of words) {
    said += word.length;
    edges.push(said === total ? to : ms(from + ((to - from) * said) / total));
  }
  const entries: Entry[] = words.map((word, i) => {
    const at = edges[i] ?? from;
    return {
      ...base,
      sourceStart: at,
      length: ms((edges[i + 1] ?? to) - at),
      text: `${i === 0 ? lead : " "}${word}`,
      confidence: 1,
    };
  });
  return { kind: "correct", start, stop, entries };
}

/** The words of entries [start, stop) as one string, as the reader shows them. */
export function textOf(content: Content, start: number, stop: number): string {
  return content
    .slice(start, stop)
    .map((e) => (e.kind === "item" ? e.text : ""))
    .join("")
    .trim();
}
