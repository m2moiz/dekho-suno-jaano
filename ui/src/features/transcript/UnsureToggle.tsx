import { type RefObject, useEffect, useMemo, useRef, useState } from "react";

import { Toggle } from "@/components/ui/toggle";
import { FIELD_BUTTON, FIELD_EDGE } from "@/features/shell/field";
import { cutoffFor, UNSURE, unsureHighlight, unsureWords } from "./confidence";
import type { Reading } from "./document";

type Props = {
  reading: Reading;
  model: string;
  /** The transcript's <article>, whose paragraphs the tint paints. */
  article: RefObject<HTMLElement | null>;
};

/**
 * Off until switched on (#62), the way both surveyed editors ship it. The
 * ranges are built the first time it is switched on and kept, so switching it
 * off and on again builds nothing. Shown only for a transcript whose engine
 * has a cut-off and whose words carry a confidence.
 */
export function UnsureToggle({ reading, model, article }: Props) {
  const [on, setOn] = useState(false);
  const highlight = useRef<Highlight | null>(null);
  const cutoff = cutoffFor(model);
  const words = useMemo(
    () => (cutoff === null ? [] : unsureWords(reading, cutoff)),
    [reading, cutoff],
  );

  useEffect(() => {
    highlight.current = null;
    return () => {
      CSS.highlights.delete(UNSURE);
    };
  }, [reading]);

  useEffect(() => {
    const root = article.current;
    if (!on || root === null) {
      CSS.highlights.delete(UNSURE);
      return;
    }
    if (highlight.current === null) {
      const texts: Text[] = [];
      for (const p of root.querySelectorAll<HTMLElement>("p[data-turn]")) {
        if (p.firstChild instanceof Text) texts[Number(p.dataset["turn"])] = p.firstChild;
      }
      highlight.current = unsureHighlight(reading, words, texts);
    }
    CSS.highlights.set(UNSURE, highlight.current);
  }, [on, reading, words, article]);

  if (cutoff === null || !reading.words.confidence.some((c) => !Number.isNaN(c))) return null;
  return (
    // It lives in the blue bar: the field's button colours, and 44 px tall on a phone.
    <Toggle
      variant="outline"
      size="sm"
      pressed={on}
      onPressedChange={setOn}
      className={`h-11 sm:h-8 ${FIELD_EDGE} ${FIELD_BUTTON}`}
    >
      Unsure words ({words.length})
    </Toggle>
  );
}
