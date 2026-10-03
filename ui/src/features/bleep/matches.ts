// The words to bleep (#84), as dsj.hatao.find found them on the server: the
// same matcher `dsj hatao` runs, phrases and all, never one written again here.

import { api } from "@/api/client";
import type { components } from "@/api/schema";
import { ApiError, fromBody } from "@/features/errors/appError";
import { type Content, itemsIn } from "@/lib/editOps";

export type Match = components["schemas"]["Match"];
export type Matches = components["schemas"]["Matches"];
export type WordAdded = components["schemas"]["WordAdded"];

/** Every word of `content` a word list spells. Throws ApiError in the server's words. */
export async function findMatches(transcriptId: number, content: Content): Promise<Matches> {
  const route = `/api/transcripts/${transcriptId}/matches`;
  const { data, error, response } = await api.POST("/api/transcripts/{transcript_id}/matches", {
    params: { path: { transcript_id: String(transcriptId) } },
    body: { content: [...content] },
  });
  if (data === undefined) throw new ApiError(fromBody(error, response, route));
  return data;
}

/** Put `word` in the user's own list, the file `dsj hatao` reads too. */
export async function addWord(word: string): Promise<WordAdded> {
  const { data, error, response } = await api.POST("/api/words", { body: { word } });
  if (data === undefined) throw new ApiError(fromBody(error, response, "/api/words"));
  return data;
}

/** Whether every word item of the match is muted: a match is muted, or it is dismissed. */
export function isMuted(content: Content, match: Match): boolean {
  let words = 0;
  for (const index of itemsIn(content, match.start, match.stop)) {
    const entry = content[index];
    if (entry?.kind !== "item" || entry.text === "") continue;
    words += 1;
    if (!entry.muted) return false;
  }
  return words > 0;
}

/** "1:05.3": where a match is, to the tenth of a second, so it can be found by ear. */
export function atLabel(seconds: number): string {
  const tenths = Math.round(seconds * 10);
  const m = Math.floor(tenths / 600);
  const s = ((tenths % 600) / 10).toFixed(1).padStart(4, "0");
  return `${m}:${s}`;
}
