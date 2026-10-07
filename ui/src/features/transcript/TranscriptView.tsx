import { memo, type Ref } from "react";

import { durationLabel } from "@/features/library/describe";
import { langOf } from "@/lib/script";
import { type Reading, speakerName } from "./document";
import "./transcript.css";

/**
 * One `<p>` per speaker turn holding one plain text node, and no element per
 * word (#58). 21,847 words drawn whole scroll at the display's own pace (#57
 * section 7), and plain text keeps Cmd+F, drag-select and copy native. The
 * playhead and every later mark paint over this text with the CSS Custom
 * Highlight API, which adds no elements either (#60).
 *
 * Memoised on the reading, which is made once per transcript: nothing that
 * changes while it plays may re-render this.
 */
export const TranscriptView = memo(function TranscriptView({
  reading,
  articleRef,
}: {
  reading: Reading;
  articleRef?: Ref<HTMLElement>;
}) {
  return (
    <article ref={articleRef} className="transcript" aria-label="Transcript">
      {reading.turns.map((turn, i) => {
        const name = speakerName(reading.speakers, turn.speaker);
        return (
          <section key={i}>
            <h2>
              {name !== null && <>{name} · </>}
              <time dateTime={`PT${turn.start.toFixed(2)}S`}>{durationLabel(turn.start)}</time>
            </h2>
            <p data-turn={i} dir="auto" lang={langOf(turn.text)}>
              {turn.text}
            </p>
          </section>
        );
      })}
    </article>
  );
});
