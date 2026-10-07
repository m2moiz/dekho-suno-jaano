// The words the library page uses for each value. Three of them carry a
// distinction the page must not flatten (#156): "speakers not labelled" is not
// "1 speaker", an engine nobody recorded is "unknown", and a dekho scan that
// never ran is not "0 marks".

import type { TranscriptRow } from "./types";

function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

export function speakersLabel(t: TranscriptRow): string {
  if (t.diarized === false) return "speakers not labelled";
  if (t.diarized === null) return "speaker labels unknown";
  return t.speaker_count === null ? "speakers labelled" : plural(t.speaker_count, "speaker", "speakers");
}

export function engineLabel(t: TranscriptRow): string {
  return t.engine ?? "unknown";
}

export function marksLabel(t: TranscriptRow): string {
  return t.mark_count === null ? "not scanned for marks" : plural(t.mark_count, "mark", "marks");
}

/** "2 Oct 2026, 18:05" in this Mac's own time zone. */
export function whenLabel(iso: string, locale?: string): string {
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return iso;
  return new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(when);
}

/** "1:02:05" or "4:09"; nothing when the length is not known. */
export function durationLabel(seconds: number | null): string | null {
  if (seconds === null) return null;
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = String(total % 60).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

/** "356 MB" in the Mac's own units, as Finder writes them (1 MB is 1,000,000 bytes). */
export function sizeLabel(bytes: number | null): string | null {
  if (bytes === null) return null;
  if (bytes < 1000) return `${bytes} bytes`;
  const [unit, scale] = bytes < 1e6 ? ["KB", 1e3] : bytes < 1e9 ? ["MB", 1e6] : ["GB", 1e9];
  const value = bytes / scale;
  return `${value < 10 ? value.toFixed(1) : Math.round(value)} ${unit}`;
}

/** The file's own name: the last part of the path it was last seen at. */
export function fileName(path: string): string {
  return path.split("/").filter(Boolean).pop() ?? path;
}

// The picture codecs both browser engines drew, measured on 2026-10-02 in
// Playwright's Chromium and WebKit on four-second files ffmpeg made (#110):
// h264 and vp9. hevc and prores drew only in WebKit, and av1 only in Chromium;
// WebKit refused an av1 file outright, sound and all. Not real Safari (#57 F6).
const DRAWN_EVERYWHERE = new Set(["h264", "vp9"]);

/** What to say about a recording whose picture some browsers cannot draw, or null. */
export function pictureNote(videoCodec: string | null): string | null {
  if (videoCodec === null || DRAWN_EVERYWHERE.has(videoCodec)) return null;
  return `Its picture (${videoCodec}) does not show in every browser. Its sound always plays.`;
}

/** "2 Oct 2026, 18:05 · whisper": how the version picker tells one transcript of a recording from another. */
export function versionLabel(t: TranscriptRow): string {
  return `${whenLabel(t.finished_at)} · ${t.engine ?? "unknown engine"}`;
}
