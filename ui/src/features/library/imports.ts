// Bringing a recording into the library, and finding a moved one again (#110).
//
// The page never sends a path, and is never told one: a browser gives a page a
// file's name, size and date, not where it lives (#127 trap 16). So each of
// these asks the server to open the Mac's own file dialog, and the server
// reads the file the person picks where it is, copying nothing. The request
// stays open for as long as the dialog does.

import { api } from "@/api/client";
import { ApiError, fromBody } from "@/features/errors/appError";
import type { RecordingRow } from "./types";

const IMPORT = "/api/recordings/import";

/** Ask for a file and add it. The library's row for it, or null when the dialog was cancelled. */
export async function importRecording(): Promise<RecordingRow | null> {
  const { data, error, response } = await api.POST(IMPORT);
  if (!response.ok) throw new ApiError(fromBody(error, response, IMPORT));
  return data ?? null;
}

/** Ask where a moved recording is now. Its row, re-pointed, or null when the dialog was cancelled. */
export async function relinkRecording(id: number): Promise<RecordingRow | null> {
  const { data, error, response } = await api.POST("/api/recordings/{recording_id}/relink", {
    params: { path: { recording_id: String(id) } },
  });
  if (!response.ok) throw new ApiError(fromBody(error, response, `/api/recordings/${id}/relink`));
  return data ?? null;
}
