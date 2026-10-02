import { useEffect, useRef, useState } from "react";

import { api } from "@/api/client";
import { ApiError, fromBody, fromThrown, showError } from "@/features/errors/appError";
import { fileName } from "@/features/library/describe";
import type { RecordingRow } from "@/features/library/types";
import { Player } from "@/features/player/Player";
import { parseTranscript, read, type Reading } from "./document";
import { TranscriptView } from "./TranscriptView";
import { UnsureToggle } from "./UnsureToggle";

type Opened = { recording: RecordingRow; model: string; reading: Reading };
type Loaded = { state: "loading" } | { state: "failed" } | ({ state: "ready" } & Opened);

async function open(recordingId: number, transcriptId: number): Promise<Opened> {
  const transcriptRoute = `/api/transcripts/${transcriptId}`;
  const [list, file] = await Promise.all([
    api.GET("/api/recordings"),
    api.GET("/api/transcripts/{transcript_id}", {
      params: { path: { transcript_id: String(transcriptId) } },
    }),
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
  const doc = parseTranscript(file.data);
  return { recording, model: doc.model, reading: read(doc) };
}

/** One transcript, opened from the library, to read (#58). */
export function TranscriptPage({ recording, transcript }: { recording: number; transcript: number }) {
  const [loaded, setLoaded] = useState<Loaded>({ state: "loading" });
  const article = useRef<HTMLElement>(null);
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
      {loaded.state === "ready" && (
        <>
          <header className="mb-8 flex items-start justify-between gap-4">
            <div>
              <h2 className="text-xl font-semibold text-balance">{fileName(loaded.recording.path)}</h2>
              <p className="text-sm text-muted-foreground">{loaded.model}</p>
            </div>
            <UnsureToggle reading={loaded.reading} model={loaded.model} article={article} />
          </header>
          <TranscriptView reading={loaded.reading} articleRef={article} />
          {loaded.recording.missing ? (
            <p className="sticky bottom-0 mt-8 border-t bg-background/95 py-3 text-sm text-muted-foreground">
              The recording is not where it was last seen, so this transcript cannot play. Last seen at{" "}
              <span className="font-mono break-all">{loaded.recording.path}</span>
            </p>
          ) : (
            <Player recording={loaded.recording} reading={loaded.reading} article={article} />
          )}
        </>
      )}
    </>
  );
}
