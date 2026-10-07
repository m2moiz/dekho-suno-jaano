// A transcript's edit list on the page (#66): loaded once, held by an Editor,
// and saved after every change, without anything waiting on the save.

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";

import { api } from "@/api/client";
import { ApiError, fromBody, fromThrown, showError } from "@/features/errors/appError";
import type { Names } from "@/features/transcript/speakers";
import { type Content, Editor } from "@/lib/editOps";
import { devCheck } from "@/lib/linter";

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
    return {
      editor: new Editor(data.content, { check: devCheck(data.content) }),
      padS: data.pad_s,
      renderable: new Latest<Renderable>({ spans: spansOf(data.spans), unrenderable: data.unrenderable }),
      names: new Latest<Names>(data.names),
      sha: data.transcript_sha,
      replaced: data.replaced,
    };
  }
  const detail = fromBody(error, response, route);
  // No word end times is a fact about the file, said under the title. Any
  // other refusal (a saved list that is broken, say) is a failure, shown.
  if (detail.error !== "TranscriptUnusable") showError(detail);
  return { reason: detail.message };
}

/** Save every speaker's name; the server's answer is what is kept. Throws ApiError in the server's words. */
export async function saveNames(transcriptId: number, names: Names): Promise<Names> {
  const route = `/api/transcripts/${transcriptId}/names`;
  const { data, error, response } = await api.PUT("/api/transcripts/{transcript_id}/names", {
    params: { path: { transcript_id: String(transcriptId) } },
    body: { names: { ...names } },
  });
  if (data === undefined) throw new ApiError(fromBody(error, response, route));
  return data.names;
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
   * Send what the server does not have yet at once, beside any save in flight,
   * with `keepalive` when it fits, so it outlives the page: for a page being
   * hidden or left (Task 14 re-review, R1-I1). Review calls it after putting
   * the box's words in the list; the hook does it by itself for the reader.
   */
  keep: () => void;
};

// The most a page may send with `keepalive` at once: the Fetch standard's
// 64 KiB limit on in-flight keepalive bodies (fetch, "inflight keepalive
// bytes"), not a measurement. A browser refuses a larger body outright, so a
// larger one goes as an ordinary request: that still lands when the page is
// only hidden (an app switch, a tab later evicted), not when it is torn down.
const KEEPALIVE_BYTES = 65_536;

/** Whether `body`, sent as JSON, fits under the browser's keepalive limit. */
export function keepaliveFits(body: unknown): boolean {
  return new TextEncoder().encode(JSON.stringify(body)).length <= KEEPALIVE_BYTES;
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

/** The list could not be brought up to date on the server, for the reason in the message. */
export class NotSaved extends Error {
  override name = "NotSaved";
}

/** The NotSaved that no retry can cure: the transcript was made again, and only a reload can (#249). */
export class Outdated extends NotSaved {
  override name = "Outdated";
}

/**
 * Save the list after every change: one request at a time, the newest list
 * each time, so a burst of edits is never saved out of order. A drag (#85)
 * is saved once, when it ends.
 */
/** The server's refusal of a save made against a transcript since made again (#249). */
const TRANSCRIPT_CHANGED = "TranscriptChanged";

export function useSave(transcriptId: number, { editor, renderable, sha }: Editable): Saving {
  const [state, setState] = useState<SaveState>("saved");
  const pending = useRef(false);
  const settling = useRef<() => Promise<void>>(() => Promise.resolve());
  const keeping = useRef<() => void>(() => undefined);
  useEffect(() => {
    const route = `/api/transcripts/${transcriptId}/edits`;
    let sent: Content = editor.content;
    let flight: Promise<boolean> | null = null;
    let live = true;
    // Set when the transcript was made again under the page: the server kept
    // what was sent aside, and every later save would be refused the same
    // way, so nothing more is sent until the page is reloaded.
    let outdated = false;
    const put = async (content: Content, keepalive: boolean) => {
      const body = { content: [...content], transcript_sha: sha };
      const { data, error, response } = await api.PUT("/api/transcripts/{transcript_id}/edits", {
        params: { path: { transcript_id: String(transcriptId) } },
        body,
        ...(keepalive && keepaliveFits(body) ? { keepalive: true } : {}),
      });
      if (data === undefined) throw new ApiError(fromBody(error, response, route));
      return data;
    };
    // True when the server has the list as it is now.
    const send = async (): Promise<boolean> => {
      while (live && !outdated && editor.content !== sent && !editor.inGesture) {
        const content = editor.content;
        setState("saving");
        try {
          const data = await put(content, false);
          sent = content;
          if (live) renderable.set({ spans: spansOf(data.spans), unrenderable: data.unrenderable });
        } catch (thrown) {
          pending.current = false;
          if (thrown instanceof ApiError && thrown.detail.error === TRANSCRIPT_CHANGED) {
            // What was sent is kept aside by the server, so leaving loses none
            // of it. Anything typed while it was in flight was not: that still
            // counts as unsaved, and leaving or reloading asks first.
            outdated = true;
            sent = content;
            pending.current = editor.content !== sent;
          }
          if (live) {
            setState("failed");
            showError(fromThrown(thrown, route));
          }
          return false;
        }
      }
      pending.current = editor.content !== sent;
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
      pending.current = editor.content !== sent;
      if (flight === null && pending.current && !editor.inGesture) void start();
    };
    settling.current = async () => {
      if (editor.inGesture) throw new NotSaved("Let go of the word you are dragging, then export.");
      const reload = "The transcript was made again since this page loaded. Reload the page.";
      if (outdated) throw new Outdated(reload);
      if (flight === null && editor.content === sent) return;
      if (!(await start())) {
        // The save just refused may be the one that found the transcript made again.
        if (outdated) throw new Outdated(reload);
        throw new NotSaved("Your latest changes are not saved, so the export would be out of date. Nothing was exported.");
      }
    };
    // The page hidden or left: what the server lacks goes now, with
    // keepalive, without waiting for a save in flight, which a page torn down
    // never finishes. The ordinary loop sends it again if the page lives on;
    // a list sent twice is the same list. A failure here is not shown: the
    // ordinary save says it, if the page is still there to say it.
    keeping.current = () => {
      if (outdated || editor.inGesture || editor.content === sent) return;
      put(editor.content, true).catch((thrown: unknown) => {
        console.warn("dsj ui: the save sent as the page went away failed", thrown);
      });
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
  }, [transcriptId, editor, renderable, sha]);
  const settle = useCallback(() => settling.current(), []);
  const keep = useCallback(() => keeping.current(), []);
  return { state, settle, keep };
}
