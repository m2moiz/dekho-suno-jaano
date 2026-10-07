// Review mode's requests (#248): the review document, saved as it changes,
// and the answer key.

import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "@/api/client";
import type { components } from "@/api/schema";
import { keepaliveFits, NotSaved, type SaveState } from "@/features/edit/editing";
import { ApiError, fromBody, fromThrown, showError } from "@/features/errors/appError";
import type { CurrentSha, ReviewDocument } from "./model";

export type ReferenceWritten = components["schemas"]["ReferenceWritten"];

// A short wait before saving, so a run of Enter presses is one request, not
// one each. A choice, not measured: under the gap between two checks.
const SAVE_AFTER_MS = 400;

/** The transcript's review, or null, and the sha of the transcript as it is now: the one a review is saved under. */
export async function loadReview(transcriptId: number): Promise<{ document: ReviewDocument | null; sha: CurrentSha }> {
  const route = `/api/transcripts/${transcriptId}/review`;
  const { data, error, response } = await api.GET("/api/transcripts/{transcript_id}/review", {
    params: { path: { transcript_id: String(transcriptId) } },
  });
  if (data === undefined) throw new ApiError(fromBody(error, response, route));
  // The one place a CurrentSha is made (model.ts): the server's word for the transcript now.
  return { document: data.document, sha: data.transcript_sha as CurrentSha };
}

async function putReview(transcriptId: number, document: ReviewDocument, keepalive = false): Promise<void> {
  const route = `/api/transcripts/${transcriptId}/review`;
  const { data, error, response } = await api.PUT("/api/transcripts/{transcript_id}/review", {
    params: { path: { transcript_id: String(transcriptId) } },
    body: document,
    ...(keepalive && keepaliveFits(document) ? { keepalive: true } : {}),
  });
  if (data === undefined) throw new ApiError(fromBody(error, response, route));
}

/** Write the answer key beside the transcript. Throws ApiError in the server's words (409 while unchecked). */
export async function saveAnswerKey(transcriptId: number, allowPartial: boolean): Promise<ReferenceWritten> {
  const route = `/api/transcripts/${transcriptId}/reference`;
  const { data, error, response } = await api.POST("/api/transcripts/{transcript_id}/reference", {
    params: { path: { transcript_id: String(transcriptId) } },
    body: { allow_partial: allowPartial },
  });
  if (data === undefined) throw new ApiError(fromBody(error, response, route));
  return data;
}

/**
 * Save the review after every change, as the edit list is saved (editing.ts
 * useSave): one request at a time, always the newest document. `flush`
 * resolves once what is on screen is saved, for leaving and for the answer
 * key, which the server builds from its own copy; it throws `NotSaved` when
 * the save failed. The document the review opened with is not sent until
 * something changes.
 */
export function useReviewSave(
  transcriptId: number,
  document: ReviewDocument,
): { state: SaveState; flush: () => Promise<void>; keep: () => void } {
  const [state, setState] = useState<SaveState>("saved");
  const latest = useRef(document);
  latest.current = document;
  const sent = useRef(document);
  const flying = useRef<Promise<boolean> | null>(null);

  const send = useCallback((): Promise<boolean> => {
    if (flying.current !== null) return flying.current;
    const run = (async () => {
      while (latest.current !== sent.current) {
        const next = latest.current;
        setState("saving");
        try {
          await putReview(transcriptId, next);
          sent.current = next;
        } catch (thrown) {
          setState("failed");
          showError(fromThrown(thrown, `/api/transcripts/${transcriptId}/review`));
          return false;
        }
      }
      setState("saved");
      return true;
    })().finally(() => {
      flying.current = null;
    });
    flying.current = run;
    return run;
  }, [transcriptId]);

  useEffect(() => {
    if (document === sent.current) return;
    const timer = setTimeout(() => void send(), SAVE_AFTER_MS);
    return () => clearTimeout(timer);
  }, [document, send]);

  /**
   * The page hidden or left (Task 14 re-review, R1-I1): send the newest
   * document at once with keepalive, not after the wait or behind a save in
   * flight. The ordinary save sends it again if the page lives on; a failure
   * here is left to that save to say.
   */
  const keep = useCallback(() => {
    if (latest.current === sent.current) return;
    putReview(transcriptId, latest.current, true).catch((thrown: unknown) => {
      console.warn("dsj ui: the review save sent as the page went away failed", thrown);
    });
  }, [transcriptId]);

  useEffect(() => {
    // Leaving with a change unsaved asks first, as the reader does, where the
    // browser asks at all (a desktop's; never iOS Safari).
    const leaving = (event: BeforeUnloadEvent) => {
      if (latest.current !== sent.current) event.preventDefault();
    };
    window.addEventListener("beforeunload", leaving);
    return () => window.removeEventListener("beforeunload", leaving);
  }, []);

  const flush = useCallback(async () => {
    if (!(await send())) throw new NotSaved("The review's latest changes are not saved.");
  }, [send]);
  return { state, flush, keep };
}
