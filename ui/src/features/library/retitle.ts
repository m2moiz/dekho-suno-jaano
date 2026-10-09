// Renaming a recording (Hashiya spec, Library: "renamable inline").

import { api } from "@/api/client";
import { ApiError, fromBody } from "@/features/errors/appError";
import type { RecordingRow } from "./types";

/** Give a recording a title; an empty one takes it away. Its row as the server now has it. */
export async function retitle(recordingId: number, title: string): Promise<RecordingRow> {
  const route = `/api/recordings/${recordingId}`;
  const { data, error, response } = await api.PATCH("/api/recordings/{recording_id}", {
    params: { path: { recording_id: String(recordingId) } },
    body: { title },
  });
  if (data === undefined) throw new ApiError(fromBody(error, response, route));
  return data;
}
