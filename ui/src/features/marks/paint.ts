// The marks painted over the transcript (#67): one Highlight per kind holding
// every range of that kind, registered under the kind's name, with one
// ::highlight() rule per kind in transcript.css. No element is added to the
// page, as the playhead and the muted words are painted (#57 section 7).

import { type RefObject, useEffect } from "react";

import { turnTexts } from "@/features/edit/selection";
import { unsureHighlight as wordsHighlight } from "@/features/transcript/confidence";
import type { Reading } from "@/features/transcript/document";
import { MARK_KINDS } from "@/registries/markKinds";
import { type Mark, wordsOfSpan } from "./marks";

export function useMarksPaint(reading: Reading, marks: readonly Mark[], article: RefObject<HTMLElement | null>): void {
  useEffect(() => {
    const root = article.current;
    if (root === null) return;
    const texts = turnTexts(root);
    const set = MARK_KINDS.map((kind) => {
      const words = marks.filter((m) => m.kind === kind.id).flatMap((m) => wordsOfSpan(reading.words, m.start_s, m.end_s));
      const highlight = wordsHighlight(reading, [...new Set(words)].sort((a, b) => a - b), texts);
      CSS.highlights.set(kind.highlight, highlight);
      return [kind.highlight, highlight] as const;
    });
    return () => {
      for (const [name, highlight] of set) {
        if (CSS.highlights.get(name) === highlight) CSS.highlights.delete(name);
      }
    };
  }, [reading, marks, article]);
}
