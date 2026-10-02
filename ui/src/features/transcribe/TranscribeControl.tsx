import { useCallback, useState } from "react";

import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import type { RecordingRow } from "@/features/library/types";
import { hasFraction, phaseLabel, progressLine } from "./describe";
import { isFinished, type Job, useJobFor } from "./jobs";
import { TranscribeDialog } from "./TranscribeDialog";

/**
 * A recording's start button, and then its job (#113): the bar while it runs,
 * the error if it failed, what it could not do if it finished with notes.
 * Cancel is #72 and a queue of many files is #90; neither is here.
 */
export function TranscribeControl({ recording }: { recording: RecordingRow }) {
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
            disabled={recording.missing}
            onClick={() => setOpen(true)}
          >
            Transcribe
          </Button>
        </div>
      )}
      {job?.state === "failed" && (
        <p className="text-sm text-destructive select-text" role="alert">
          The last transcription failed: {job.error}
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
  return (
    <div className="flex flex-col gap-1" aria-label="Transcription" role="status">
      <span className="text-sm">
        {phaseLabel(job)} with {job.engine}
      </span>
      {/* null is the busy bar: no number to show, and none is made up. */}
      <Progress value={hasFraction(job) ? Math.round(job.fraction * 100) : null} />
      {line !== "" && <span className="text-xs text-muted-foreground tabular-nums">{line}</span>}
    </div>
  );
}
