// The transcript as edited, downloaded from the reader's menu (#244):
// dsj likho's own SRT, WebVTT or text, worked out on the server from the edit
// list, so corrections and speaker names are in it. Fetched, not linked: a
// link sends no Authorization header, and only the media routes take the
// token in the query (#59).

import { api } from "@/api/client";
import { ApiError, fromBody } from "@/features/errors/appError";
import { MEDIA } from "@/features/library/title";

export type ExportFormat = "srt" | "vtt" | "txt";

/**
 * `title` as a file name: a recording's own extension dropped (talk.wav is
 * talk.srt, not talk.wav.srt), by the library's list of them, so a typed
 * "acme.com" or "Notes v1.2" keeps its dot. The characters Finder or a phone
 * refuses in one become a dot or a space, a control character a space, and a
 * leading dot, which would hide the file, goes.
 */
function fileStem(title: string): string {
  const stem = title
    .replace(MEDIA, "")
    .replace(/:/g, ".")
    .replace(/[/\\*?"<>|\u0000-\u001f\u007f]+/g, " ")
    .replace(/ {2,}/g, " ")
    .replace(/^[\s.]+/, "")
    .trim();
  return stem || "transcript";
}

export async function exportTranscript(transcriptId: number, format: ExportFormat, title: string): Promise<void> {
  const route = `/api/transcripts/${transcriptId}/export/${format}`;
  const { data, error, response } = await api.GET("/api/transcripts/{transcript_id}/export/{fmt}", {
    params: { path: { transcript_id: String(transcriptId), fmt: format } },
    parseAs: "text",
  });
  if (!response.ok) throw new ApiError(fromBody(error, response, route));
  // A transcript with no words exports an empty file, and the client reads an empty body as no data.
  const url = URL.createObjectURL(new Blob([data ?? ""], { type: "text/plain;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `${fileStem(title)}.${format}`;
  link.click();
  // Let the download start before the address goes.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
