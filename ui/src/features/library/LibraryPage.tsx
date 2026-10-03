import { useCallback, useEffect, useState } from "react";

import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { ApiError, fromBody, fromThrown, showError } from "@/features/errors/appError";
import { transcriptHref } from "@/lib/route";
import { useFinishedCount } from "@/features/transcribe/jobs";
import { TranscribeControl } from "@/features/transcribe/TranscribeControl";
import {
  durationLabel,
  engineLabel,
  fileName,
  marksLabel,
  pictureNote,
  sizeLabel,
  speakersLabel,
  whenLabel,
} from "./describe";
import { importRecording, relinkRecording } from "./imports";
import type { RecordingRow, TranscriptRow } from "./types";

const ROUTE = "/api/recordings";

type Loaded = { state: "loading" } | { state: "failed" } | { state: "ready"; rows: RecordingRow[] };

async function loadRecordings(): Promise<RecordingRow[]> {
  const { data, error, response } = await api.GET(ROUTE);
  if (data === undefined) throw new ApiError(fromBody(error, response, ROUTE));
  return data;
}

/**
 * Every recording dsj knows, newest first, each with its transcripts (#156),
 * and the way a new one comes in (#110).
 */
export function LibraryPage() {
  const [loaded, setLoaded] = useState<Loaded>({ state: "loading" });
  // Read again when a transcription started from this page finishes (#113), so
  // its transcript appears without a reload, and when a recording is added or
  // found again (#110).
  const finished = useFinishedCount();
  const [changed, setChanged] = useState(0);
  const reload = useCallback(() => setChanged((n) => n + 1), []);
  useEffect(() => {
    let live = true;
    loadRecordings().then(
      (rows) => {
        if (live) setLoaded({ state: "ready", rows });
      },
      (thrown: unknown) => {
        if (!live) return;
        setLoaded({ state: "failed" });
        showError(fromThrown(thrown, ROUTE));
      },
    );
    return () => {
      live = false;
    };
  }, [finished, changed]);

  // No skeleton: the list is one local request, and a flash of placeholder is
  // worse than a few milliseconds of nothing (#57 section 11.7).
  if (loaded.state === "loading") return null;
  return (
    <div className="flex flex-col gap-6">
      <AddRecording onAdded={reload} />
      {loaded.state === "failed" ? (
        <p className="text-muted-foreground">The library could not be read.</p>
      ) : loaded.rows.length === 0 ? (
        <p className="text-muted-foreground">The library is empty.</p>
      ) : (
        <ul className="flex flex-col gap-6" aria-label="Recordings">
          {loaded.rows.map((row) => (
            <Recording key={row.id} row={row} onChanged={reload} />
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * Run one of the dialog's requests: the button waits while the dialog is open,
 * a refusal goes to the error dialog in the server's words, and a cancel does
 * nothing at all.
 */
function useDialog(ask: () => Promise<RecordingRow | null>, done: () => void, request: string) {
  const [asking, setAsking] = useState(false);
  const run = () => {
    setAsking(true);
    ask().then(
      (row) => {
        setAsking(false);
        if (row !== null) done();
      },
      (thrown: unknown) => {
        setAsking(false);
        showError(fromThrown(thrown, request));
      },
    );
  };
  return [asking, run] as const;
}

/**
 * The library's front door (#110): the Mac's own file dialog, opened by the
 * server, so the file is read where it lies and never copied. Drag and drop
 * is not here: a page is never told where a dropped file is (#127 trap 16).
 */
function AddRecording({ onAdded }: { onAdded: () => void }) {
  const [asking, run] = useDialog(importRecording, onAdded, "/api/recordings/import");
  return (
    <div className="flex items-center gap-3">
      <Button variant="outline" size="sm" disabled={asking} onClick={run}>
        Add recording
      </Button>
      {asking && (
        <span className="text-sm text-muted-foreground" role="status">
          Choose a file in the dialog. It may be behind this window.
        </span>
      )}
    </div>
  );
}

function FindFile({ row, onFound }: { row: RecordingRow; onFound: () => void }) {
  const [asking, run] = useDialog(
    () => relinkRecording(row.id),
    onFound,
    `/api/recordings/${row.id}/relink`,
  );
  return (
    <div className="mt-1">
      <Button variant="outline" size="sm" disabled={asking} onClick={run}>
        Find this file
      </Button>
    </div>
  );
}

function Recording({ row, onChanged }: { row: RecordingRow; onChanged: () => void }) {
  const length = durationLabel(row.duration_s);
  const size = sizeLabel(row.size_bytes);
  const picture = pictureNote(row.video_codec);
  return (
    <li
      className={row.missing ? "opacity-50" : undefined}
      data-missing={row.missing || undefined}
      aria-label={fileName(row.path)}
    >
      <div className="flex items-baseline gap-3">
        <h2 className="font-medium text-balance">{fileName(row.path)}</h2>
        {length !== null && <span className="text-sm text-muted-foreground">{length}</span>}
        {size !== null && <span className="text-sm text-muted-foreground">{size}</span>}
        {row.video_codec !== null && <span className="text-sm text-muted-foreground">video</span>}
      </div>
      {row.missing && (
        <>
          <p className="text-sm text-muted-foreground">
            Missing. Last seen at <span className="font-mono break-all">{row.path}</span>
          </p>
          <FindFile row={row} onFound={onChanged} />
        </>
      )}
      {row.unreadable !== null && (
        <p className="text-sm text-destructive select-text whitespace-pre-wrap" role="note">
          ffmpeg could not read this file: {row.unreadable}
        </p>
      )}
      {picture !== null && <p className="text-sm text-muted-foreground">{picture}</p>}
      <ul className="mt-1 flex flex-col gap-0.5">
        {row.transcripts.map((t) => (
          <Transcript key={t.id} recording={row.id} t={t} />
        ))}
      </ul>
      <TranscribeControl recording={row} />
    </li>
  );
}

function Transcript({ recording, t }: { recording: number; t: TranscriptRow }) {
  const parts = [
    whenLabel(t.finished_at),
    engineLabel(t),
    t.model,
    ...(t.language === null ? [] : [t.language]),
    speakersLabel(t),
    marksLabel(t),
    // Corrected by hand in the app (#83): the edit list changed, never the file.
    ...(t.last_edited_at === null ? [] : [`edited ${whenLabel(t.last_edited_at)}`]),
  ];
  // The whole line opens the transcript (#58): its date and model are what tell
  // one transcript of a recording from another. A block, so the whole row
  // takes the click: as an inline link wrapped onto two lines, a click on the
  // row's middle did not open it in Chromium (2026-10-02).
  return (
    <li className="text-sm text-muted-foreground">
      <a
        href={transcriptHref(recording, t.id)}
        className="block underline-offset-4 hover:text-foreground hover:underline"
      >
        {parts.join(" · ")}
      </a>
    </li>
  );
}
