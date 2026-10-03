// A bleep render started from the page (#215): dsj.hatao.render on the
// server, the function `dsj hatao` calls, run as a job beside the recording.

import { useEffect, useState } from "react";

import { api } from "@/api/client";
import type { components } from "@/api/schema";
import { ApiError, fromBody } from "@/features/errors/appError";
import { sessionToken } from "@/features/session/session";
import { type Content, itemsIn } from "@/lib/editOps";
import type { Match } from "./matches";

export type RenderJob = components["schemas"]["RenderJob"];

// ffmpeg writes a minute of audio in well under a second here, so half a
// second between looks shows the bar move without asking for nothing.
export const POLL_MS = 500;

export function isOver(job: RenderJob): boolean {
  return job.state === "done" || job.state === "failed";
}

/** Render `content` beside the recording. Throws ApiError with the server's own words when refused. */
export async function startRender(transcriptId: number, content: Content): Promise<RenderJob> {
  const route = `/api/transcripts/${transcriptId}/render`;
  const { data, error, response } = await api.POST("/api/transcripts/{transcript_id}/render", {
    params: { path: { transcript_id: String(transcriptId) } },
    body: { content: [...content] },
  });
  if (data === undefined) throw new ApiError(fromBody(error, response, route));
  return data;
}

/** `content` with only `match` muted: one span, rendered alone (#84). */
export function alone(content: Content, match: Match): Content {
  const keep = new Set(itemsIn(content, match.start, match.stop));
  return content.map((entry, index) =>
    entry.kind === "item" && entry.muted !== keep.has(index) ? { ...entry, muted: keep.has(index) } : entry,
  );
}

/**
 * A finished render's address, by its id. A media element or a link sends no
 * header, so the token rides in the query, as the recording's own does (#59).
 */
export function renderSrc(id: number): string {
  return `/api/renders/${id}/media?t=${encodeURIComponent(sessionToken() ?? "")}`;
}

/** The render `started` as the server last reported it, looked at until it is over. */
export function useRender(started: RenderJob | null): RenderJob | null {
  const [job, setJob] = useState<RenderJob | null>(started);
  useEffect(() => {
    setJob(started);
    if (started === null || isOver(started)) return;
    let live = true;
    const look = async () => {
      const { data } = await api.GET("/api/renders");
      const now = data?.find((r) => r.id === started.id);
      if (!live) return;
      if (now !== undefined) setJob(now);
      if (now === undefined || !isOver(now)) timer = setTimeout(look, POLL_MS);
    };
    let timer = setTimeout(look, POLL_MS);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [started]);
  return job;
}
