import { useState } from "react";

import { Button } from "@/components/ui/button";
import { displayTitle } from "@/features/library/title";
import type { RecordingRow } from "@/features/library/types";
import { isFinished, type Job, useJobs } from "./jobs";

/**
 * The batch (#90): more than one transcription asked for in this launch. While
 * any is going, how far the batch is and which file is on; once all are over,
 * what succeeded and what failed, by name and with the error, until dismissed.
 * One job alone says everything on its own row, so the banner stays away.
 */
export function BatchBanner({ rows }: { rows: readonly RecordingRow[] }) {
  const jobs = useJobs();
  // How many jobs the batch held when its summary was dismissed: a new job
  // after that is a new batch with a new summary.
  const [dismissedAt, setDismissedAt] = useState(0);
  if (jobs.length < 2) return null;
  const title = (job: Job) => {
    const row = rows.find((r) => r.id === job.recording_id);
    return row === undefined ? `recording ${job.recording_id}` : displayTitle(row);
  };
  const live = jobs.filter((j) => !isFinished(j));
  const done = jobs.filter((j) => j.state === "done");
  const failed = jobs.filter((j) => j.state === "failed");
  if (live.length > 0) {
    const current = live.find((j) => j.state !== "queued") ?? live[0];
    const parts = [`${done.length} done`];
    if (failed.length > 0) parts.push(`${failed.length} failed`);
    if (live.length > 1) parts.push(`${live.length - 1} waiting`);
    return (
      <section role="status" aria-label="Batch" className="rounded-xl border border-border bg-card px-4 py-3 text-sm">
        <p>
          <span className="font-semibold">
            Transcribing {jobs.length - live.length + 1} of {jobs.length}:
          </span>{" "}
          {current === undefined ? "" : title(current)}
        </p>
        <p className="text-muted-foreground tabular-nums">{parts.join(" · ")}</p>
      </section>
    );
  }
  if (jobs.length <= dismissedAt) return null;
  return (
    <section role="status" aria-label="Batch finished" className="flex flex-col gap-2 rounded-xl border border-border bg-card px-4 py-3 text-sm">
      <div className="flex items-center justify-between gap-2">
        <p className="font-semibold">
          {done.length} transcribed, {failed.length} failed
          {jobs.length - done.length - failed.length > 0 ? `, ${jobs.length - done.length - failed.length} stopped` : ""}
        </p>
        <Button variant="outline" size="sm" className="h-9" onClick={() => setDismissedAt(jobs.length)}>
          Dismiss
        </Button>
      </div>
      {failed.length > 0 && (
        <ul className="flex list-disc flex-col gap-1 pl-5">
          {failed.map((job) => (
            <li key={job.id} className="text-destructive">
              {title(job)}: {job.error}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
