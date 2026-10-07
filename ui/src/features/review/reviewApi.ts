// Review mode's requests (#248): the review document, saved as it changes,
// one change at a time (#251), and the answer key.

import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "@/api/client";
import type { components } from "@/api/schema";
import { KEEPALIVE_SHARE, keepaliveFits, NotSaved, Outdated, type SaveState } from "@/features/edit/editing";
import { ApiError, fromBody, fromThrown, showError } from "@/features/errors/appError";
import { spliceOf } from "@/lib/splice";
import type { CurrentSha, ReviewDocument, Segment } from "./model";

export type ReferenceWritten = components["schemas"]["ReferenceWritten"];
type ReviewPatch = components["schemas"]["ReviewPatch"];

// A short wait before saving, so a run of Enter presses is one request, not
// one each. A choice, not measured: under the gap between two checks.
const SAVE_AFTER_MS = 400;

/** The server's refusals no retry cures, only a reload: the transcript made again (#249), the review changed in another tab (#251). */
const RELOAD_ONLY = new Set(["TranscriptChanged", "ReviewChanged"]);

/**
 * The transcript's review, or null; the sha of the transcript as it is now,
 * the one a review is saved under; and the review's own sha, which its first
 * patch is made against (#251).
 */
export async function loadReview(
  transcriptId: number,
): Promise<{ document: ReviewDocument | null; sha: CurrentSha; reviewSha: string | null }> {
  const route = `/api/transcripts/${transcriptId}/review`;
  const { data, error, response } = await api.GET("/api/transcripts/{transcript_id}/review", {
    params: { path: { transcript_id: String(transcriptId) } },
  });
  if (data === undefined) throw new ApiError(fromBody(error, response, route));
  // The one place a CurrentSha is made (model.ts): the server's word for the transcript now.
  return { document: data.document, sha: data.transcript_sha as CurrentSha, reviewSha: data.review_sha };
}

/** Save a review whole: once, for a review the server does not have yet. Answers its sha. */
async function putReview(transcriptId: number, document: ReviewDocument, keepalive: boolean): Promise<string> {
  const route = `/api/transcripts/${transcriptId}/review`;
  const { data, error, response } = await api.PUT("/api/transcripts/{transcript_id}/review", {
    params: { path: { transcript_id: String(transcriptId) } },
    body: document,
    ...(keepalive ? { keepalive: true } : {}),
  });
  if (data === undefined) throw new ApiError(fromBody(error, response, route));
  return data.review_sha;
}

/** Save one change to the review, made against the review `body.review_sha` names (#251). Answers the new sha. */
async function patchReview(transcriptId: number, body: ReviewPatch, keepalive: boolean): Promise<string> {
  const route = `/api/transcripts/${transcriptId}/review`;
  const { data, error, response } = await api.PATCH("/api/transcripts/{transcript_id}/review", {
    params: { path: { transcript_id: String(transcriptId) } },
    body,
    ...(keepalive ? { keepalive: true } : {}),
  });
  if (data === undefined) throw new ApiError(fromBody(error, response, route));
  return data.review_sha;
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

/** Two segments are the same when every field the review holds is equal. */
function sameSegment(a: Segment, b: Segment): boolean {
  return (
    a === b ||
    (a.start === b.start &&
      a.end === b.end &&
      a.state === b.state &&
      a.speaker === b.speaker &&
      a.edited === b.edited &&
      a.flags.length === b.flags.length &&
      a.flags.every((flag, i) => flag === b.flags[i]))
  );
}

/** The review as the server holds it: what the next patch is worked out from and made against (#251). */
type Held = { document: ReviewDocument; reviewSha: string };

/**
 * The patch that turns the server's review into `next`, or null when they
 * hold the same: its segments spliced (splice.ts), the corrections made since
 * appended (a review's corrections are only ever added to), the pass, the
 * cursor and the transcript sha as `next` has them.
 */
function patchOf(held: Held, next: ReviewDocument): ReviewPatch | null {
  const was = held.document;
  const change = spliceOf(was.segments, next.segments, sameSegment);
  const corrections = next.corrections.slice(was.corrections.length);
  const same =
    change === null &&
    corrections.length === 0 &&
    was.review_pass === next.review_pass &&
    was.cursor_s === next.cursor_s &&
    was.transcript_sha === next.transcript_sha;
  if (same) return null;
  return {
    transcript_sha: next.transcript_sha,
    review_sha: held.reviewSha,
    start: change?.start ?? 0,
    delete: change?.delete ?? 0,
    insert: change?.insert ?? [],
    corrections,
    review_pass: next.review_pass,
    cursor_s: next.cursor_s,
  };
}

/**
 * Save the review after every change, as the edit list is saved (editing.ts
 * useSave): one request at a time, each a patch of what changed since the
 * last answer, made against the sha that answer gave (#251), with keepalive
 * when it fits its share. `flush` resolves once what is on screen is saved,
 * for leaving and for the answer key, which the server builds from its own
 * copy; it throws `NotSaved` when the save failed, `Outdated` when only a
 * reload can help.
 *
 * A review the server does not have yet is saved whole once, as soon as a
 * pass is picked (`started`): on a 2.5 h transcript that is about 142 KB
 * (#251, measured), better sent then than by the first check, and every
 * later save is a patch against it. Picking nothing saves nothing. The
 * document a saved review opened with is not sent until something changes.
 */
export function useReviewSave(
  transcriptId: number,
  document: ReviewDocument,
  opened: { document: ReviewDocument | null; reviewSha: string | null },
  started: boolean,
): { state: SaveState; flush: () => Promise<void>; keep: () => void } {
  const [state, setState] = useState<SaveState>("saved");
  const latest = useRef(document);
  latest.current = document;
  const sent = useRef(document);
  const begun = useRef(started);
  begun.current = started;
  const held = useRef<Held | null>(
    opened.document === null || opened.reviewSha === null ? null : { document: opened.document, reviewSha: opened.reviewSha },
  );
  // Set, to the sentence flush throws, once no save can succeed until the page is reloaded.
  const outdated = useRef<string | null>(null);
  const flying = useRef<Promise<boolean> | null>(null);

  const save = useCallback(
    async (next: ReviewDocument) => {
      const was = held.current;
      if (was === null) {
        held.current = { document: next, reviewSha: await putReview(transcriptId, next, keepaliveFits(next, KEEPALIVE_SHARE)) };
        return;
      }
      const body = patchOf(was, next);
      if (body === null) return;
      held.current = { document: next, reviewSha: await patchReview(transcriptId, body, keepaliveFits(body, KEEPALIVE_SHARE)) };
    },
    [transcriptId],
  );

  const send = useCallback((): Promise<boolean> => {
    if (flying.current !== null) return flying.current;
    const run = (async () => {
      while (outdated.current === null && (latest.current !== sent.current || (held.current === null && begun.current))) {
        const next = latest.current;
        setState("saving");
        try {
          await save(next);
          sent.current = next;
        } catch (thrown) {
          if (thrown instanceof ApiError && RELOAD_ONLY.has(thrown.detail.error)) {
            // Every later patch would be refused the same way: nothing more is sent.
            outdated.current = thrown.detail.message;
          }
          setState("failed");
          showError(fromThrown(thrown, `/api/transcripts/${transcriptId}/review`));
          return false;
        }
      }
      if (outdated.current !== null) return false;
      setState("saved");
      return true;
    })().finally(() => {
      flying.current = null;
    });
    flying.current = run;
    return run;
  }, [transcriptId, save]);

  useEffect(() => {
    if (document === sent.current) return;
    const timer = setTimeout(() => void send(), SAVE_AFTER_MS);
    return () => clearTimeout(timer);
  }, [document, send]);

  // A pass picked on a review the server does not have: it is saved whole now.
  useEffect(() => {
    if (started && held.current === null) void send();
  }, [started, send]);

  /**
   * The page hidden or left (Task 14 re-review, R1-I1): send the newest
   * document now, not after the wait. Behind a save in flight it follows that
   * save's answer, which names the review it is made against (#251); each
   * goes with keepalive when it fits. A failure here is left to the ordinary
   * save to say.
   */
  const keep = useCallback(() => {
    void send();
  }, [send]);

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
    if (await send()) return;
    if (outdated.current !== null) throw new Outdated(outdated.current);
    throw new NotSaved("The review's latest changes are not saved.");
  }, [send]);
  return { state, flush, keep };
}
