import { type ReactNode, type RefObject, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { api } from "@/api/client";
import { buttonVariants } from "@/components/ui/button";
import { DropdownMenuGroup, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator } from "@/components/ui/dropdown-menu";
import { BleepDrawer } from "@/features/bleep/BleepDrawer";
import { BleepPanel } from "@/features/bleep/BleepPanel";
import { isMuted } from "@/features/bleep/matches";
import type { RenderJob } from "@/features/bleep/render";
import { useMatches } from "@/features/bleep/useMatches";
import { correction, textOf } from "@/features/edit/correct";
import { type Correction, corrections, tokensOf } from "@/features/edit/corrections";
import { EditBar, useCorrectedPaint, useMutedPaint, useSelection, useUndoKeys } from "@/features/edit/EditBar";
import { type Editable, loadEditable, Outdated, type Span, useContent, useLatest, useSave } from "@/features/edit/editing";
import { InlineCorrect } from "@/features/edit/InlineCorrect";
import { type EditReading, keepReading, readContent } from "@/features/edit/readContent";
import { focusText, selectWords, turnTexts } from "@/features/edit/selection";
import { type Picked, SelectionToolbar } from "@/features/edit/SelectionToolbar";
import { TimingStrip } from "@/features/edit/TimingStrip";
import { ApiError, fromBody, fromThrown, showError } from "@/features/errors/appError";
import type { ReviewDocument } from "@/features/review/model";
import { loadReview } from "@/features/review/reviewApi";
import { displayTitle, titleFace } from "@/features/library/title";
import type { RecordingRow } from "@/features/library/types";
import { Player, type PlayerControls } from "@/features/player/Player";
import { PLAYER_HEIGHT } from "@/features/player/playhead";
import { AppBar, BAR_HEIGHT } from "@/features/shell/AppBar";
import { KeysItem } from "@/features/shell/KeySheet";
import { READ_ONLY_SHEET, READER_SHEET, type Sheet } from "@/features/shell/keys";
import { TOUCH, useMediaQuery } from "@/lib/media";
import { reviewHref } from "@/lib/route";
import { cn } from "@/lib/utils";
import { parseTranscript, read, type Reading, TIME_EPS_S, type TranscriptDoc } from "./document";
import { type ExportFormat, exportTranscript } from "./exportFile";
import { MoreMenu } from "./MoreMenu";
import { Nameplate } from "./Nameplate";
import { useReaderKeys } from "./readerKeys";
import type { Names } from "./speakers";
import { type ReviewMarks, type ReviewState, TranscriptView } from "./TranscriptView";
import { UnsureNav } from "./UnsureNav";
import { VersionPicker } from "./VersionPicker";

export type Opened = {
  recording: RecordingRow;
  doc: TranscriptDoc;
  /** The edit list, or why this transcript has none (#66). */
  editable: Editable | { reason: string };
};
type Loaded = { state: "loading" } | { state: "failed" } | ({ state: "ready" } & Opened);

export async function openTranscript(recordingId: number, transcriptId: number): Promise<Opened> {
  const transcriptRoute = `/api/transcripts/${transcriptId}`;
  const [list, file, editable] = await Promise.all([
    api.GET("/api/recordings"),
    api.GET("/api/transcripts/{transcript_id}", {
      params: { path: { transcript_id: String(transcriptId) } },
    }),
    loadEditable(transcriptId),
  ]);
  if (list.data === undefined) {
    throw new ApiError(fromBody(list.error, list.response, "/api/recordings"));
  }
  if (file.data === undefined) {
    throw new ApiError(fromBody(file.error, file.response, transcriptRoute));
  }
  const recording = list.data.find((row) => row.id === recordingId);
  if (recording === undefined || !recording.transcripts.some((t) => t.id === transcriptId)) {
    throw new ApiError({
      error: "NotInLibrary",
      message: `The library has no transcript ${transcriptId} of recording ${recordingId}.`,
      request: transcriptRoute,
    });
  }
  return { recording, doc: parseTranscript(file.data), editable };
}

type Navigate = (href: string) => void;

/** One transcript, opened from the library, to read (#58) and to edit (#66). */
export function TranscriptPage({
  recording,
  transcript,
  navigate = (href) => window.location.assign(href),
}: {
  recording: number;
  transcript: number;
  /** Where opening Review goes; the tests pass their own. */
  navigate?: Navigate;
}) {
  const [loaded, setLoaded] = useState<Loaded>({ state: "loading" });
  useEffect(() => {
    let live = true;
    openTranscript(recording, transcript).then(
      (opened) => {
        if (live) setLoaded({ state: "ready", ...opened });
      },
      (thrown: unknown) => {
        if (!live) return;
        setLoaded({ state: "failed" });
        showError(fromThrown(thrown, `/api/transcripts/${transcript}`));
      },
    );
    return () => {
      live = false;
    };
  }, [recording, transcript]);

  if (loaded.state !== "ready") {
    return (
      <>
        <AppBar back>
          <h1 className="min-w-0 flex-1 truncate font-reading text-lg font-semibold">Transcript</h1>
        </AppBar>
        {loaded.state === "failed" && (
          <main className="mx-auto w-full max-w-3xl px-3 py-6 sm:px-6">
            <p className="text-muted-foreground">This transcript could not be opened.</p>
          </main>
        )}
      </>
    );
  }
  return "editor" in loaded.editable ? (
    <EditablePage opened={loaded} editable={loaded.editable} transcriptId={transcript} navigate={navigate} />
  ) : (
    <ReadOnlyPage opened={loaded} reason={loaded.editable.reason} transcriptId={transcript} />
  );
}

function ReadOnlyPage({ opened, reason, transcriptId }: { opened: Opened; reason: string; transcriptId: number }) {
  const reading = useMemo(() => read(opened.doc), [opened.doc]);
  const article = useRef<HTMLElement>(null);
  const controls = useRef<PlayerControls | null>(null);
  useReaderKeys(controls, READ_ONLY_SHEET);
  return (
    <Page opened={opened} transcriptId={transcriptId} reading={reading} article={article} controls={controls} sheet={READ_ONLY_SHEET}>
      <p className="mb-6 text-sm text-muted-foreground" role="note">
        This transcript cannot be edited: {reason}
      </p>
    </Page>
  );
}

// The custom property on <html> holding the Timing dock's height while it is open.
const DOCK_HEIGHT = "--dsj-dock-height";
// Clear space kept between the word and the dock or the bar, in pixels.
const CLEAR_PX = 12;

function heightOf(property: string): number {
  return Number.parseFloat(document.documentElement.style.getPropertyValue(property)) || 0;
}

/**
 * When the Timing dock opens on a word, scroll the word clear of it and of
 * the bar (Task 3 review: the dock covered a word near the window's bottom).
 * The page's bottom padding grows by the dock's height while it is open, so
 * even the last turn's words can be scrolled above it.
 */
function useTimingInSight(
  word: number | null,
  reading: Reading,
  article: RefObject<HTMLElement | null>,
  dock: RefObject<HTMLDivElement | null>,
): void {
  // Read when the dock opens, not followed: a drag in the strip makes a new
  // reading on every move, and the view must not jump while it does.
  const now = useRef(reading);
  now.current = reading;
  useLayoutEffect(() => {
    const root = article.current;
    const element = dock.current;
    const drawn = now.current;
    if (word === null || root === null || element === null) return;
    const html = document.documentElement;
    const box = element.getBoundingClientRect();
    html.style.setProperty(DOCK_HEIGHT, `${box.height + CLEAR_PX}px`);
    const text = turnTexts(root)[drawn.words.turn[word] ?? -1];
    if (text !== undefined && typeof Range.prototype.getBoundingClientRect === "function") {
      const from = drawn.words.offset[word] ?? 0;
      const range = document.createRange();
      range.setStart(text, from);
      range.setEnd(text, from + (drawn.words.length[word] ?? 0));
      const at = range.getBoundingClientRect();
      const top = heightOf(BAR_HEIGHT) + CLEAR_PX;
      const bottom = box.top - CLEAR_PX;
      // Below the dock: up until it clears it; under the bar: down until it clears that.
      const by = at.bottom > bottom ? at.bottom - bottom : at.top < top ? at.top - top : 0;
      if (by !== 0) window.scrollBy({ top: by, behavior: "instant" });
    }
    return () => {
      html.style.removeProperty(DOCK_HEIGHT);
    };
  }, [word, article, dock]);
}

/** The margin's review marks (Hashiya spec, "The margin"): a flagged sentence as flagged, else a checked one as checked. */
export function reviewMarks(document: ReviewDocument): ReviewMarks {
  const sentences: { start: number; end: number; state: ReviewState }[] = [];
  for (const s of document.segments) {
    if (s.flags.length > 0) sentences.push({ start: s.start, end: s.end, state: "flagged" });
    else if (s.state === "checked") sentences.push({ start: s.start, end: s.end, state: "checked" });
  }
  return { sentences };
}

/**
 * The transcript's review, as marks for the margin. None while it loads, when
 * there is no review, or when the review was made against an earlier version
 * of the transcript: its checks vouch for other words (#249).
 */
function useReviewMarks(transcriptId: number, sha: string): ReviewMarks | undefined {
  const [marks, setMarks] = useState<ReviewMarks | undefined>(undefined);
  useEffect(() => {
    let live = true;
    loadReview(transcriptId).then(
      ({ document }) => {
        if (live && document !== null && document.transcript_sha === sha) setMarks(reviewMarks(document));
      },
      (thrown: unknown) => {
        if (live) showError(fromThrown(thrown, `/api/transcripts/${transcriptId}/review`));
      },
    );
    return () => {
      live = false;
    };
  }, [transcriptId, sha]);
  return marks;
}

const EXPORTS: readonly (readonly [ExportFormat, string])[] = [
  ["srt", "Subtitles (SRT)"],
  ["vtt", "Subtitles (WebVTT)"],
  ["txt", "Text"],
];

function EditablePage({ opened, editable, transcriptId, navigate }: { opened: Opened; editable: Editable; transcriptId: number; navigate: Navigate }) {
  const { editor } = editable;
  // 44 px menu rows where the reader has its touch layout, as MoreMenu's own (F15).
  const tall = useMediaQuery(TOUCH) ? "min-h-11" : "";
  const content = useContent(editor);
  const previous = useRef<EditReading | null>(null);
  const edit = useMemo(() => {
    const next = keepReading(previous.current, readContent(content, opened.doc.speakers));
    previous.current = next;
    return next;
  }, [content, opened.doc.speakers]);
  const article = useRef<HTMLElement>(null);
  const { state: saving, settle, rename: saveNames } = useSave(transcriptId, editable);
  const selected = useSelection(edit, article);
  const renderable = useLatest(editable.renderable);
  // The speakers' names (#243): saved on their own route, kept beside the editor.
  const names = useLatest(editable.names);
  const rename = useCallback(
    (label: string, name: string) => {
      const next: Record<string, string> = { ...names };
      if (name.trim() === "") delete next[label];
      else next[label] = name.trim();
      // In turn with the list's own saves (#251); the names it keeps are set by the hook.
      saveNames(next).catch((thrown: unknown) => showError(fromThrown(thrown, `/api/transcripts/${transcriptId}/names`)));
    },
    [names, transcriptId, saveNames],
  );
  // Stable between renames, so the memoised TranscriptView redraws only when a name changes.
  const nameplate = useCallback(
    (_speaker: number, label: string, name: string) => <Nameplate label={label} name={name} onRename={rename} />,
    [rename],
  );
  const controls = useRef<PlayerControls | null>(null);
  // The word whose edges are being dragged (#85), while the strip is open.
  const [timing, setTiming] = useState<number | null>(null);
  const dock = useRef<HTMLDivElement>(null);
  useTimingInSight(timing, edit.reading, article, dock);
  // The bleep drawer, and the render it started, which outlives the drawer's closing.
  const [bleeping, setBleeping] = useState(false);
  const [rendering, setRendering] = useState<RenderJob | null>(null);
  const matches = useMatches(transcriptId, editor, edit.reading);
  // The badge counts what Mute all would still mute, not every word the lists found.
  const unmuted = (matches.found?.matches ?? []).filter((m) => !isMuted(content, m)).length;
  const more = useRef<HTMLButtonElement>(null);
  // The words being retyped in place (#83), while the field is open.
  const [correcting, setCorrecting] = useState<Picked | null>(null);
  // Where focus goes back to once Correct or Timing closes: these words, by
  // time, as they read after the edit (Task 3 review: never to the body).
  const [back, setBack] = useState<{ turn: number; from: number; to: number } | null>(null);
  useEffect(() => {
    const root = article.current;
    if (back === null || root === null) return;
    setBack(null);
    const { start, turn } = edit.reading.words;
    let first = -1;
    let last = -1;
    for (let w = edit.reading.turns[back.turn]?.first ?? 0; w < start.length && turn[w] === back.turn; w += 1) {
      const at = start[w] ?? 0;
      if (at < back.from - TIME_EPS_S || at >= back.to - TIME_EPS_S) continue;
      if (first < 0) first = w;
      last = w;
    }
    const texts = turnTexts(root);
    // A stretch emptied of words leaves only its paragraph to go back to.
    if (first >= 0) selectWords(edit.reading, texts, first, last);
    focusText(texts[back.turn]?.parentElement);
  }, [back, edit]);
  const tokens = useMemo(() => tokensOf(opened.doc), [opened.doc]);
  const fixed = useMemo(() => corrections(edit.reading, tokens), [edit.reading, tokens]);
  useUndoKeys(editor);
  useMutedPaint(edit, content, article);
  useCorrectedPaint(edit.reading, fixed, article);
  const review = reviewHref(opened.recording.id, transcriptId);
  const marks = useReviewMarks(transcriptId, editable.sha);
  // Review loads the edit list afresh, so it opens only once the server holds
  // every edit made here: leaving with one in flight could open Review on the
  // list without it (Task 13 re-review), and Review's first patch would then
  // be refused as made against another list (#251). If the save fails, the
  // reader stays.
  const openReview = () => {
    settle().then(
      () => navigate(review),
      (thrown: unknown) =>
        showError({
          error: "NotSaved",
          message:
            thrown instanceof Outdated
              ? `Review did not open: ${thrown.message}`
              : "Review did not open, because the latest edits here are not saved yet. Try again once the bar says Saved.",
          request: `/api/transcripts/${transcriptId}/edits`,
        }),
    );
  };
  const openReviewNow = useRef(openReview);
  openReviewNow.current = openReview;
  const onReview = useCallback(() => openReviewNow.current(), []);
  useReaderKeys(controls, READER_SHEET, onReview);
  return (
    <Page
      opened={opened}
      transcriptId={transcriptId}
      reading={edit.reading}
      article={article}
      muteSpans={renderable.spans}
      controls={controls}
      corrections={fixed}
      names={names}
      nameplate={nameplate}
      {...(marks === undefined ? {} : { review: marks })}
      selectOnTap
      tools={
        <>
          <EditBar editor={editor} saving={saving} />
          {/* The bar's one gold primary (Hashiya spec, Reader): the default variant is gold. */}
          <a
            href={review}
            className={cn(buttonVariants(), "h-11 px-4 font-semibold")}
            onClick={(event) => {
              // Cmd+click and the like keep the link's own new tab.
              if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return;
              event.preventDefault();
              openReview();
            }}
          >
            Review
          </a>
          <MoreMenu
            matchCount={unmuted}
            triggerRef={more}
            onBleep={() => setBleeping(true)}
            timingWord={selected !== null && selected.first === selected.last ? selected.first : null}
            onTiming={setTiming}
            extra={
              <>
                <DropdownMenuSeparator />
                <DropdownMenuGroup>
                  <DropdownMenuLabel>Export as edited</DropdownMenuLabel>
                  {EXPORTS.map(([format, label]) => (
                    <DropdownMenuItem
                      key={format}
                      className={tall}
                      onClick={() =>
                        // The server exports its own copy of the list, so it is brought up to date first.
                        settle()
                          .then(() => exportTranscript(transcriptId, format, displayTitle(opened.recording)))
                          .catch((thrown: unknown) =>
                            showError(fromThrown(thrown, `/api/transcripts/${transcriptId}/export/${format}`)),
                          )
                      }
                    >
                      {label}
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuGroup>
              </>
            }
          />
        </>
      }
    >
      {editable.replaced !== null && (
        <p role="note" className="mb-6 rounded-lg border border-border bg-card px-4 py-3 text-sm">
          {editable.replaced}
        </p>
      )}
      <SelectionToolbar
        editor={editor}
        content={content}
        edit={edit}
        selected={correcting === null && timing === null ? selected : null}
        controls={controls}
        onCorrect={setCorrecting}
        onTiming={setTiming}
      />
      {correcting !== null && (
        <InlineCorrect
          heard={textOf(content, correcting.start, correcting.stop)}
          box={correcting.box}
          paragraph={correcting.paragraph}
          onHear={() => controls.current?.hear(Math.max(0, correcting.from - 0.3), correcting.to + 0.3)}
          onCancel={() => {
            setCorrecting(null);
            setBack({ turn: Number(correcting.paragraph.dataset["turn"]), from: correcting.from, to: correcting.to });
          }}
          onSave={(text) => {
            editor.applyEdit(correction(content, correcting.start, correcting.stop, text));
            setCorrecting(null);
            setBack({ turn: Number(correcting.paragraph.dataset["turn"]), from: correcting.from, to: correcting.to });
          }}
        />
      )}
      {timing !== null && timing < edit.first.length && (
        // Docked above the rail, where it is in sight whichever word it is for
        // (Task 3 review: in the page's flow it opened off screen).
        <div
          ref={dock}
          className="fixed inset-x-2 z-30 mx-auto max-w-3xl"
          style={{ bottom: `calc(var(${PLAYER_HEIGHT}, 0px) + 0.5rem)` }}
        >
          <TimingStrip
            editor={editor}
            content={content}
            edit={edit}
            word={timing}
            recordingId={opened.recording.id}
            controls={controls}
            onClose={() => {
              const { turn, start, end } = edit.reading.words;
              setBack({ turn: turn[timing] ?? 0, from: start[timing] ?? 0, to: end[timing] ?? 0 });
              setTiming(null);
            }}
          />
        </div>
      )}
      <BleepDrawer open={bleeping} onOpenChange={setBleeping} returnFocus={more}>
        <BleepPanel
          transcriptId={transcriptId}
          editor={editor}
          content={content}
          renderable={renderable}
          padS={editable.padS}
          controls={controls}
          matches={matches}
          started={rendering}
          onStarted={setRendering}
        />
      </BleepDrawer>
    </Page>
  );
}

type PageProps = {
  opened: Opened;
  transcriptId: number;
  reading: Reading;
  article: RefObject<HTMLElement | null>;
  children?: ReactNode;
  /** In the bar, after the unsure count: the Edit toolbar, and later Review and the menu. */
  tools?: ReactNode;
  muteSpans?: readonly Span[] | null;
  controls?: RefObject<PlayerControls | null>;
  corrections?: readonly Correction[];
  names?: Names;
  nameplate?: (speaker: number, label: string, name: string) => ReactNode;
  /** Review's marks for the margin (Task 13). */
  review?: ReviewMarks;
  selectOnTap?: boolean;
  /** The key sheet this page's `?` and settings menu show. */
  sheet?: Sheet;
};

/** The recording's title as the library shows it, in Nastaliq when it is in Urdu script (Hashiya spec, Type). */
function PageTitle({ title }: { title: string }) {
  const face = titleFace(title);
  return (
    <h1 dir="auto" lang={face.lang} className={`min-w-0 flex-1 truncate font-semibold ${face.className}`}>
      {title}
    </h1>
  );
}

function Page({ opened, transcriptId, reading, article, children, tools, muteSpans, controls, corrections: fixed, names, nameplate, review, selectOnTap = false, sheet = READER_SHEET }: PageProps) {
  const { recording, doc } = opened;
  return (
    <>
      <AppBar back settings={<KeysItem sheet={sheet} />}>
        <PageTitle title={displayTitle(recording)} />
        <VersionPicker recording={recording} transcript={transcriptId} />
        <UnsureNav reading={reading} model={doc.model} article={article} />
        {tools}
      </AppBar>
      {/* Room below the last turn for the Timing dock, so its word can be scrolled clear of it. */}
      <main
        className="mx-auto w-full max-w-5xl flex-1 px-3 pt-6 sm:px-6"
        style={{ paddingBottom: `calc(2.5rem + var(${DOCK_HEIGHT}, 0px))` }}
      >
        {children}
        <TranscriptView
          reading={reading}
          articleRef={article}
          {...(fixed === undefined ? {} : { corrections: fixed })}
          {...(names === undefined ? {} : { names })}
          {...(nameplate === undefined ? {} : { nameplate })}
          {...(review === undefined ? {} : { review })}
        />
      </main>
      {recording.missing ? (
        <p className="sticky bottom-0 bg-field px-4 py-3 text-sm text-field-foreground">
          The recording is not where it was last seen, so this transcript cannot play. Last seen at{" "}
          <span className="font-mono break-all">{recording.path}</span>
        </p>
      ) : (
        <Player
          recording={recording}
          reading={reading}
          article={article}
          muteSpans={muteSpans ?? null}
          selectOnTap={selectOnTap}
          {...(controls === undefined ? {} : { controls })}
        />
      )}
    </>
  );
}
