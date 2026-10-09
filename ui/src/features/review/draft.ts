// A copy of Review's box in the browser (Task 14 fix round 3). Words typed in
// the box live in React state until a key or a button commits them, and a
// phone can tear the page down first: iOS Safari fires no beforeunload, and
// hiding the page does not commit a half-typed box (fix round 4). A committed
// sentence is the saves' to keep: since #251 each is one change, sent with
// keepalive. So while the box differs from its sentence, its words are also
// in localStorage, and the next opening of Review on the same transcript,
// unchanged, puts them back.
//
// One key per transcript, holding only the box in hand: the transcript's sha,
// the sentence's span, what the list said for it when typing began (`base`),
// and the words. It is cleared once the box is committed and the edit list
// saved. It is put back only into that same span whose words are still
// `base`: a correction made since, or a split or merge the review never
// saved, would otherwise lose words (Task 14 re-review 2, R2-I1).

import type { Span } from "./model";

export type Draft = { sha: string; start: number; end: number; base: string; text: string };

const key = (transcriptId: number) => `dsj-review-draft-${transcriptId}`;

// localStorage can be missing or full (a private window, a quota): the copy is
// a second line of defence behind the saves, so its failure is logged, not shown.
function storage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export function writeDraft(transcriptId: number, sha: string, span: Span, base: string, text: string): void {
  try {
    storage()?.setItem(key(transcriptId), JSON.stringify({ sha, start: span.start, end: span.end, base, text } satisfies Draft));
  } catch (thrown) {
    console.warn("dsj ui: could not keep a copy of the box", thrown);
  }
}

export function clearDraft(transcriptId: number): void {
  storage()?.removeItem(key(transcriptId));
}

/** The draft kept for this transcript, or null; one that cannot be read is dropped. */
export function readDraft(transcriptId: number): Draft | null {
  const raw = storage()?.getItem(key(transcriptId)) ?? null;
  if (raw === null) return null;
  try {
    const draft = JSON.parse(raw) as Partial<Draft>;
    const { sha, start, end, base, text } = draft;
    if (typeof sha === "string" && typeof start === "number" && typeof end === "number" && typeof base === "string" && typeof text === "string") {
      return { sha, start, end, base, text };
    }
  } catch {
    // Not JSON: dropped below.
  }
  clearDraft(transcriptId);
  return null;
}
