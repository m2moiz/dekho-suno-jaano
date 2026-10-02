// The reply of GET /api/recordings, as dsj/ui/schemas.py defines it.
//
// Written by hand until #155 generates ui/src/api/schema.d.ts from those same
// models; then these two types become aliases of the generated ones, and a
// field renamed in Python becomes a type error here.

export type TranscriptRow = {
  id: number;
  finished_at: string;
  engine: string | null;
  model: string;
  diarized: boolean | null;
  speaker_count: number | null;
  mark_count: number | null;
  language: string | null;
};

export type RecordingRow = {
  id: number;
  path: string;
  missing: boolean;
  duration_s: number | null;
  video_codec: string | null;
  first_seen: string;
  transcripts: TranscriptRow[];
};
