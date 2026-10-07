import { type ReactNode, type RefObject, useEffect, useMemo, useRef, useState } from "react";

import { api } from "@/api/client";
import { BleepPanel } from "@/features/bleep/BleepPanel";
import { correction, textOf } from "@/features/edit/correct";
import { type Correction, corrections, tokensOf } from "@/features/edit/corrections";
import { EditBar, useCorrectedPaint, useMutedPaint, useSelection, useUndoKeys } from "@/features/edit/EditBar";
import { type Editable, loadEditable, type Span, useContent, useLatest, useSave } from "@/features/edit/editing";
import { InlineCorrect } from "@/features/edit/InlineCorrect";
import { type EditReading, keepReading, readContent } from "@/features/edit/readContent";
import { type Picked, SelectionToolbar } from "@/features/edit/SelectionToolbar";
import { TimingStrip } from "@/features/edit/TimingStrip";
import { ApiError, fromBody, fromThrown, showError } from "@/features/errors/appError";
import { fileName } from "@/features/library/describe";
import type { RecordingRow } from "@/features/library/types";
import { Player, type PlayerControls } from "@/features/player/Player";
import { AppBar } from "@/features/shell/AppBar";
import { KeysItem } from "@/features/shell/KeySheet";
import { READER_SHEET } from "@/features/shell/keys";
import { parseTranscript, read, type Reading, type TranscriptDoc } from "./document";
import { useReaderKeys } from "./readerKeys";
import type { Names } from "./speakers";
import { TranscriptView } from "./TranscriptView";
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

/** One transcript, opened from the library, to read (#58) and to edit (#66). */
export function TranscriptPage({ recording, transcript }: { recording: number; transcript: number }) {
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
    <EditablePage opened={loaded} editable={loaded.editable} transcriptId={transcript} />
  ) : (
    <ReadOnlyPage opened={loaded} reason={loaded.editable.reason} transcriptId={transcript} />
  );
}

function ReadOnlyPage({ opened, reason, transcriptId }: { opened: Opened; reason: string; transcriptId: number }) {
  const reading = useMemo(() => read(opened.doc), [opened.doc]);
  const article = useRef<HTMLElement>(null);
  const controls = useRef<PlayerControls | null>(null);
  useReaderKeys(controls, READER_SHEET);
  return (
    <Page opened={opened} transcriptId={transcriptId} reading={reading} article={article} controls={controls}>
      <p className="mb-6 text-sm text-muted-foreground" role="note">
        This transcript cannot be edited: {reason}
      </p>
    </Page>
  );
}

function EditablePage({ opened, editable, transcriptId }: { opened: Opened; editable: Editable; transcriptId: number }) {
  const { editor } = editable;
  const content = useContent(editor);
  const previous = useRef<EditReading | null>(null);
  const edit = useMemo(() => {
    const next = keepReading(previous.current, readContent(content, opened.doc.speakers));
    previous.current = next;
    return next;
  }, [content, opened.doc.speakers]);
  const article = useRef<HTMLElement>(null);
  const saving = useSave(transcriptId, editable);
  const selected = useSelection(edit, article);
  const renderable = useLatest(editable.renderable);
  const controls = useRef<PlayerControls | null>(null);
  // The word whose edges are being dragged (#85), while the strip is open.
  const [timing, setTiming] = useState<number | null>(null);
  // The words being retyped in place (#83), while the field is open.
  const [correcting, setCorrecting] = useState<Picked | null>(null);
  const tokens = useMemo(() => tokensOf(opened.doc), [opened.doc]);
  const fixed = useMemo(() => corrections(edit.reading, tokens), [edit.reading, tokens]);
  useUndoKeys(editor);
  useMutedPaint(edit, content, article);
  useCorrectedPaint(edit.reading, fixed, article);
  useReaderKeys(controls, READER_SHEET);
  return (
    <Page
      opened={opened}
      transcriptId={transcriptId}
      reading={edit.reading}
      article={article}
      muteSpans={renderable.spans}
      controls={controls}
      corrections={fixed}
      selectOnTap
      tools={<EditBar editor={editor} saving={saving} />}
    >
      <SelectionToolbar
        editor={editor}
        content={content}
        edit={edit}
        selected={correcting === null ? selected : null}
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
          onCancel={() => setCorrecting(null)}
          onSave={(text) => {
            editor.applyEdit(correction(content, correcting.start, correcting.stop, text));
            setCorrecting(null);
            window.getSelection()?.removeAllRanges();
          }}
        />
      )}
      {timing !== null && timing < edit.first.length && (
        <TimingStrip
          editor={editor}
          content={content}
          edit={edit}
          word={timing}
          recordingId={opened.recording.id}
          controls={controls}
          onClose={() => setTiming(null)}
        />
      )}
      <BleepPanel
        transcriptId={transcriptId}
        editor={editor}
        content={content}
        edit={edit}
        renderable={renderable}
        padS={editable.padS}
        controls={controls}
      />
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
  selectOnTap?: boolean;
};

function Page({ opened, transcriptId, reading, article, children, tools, muteSpans, controls, corrections: fixed, names, nameplate, selectOnTap = false }: PageProps) {
  const { recording, doc } = opened;
  return (
    <>
      <AppBar back settings={<KeysItem sheet={READER_SHEET} />}>
        <h1 className="min-w-0 flex-1 truncate font-reading text-lg font-semibold">{fileName(recording.path)}</h1>
        <VersionPicker recording={recording} transcript={transcriptId} />
        <UnsureNav reading={reading} model={doc.model} article={article} />
        {tools}
      </AppBar>
      <main className="mx-auto w-full max-w-5xl flex-1 px-3 pt-6 pb-10 sm:px-6">
        {children}
        <TranscriptView
          reading={reading}
          articleRef={article}
          {...(fixed === undefined ? {} : { corrections: fixed })}
          {...(names === undefined ? {} : { names })}
          {...(nameplate === undefined ? {} : { nameplate })}
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
