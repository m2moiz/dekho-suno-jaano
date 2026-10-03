import { type ReactNode, type RefObject, useEffect, useMemo, useRef, useState } from "react";

import { api } from "@/api/client";
import { BleepPanel } from "@/features/bleep/BleepPanel";
import { EditBar, useMutedPaint, useSelection, useUndoKeys } from "@/features/edit/EditBar";
import { type Editable, loadEditable, type Span, useContent, useLatest, useSave } from "@/features/edit/editing";
import { type EditReading, keepReading, readContent } from "@/features/edit/readContent";
import { ApiError, fromBody, fromThrown, showError } from "@/features/errors/appError";
import { fileName } from "@/features/library/describe";
import type { RecordingRow } from "@/features/library/types";
import { Player, type PlayerControls } from "@/features/player/Player";
import { parseTranscript, read, type Reading, type TranscriptDoc } from "./document";
import { TranscriptView } from "./TranscriptView";
import { UnsureToggle } from "./UnsureToggle";

type Opened = {
  recording: RecordingRow;
  doc: TranscriptDoc;
  /** The edit list, or why this transcript has none (#66). */
  editable: Editable | { reason: string };
};
type Loaded = { state: "loading" } | { state: "failed" } | ({ state: "ready" } & Opened);

async function open(recordingId: number, transcriptId: number): Promise<Opened> {
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
    open(recording, transcript).then(
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

  return (
    <>
      <nav className="mb-6 text-sm">
        <a href="/" className="text-muted-foreground underline-offset-4 hover:underline">
          ← Library
        </a>
      </nav>
      {loaded.state === "failed" && (
        <p className="text-muted-foreground">This transcript could not be opened.</p>
      )}
      {loaded.state === "ready" &&
        ("editor" in loaded.editable ? (
          <EditablePage opened={loaded} editable={loaded.editable} transcriptId={transcript} />
        ) : (
          <ReadOnlyPage opened={loaded} reason={loaded.editable.reason} />
        ))}
    </>
  );
}

function ReadOnlyPage({ opened, reason }: { opened: Opened; reason: string }) {
  const reading = useMemo(() => read(opened.doc), [opened.doc]);
  const article = useRef<HTMLElement>(null);
  return (
    <Page opened={opened} reading={reading} article={article}>
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
  useUndoKeys(editor);
  useMutedPaint(edit, content, article);
  return (
    <Page opened={opened} reading={edit.reading} article={article} muteSpans={renderable.spans} controls={controls}>
      <EditBar editor={editor} content={content} edit={edit} selected={selected} saving={saving} />
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
  reading: Reading;
  article: RefObject<HTMLElement | null>;
  children?: ReactNode;
  muteSpans?: readonly Span[] | null;
  controls?: RefObject<PlayerControls | null>;
};

function Page({ opened, reading, article, children, muteSpans, controls }: PageProps) {
  const { recording, doc } = opened;
  return (
    <>
      <header className="mb-8 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold text-balance">{fileName(recording.path)}</h2>
          <p className="text-sm text-muted-foreground">{doc.model}</p>
        </div>
        <UnsureToggle reading={reading} model={doc.model} article={article} />
      </header>
      {children}
      <TranscriptView reading={reading} articleRef={article} />
      {recording.missing ? (
        <p className="sticky bottom-0 mt-8 border-t bg-background/95 py-3 text-sm text-muted-foreground">
          The recording is not where it was last seen, so this transcript cannot play. Last seen at{" "}
          <span className="font-mono break-all">{recording.path}</span>
        </p>
      ) : (
        <Player
          recording={recording}
          reading={reading}
          article={article}
          muteSpans={muteSpans ?? null}
          {...(controls === undefined ? {} : { controls })}
        />
      )}
    </>
  );
}
