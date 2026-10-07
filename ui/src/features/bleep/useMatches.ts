// The words to bleep (#84), looked for while the reader is open, not only
// while the drawer is: the menu's Bleep item carries a badge exactly when the
// lists found something (Hashiya spec, Reader).

import { useCallback, useEffect, useState } from "react";

import { fromThrown, showError } from "@/features/errors/appError";
import type { Reading } from "@/features/transcript/document";
import type { Editor } from "@/lib/editOps";
import { findMatches, type Matches } from "./matches";

export type MatchesState = {
  found: Matches | null;
  setFound: (next: Matches) => void;
  /** Look again: after a word is added to the user's list. */
  again: () => void;
};

/** Looked for again when the words change (a word retyped, #83) or `again` is called; a mute changes neither. */
export function useMatches(transcriptId: number, editor: Editor, reading: Reading): MatchesState {
  const [found, setFound] = useState<Matches | null>(null);
  const [looked, setLooked] = useState(0);
  useEffect(() => {
    let live = true;
    findMatches(transcriptId, editor.content).then(
      (next) => {
        if (live) setFound(next);
      },
      (thrown: unknown) => {
        if (live) showError(fromThrown(thrown, `/api/transcripts/${transcriptId}/matches`));
      },
    );
    return () => {
      live = false;
    };
  }, [transcriptId, editor, reading, looked]);
  const again = useCallback(() => setLooked((n) => n + 1), []);
  return { found, setFound, again };
}
