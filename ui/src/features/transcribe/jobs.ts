// Transcriptions started from the page (#113), as the server reports them.
//
// The server runs each job in its own process, on a thread of its own, and
// the run writes its progress to a status file; GET /api/jobs reads it back. So this module polls, once a
// second, and only while some job is still going. Module state rather than
// React state, as the error dialog's is, so every recording row reads one
// list and the library page can hear that a job finished.

import { useSyncExternalStore } from "react";

import { api } from "@/api/client";
import type { components } from "@/api/schema";
import { ApiError, fromBody } from "@/features/errors/appError";

export type Job = components["schemas"]["Job"];
export type Engine = components["schemas"]["Engine"];
export type TranscribeRequest = components["schemas"]["TranscribeRequest"];

const JOBS = "/api/jobs";
const ENGINES = "/api/engines";

// A chunk is 120 s of audio and parakeet reads one in a few seconds, so a
// second between looks is the slowest that still shows every chunk.
export const POLL_MS = 1000;

export function isFinished(job: Job): boolean {
  return job.state === "done" || job.state === "failed";
}

let jobs: Job[] = [];
let finishedCount = 0;
let looked = false;
let timer: ReturnType<typeof setTimeout> | null = null;
const listeners = new Set<() => void>();

function emit() {
  for (const listener of listeners) listener();
}

function take(next: Job[]) {
  const before = new Map(jobs.map((j) => [j.id, j]));
  const ended = next.some((j) => {
    const was = before.get(j.id);
    return was !== undefined && !isFinished(was) && isFinished(j);
  });
  jobs = next;
  if (ended) finishedCount += 1;
  emit();
  schedule();
}

function schedule() {
  if (timer !== null || !jobs.some((j) => !isFinished(j))) return;
  timer = setTimeout(() => {
    timer = null;
    void look();
  }, POLL_MS);
}

async function look(): Promise<void> {
  const { data, error, response } = await api.GET(JOBS).catch((thrown: unknown) => {
    // A missed look is not worth the error dialog: the next one may land, and
    // a server that is gone shows itself on the next thing the reader does.
    console.warn("dsj ui could not read the jobs", thrown);
    return { data: undefined, error: undefined, response: undefined };
  });
  if (data !== undefined) {
    take(data);
  } else {
    if (response !== undefined) console.warn("dsj ui could not read the jobs", fromBody(error, response, JOBS));
    schedule();
  }
}

/** Start transcribing a recording. Throws ApiError with the server's own words when refused. */
export async function startJob(recordingId: number, request: TranscribeRequest): Promise<Job> {
  const path = "/api/recordings/{recording_id}/transcribe";
  const { data, error, response } = await api.POST(path, {
    params: { path: { recording_id: String(recordingId) } },
    body: request,
  });
  if (data === undefined) {
    throw new ApiError(fromBody(error, response, `/api/recordings/${recordingId}/transcribe`));
  }
  take([...jobs.filter((j) => j.id !== data.id), data]);
  return data;
}

/** Every engine, each with the reason it cannot run on this machine, or none. */
export async function loadEngines(): Promise<Engine[]> {
  const { data, error, response } = await api.GET(ENGINES);
  if (data === undefined) throw new ApiError(fromBody(error, response, ENGINES));
  return data;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

// The first row on screen asks once what is already running, so a reload in
// the middle of a job finds it again.
function subscribeAndLook(listener: () => void): () => void {
  if (!looked) {
    looked = true;
    void look();
  }
  return subscribe(listener);
}

/** The newest job for one recording, if it has one. */
export function useJobFor(recordingId: number): Job | undefined {
  const all = useSyncExternalStore(subscribeAndLook, () => jobs);
  return all.findLast((j) => j.recording_id === recordingId);
}

/** A number that goes up each time a job is seen to finish, for a list to reload on. */
export function useFinishedCount(): number {
  return useSyncExternalStore(subscribe, () => finishedCount);
}

/** Back to a page that has seen no job: for the unit tests, between them. */
export function forgetJobs(): void {
  if (timer !== null) clearTimeout(timer);
  timer = null;
  jobs = [];
  finishedCount = 0;
  looked = false;
  emit();
}
