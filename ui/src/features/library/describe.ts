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

/** The file's own name: the last part of the path it was last seen at. */
export function fileName(path: string): string {
  return path.split("/").filter(Boolean).pop() ?? path;
}
