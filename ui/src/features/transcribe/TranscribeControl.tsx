import { useCallback, useState } from "react";

import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import type { RecordingRow } from "@/features/library/types";
import { fromThrown, showError } from "@/features/errors/appError";
import { hasFraction, phaseLabel, progressLine, stopCost } from "./describe";
import { cancelJob, isFinished, type Job, useJobFor } from "./jobs";
import { TranscribeDialog } from "./TranscribeDialog";

/**
 * A recording's start button, and then its job (#113): the bar while it runs,
 * with Stop beside it (#72), the error if it failed, what it could not do if
 * it finished with notes. A queue of many files is #90, not here.
 */
export function TranscribeControl({ recording, label = "Transcribe" }: { recording: RecordingRow; label?: string }) {
  const job = useJobFor(recording.id);
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);
  const running = job !== undefined && !isFinished(job);
  return (
    <div className="mt-2 flex flex-col gap-1">
      {running ? (
        <Running job={job} />
      ) : (
        <div>
          <Button
            variant="outline"
            size="sm"
            className="h-11 sm:h-9"
            disabled={recording.missing || recording.unreadable !== null}
            onClick={() => setOpen(true)}
          >
            {label}
          </Button>
        </div>
      )}
      {job?.state === "failed" && (
        <p className="text-sm whitespace-pre-wrap text-destructive select-text" role="alert">
          The last transcription failed: {job.error}
        </p>
      )}
      {job?.state === "cancelled" && (
        <p className="text-sm text-muted-foreground" role="status">
          Stopped. {job.resumable ? "The next run picks up where this one left off." : `The next ${job.engine} run starts again.`}
        </p>
      )}
      {job?.state === "done" &&
        job.notes.map((note) => (
          <p key={note} className="text-sm text-muted-foreground">
            {note}
          </p>
        ))}
      {open && <TranscribeDialog recording={recording} onClose={close} />}
    </div>
  );
}

function Running({ job }: { job: Job }) {
  const line = progressLine(job);
  const stopping = job.state === "stopping";
  const stop = () => {
    cancelJob(job.id).catch((thrown: unknown) => showError(fromThrown(thrown, `/api/jobs/${job.id}/cancel`)));
  };
  return (
    <div className="flex flex-col gap-1" aria-label="Transcription" role="status">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm">
          {phaseLabel(job)} with {job.engine}
        </span>
        <Button variant="outline" size="sm" className="h-9" disabled={stopping} title={stopCost(job)} onClick={stop}>
          {stopping ? "Stopping" : "Stop"}
        </Button>
      </div>
      {/* null is the busy bar: no number to show, and none is made up. */}
      <Progress value={hasFraction(job) ? Math.round(job.fraction * 100) : null} />
      {line !== "" && <span className="text-xs text-muted-foreground tabular-nums">{line}</span>}
    </div>
  );
}
