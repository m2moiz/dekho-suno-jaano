import { Search } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, fromBody, fromThrown, showError } from "@/features/errors/appError";
import { AppBar } from "@/features/shell/AppBar";
import { FIELD_EDGE } from "@/features/shell/field";
import { useFinishedCount } from "@/features/transcribe/jobs";
import { fold } from "@/lib/fold";
import { fileName } from "./describe";
import { importRecording } from "./imports";
import { RecordingRowItem } from "./RecordingRow";
import { displayTitle } from "./title";
import type { RecordingRow } from "./types";

const ROUTE = "/api/recordings";

// The list is one local request, and a flash of placeholder is worse than a
// few milliseconds of nothing (#57 section 11.7). So the skeleton shows only
// when the answer is late enough to be seen waiting: 300 ms, the commonly
// cited edge of a delay people notice (a convention, not measured here).
const SKELETON_AFTER_MS = 300;

type Loaded = { state: "loading" } | { state: "failed" } | { state: "ready"; rows: RecordingRow[] };

async function loadRecordings(): Promise<RecordingRow[]> {
  const { data, error, response } = await api.GET(ROUTE);
  if (data === undefined) throw new ApiError(fromBody(error, response, ROUTE));
  return data;
}

/** True once `on` has stayed true for `ms`. */
function useLate(on: boolean, ms: number): boolean {
  const [late, setLate] = useState(false);
  useEffect(() => {
    if (!on) {
      setLate(false);
      return;
    }
    const timer = setTimeout(() => setLate(true), ms);
    return () => clearTimeout(timer);
  }, [on, ms]);
  return late;
}

/** Titles and file names holding every word of `query`, in any order and case. */
function matches(row: RecordingRow, query: string): boolean {
  const haystack = fold(`${displayTitle(row)} ${fileName(row.path)}`);
  return fold(query)
    .split(/\s+/)
    .filter(Boolean)
    .every((word) => haystack.includes(word));
}

/**
 * The library's front door (#110): the Mac's own file dialog, opened by the
 * server. The gold primary, in the bar; the empty library offers it again,
 * in outline, so the screen still has one gold action (rulings F23). Its
 * waiting line sits on the ground there rather than the blue field.
 */
function AddRecording({ onAdded, onField = true }: { onAdded: () => void; onField?: boolean }) {
  const [asking, setAsking] = useState(false);
  const run = () => {
    setAsking(true);
    importRecording().then(
      (row) => {
        setAsking(false);
        if (row !== null) onAdded();
      },
      (thrown: unknown) => {
        setAsking(false);
        showError(fromThrown(thrown, "/api/recordings/import"));
      },
    );
  };
  return (
    <>
      <Button
        variant={onField ? "default" : "outline"}
        disabled={asking}
        onClick={run}
        className={onField ? "h-11 bg-gold px-4 font-semibold text-primary-foreground hover:bg-gold/90" : "h-11 px-4"}
      >
        Add recording
      </Button>
      {asking && (
        <span
          className={`basis-full px-2 text-sm sm:basis-auto ${onField ? "text-field-muted" : "text-muted-foreground"}`}
          role="status"
        >
          Choose a file in the dialog. It may be behind this window.
        </span>
      )}
    </>
  );
}

/**
 * Every recording dsj knows, newest first (#156), as conversations: readable
 * titles, search, and the way a new one comes in (#110).
 */
export function LibraryPage() {
  const [loaded, setLoaded] = useState<Loaded>({ state: "loading" });
  // Read again when a transcription started from this page finishes (#113),
  // and when a recording is added, found again or renamed.
  const finished = useFinishedCount();
  const [changed, setChanged] = useState(0);
  const reload = useCallback(() => setChanged((n) => n + 1), []);
  const [query, setQuery] = useState("");
  const search = useRef<HTMLInputElement>(null);
  const late = useLate(loaded.state === "loading", SKELETON_AFTER_MS);
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

  const empty = loaded.state === "ready" && loaded.rows.length === 0;
  const shown = loaded.state === "ready" ? loaded.rows.filter((row) => matches(row, query)) : [];
  return (
    <>
      {/* The bar's content lines up with the list below it. */}
      <AppBar measure="max-w-3xl">
        <h1 className="sr-only">Library</h1>
        {/* Nothing to search in an empty library. */}
        {!empty && (
          <label className="relative order-last flex min-w-0 basis-full items-center sm:order-none sm:max-w-sm sm:flex-1 sm:basis-auto">
            <Search aria-hidden className="pointer-events-none absolute left-3 size-4 text-field-muted" />
            <Input
              ref={search}
              type="search"
              dir="auto"
              aria-label="Search titles"
              placeholder="Search titles"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              className={`h-11 bg-transparent pr-3 pl-9 text-base text-field-foreground placeholder:text-field-muted md:text-sm dark:bg-transparent ${FIELD_EDGE}`}
            />
          </label>
        )}
        <AddRecording onAdded={reload} />
      </AppBar>
      <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-3 px-3 py-6 sm:px-6">
        {loaded.state === "loading" ? (
          late && (
            <ul
              aria-label="Loading recordings"
              className="divide-y divide-border overflow-hidden rounded-xl border border-border bg-card"
            >
              {[0, 1, 2, 3].map((i) => (
                <li key={i} className="px-4 py-3">
                  <Skeleton className="h-6 w-2/3" />
                  <Skeleton className="mt-2 h-4 w-1/3" />
                </li>
              ))}
            </ul>
          )
        ) : loaded.state === "failed" ? (
          <div className="flex flex-col items-start gap-3">
            <p className="text-muted-foreground">The library could not be read.</p>
            <Button variant="outline" className="h-11 px-4 sm:h-9" onClick={reload}>
              Try again
            </Button>
          </div>
        ) : empty ? (
          <section className="mx-auto mt-16 flex max-w-md flex-col items-start gap-3">
            <h2 className="font-reading text-2xl font-semibold">No recordings yet</h2>
            <p className="text-muted-foreground">
              Add a recording from this Mac. dsj reads it where it is, transcribes it here, and nothing leaves the
              machine.
            </p>
            <AddRecording onAdded={reload} onField={false} />
          </section>
        ) : (
          // A block, not the main column's gap: the status line takes no room while empty.
          <div>
            {/* On the page from the first list, so a screen reader hears it
                when a search stops matching (a live region added already
                full is often not read). */}
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
              <p role="status" className="text-muted-foreground">
                {shown.length === 0 && (
                  <>
                    No title or file name has “<bdi>{query.trim()}</bdi>” in it.
                  </>
                )}
              </p>
              {shown.length === 0 && (
                <Button
                  variant="outline"
                  className="h-11 px-4 sm:h-9"
                  onClick={() => {
                    setQuery("");
                    search.current?.focus();
                  }}
                >
                  Clear search
                </Button>
              )}
            </div>
            {shown.length > 0 && (
              // One surface, a hairline between conversations: an archive to read
              // down, not a stack of boxes (craft floor, "cards are the lazy container").
              <ul
                className="divide-y divide-border overflow-hidden rounded-xl border border-border bg-card text-card-foreground"
                aria-label="Recordings"
              >
                {shown.map((row) => (
                  <RecordingRowItem key={row.id} row={row} onChanged={reload} />
                ))}
              </ul>
            )}
          </div>
        )}
      </main>
    </>
  );
}
