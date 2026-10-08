import { ChevronLeft, ChevronRight } from "lucide-react";
import { type RefObject, useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { selectWords, turnTexts } from "@/features/edit/selection";
import { FIELD_BUTTON, FIELD_ICON_BUTTON } from "@/features/shell/field";
import { cutoffFor, UNSURE, unsureHighlight, unsureWords } from "./confidence";
import { type Reading, TIME_EPS_S } from "./document";
import { isOurs } from "./readerKeys";

const SWITCH_ID = "unsure-switch";
const LABEL_ID = "unsure-switch-label";

type Props = {
  reading: Reading;
  model: string;
  /** The transcript's <article>, whose paragraphs the tint paints. */
  article: RefObject<HTMLElement | null>;
};

/** Select word `word` and bring it to a third of the way down the window. */
function goTo(reading: Reading, root: HTMLElement, word: number): void {
  const range = selectWords(reading, turnTexts(root), word);
  if (range !== null && typeof range.getBoundingClientRect === "function") {
    const behavior = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
    window.scrollBy({ top: range.getBoundingClientRect().top - window.innerHeight * 0.35, behavior });
  }
}

/**
 * The unsure word after (`by` 1) or before (-1) the time `at`, wrapping
 * round; the first or the last when nothing has been visited yet.
 */
export function stepUnsure(starts: Float64Array, words: readonly number[], at: number | null, by: 1 | -1): number | undefined {
  if (words.length === 0) return undefined;
  if (at === null) return by > 0 ? words[0] : words.at(-1);
  if (by > 0) return words.find((w) => (starts[w] ?? 0) > at + TIME_EPS_S) ?? words[0];
  return words.findLast((w) => (starts[w] ?? 0) < at - TIME_EPS_S) ?? words.at(-1);
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
  // Where the last arrow went, in seconds, not as a word index: a correction
  // renumbers the words, and `]` after one goes on from where it was.
  const at = useRef<number | null>(null);
  const highlight = useRef<Highlight | null>(null);
  const cutoff = cutoffFor(model);
  const words = useMemo(() => (cutoff === null ? [] : unsureWords(reading, cutoff)), [reading, cutoff]);

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
    if (highlight.current === null) highlight.current = unsureHighlight(reading, words, turnTexts(root));
    CSS.highlights.set(UNSURE, highlight.current);
  }, [on, reading, words, article]);

  const go = (by: 1 | -1) => {
    const root = article.current;
    if (words.length === 0 || root === null) return;
    const word = stepUnsure(reading.words.start, words, at.current, by);
    if (word === undefined) return;
    setOn(true);
    at.current = reading.words.start[word] ?? 0;
    goTo(reading, root, word);
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
  const quiet = FIELD_ICON_BUTTON;
  return (
    <div className="flex items-center gap-1">
      {/* A real switch, track and thumb, named for what it does, its count
          beside it, and the arrows a group of their own (critique 7 Oct round
          2, P2-4). Off by default, as #62 decided. On, the track is the
          unsure rose, not gold, which is the screen's one action. */}
      <div role="group" aria-label="Unsure words" className={`flex h-11 items-center gap-2 rounded-lg px-2 ${FIELD_BUTTON}`}>
        <Switch
          id={SWITCH_ID}
          aria-labelledby={LABEL_ID}
          checked={on}
          onCheckedChange={setOn}
          className="data-checked:bg-unsure-mark data-unchecked:bg-field-wave dark:data-unchecked:bg-field-wave"
        />
        {/* Heard on a phone, not shown: there the title needs the width. */}
        <label id={LABEL_ID} htmlFor={SWITCH_ID} className="cursor-pointer text-sm font-medium max-sm:sr-only">
          Unsure words
        </label>
        <span className="rounded-full bg-white/10 px-2 text-xs font-semibold tabular-nums">{words.length}</span>
      </div>
      <div role="group" aria-label="Step through unsure words" className="flex items-center">
        <Button variant="ghost" size="icon" aria-label="Previous unsure word" disabled={words.length === 0} className={quiet} onClick={() => go(-1)}>
          <ChevronLeft aria-hidden />
        </Button>
        <Button variant="ghost" size="icon" aria-label="Next unsure word" disabled={words.length === 0} className={quiet} onClick={() => go(1)}>
          <ChevronRight aria-hidden />
        </Button>
      </div>
    </div>
  );
}
