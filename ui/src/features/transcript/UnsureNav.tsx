import { ChevronLeft, ChevronRight } from "lucide-react";
import { type RefObject, useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Toggle } from "@/components/ui/toggle";
import { FIELD_BUTTON } from "@/features/shell/field";
import { cutoffFor, UNSURE, unsureHighlight, unsureWords } from "./confidence";
import type { Reading } from "./document";
import { isOurs } from "./readerKeys";

type Props = {
  reading: Reading;
  model: string;
  /** The transcript's <article>, whose paragraphs the tint paints. */
  article: RefObject<HTMLElement | null>;
};

/** Select word `word` and bring it to a third of the way down the window. */
function goTo(reading: Reading, root: HTMLElement, word: number): void {
  const { turn, offset, length } = reading.words;
  const text = root.querySelector(`p[data-turn="${turn[word] ?? -1}"]`)?.firstChild;
  if (!(text instanceof Text)) return;
  const from = offset[word] ?? 0;
  const to = from + (length[word] ?? 0);
  const lead = /^\s*/.exec(text.data.slice(from, to))?.[0].length ?? 0;
  const range = document.createRange();
  range.setStart(text, from + lead);
  range.setEnd(text, to);
  const selection = window.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(range);
  if (typeof range.getBoundingClientRect === "function") {
    const behavior = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
    window.scrollBy({ top: range.getBoundingClientRect().top - window.innerHeight * 0.35, behavior });
  }
}

/**
 * The unsure words (#62) as a count with previous and next (Hashiya spec,
 * Reader; critique: "158 unsure words with no next/previous"). The count
 * switches the tint; an arrow switches it on, selects the word, so the
 * selection toolbar offers Correct and Hear at once, and brings it into view.
 * `]` and `[` do the same from the keyboard.
 */
export function UnsureNav({ reading, model, article }: Props) {
  const [on, setOn] = useState(false);
  const at = useRef(-1);
  const highlight = useRef<Highlight | null>(null);
  const cutoff = cutoffFor(model);
  const words = useMemo(() => (cutoff === null ? [] : unsureWords(reading, cutoff)), [reading, cutoff]);

  useEffect(() => {
    highlight.current = null;
    at.current = -1;
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

  const go = (by: 1 | -1) => {
    const root = article.current;
    if (words.length === 0 || root === null) return;
    setOn(true);
    at.current = at.current < 0 ? (by > 0 ? 0 : words.length - 1) : (at.current + by + words.length) % words.length;
    goTo(reading, root, words[at.current] ?? 0);
  };
  const goRef = useRef(go);
  goRef.current = go;

  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (!isOurs(event)) return;
      if (event.code === "BracketRight") goRef.current(1);
      else if (event.code === "BracketLeft") goRef.current(-1);
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);

  if (cutoff === null || !reading.words.confidence.some((c) => !Number.isNaN(c))) return null;
  // It lives in the blue bar: the field's button colours, 44 px targets.
  const quiet = `size-11 ${FIELD_BUTTON}`;
  return (
    <div role="group" aria-label="Unsure words" className="flex items-center">
      <Toggle
        pressed={on}
        onPressedChange={setOn}
        className={`h-11 px-3 ${FIELD_BUTTON}`}
      >
        <span className="tabular-nums">{words.length}</span> unsure
      </Toggle>
      <Button variant="ghost" size="icon" aria-label="Previous unsure word" disabled={words.length === 0} className={quiet} onClick={() => go(-1)}>
        <ChevronLeft aria-hidden />
      </Button>
      <Button variant="ghost" size="icon" aria-label="Next unsure word" disabled={words.length === 0} className={quiet} onClick={() => go(1)}>
        <ChevronRight aria-hidden />
      </Button>
    </div>
  );
}
