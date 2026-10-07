// A copy of Review's box in the browser (Task 14 fix round 3). Words typed in
// the box live in React state until a key or a button commits them, and a
// phone can tear the page down first: iOS Safari fires no beforeunload, and a
// keepalive save carries at most 64 KiB, about 290 words of an edit list
// (editing.ts KEEPALIVE_BYTES). So while the box differs from its sentence,
// its words are also in localStorage, and the next opening of Review on the
// same transcript, unchanged, puts them back.
//
// One key per transcript, holding only the box in hand: the sentence's span,
// the transcript's sha, and the words. It is cleared once the box is
// committed and the edit list saved.

import type { Span } from "./model";

export type Draft = { sha: string; start: number; end: number; text: string };

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

export function writeDraft(transcriptId: number, sha: string, span: Span, text: string): void {
  try {
    storage()?.setItem(key(transcriptId), JSON.stringify({ sha, start: span.start, end: span.end, text } satisfies Draft));
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
    if (typeof draft.sha === "string" && typeof draft.start === "number" && typeof draft.end === "number" && typeof draft.text === "string") {
      return { sha: draft.sha, start: draft.start, end: draft.end, text: draft.text };
    }
  } catch {
    // Not JSON: dropped below.
  }
  clearDraft(transcriptId);
  return null;
}
