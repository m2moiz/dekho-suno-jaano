// Who said a stretch of the edit list, and the edit that changes it (Hashiya
// spec, Review mode: "Speaker changes are a new EditOp kind that splits the
// speaker's paragraph at the sentence boundary and sets the speaker").
//
// A paragraph mark governs every item after it up to the next mark, and the
// list built from a transcript has one mark per sentence (dsj/hatao.py,
// from_transcript). So a whole sentence changes speaker by changing its own
// mark; a stretch inside one gets a mark of its own in front of it, and a
// mark after it hands what follows back to the speaker it had. Each added
// mark copies the language of the one it splits.

import type { Content, Entry, Paragraph, SpeakerOp } from "@/lib/editOps";

/** The index of the paragraph mark governing entry `index`: the nearest at or before it, or -1. */
export function governingParagraph(content: Content, index: number): number {
  for (let i = Math.min(index, content.length - 1); i >= 0; i -= 1) {
    if (content[i]?.kind === "paragraph") return i;
  }
  return -1;
}

/** Who says entry `index`, by label, or null. */
export function speakerAt(content: Content, index: number): string | null {
  const entry = content[governingParagraph(content, index)];
  return entry?.kind === "paragraph" ? entry.speaker : null;
}

/** Whether any item in [from, to) has words. */
function wordsIn(content: Content, from: number, to: number): boolean {
  for (let i = from; i < to; i += 1) {
    const entry = content[i];
    if (entry?.kind === "item" && entry.text !== "") return true;
  }
  return false;
}

/** Whether words follow `index` before the next paragraph mark. */
function continues(content: Content, index: number): boolean {
  for (let i = index; i < content.length; i += 1) {
    const entry = content[i];
    if (entry?.kind === "paragraph") return false;
    if (entry?.kind === "item" && entry.text !== "") return true;
  }
  return false;
}

/**
 * The edit that makes `speaker` say entries [start, stop), which open on a
 * word, or null when they already all have that speaker.
 */
export function speakerChange(content: Content, start: number, stop: number, speaker: string | null): SpeakerOp | null {
  const p = governingParagraph(content, start);
  const governing = content[p];
  if (governing?.kind !== "paragraph") throw new RangeError(`entry ${start} has no paragraph mark before it`);
  const after = content[governingParagraph(content, stop - 1)] as Paragraph;
  // A stretch that opens where its paragraph's words open changes that mark;
  // one that opens later gets a mark of its own, unless its speaker already
  // says it (a stretch running on into someone else's sentence).
  const opensParagraph = !wordsIn(content, p + 1, start);
  const from = opensParagraph ? p : start;
  const lead = !opensParagraph && governing.speaker !== speaker;
  const out: Entry[] = lead ? [{ ...governing, speaker }] : [];
  let changed = lead;
  for (let i = from; i < stop; i += 1) {
    const entry = content[i] as Entry;
    if (entry.kind === "paragraph") {
      if (entry.speaker !== speaker) changed = true;
      // A mark inside the stretch would only say its speaker again (a merged
      // sentence's middle, Task 5 review): the stretch becomes one paragraph.
      // The first entry is the stretch's own mark, a sentence boundary, kept.
      if (i > from || lead) continue;
      out.push({ ...entry, speaker });
    } else {
      out.push(entry);
    }
  }
  if (!changed) return null;
  // What follows the stretch in its last paragraph goes back to who said it.
  if (after.speaker !== speaker && continues(content, stop)) out.push({ ...after });
  return { kind: "speaker", start: from, stop, entries: out };
}

/** A label for a new speaker: the first SPEAKER_nn no speaker has. */
export function newSpeakerLabel(labels: readonly string[]): string {
  for (let n = 0; ; n += 1) {
    const label = `SPEAKER_${String(n).padStart(2, "0")}`;
    if (!labels.includes(label)) return label;
  }
}
