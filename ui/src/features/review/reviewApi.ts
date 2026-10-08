// Review mode's requests (#248): the review document, saved as it changes,
// one change at a time (#251), and the answer key.

import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "@/api/client";
import type { components } from "@/api/schema";
import { KEEPALIVE_SHARE, keepaliveFits, NotSaved, Outdated, type SaveState } from "@/features/edit/editing";
import { ApiError, fromBody, fromThrown, inDoubt, showError } from "@/features/errors/appError";
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

/**
 * Save a review whole: once, for a review the server does not have yet, so
 * only if it still has none (`review_sha=none`). A tab that opened Review
 * before any review existed is refused 409 ReviewChanged rather than writing
 * over one another device made since (#251 fix round 1, I2). Answers its sha.
 */
async function putReview(transcriptId: number, document: ReviewDocument, keepalive: boolean): Promise<string> {
  const route = `/api/transcripts/${transcriptId}/review`;
  const { data, error, response } = await api.PUT("/api/transcripts/{transcript_id}/review", {
    params: { path: { transcript_id: String(transcriptId) }, query: { review_sha: "none" } },
    body: document,
    ...(keepalive ? { keepalive: true } : {}),
  });
  if (data === undefined) throw new ApiError(fromBody(error, response, route), response.status);
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
  if (data === undefined) throw new ApiError(fromBody(error, response, route), response.status);
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
      a.words_hash === b.words_hash &&
      a.flags.length === b.flags.length &&
      a.flags.every((flag, i) => flag === b.flags[i]))
  );
}

/**
 * Whether two reviews hold the same: segments, corrections, pass, cursor and
 * transcript. Not `updated_at`, which the server sets on each patch, nor
 * `started_at`, which a patch keeps from the review it patches.
 */
function sameReview(a: ReviewDocument, b: ReviewDocument): boolean {
  return (
    a.transcript_sha === b.transcript_sha &&
    a.review_pass === b.review_pass &&
    a.cursor_s === b.cursor_s &&
    a.segments.length === b.segments.length &&
    a.segments.every((segment, i) => sameSegment(segment, b.segments[i] as Segment)) &&
    JSON.stringify(a.corrections) === JSON.stringify(b.corrections)
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
  // Corrections are only ever added, so the server's are the first of the page's;
  // a change that removed or replaced one would be lost here, so it fails loudly (review Minor 8).
  if (was.corrections.some((c, i) => c !== next.corrections[i] && JSON.stringify(c) !== JSON.stringify(next.corrections[i]))) {
    throw new Error("A correction the server holds was changed or removed on the page; a patch only adds corrections.");
  }
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
 *
 * Each save waits first for the edit list's save in flight (`editsIdle`,
 * editing.ts useSave's `idle`), and none is sent once that list can no
 * longer save (#274, final review I2): a check saved while its correction is
 * refused would store the sentence as checked with words saved nowhere.
 */
export function useReviewSave(
  transcriptId: number,
  document: ReviewDocument,
  opened: { document: ReviewDocument | null; reviewSha: string | null },
  started: boolean,
  editsIdle: () => Promise<string | null> = () => Promise.resolve(null),
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
  const idleEdits = useRef(editsIdle);
  idleEdits.current = editsIdle;
  const flying = useRef<Promise<boolean> | null>(null);

  const saveOnce = useCallback(
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

  // A save whose fate is in doubt (#251 fix round 1, I1), as the edit list's
  // (editing.ts, useSave): its answer lost, a 5xx, or a ReviewChanged that may
  // be this page's own save landing with its answer lost. The review is read
  // once. Holding `next`, the save landed and its sha is taken; holding the
  // review before it (or none, for the creating save), it did not, and is sent
  // once more. Anything else was saved elsewhere, and only a reload helps.
  const save = useCallback(
    async (next: ReviewDocument) => {
      try {
        await saveOnce(next);
      } catch (thrown) {
        if (!inDoubt(thrown, "ReviewChanged")) throw thrown;
        const route = `/api/transcripts/${transcriptId}/review`;
        const read = await loadReview(transcriptId).catch(() => null);
        // Not readable either: the network is still down, and the ordinary failure says so.
        if (read === null) throw thrown;
        if (read.sha !== next.transcript_sha) {
          throw new ApiError({ error: "TranscriptChanged", message: "This transcript was made again while its review was open. Reload the page.", request: route });
        }
        const before = held.current?.document ?? null;
        const server = read.document;
        if (server !== null && read.reviewSha !== null && sameReview(server, next)) {
          held.current = { document: next, reviewSha: read.reviewSha };
          return;
        }
        const notLanded = before === null ? server === null : server !== null && sameReview(server, before);
        if (!notLanded) {
          if (thrown instanceof ApiError && thrown.detail.error === "ReviewChanged") throw thrown;
          throw new ApiError({
            error: "ReviewChanged",
            message: "This review was changed in another tab or window after this page loaded it, so this change was not saved. Reload the page to load it again.",
            request: route,
          });
        }
        if (before !== null && read.reviewSha !== null) held.current = { document: before, reviewSha: read.reviewSha };
        await saveOnce(next);
      }
    },
    [transcriptId, saveOnce],
  );

  const send = useCallback((): Promise<boolean> => {
    if (flying.current !== null) return flying.current;
    const run = (async () => {
      while (outdated.current === null && (latest.current !== sent.current || (held.current === null && begun.current))) {
        setState("saving");
        // The edit list's save in flight answers first; refused for good, the
        // review stops with it, and the edit list's own refusal is the one shown.
        const blocked = await idleEdits.current();
        if (blocked !== null) {
          outdated.current = blocked;
          setState("failed");
          return false;
        }
        const next = latest.current;
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
