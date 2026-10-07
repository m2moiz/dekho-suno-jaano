import { useEffect, useState } from "react";

import { Button, buttonVariants } from "@/components/ui/button";
import { fromThrown, showError } from "@/features/errors/appError";
import { cn } from "@/lib/utils";
import type { Counts } from "./model";
import { type ReferenceWritten, saveAnswerKey } from "./reviewApi";

type Props = {
  transcriptId: number;
  progress: Counts;
  /** The transcript's address, for the link's own sake (a new tab, a copied link). */
  back: string;
  /** Save, then go back to the transcript, as Esc does. */
  leave: () => void;
  /** Resolve once the review and the edit list are saved; throws when not (Session.settle). */
  settle: () => Promise<void>;
};

/**
 * The end of a pass (Hashiya spec, "Finishing"): what it did, and two ways
 * on. "Save as answer key" writes `<name>.reference.json` and `.txt` beside
 * the transcript, from the server's copy of the review, so that copy is
 * brought up to date first; with sentences still unchecked it asks first, and
 * the key says it is partial.
 */
export function FinishPanel({ transcriptId, progress, back, leave, settle }: Props) {
  const [written, setWritten] = useState<ReferenceWritten | null>(null);
  const [asking, setAsking] = useState(false);
  const unchecked = progress.total - progress.checked;
  // Esc leaves Review here too (spec key table; Task 13 review, Minor 7).
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !event.defaultPrevented) leave();
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [leave]);
  const save = (partial: boolean) => {
    setAsking(false);
    settle()
      .then(() => saveAnswerKey(transcriptId, partial))
      .then(setWritten, (thrown: unknown) => showError(fromThrown(thrown, `/api/transcripts/${transcriptId}/reference`)));
  };
  const rows: [string, string][] = [
    ["Checked", `${progress.checked.toLocaleString("en")} of ${progress.total.toLocaleString("en")}`],
    ["Words changed", progress.edited.toLocaleString("en")],
    ["Flagged", progress.flagged.toLocaleString("en")],
    ["Speaker changed", progress.reassigned.toLocaleString("en")],
  ];
  return (
    <main className="mx-auto flex w-full max-w-xl flex-1 flex-col gap-6 px-3 py-12 sm:px-6">
      <h2 className="font-reading text-3xl font-semibold text-balance">This pass is done</h2>
      <dl className="grid grid-cols-[auto_1fr] gap-x-8 gap-y-2 text-lg tabular-nums">
        {rows.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-muted-foreground">{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      {written !== null && (
        <p role="status">
          Saved {written.files.join(" and ")} beside the transcript
          {written.unchecked > 0 ? `, with ${written.unchecked.toLocaleString("en")} sentences marked not checked` : ""}.
        </p>
      )}
      {asking && (
        <div role="group" aria-label="Partial answer key" className="flex flex-col gap-3 rounded-xl border border-border bg-card p-4">
          <p>
            {unchecked.toLocaleString("en")} {unchecked === 1 ? "sentence is" : "sentences are"} not checked yet. Save a partial
            answer key? It says it is partial.
          </p>
          <div className="flex flex-wrap gap-3">
            <Button variant="outline" className="h-11 px-4" onClick={() => save(true)}>
              Save partial
            </Button>
            <Button variant="ghost" className="h-11 px-4" onClick={() => setAsking(false)}>
              Not now
            </Button>
          </div>
        </div>
      )}
      <div className="flex flex-wrap gap-3">
        <a
          href={back}
          className={cn(buttonVariants({ variant: "outline" }), "h-11 px-4")}
          onClick={(event) => {
            if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return;
            event.preventDefault();
            leave();
          }}
        >
          Back to the transcript
        </a>
        {/* The screen's one gold primary (F23): the default variant is gold. */}
        <Button className="h-11 px-4 font-semibold" onClick={() => (unchecked > 0 ? setAsking(true) : save(false))}>
          Save as answer key
        </Button>
      </div>
    </main>
  );
}
