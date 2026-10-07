import { ChevronDown, Pencil } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";
import { fromThrown, showError } from "@/features/errors/appError";
import { isFinished, useJobFor } from "@/features/transcribe/jobs";
import { TranscribeControl } from "@/features/transcribe/TranscribeControl";
import { speakerColour } from "@/features/transcript/speakers";
import { transcriptHref } from "@/lib/route";
import {
  durationLabel,
  fileName,
  languageLabel,
  marksLabel,
  pictureNote,
  progressLabel,
  sizeLabel,
  speakersLabel,
  versionLabel,
  whenLabel,
} from "./describe";
import { relinkRecording } from "./imports";
import { retitle } from "./retitle";
import { displayTitle } from "./title";
import type { RecordingRow, TranscriptRow } from "./types";

// The longest title the server keeps (dsj/ui/schemas.py, TitleUpdate).
const TITLE_MAX = 200;

/** Speakers as coloured dots, one a speaker up to six (Hashiya spec, Library). */
function SpeakerDots({ count }: { count: number }) {
  return (
    <span className="flex items-center gap-1" aria-label={`${count} ${count === 1 ? "speaker" : "speakers"}`}>
      {Array.from({ length: Math.min(count, 6) }, (_, i) => (
        <span key={i} aria-hidden className="size-2.5 rounded-full" style={{ background: speakerColour(i) }} />
      ))}
      {count > 6 && <span aria-hidden>+{count - 6}</span>}
    </span>
  );
}

function Title({
  row,
  title,
  href,
  onChanged,
}: {
  row: RecordingRow;
  title: string;
  href: string | null;
  onChanged: () => void;
}) {
  const [renaming, setRenaming] = useState(false);
  const rename = useRef<HTMLButtonElement>(null);
  // Focus goes back to the pencil once the field closes, not to the page's start.
  const closed = useRef(false);
  useEffect(() => {
    if (renaming || !closed.current) return;
    closed.current = false;
    rename.current?.focus();
  }, [renaming]);
  const close = () => {
    closed.current = true;
    setRenaming(false);
  };
  const save = (typed: string) => {
    close();
    if (typed === title) return;
    // The title it shows without one is not a title someone typed.
    const next = typed === displayTitle({ title: null, path: row.path }) ? "" : typed;
    retitle(row.id, next).then(onChanged, (thrown: unknown) =>
      showError(fromThrown(thrown, `/api/recordings/${row.id}`)),
    );
  };
  if (renaming) {
    return (
      <Input
        autoFocus
        aria-label="Title"
        defaultValue={title}
        dir="auto"
        maxLength={TITLE_MAX}
        className="relative z-10 h-11 font-reading text-lg md:text-lg sm:h-9"
        onFocus={(event) => event.currentTarget.select()}
        // Leaving the field keeps what was typed, as Enter does; only Escape
        // throws it away (a phone has no Enter to reach for).
        onBlur={(event) => {
          if (closed.current) return;
          save(event.currentTarget.value.trim());
        }}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.preventDefault();
            close();
          }
          if (event.key !== "Enter") return;
          event.preventDefault();
          save(event.currentTarget.value.trim());
        }}
      />
    );
  }
  const missing = row.missing ? "text-muted-foreground" : "";
  return (
    <div className="flex min-w-0 items-center gap-1">
      {href === null ? (
        <span dir="auto" className={`truncate font-reading text-lg font-semibold ${missing}`}>
          {title}
        </span>
      ) : (
        // The whole row opens the latest transcript (critique: "grey line as
        // the only link"): the link's box is stretched over the row, and the
        // row's own controls sit above it.
        <a
          href={href}
          dir="auto"
          className={`truncate font-reading text-lg font-semibold underline-offset-4 after:absolute after:inset-0 group-hover:underline ${missing}`}
        >
          {title}
        </a>
      )}
      <Button
        ref={rename}
        variant="ghost"
        size="icon"
        aria-label={`Rename ${title}`}
        className="relative z-10 size-11 shrink-0 text-muted-foreground sm:size-9"
        onClick={() => setRenaming(true)}
      >
        <Pencil aria-hidden className="size-4" />
      </Button>
    </div>
  );
}

// A fold's trigger: quiet text, ink once open, its chevron turned.
const QUIET_TRIGGER =
  "group/trigger relative z-10 inline-flex min-h-11 items-center gap-1 text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline data-[panel-open]:text-foreground sm:min-h-0";

function Versions({ recording, transcripts }: { recording: number; transcripts: TranscriptRow[] }) {
  return (
    <Collapsible>
      <CollapsibleTrigger className={QUIET_TRIGGER}>
        {transcripts.length === 1 ? "1 earlier version" : `${transcripts.length} earlier versions`}
        <ChevronDown aria-hidden className="size-3.5 transition-transform group-data-[panel-open]/trigger:rotate-180" />
      </CollapsibleTrigger>
      <CollapsibleContent className="relative z-10">
        <ul className="mt-1 flex flex-col gap-1 text-sm">
          {transcripts.map((t) => (
            <li key={t.id}>
              <a
                href={transcriptHref(recording, t.id)}
                className="inline-flex min-h-11 items-center tabular-nums underline-offset-4 hover:underline sm:min-h-0"
              >
                {versionLabel(t)}
              </a>
            </li>
          ))}
        </ul>
      </CollapsibleContent>
    </Collapsible>
  );
}

/** What the row leaves out: how the latest transcript was made, and the file. Its trigger sits on the row's meta line. */
function DetailsPanel({ row, latest, again }: { row: RecordingRow; latest: TranscriptRow | undefined; again: boolean }) {
  const picture = pictureNote(row.video_codec);
  const size = sizeLabel(row.size_bytes);
  return (
    <CollapsibleContent className="relative z-10">
      <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
        {latest !== undefined && (
          <>
            <dt className="text-muted-foreground">Made</dt>
            <dd className="tabular-nums">{versionLabel(latest)}</dd>
            <dt className="text-muted-foreground">Model</dt>
            <dd className="break-all">{latest.model}</dd>
            <dt className="text-muted-foreground">Speakers</dt>
            <dd>{speakersLabel(latest)}</dd>
            <dt className="text-muted-foreground">Marks</dt>
            <dd>{marksLabel(latest)}</dd>
            {latest.last_edited_at !== null && (
              <>
                <dt className="text-muted-foreground">Edited</dt>
                <dd className="tabular-nums">{whenLabel(latest.last_edited_at)}</dd>
              </>
            )}
          </>
        )}
        <dt className="text-muted-foreground">File</dt>
        <dd className="font-mono text-xs leading-5 break-all select-text">{row.path}</dd>
        {size !== null && (
          <>
            <dt className="text-muted-foreground">Size</dt>
            <dd className="tabular-nums">{size}</dd>
          </>
        )}
      </dl>
      {picture !== null && <p className="mt-1 text-sm text-muted-foreground">{picture}</p>}
      {again && <TranscribeControl recording={row} label="Transcribe again" />}
    </CollapsibleContent>
  );
}

function Relink({ row, onChanged }: { row: RecordingRow; onChanged: () => void }) {
  const [relinking, setRelinking] = useState(false);
  return (
    <p className="relative z-10 mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted-foreground">
      Not where it was last seen.
      <Button
        variant="outline"
        size="sm"
        className="h-11 sm:h-7"
        disabled={relinking}
        onClick={() => {
          setRelinking(true);
          relinkRecording(row.id).then(
            (found) => {
              setRelinking(false);
              if (found !== null) onChanged();
            },
            (thrown: unknown) => {
              setRelinking(false);
              showError(fromThrown(thrown, `/api/recordings/${row.id}/relink`));
            },
          );
        }}
      >
        Relink
      </Button>
    </p>
  );
}

/**
 * One recording as a conversation, not a file (Hashiya spec, Library): a
 * readable title, its length, its language, its speakers as dots, and how far
 * its review got, or Transcribe when it has no transcript. The whole row
 * opens the latest transcript; older ones fold under "2 earlier versions",
 * model names under Details.
 */
export function RecordingRowItem({ row, onChanged }: { row: RecordingRow; onChanged: () => void }) {
  const title = displayTitle(row);
  const [latest, ...earlier] = row.transcripts;
  const job = useJobFor(row.id);
  // A run going, or one that failed: either is news, so it shows on the row
  // itself, not folded under Details where "Transcribe again" started it.
  const news = job !== undefined && (!isFinished(job) || job.state === "failed");
  const length = durationLabel(row.duration_s);
  const language = latest === undefined ? null : languageLabel(latest.language_tag);
  const progress = latest === undefined ? null : progressLabel(latest);
  const done = latest !== undefined && latest.review_total !== null && latest.review_checked === latest.review_total;
  // The row is the Details collapsible, so its trigger can sit on the meta
  // line and its panel at the foot, in the order a keyboard reaches them.
  return (
    <Collapsible
      render={
        <li
          aria-label={title}
          data-missing={row.missing || undefined}
          className="group relative px-4 py-3 transition-colors focus-within:bg-muted/50 hover:bg-muted/50"
        />
      }
    >
      <Title
        row={row}
        title={title}
        href={latest === undefined ? null : transcriptHref(row.id, latest.id)}
        onChanged={onChanged}
      />
      <div className="flex flex-wrap items-center gap-x-3 text-sm text-muted-foreground tabular-nums">
        {length !== null && <span>{length}</span>}
        {language !== null && <span className="rounded-full border border-border px-2 text-xs leading-5">{language}</span>}
        {latest?.speaker_count != null && latest.speaker_count > 0 && <SpeakerDots count={latest.speaker_count} />}
        {progress !== null && <span className={done ? "text-checked" : undefined}>{progress}</span>}
        {latest === undefined && !news && <span>Not transcribed yet</span>}
        <CollapsibleTrigger className={`${QUIET_TRIGGER} ml-auto`}>
          Details
          <ChevronDown aria-hidden className="size-3.5 transition-transform group-data-[panel-open]/trigger:rotate-180" />
        </CollapsibleTrigger>
      </div>
      {row.missing && <Relink row={row} onChanged={onChanged} />}
      {row.unreadable !== null && (
        <p className="mt-1 text-sm text-muted-foreground select-text" role="note">
          ffmpeg could not read this file: {row.unreadable}
        </p>
      )}
      {/* In the row's own column, so a running job's bar has the row's width. */}
      {(latest === undefined || news) && (
        <div className="relative z-10">
          <TranscribeControl recording={row} label={latest === undefined ? "Transcribe" : "Transcribe again"} />
        </div>
      )}
      {earlier.length > 0 && <Versions recording={row.id} transcripts={earlier} />}
      <DetailsPanel row={row} latest={latest} again={latest !== undefined && !news} />
      <span className="sr-only">{fileName(row.path)}</span>
    </Collapsible>
  );
}
