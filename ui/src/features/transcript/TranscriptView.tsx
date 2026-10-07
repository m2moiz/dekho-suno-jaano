import { Check, Flag } from "lucide-react";
import { type CSSProperties, memo, type ReactNode, type Ref } from "react";

import type { Correction } from "@/features/edit/corrections";
import { durationLabel } from "@/features/library/describe";
import { langOf } from "@/lib/script";
import { type Reading, TIME_EPS_S } from "./document";
import { displayName, type Names, NO_NAMES, speakerColour } from "./speakers";
import "./transcript.css";

// A minute of speech fills the margin's tick; a longer turn stops there.
const TICK_FULL_S = 60;
const NONE: readonly Correction[] = [];

/** Where Review has got to with a turn or a sentence (Hashiya spec, "The margin": the review mark). */
export type ReviewState = "checked" | "flagged";

/**
 * Review's marks for the margin: per turn, by its index, and per sentence, by
 * its stretch of the recording in seconds. Anything not named is unmarked.
 * Review mode fills it (Task 13); the reader draws nothing without it.
 */
export type ReviewMarks = {
  turns?: ReadonlyMap<number, ReviewState>;
  sentences?: readonly { start: number; end: number; state: ReviewState }[];
};

/** The review mark for one turn: its own, and a count of its sentences', or nothing. */
function ReviewMark({ own, sentences }: { own: ReviewState | undefined; sentences: readonly ReviewState[] }) {
  const checked = sentences.filter((s) => s === "checked").length;
  const flagged = sentences.length - checked;
  if (own === undefined && sentences.length === 0) return null;
  return (
    <span className="review" data-review={own ?? "sentences"}>
      {own === "checked" && (
        <span className="checked">
          <Check aria-hidden className="size-3.5" /> Checked
        </span>
      )}
      {own === "flagged" && (
        <span>
          <Flag aria-hidden className="size-3.5" /> Flagged
        </span>
      )}
      {own === undefined && checked > 0 && (
        <span className="checked" aria-label={`${checked} of ${sentences.length} sentences checked`}>
          <Check aria-hidden className="size-3.5" /> {checked}
        </span>
      )}
      {own === undefined && flagged > 0 && (
        <span aria-label={`${flagged} flagged`}>
          <Flag aria-hidden className="size-3.5" /> {flagged}
        </span>
      )}
    </span>
  );
}

type Props = {
  reading: Reading;
  articleRef?: Ref<HTMLElement>;
  /** Corrected stretches, shown struck through in the margin beside their turn. */
  corrections?: readonly Correction[];
  names?: Names;
  /** Draws a speaker's nameplate; the reader passes a renamable one (Task 5). */
  nameplate?: (speaker: number, label: string, name: string) => ReactNode;
  /** Review's marks, shown in the margin; none in the reader. */
  review?: ReviewMarks;
};

/**
 * One list item per speaker turn: the margin (who, when, how long, what was
 * corrected) and one `<p>` holding one plain text node, with no element per
 * word (#58). 21,847 words drawn whole scroll at the display's own pace (#57
 * section 7), and plain text keeps Cmd+F, drag-select and copy native. The
 * playhead and every later mark paint over this text with the CSS Custom
 * Highlight API, which adds no elements either (#60).
 *
 * Turns are list items under the page's one heading, not 238 headings
 * (critique: "56 level-2 headings"). Memoised: nothing that changes while it
 * plays may re-render this.
 */
export const TranscriptView = memo(function TranscriptView({
  reading,
  articleRef,
  corrections = NONE,
  names = NO_NAMES,
  nameplate,
  review,
}: Props) {
  const byTurn = new Map<number, Correction[]>();
  for (const c of corrections) byTurn.set(c.turn, [...(byTurn.get(c.turn) ?? []), c]);
  const { end } = reading.words;
  return (
    <article ref={articleRef} className="transcript" aria-label="Transcript">
      <ol className="turns">
        {reading.turns.map((turn, i) => {
          const name = displayName(reading.speakers, names, turn.speaker);
          const label = turn.speaker === null ? undefined : reading.speakers[turn.speaker];
          const until = end[turn.first + turn.count - 1] ?? turn.start;
          const seconds = Math.max(0, until - turn.start);
          const marks = (review?.sentences ?? [])
            .filter((m) => m.start >= turn.start - TIME_EPS_S && m.start < until - TIME_EPS_S)
            .map((m) => m.state);
          const style = {
            "--speaker": speakerColour(turn.speaker),
            "--tick": `${Math.min(100, (seconds / TICK_FULL_S) * 100)}%`,
          } as CSSProperties;
          return (
            <li key={i} className="turn" style={style}>
              <div className="margin" data-margin>
                {name !== null &&
                  label !== undefined &&
                  turn.speaker !== null &&
                  (nameplate ? nameplate(turn.speaker, label, name) : <span className="nameplate">{name}</span>)}
                <time dateTime={`PT${turn.start.toFixed(2)}S`}>{durationLabel(turn.start)}</time>
                <span className="tick" aria-hidden />
                {review !== undefined && <ReviewMark own={review.turns?.get(i)} sentences={marks} />}
                {byTurn.get(i)?.map((c) => (
                  <span key={`${c.first}:${c.last}`} className="correction" dir="auto">
                    <span className="sr-only">{c.now === "" ? "Deleted: " : "Was: "}</span>
                    <del>{c.original === "" ? "nothing" : c.original}</del>
                  </span>
                ))}
              </div>
              <p data-turn={i} dir="auto" lang={langOf(turn.text)}>
                {turn.text}
              </p>
            </li>
          );
        })}
      </ol>
    </article>
  );
});
