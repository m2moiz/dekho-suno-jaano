// Marks on a recording (#67): a stretch in seconds, a kind, a note and the
// words under it when made, kept by the server on the recording
// (dsj/ui/routes/highlights.py), so they are there tomorrow and on every
// transcript of the recording. Seconds, not character positions: a
// correction keeps a word's time, and a re-run with the same words gives the
// same times, so a mark sits on the same words in both (#106, #83).

import { useCallback, useEffect, useState } from "react";

import { api } from "@/api/client";
import type { components } from "@/api/schema";
import { ApiError, fromBody } from "@/features/errors/appError";
import type { Words } from "@/features/transcript/document";
import type { MarkKind } from "@/registries/markKinds";

export type Mark = components["schemas"]["Highlight"];

// A word within this of a mark's edge counts as under it: the times are the
// recogniser's, to the millisecond, and a re-run can move one by less.
const EDGE_S = 0.02;

/** The words a mark covers: every word that starts before its end and ends after its start. */
export function wordsOfSpan(words: Words, startS: number, endS: number): number[] {
  const found: number[] = [];
  for (let i = 0; i < words.start.length; i += 1) {
    const start = words.start[i] ?? 0;
    const end = words.end[i] ?? start;
    if (start < endS - EDGE_S && end > startS + EDGE_S) found.push(i);
  }
  return found;
}

export async function loadMarks(recordingId: number): Promise<Mark[]> {
  const route = `/api/recordings/${recordingId}/highlights`;
  const { data, error, response } = await api.GET("/api/recordings/{recording_id}/highlights", {
    params: { path: { recording_id: String(recordingId) } },
  });
  if (data === undefined) throw new ApiError(fromBody(error, response, route));
  return data;
}

export async function addMark(recordingId: number, mark: { start_s: number; end_s: number; kind: MarkKind; text: string }): Promise<Mark> {
  const route = `/api/recordings/${recordingId}/highlights`;
  const { data, error, response } = await api.POST("/api/recordings/{recording_id}/highlights", {
    params: { path: { recording_id: String(recordingId) } },
    body: { ...mark, note: "" },
  });
  if (data === undefined) throw new ApiError(fromBody(error, response, route));
  return data;
}

export async function changeMark(markId: number, change: { kind?: MarkKind; note?: string }): Promise<Mark> {
  const route = `/api/highlights/${markId}`;
  const { data, error, response } = await api.PATCH("/api/highlights/{highlight_id}", {
    params: { path: { highlight_id: String(markId) } },
    body: change,
  });
  if (data === undefined) throw new ApiError(fromBody(error, response, route));
  return data;
}

export async function removeMark(markId: number): Promise<void> {
  const route = `/api/highlights/${markId}`;
  const { error, response } = await api.DELETE("/api/highlights/{highlight_id}", {
    params: { path: { highlight_id: String(markId) } },
  });
  if (!response.ok) throw new ApiError(fromBody(error, response, route));
}

/** The marks as Markdown with timestamps, the one export (README, Likho). */
export async function exportMarks(recordingId: number): Promise<string> {
  const route = `/api/recordings/${recordingId}/highlights.md`;
  const { data, error, response } = await api.GET("/api/recordings/{recording_id}/highlights.md", {
    params: { path: { recording_id: String(recordingId) } },
    parseAs: "text",
  });
  if (!response.ok) throw new ApiError(fromBody(error, response, route));
  return data ?? "";
}

export type Marks = {
  list: Mark[];
  add: (mark: { start_s: number; end_s: number; kind: MarkKind; text: string }) => Promise<Mark>;
  change: (markId: number, change: { kind?: MarkKind; note?: string }) => Promise<Mark>;
  remove: (markId: number) => Promise<void>;
};

/**
 * The recording's marks, read once and kept in step with every change made
 * here. A read that fails is an empty list with a console line: the
 * transcript must still open; a change that fails is said, through `onError`,
 * by the panel or the toolbar that asked for it.
 */
export function useMarks(recordingId: number): Marks {
  const [list, setList] = useState<Mark[]>([]);
  useEffect(() => {
    let live = true;
    loadMarks(recordingId).then(
      (found) => {
        if (live) setList(found);
      },
      (thrown: unknown) => {
        console.warn("dsj ui could not read the marks", thrown);
      },
    );
    return () => {
      live = false;
    };
  }, [recordingId]);
  const sort = (marks: Mark[]) => [...marks].sort((a, b) => a.start_s - b.start_s || a.end_s - b.end_s || a.id - b.id);
  const add = useCallback(
    async (mark: { start_s: number; end_s: number; kind: MarkKind; text: string }) => {
      const made = await addMark(recordingId, mark);
      setList((now) => sort([...now, made]));
      return made;
    },
    [recordingId],
  );
  const change = useCallback(async (markId: number, next: { kind?: MarkKind; note?: string }) => {
    const changed = await changeMark(markId, next);
    setList((now) => now.map((m) => (m.id === markId ? changed : m)));
    return changed;
  }, []);
  const remove = useCallback(async (markId: number) => {
    await removeMark(markId);
    setList((now) => now.filter((m) => m.id !== markId));
  }, []);
  return { list, add, change, remove };
}
