// The words a running job is shown in. The one distinction that matters most
// (#113): whisper without Roman Urdu reports nothing between its first frame
// and its last, and a bar sitting at 0% for an hour reads as stuck. So that
// case says so, in words, instead of drawing a bar.

import { durationLabel } from "@/features/library/describe";
import type { Job } from "./jobs";

const PHASES: Record<Job["state"], string> = {
  starting: "Loading the model",
  extracting: "Reading the audio out of the file",
  running: "Transcribing",
  retrying: "Reading unclear stretches again",
  diarizing: "Labelling speakers",
  saving: "Finishing",
  done: "Transcribed",
  failed: "Failed",
};

export function phaseLabel(job: Job): string {
  return PHASES[job.state];
}

/** Whether the bar can show how far the job has got, or only that it is busy. */
export function hasFraction(job: Job): boolean {
  if (job.state === "running") return job.reports_progress;
  // ffmpeg reports while extracting and a retry counts its seconds; the model
  // load, the labelling pass (senko has no callback) and the save say nothing.
  return job.state === "extracting" || job.state === "retrying";
}

/** The line under the bar: how much audio, how fast, how long left. */
export function progressLine(job: Job): string {
  if (job.state === "running" && !job.reports_progress) {
    return `${job.engine} reports no progress until it is done.`;
  }
  if (!hasFraction(job)) return "";
  const parts = [
    `${durationLabel(job.audio_done_s) ?? "0:00"} of ${durationLabel(job.audio_total_s) ?? "0:00"}`,
  ];
  if (job.speed > 0) parts.push(`${job.speed.toFixed(1)}x`);
  if (job.eta_s !== null) parts.push(`about ${durationLabel(job.eta_s) ?? "0:00"} left`);
  if (job.stalled_s !== null) parts.push(`not moved for ${Math.round(job.stalled_s)} s`);
  return parts.join(" · ");
}
