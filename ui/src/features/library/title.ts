// A recording's title as the library shows it (Hashiya spec, Library: "a
// readable title (default from the file's timestamp, e.g. 'Sat 20 Sep, 9:42
// am', else the filename; renamable inline)"; critique: "a library of
// filenames").
//
// Recorders name a file by when it started, in a handful of shapes: macOS's
// "Screen Recording 2025-09-20 at 9.42.00 AM.mov", phone recorders'
// "20250920_094234.m4a" and "recording-20250920-094234.m4a" (the shape most of
// the owner's library has, counted on 2026-10-07 with `sqlite3` over its
// recordings' paths), "2025-09-20 09.42.34.m4a" and
// "Recording 2025-09-20T21-05.wav". The stamp is read as this Mac's local
// time, which is what the recorder wrote.

import { langOf } from "@/lib/script";
import { durationLabel, fileName } from "./describe";
import type { RecordingRow } from "./types";

const STAMP = /(\d{4})-?(\d{2})-?(\d{2})(?:\s+at\s+|[ _T-])(\d{1,2})[.:-]?(\d{2})(?:[.:-]?(\d{2}))?(?:\s*([AaPp])\.?[Mm]\.?)?/;
// A cut of a longer recording names its span after the stamp, minutes and
// seconds: "recording-20250920-094234_07m00-17m00.m4a" (the one cut in the
// owner's library, counted with the same `sqlite3` query).
const CUT = /_(\d+)m(\d{2})-(\d+)m(\d{2})(?=\.[^.]*$|$)/;
// The sound and picture containers a recording comes in. Only these are cut
// from a file name standing in for a title: "notes.v2" keeps its ".v2".
export const MEDIA = /\.(?:wav|m4a|mp3|mp4|mov|aac|flac|ogg|oga|opus|webm|mkv|m4v|caf|aiff?|amr|3gp|wma)$/i;
const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** When a file's name says it was recorded, or null when it says nothing a real date can be made of. */
export function stampOf(name: string): Date | null {
  const found = STAMP.exec(name);
  if (found === null) return null;
  const year = Number(found[1]);
  const month = Number(found[2]);
  const day = Number(found[3]);
  let hour = Number(found[4]);
  const minute = Number(found[5]);
  const half = found[7]?.toLowerCase();
  if (half !== undefined) {
    if (hour < 1 || hour > 12) return null;
    hour = (hour % 12) + (half === "p" ? 12 : 0);
  }
  if (month < 1 || month > 12 || hour > 23 || minute > 59) return null;
  const when = new Date(year, month - 1, day, hour, minute);
  // 30 February rolls over into March: a date that moved was not a date.
  return when.getMonth() === month - 1 && when.getDate() === day ? when : null;
}

/** "Sat 20 Sep, 9:42 am", with the year when it is not this one. */
export function whenTitle(when: Date, now: Date = new Date()): string {
  const year = when.getFullYear() === now.getFullYear() ? "" : ` ${when.getFullYear()}`;
  const hour = when.getHours() % 12 || 12;
  const half = when.getHours() < 12 ? "am" : "pm";
  const minute = String(when.getMinutes()).padStart(2, "0");
  return `${DAYS[when.getDay()] ?? ""} ${when.getDate()} ${MONTHS[when.getMonth()] ?? ""}${year}, ${hour}:${minute} ${half}`;
}

/** "7:00 to 17:00" for a cut's span in its file's name, or null when the name holds none. */
function cutOf(name: string): string | null {
  const found = CUT.exec(name);
  if (found === null) return null;
  const [from, to] = [Number(found[1]) * 60 + Number(found[2]), Number(found[3]) * 60 + Number(found[4])];
  return `${durationLabel(from) ?? ""} to ${durationLabel(to) ?? ""}`;
}

/**
 * The title a person gave the recording, else when its file's name says it
 * was made (and the span, for a cut), else that name without its extension.
 */
export function displayTitle(row: Pick<RecordingRow, "title" | "path">, now?: Date): string {
  if (row.title) return row.title;
  const name = fileName(row.path);
  const when = stampOf(name);
  if (when === null) return name.replace(MEDIA, "") || name;
  const cut = cutOf(name);
  return cut === null ? whenTitle(when, now) : `${whenTitle(when, now)} · ${cut}`;
}

/**
 * How a title is set (Hashiya spec, Type): one that opens in Urdu script in
 * Nastaliq, about 1.3 times the size (text-lg's 1.125rem x 1.3), with the
 * line height its tall letters need, and lang="ur"; any other in Literata.
 */
export function titleFace(title: string): { lang: "ur" | undefined; className: string } {
  return langOf(title) === "ur"
    ? { lang: "ur", className: "font-urdu text-[1.4625rem] leading-[2.1]" }
    : { lang: undefined, className: "font-reading text-lg" };
}
