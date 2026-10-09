// A transcript's edit list on the page (#66): loaded once, held by an Editor,
// and saved after every change, without anything waiting on the save.

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";

import { api } from "@/api/client";
import { ApiError, fromBody, fromThrown, inDoubt, showError } from "@/features/errors/appError";
import type { Names } from "@/features/transcript/speakers";
import { type Content, Editor, type Entry } from "@/lib/editOps";
import { devCheck } from "@/lib/linter";
import { sameEntry, spliceOf } from "@/lib/splice";

/** A stretch of the recording to silence, in seconds: [start, end). */
export type Span = readonly [number, number];

/** What a render of the list as last saved would silence, or why it cannot be rendered. */
export type Renderable = { spans: readonly Span[] | null; unrenderable: string | null };

/** One value that changes, and the listeners told when it does: React reads it through useLatest. */
export class Latest<T> {
  private listeners = new Set<() => void>();
  private current: T;
  constructor(current: T) {
    this.current = current;
  }
  get value(): T {
    return this.current;
  }
  set(next: T): void {
    this.current = next;
    for (const listener of this.listeners) listener();
  }
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };
}

export function useLatest<T>(latest: Latest<T>): T {
  return useSyncExternalStore(latest.subscribe, () => latest.value);
}

/** The server's spans, each a [start, end] pair in its JSON. */
function spansOf(raw: number[][] | null): Span[] | null {
  return raw === null ? null : raw.map(([start = 0, end = 0]) => [start, end] as const);
}

export type Editable = {
  editor: Editor;
  padS: number;
  /**
   * The spans dsj.hatao.spans_to_mute gives the list as last saved (#84),
   * from the server's reply to each save: the page never works them out
   * itself, so its preview mutes what a render mutes.
   */
  renderable: Latest<Renderable>;
  /** The speakers' names, by label (#243), as last saved. */
  names: Latest<Names>;
  /**
   * The sha of the transcript the list was loaded against, sent back with
   * every save: the server refuses a save made against a transcript since
   * made again (#249) instead of trusting old words over new ones.
   */
  sha: string;
  /** Why a saved list was put aside and this one built fresh (#249), or null. */
  replaced: string | null;
  /**
   * The list as the server holds it, and its sha (#251): each save sends
   * only what differs from `content`, made against `listSha`, and useSave
   * moves both on with every answer. Kept here, not in the hook, so a hook
   * mounted again (StrictMode) starts from the server's copy, not the page's.
   */
  saved: { content: Content; listSha: string };
};

/**
 * The transcript's edit list, or the server's reason it has none. Either way
 * the transcript still reads: a list that cannot be opened costs the editing,
 * not the reading.
 */
export async function loadEditable(transcriptId: number): Promise<Editable | { reason: string }> {
  const route = `/api/transcripts/${transcriptId}/edits`;
  const { data, error, response } = await api.GET("/api/transcripts/{transcript_id}/edits", {
    params: { path: { transcript_id: String(transcriptId) } },
  });
  if (data !== undefined) {
    // Checked after every edit in development builds (#86).
    const editor = new Editor(data.content, { check: devCheck(data.content) });
    return {
      editor,
      padS: data.pad_s,
      renderable: new Latest<Renderable>({ spans: spansOf(data.spans), unrenderable: data.unrenderable }),
      names: new Latest<Names>(data.names),
      sha: data.transcript_sha,
      replaced: data.replaced,
      saved: { content: editor.content, listSha: data.list_sha },
    };
  }
  const detail = fromBody(error, response, route);
  // No word end times is a fact about the file, said under the title. Any
  // other refusal (a saved list that is broken, say) is a failure, shown.
  if (detail.error !== "TranscriptUnusable") showError(detail);
  return { reason: detail.message };
}

/**
 * Save every speaker's name; the server's answer is what is kept, with the
 * list's new sha, since names are part of the list (#251). Made against the
 * list `listSha` names and the transcript `sha` names, and refused 409 as a
 * patch is when either has changed (#274, final review C1). Throws ApiError
 * in the server's words. Called through useSave's `rename`, in turn with the
 * list's own saves.
 */
async function saveNames(transcriptId: number, names: Names, sha: string, listSha: string): Promise<{ names: Names; listSha: string }> {
  const route = `/api/transcripts/${transcriptId}/names`;
  const { data, error, response } = await api.PUT("/api/transcripts/{transcript_id}/names", {
    params: { path: { transcript_id: String(transcriptId) } },
    body: { names: { ...names }, transcript_sha: sha, list_sha: listSha },
  });
  if (data === undefined) throw new ApiError(fromBody(error, response, route), response.status);
  return { names: data.names, listSha: data.list_sha };
}

/** The names as the server keeps them (dsj/ui/edits.py save_names): trimmed, a blank one left out. */
function keptNames(names: Names): Names {
  return Object.fromEntries(
    Object.entries(names)
      .map(([label, name]) => [label, name.trim()] as const)
      .filter(([, name]) => name !== ""),
  );
}

function sameNames(a: Names, b: Names): boolean {
  const keys = Object.keys(a);
  return keys.length === Object.keys(b).length && keys.every((label) => a[label] === b[label]);
}

/** The editor's list as it is now, re-rendering on each change. */
export function useContent(editor: Editor): Content {
  return useSyncExternalStore(editor.subscribe, () => editor.content);
}

export type SaveState = "saved" | "saving" | "failed";

/** What `useSave` gives back: where the save stands, and a way to wait for it. */
export type Saving = {
  state: SaveState;
  /**
   * Resolve once the server holds the list as it is now: wait for the save in
   * flight, or start one for a change not yet sent or one that failed. Throws
   * `NotSaved` instead of resolving while a drag is under way or when the save
   * fails, so nothing reads the server's copy while it is behind the page's.
   */
  settle: () => Promise<void>;
  /**
   * Send what the server does not have yet now, for a page being hidden or
   * left (Task 14 re-review, R1-I1): every save small enough goes with
   * `keepalive`, so it outlives the page. Behind a save in flight it waits
   * for that save's answer, which names the list it is made against (#251).
   * Review calls it; the hook does it by itself for the reader.
   */
  keep: () => void;
  /**
   * Save every speaker's name (#243), in turn with the list's saves: a name is
   * part of the list, so a patch sent beside a rename would be made against a
   * list the server no longer holds (#251). Resolves to the names kept.
   */
  rename: (names: Names) => Promise<Names>;
  /**
   * Why nothing more saves until the page is reloaded (the transcript made
   * again, #249, or the list changed in another tab, #251), or null. Review
   * stops its own save on it (#274, final review I2).
   */
  outdated: string | null;
  /**
   * Resolve once no save or rename of the list is in flight, to `outdated` as
   * it is then. Never starts a save and never throws: Review waits on it
   * before each save of its own, so a check is never saved beside a
   * correction the server is about to refuse (#274, I2).
   */
  idle: () => Promise<string | null>;
};

// The most a page may send with `keepalive` at once: the Fetch standard's
// 64 KiB limit on in-flight keepalive bodies (fetch, "inflight keepalive
// bytes"), not a measurement. A browser refuses a larger body outright, so a
// larger one goes as an ordinary request: that still lands when the page is
// only hidden (an app switch, a tab later evicted), not when it is torn down.
const KEEPALIVE_BYTES = 65_536;

// The edit list and the review each have at most one save in flight, so each
// may take half the limit above, and two at once never go over it (a request
// over it fails outright). A correction's patch is far under it (#251).
export const KEEPALIVE_SHARE = KEEPALIVE_BYTES / 2;

/** Whether `body`, sent as JSON, fits under the browser's keepalive limit, or under `limit`. */
export function keepaliveFits(body: unknown, limit = KEEPALIVE_BYTES): boolean {
  return new TextEncoder().encode(JSON.stringify(body)).length <= limit;
}

/**
 * Call `onHide` when the page is hidden or left: `visibilitychange` to hidden
 * (an app switch, after which a phone may evict the tab) and `pagehide` (a
 * swipe back, a reload, a close). A phone gives nothing else: iOS Safari never
 * fires `beforeunload`, which is only a question anyway, never a save.
 */
export function onPageHide(onHide: () => void): () => void {
  const hidden = () => {
    if (document.visibilityState === "hidden") onHide();
  };
  document.addEventListener("visibilitychange", hidden);
  window.addEventListener("pagehide", onHide);
  return () => {
    document.removeEventListener("visibilitychange", hidden);
    window.removeEventListener("pagehide", onHide);
  };
}

/**
 * The list could not be brought up to date on the server, for the reason in
 * the message. `reason` is the last save's own refusal, when one was seen, for
 * a caller whose message stands in for it in the one error dialog.
 */
export class NotSaved extends Error {
  override name = "NotSaved";
  readonly reason: string | null;
  constructor(message: string, reason: string | null = null) {
    super(message);
    this.reason = reason;
  }
}

/**
 * The NotSaved that no retry can cure, only a reload: the transcript was made
 * again (#249), or the list was changed in another tab (#251).
 */
export class Outdated extends NotSaved {
  override name = "Outdated";
}

/** The server's refusal of a save made against a transcript since made again (#249). */
const TRANSCRIPT_CHANGED = "TranscriptChanged";
/** The server's refusal of a patch made against a list changed since, in another tab (#251). */
const LIST_CHANGED = "ListChanged";

/** Whether two edit lists hold the same entries, by the fields the file holds. */
function sameList(a: readonly Entry[], b: readonly Entry[]): boolean {
  return a.length === b.length && a.every((entry, i) => sameEntry(entry, b[i] as Entry));
}

/**
 * Save the list after every change, one request at a time, so a burst of
 * edits is never saved out of order. Each save is a patch (#251): only the
 * entries between what the server holds and the list now, made against the
 * sha of the list the server holds, which each answer moves on. So no two
 * patches are ever made against the same list. A drag (#85) is saved once,
 * when it ends.
 */
export function useSave(transcriptId: number, { editor, renderable, sha, saved, names }: Editable): Saving {
  const [state, setState] = useState<SaveState>("saved");
  const [outdatedNow, setOutdatedNow] = useState<string | null>(null);
  const pending = useRef(false);
  const settling = useRef<() => Promise<void>>(() => Promise.resolve());
  const keeping = useRef<() => void>(() => undefined);
  const renaming = useRef<(names: Names) => Promise<Names>>(() => Promise.reject(new NotSaved("The page is not ready yet.")));
  const idling = useRef<() => Promise<string | null>>(() => Promise.resolve(null));
  useEffect(() => {
    const route = `/api/transcripts/${transcriptId}/edits`;
    let flight: Promise<boolean> | null = null;
    let live = true;
    // Set, to the sentence settle throws, once no save can succeed until the
    // page is reloaded: the transcript was made again (#249), or the list was
    // changed in another tab (#251). Every later save would be refused the
    // same way, so nothing more is sent.
    let outdated: string | null = null;
    const goOutdated = (reason: string) => {
      outdated = reason;
      if (live) setOutdatedNow(reason);
    };
    // Why the last save failed, in the server's words, until one succeeds.
    let failure: string | null = null;
    // Every request that changes the list on the server, one after another,
    // each made once the one before has answered (#251).
    let turn: Promise<unknown> = Promise.resolve();
    const inTurn = <T>(job: () => Promise<T>): Promise<T> => {
      const run = turn.then(job);
      turn = run.catch(() => undefined);
      return run;
    };
    // The list as it is now, whole: only to be kept aside by the server when
    // the transcript was made again under the page (#249).
    const putWhole = async (content: Content) => {
      const body = { content: [...content], transcript_sha: sha };
      const { data, error, response } = await api.PUT("/api/transcripts/{transcript_id}/edits", {
        params: { path: { transcript_id: String(transcriptId) } },
        body,
        ...(keepaliveFits(body, KEEPALIVE_SHARE) ? { keepalive: true } : {}),
      });
      if (data === undefined) throw new ApiError(fromBody(error, response, route));
      return data;
    };
    // What differs between the server's list and `content`, made against the
    // server's list, with keepalive when it fits: so a commit a moment before
    // the page dies still lands (#251).
    const patchOnce = async (content: Content) => {
      const change = spliceOf(saved.content, content, sameEntry);
      if (change === null) {
        saved.content = content;
        return;
      }
      const body = { transcript_sha: sha, list_sha: saved.listSha, start: change.start, delete: change.delete, insert: change.insert };
      const { data, error, response } = await api.PATCH("/api/transcripts/{transcript_id}/edits", {
        params: { path: { transcript_id: String(transcriptId) } },
        body,
        ...(keepaliveFits(body, KEEPALIVE_SHARE) ? { keepalive: true } : {}),
      });
      if (data === undefined) throw new ApiError(fromBody(error, response, route), response.status);
      saved.content = content;
      saved.listSha = data.list_sha;
      if (live) renderable.set({ spans: spansOf(data.spans), unrenderable: data.unrenderable });
    };
    // A patch whose fate is in doubt (#251 fix round 1, I1): its answer lost,
    // a 5xx, or a ListChanged that may be this page's own patch landing with
    // its answer lost. The list is read once and compared with what the page
    // holds. Holding `content`, the patch landed: its sha is taken and the
    // queue goes on. Holding the list before it, it did not: it is sent once
    // more. Anything else is a change made elsewhere, and only a reload helps.
    // Within the patch's own turn, so no other save goes between.
    const patch = async (content: Content) => {
      try {
        await patchOnce(content);
      } catch (thrown) {
        if (!inDoubt(thrown, LIST_CHANGED)) throw thrown;
        const read = await api
          .GET("/api/transcripts/{transcript_id}/edits", { params: { path: { transcript_id: String(transcriptId) } } })
          .catch(() => null);
        // Not readable either: the network is still down, and the ordinary failure says so.
        const data = read?.data;
        if (data === undefined) throw thrown;
        if (data.transcript_sha !== sha) {
          throw new ApiError({ error: TRANSCRIPT_CHANGED, message: "This transcript was made again while it was open. Reload the page.", request: route });
        }
        const landed = sameList(data.content, content);
        if (!landed && !sameList(data.content, saved.content)) {
          if (thrown instanceof ApiError && thrown.detail.error === LIST_CHANGED) throw thrown;
          throw new ApiError({
            error: LIST_CHANGED,
            message: "This transcript's edits were changed in another tab or window after this page loaded them, so this change was not saved. Reload the page to load them again.",
            request: route,
          });
        }
        // A rename whose answer was lost is the server's too: its names are taken with its sha.
        saved.listSha = data.list_sha;
        if (live) names.set(data.names);
        if (landed) {
          saved.content = content;
          if (live) renderable.set({ spans: spansOf(data.spans), unrenderable: data.unrenderable });
          return;
        }
        await patchOnce(content);
      }
    };
    // The transcript was made again under the page: the patch kept nothing,
    // so the whole list goes, for the server to keep aside under its own
    // name (#249); its refusal says where, and is the one shown.
    const keepAside = async (content: Content, refusal: unknown): Promise<unknown> => {
      try {
        await putWhole(content);
        return refusal;
      } catch (thrown) {
        return thrown;
      }
    };
    // True when the server has the list as it is now.
    const send = async (): Promise<boolean> => {
      while (live && outdated === null && editor.content !== saved.content && !editor.inGesture) {
        const content = editor.content;
        setState("saving");
        try {
          await inTurn(() => patch(content));
          failure = null;
        } catch (thrown) {
          let shown = thrown;
          if (thrown instanceof ApiError && thrown.detail.error === TRANSCRIPT_CHANGED) {
            // What was sent is kept aside by the server, so leaving loses none
            // of it. Anything typed while it was in flight was not: that still
            // counts as unsaved, and leaving or reloading asks first.
            goOutdated("The transcript was made again since this page loaded. Reload the page.");
            shown = await keepAside(content, thrown);
            saved.content = content;
          } else if (thrown instanceof ApiError && thrown.detail.error === LIST_CHANGED) {
            // Another tab saved the list since: this change is not saved
            // anywhere, so leaving still asks. Review's box keeps its own
            // copy in the browser (draft.ts) for after the reload.
            goOutdated("This transcript's edits were changed in another tab. Reload the page.");
          }
          pending.current = editor.content !== saved.content;
          if (live) {
            setState("failed");
            failure = fromThrown(shown, route).message;
            showError(fromThrown(shown, route));
          }
          return false;
        }
      }
      pending.current = editor.content !== saved.content;
      if (live && !pending.current) setState("saved");
      return !pending.current;
    };
    const start = (): Promise<boolean> => {
      flight ??= send().finally(() => {
        flight = null;
      });
      return flight;
    };
    const changed = () => {
      pending.current = editor.content !== saved.content;
      if (flight === null && pending.current && !editor.inGesture) void start();
    };
    settling.current = async () => {
      if (editor.inGesture) throw new NotSaved("Let go of the word you are dragging, then export.");
      if (outdated !== null) throw new Outdated(outdated);
      if (flight === null && editor.content === saved.content) return;
      if (!(await start())) {
        // The save just refused may be the one that found the transcript made again.
        if (outdated !== null) throw new Outdated(outdated);
        throw new NotSaved("Your latest changes are not saved, so the export would be out of date. Nothing was exported.", failure);
      }
    };
    // The page hidden or left: what the server lacks goes now, a save that
    // failed tried again. Every save small enough already goes with
    // keepalive, so the one in flight outlives the page; a change made behind
    // it waits for its answer, which names the list the next is made against
    // (#251). Sending it beside the one in flight, as before #251, would make
    // two patches against one list. The window that leaves is one small
    // request's round trip. Review's box words are covered across it by the
    // draft (draft.ts), cleared only once the list is saved; a reader edit or
    // a check made in that window is not (Task 15c review, Minor 2).
    keeping.current = () => {
      if (outdated === null && !editor.inGesture && editor.content !== saved.content) void start();
    };
    // A rename made against the list the server holds, which its answer moves
    // on (#274, final review C1). Before, a rename was unguarded and the page
    // took the sha it answered while holding the list from before another
    // tab's patch, so its next patch was spliced into a list of another shape.
    const renameOnce = async (next: Names): Promise<Names> => {
      const kept = await saveNames(transcriptId, next, sha, saved.listSha);
      saved.listSha = kept.listSha;
      return kept.names;
    };
    // A rename whose fate is in doubt is resolved as a patch's is: the list is
    // read once. With this page's words and the names asked for, it landed and
    // its sha is taken; with this page's words and names, it did not and is
    // sent once more. Anything else was changed elsewhere: only a reload helps.
    const renameResolved = async (next: Names): Promise<Names> => {
      try {
        return await renameOnce(next);
      } catch (thrown) {
        if (!inDoubt(thrown, LIST_CHANGED)) throw thrown;
        const route = `/api/transcripts/${transcriptId}/names`;
        const read = await api
          .GET("/api/transcripts/{transcript_id}/edits", { params: { path: { transcript_id: String(transcriptId) } } })
          .catch(() => null);
        const data = read?.data;
        if (data === undefined) throw thrown;
        if (data.transcript_sha !== sha) {
          throw new ApiError({ error: TRANSCRIPT_CHANGED, message: "This transcript was made again while it was open. Reload the page.", request: route });
        }
        const mine = sameList(data.content, saved.content);
        if (mine && sameNames(data.names, keptNames(next))) {
          saved.listSha = data.list_sha;
          return data.names;
        }
        if (!mine || !sameNames(data.names, names.value)) {
          if (thrown instanceof ApiError && thrown.detail.error === LIST_CHANGED) throw thrown;
          throw new ApiError({
            error: LIST_CHANGED,
            message: "This transcript's edits were changed in another tab or window after this page loaded them, so these names were not saved. Reload the page to load them again.",
            request: route,
          });
        }
        saved.listSha = data.list_sha;
        return await renameOnce(next);
      }
    };
    renaming.current = (next: Names) => {
      if (outdated !== null) return Promise.reject(new Outdated(outdated));
      return inTurn(async () => {
        try {
          const kept = await renameResolved(next);
          names.set(kept);
          return kept;
        } catch (thrown) {
          if (thrown instanceof ApiError && thrown.detail.error === TRANSCRIPT_CHANGED) {
            goOutdated("The transcript was made again since this page loaded. Reload the page.");
          } else if (thrown instanceof ApiError && thrown.detail.error === LIST_CHANGED) {
            goOutdated("This transcript's edits were changed in another tab. Reload the page.");
          }
          throw thrown;
        }
      });
    };
    idling.current = async () => {
      await flight;
      await turn;
      return outdated;
    };
    // Leaving with a change unsaved asks first, as any editor does, where the
    // browser asks at all (a desktop's; never iOS Safari).
    const leaving = (event: BeforeUnloadEvent) => {
      if (pending.current) event.preventDefault();
    };
    window.addEventListener("beforeunload", leaving);
    const stopHiding = onPageHide(() => keeping.current());
    const unsubscribe = editor.subscribe(changed);
    return () => {
      live = false;
      unsubscribe();
      window.removeEventListener("beforeunload", leaving);
      stopHiding();
    };
    // Every value here is fixed for one load of the list. Were the effect to run
    // again with a save in flight, the new `turn` would not wait for the old
    // one, and two patches could be made against one sha (Task 15c review, Minor 7).
  }, [transcriptId, editor, renderable, sha, saved, names]);
  const settle = useCallback(() => settling.current(), []);
  const keep = useCallback(() => keeping.current(), []);
  const rename = useCallback((next: Names) => renaming.current(next), []);
  const idle = useCallback(() => idling.current(), []);
  return { state, settle, keep, rename, outdated: outdatedNow, idle };
}
