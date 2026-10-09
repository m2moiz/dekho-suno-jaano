import { useEffect, useMemo, useRef, useState } from "react";

import { type Editable, useSave } from "@/features/edit/editing";
import { fromThrown, showError } from "@/features/errors/appError";
import { displayTitle } from "@/features/library/title";
import { Player, type PlayerControls } from "@/features/player/Player";
import { AppBar } from "@/features/shell/AppBar";
import { read, type Reading } from "@/features/transcript/document";
import { type Opened, openTranscript } from "@/features/transcript/TranscriptPage";
import { REVIEW_CARD_SHEET, REVIEW_SHEET } from "@/features/shell/keys";
import { TOUCH, useMediaQuery } from "@/lib/media";
import { transcriptHref } from "@/lib/route";
import type { CurrentSha, ReviewDocument } from "./model";
import { ReviewCard } from "./ReviewCard";
import { ReviewDesk } from "./ReviewDesk";
import { loadReview } from "./reviewApi";
import { loadReading, otherTranscript } from "./secondOpinion";
import { useReviewSession } from "./useReviewSession";

type Review = { document: ReviewDocument | null; sha: CurrentSha; reviewSha: string | null };
type Loaded = { state: "loading" } | { state: "failed" } | { state: "ready"; opened: Opened; review: Review };

type Props = {
  recording: number;
  transcript: number;
  /** Where leaving goes; the tests pass their own. */
  navigate?: (href: string) => void;
};

/** Review mode (Hashiya spec): one transcript, checked sentence by sentence against its audio. */
export function ReviewPage({ recording, transcript, navigate = (href) => window.location.assign(href) }: Props) {
  const [loaded, setLoaded] = useState<Loaded>({ state: "loading" });
  const [other, setOther] = useState<Reading | null>(null);
  useEffect(() => {
    let live = true;
    Promise.all([openTranscript(recording, transcript), loadReview(transcript)]).then(
      ([opened, review]) => {
        if (!live) return;
        setLoaded({ state: "ready", opened, review });
        const another = otherTranscript(opened.recording, transcript);
        // A second opinion that cannot be read is said once and left out; the review goes on without it.
        if (another !== null) {
          loadReading(another.id).then(
            (reading) => {
              if (live) setOther(reading);
            },
            (thrown: unknown) => {
              if (live) showError(fromThrown(thrown, `/api/transcripts/${another.id}`));
            },
          );
        }
      },
      (thrown: unknown) => {
        if (!live) return;
        setLoaded({ state: "failed" });
        showError(fromThrown(thrown, `/api/transcripts/${transcript}/review`));
      },
    );
    return () => {
      live = false;
    };
  }, [recording, transcript]);

  const back = transcriptHref(recording, transcript);
  const backTo = { href: back, label: "Back to the transcript" };
  if (loaded.state !== "ready") {
    return (
      <>
        <AppBar back={backTo}>
          <h1 className="min-w-0 flex-1 truncate font-reading text-lg font-semibold">Review</h1>
        </AppBar>
        {loaded.state === "failed" && (
          <main className="mx-auto w-full max-w-3xl px-3 py-6 sm:px-6">
            <p className="text-muted-foreground">This review could not be opened.</p>
          </main>
        )}
      </>
    );
  }
  const { opened, review } = loaded;
  // The edit list and the review were read a moment apart; a transcript made
  // again between the two would pair new words with an old list, and every
  // save after would be refused (#249).
  const reason = !("editor" in opened.editable)
    ? opened.editable.reason
    : opened.editable.sha !== review.sha
      ? "the transcript was made again while this page opened. Reload the page."
      : null;
  if (reason !== null || !("editor" in opened.editable)) {
    return (
      <>
        <AppBar back={backTo}>
          <h1 className="min-w-0 flex-1 truncate font-reading text-lg font-semibold">Review · {displayTitle(opened.recording)}</h1>
        </AppBar>
        <main className="mx-auto flex w-full max-w-3xl flex-col gap-3 px-3 py-6 sm:px-6">
          <p>This transcript cannot be reviewed: {reason}</p>
          <a href={back} className="underline underline-offset-4">
            Back to the transcript
          </a>
        </main>
      </>
    );
  }
  return <InSession opened={opened} editable={opened.editable} transcriptId={transcript} review={review} other={other} back={back} navigate={navigate} />;
}

type InSessionProps = {
  opened: Opened;
  editable: Editable;
  transcriptId: number;
  review: Review;
  other: Reading | null;
  back: string;
  navigate: (href: string) => void;
};

function InSession({ opened, editable, transcriptId, review, other, back, navigate }: InSessionProps) {
  const controls = useRef<PlayerControls | null>(null);
  // A touch screen, or a window narrower than 768 px, gets the card; the desk
  // and the card draw the one session, so switching between them mid-review
  // (a window dragged narrower) loses nothing (F14).
  const touch = useMediaQuery(TOUCH);
  // Review's corrections and speaker changes are edits, saved as the reader saves them.
  const edits = useSave(transcriptId, editable);
  const session = useReviewSession({
    transcriptId,
    doc: opened.doc,
    editable,
    edits,
    saved: review.document,
    savedSha: review.reviewSha,
    sha: review.sha,
    other,
    controls,
    onLeave: () => navigate(back),
    sheet: touch ? REVIEW_CARD_SHEET : REVIEW_SHEET,
  });
  const reading = useMemo(() => read(opened.doc), [opened.doc]);
  const title = displayTitle(opened.recording);
  return (
    <>
      {touch ? (
        <ReviewCard session={session} title={title} back={back} transcriptId={transcriptId} />
      ) : (
        <ReviewDesk session={session} title={title} back={back} transcriptId={transcriptId} />
      )}
      {opened.recording.missing ? (
        <p className="sticky bottom-0 bg-field px-4 py-3 text-sm text-field-foreground">
          The recording is not where it was last seen, so this review cannot play it. Last seen at{" "}
          <span className="font-mono break-all">{opened.recording.path}</span>
        </p>
      ) : (
        <Player recording={opened.recording} reading={reading} controls={controls} />
      )}
    </>
  );
}
