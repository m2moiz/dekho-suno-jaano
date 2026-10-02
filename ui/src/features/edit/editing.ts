// A transcript's edit list on the page (#66): loaded once, held by an Editor,
// and saved after every change, without anything waiting on the save.

import { useEffect, useRef, useState, useSyncExternalStore } from "react";

import { api } from "@/api/client";
import { ApiError, fromBody, fromThrown, showError } from "@/features/errors/appError";
import { type Content, Editor } from "@/lib/editOps";

export type Editable = { editor: Editor; padS: number };

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
  if (data !== undefined) return { editor: new Editor(data.content), padS: data.pad_s };
  const detail = fromBody(error, response, route);
  // No word end times is a fact about the file, said under the title. Any
  // other refusal (a saved list that is broken, say) is a failure, shown.
  if (detail.error !== "TranscriptUnusable") showError(detail);
  return { reason: detail.message };
}

/** The editor's list as it is now, re-rendering on each change. */
export function useContent(editor: Editor): Content {
  return useSyncExternalStore(editor.subscribe, () => editor.content);
}

export type SaveState = "saved" | "saving" | "failed";

/**
 * Save the list after every change: one request at a time, the newest list
 * each time, so a burst of edits is never saved out of order. A drag (#85)
 * is saved once, when it ends.
 */
export function useSave(transcriptId: number, editor: Editor): SaveState {
  const [state, setState] = useState<SaveState>("saved");
  const pending = useRef(false);
  useEffect(() => {
    const route = `/api/transcripts/${transcriptId}/edits`;
    let sent: Content = editor.content;
    let flying = false;
    let live = true;
    const send = async (): Promise<void> => {
      flying = true;
      while (live && editor.content !== sent && !editor.inGesture) {
        const content = editor.content;
        setState("saving");
        try {
          const { error, response } = await api.PUT("/api/transcripts/{transcript_id}/edits", {
            params: { path: { transcript_id: String(transcriptId) } },
            body: { content: [...content] },
          });
          if (!response.ok) throw new ApiError(fromBody(error, response, route));
          sent = content;
        } catch (thrown) {
          flying = false;
          pending.current = false;
          if (live) {
            setState("failed");
            showError(fromThrown(thrown, route));
          }
          return;
        }
      }
      flying = false;
      pending.current = editor.content !== sent;
      if (live && !pending.current) setState("saved");
    };
    const changed = () => {
      pending.current = editor.content !== sent;
      if (!flying && pending.current && !editor.inGesture) void send();
    };
    // Leaving with a change unsaved asks first, as any editor does.
    const leaving = (event: BeforeUnloadEvent) => {
      if (pending.current) event.preventDefault();
    };
    window.addEventListener("beforeunload", leaving);
    const unsubscribe = editor.subscribe(changed);
    return () => {
      live = false;
      unsubscribe();
      window.removeEventListener("beforeunload", leaving);
    };
  }, [transcriptId, editor]);
  return state;
}
