import { useEffect, useState } from "react";

import { api } from "@/api/client";
import { ApiError, fromBody, fromThrown, showError } from "@/features/errors/appError";
import {
  durationLabel,
  engineLabel,
  fileName,
  marksLabel,
  speakersLabel,
  whenLabel,
} from "./describe";
import type { RecordingRow, TranscriptRow } from "./types";

const ROUTE = "/api/recordings";

type Loaded = { state: "loading" } | { state: "failed" } | { state: "ready"; rows: RecordingRow[] };

async function loadRecordings(): Promise<RecordingRow[]> {
  const { data, error, response } = await api.GET(ROUTE);
  if (data === undefined) throw new ApiError(fromBody(error, response, ROUTE));
  return data;
}

/** Every recording dsj knows, newest first, each with its transcripts (#156). */
export function LibraryPage() {
  const [loaded, setLoaded] = useState<Loaded>({ state: "loading" });
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
  }, []);

  // No skeleton: the list is one local request, and a flash of placeholder is
  // worse than a few milliseconds of nothing (#57 section 11.7).
  if (loaded.state === "loading") return null;
  if (loaded.state === "failed") {
    return <p className="text-muted-foreground">The library could not be read.</p>;
  }
  if (loaded.rows.length === 0) {
    return <p className="text-muted-foreground">The library is empty.</p>;
  }
  return (
    <ul className="flex flex-col gap-6" aria-label="Recordings">
      {loaded.rows.map((row) => (
        <Recording key={row.id} row={row} />
      ))}
    </ul>
  );
}

function Recording({ row }: { row: RecordingRow }) {
  const length = durationLabel(row.duration_s);
  return (
    <li
      className={row.missing ? "opacity-50" : undefined}
      data-missing={row.missing || undefined}
      aria-label={fileName(row.path)}
    >
      <div className="flex items-baseline gap-3">
        <h2 className="font-medium text-balance">{fileName(row.path)}</h2>
        {length !== null && <span className="text-sm text-muted-foreground">{length}</span>}
        {row.video_codec !== null && <span className="text-sm text-muted-foreground">video</span>}
      </div>
      {row.missing && (
        <p className="text-sm text-muted-foreground">
          Missing. Last seen at <span className="font-mono break-all">{row.path}</span>
        </p>
      )}
      <ul className="mt-1 flex flex-col gap-0.5">
        {row.transcripts.map((t) => (
          <Transcript key={t.id} t={t} />
        ))}
      </ul>
    </li>
  );
}

function Transcript({ t }: { t: TranscriptRow }) {
  const parts = [
    whenLabel(t.finished_at),
    engineLabel(t),
    t.model,
    ...(t.language === null ? [] : [t.language]),
    speakersLabel(t),
    marksLabel(t),
  ];
  return <li className="text-sm text-muted-foreground">{parts.join(" · ")}</li>;
}
