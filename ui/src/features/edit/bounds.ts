// Dragging a word's edge when the recogniser put it in the wrong place (#85).
//
// The edge moves; its neighbour gives up the time it moves into, and never
// overlaps it; nothing gets a negative length. That is the clamp
// wassgha/rescript applies (reimplemented: its licence is noncommercial).
// Whatever opens or closes between the words becomes a pause, so the list
// still plays the whole recording in order and a render still takes it
// (ui/src/lib/linter.ts checks that after every edit).

import { TIME_EPS_S } from "@/features/transcript/document";
import type { Content, Entry, Item, RetimeOp } from "@/lib/editOps";

// The file's own precision: dsj/hatao.py rounds lengths to the millisecond.
function ms(seconds: number): number {
  return Math.round(seconds * 1000) / 1000;
}

export type Edge = "start" | "end";

/** One word's part of the list, and its neighbours: what a drag can change. */
export type Bounds = {
  /** The entries the drag rewrites: from the word before to the word after. */
  from: number;
  stop: number;
  /** The word's first and last piece, and its neighbours' nearest ones, as entry indexes. */
  first: number;
  last: number;
  previous: number | null;
  next: number | null;
  /** Where the window starts and ends in the recording, in seconds. */
  floor: number;
  ceiling: number;
};

function textAt(content: Content, index: number): Item | null {
  const entry = content[index];
  return entry?.kind === "item" && entry.text !== "" ? entry : null;
}

const end = (item: Item) => item.sourceStart + item.length;

/** The part of the list a drag of the word in entries [first, stop) can touch. */
export function boundsOf(content: Content, first: number, stop: number): Bounds {
  let firstPiece = first;
  while (firstPiece < stop && textAt(content, firstPiece) === null) firstPiece += 1;
  let last = stop - 1;
  while (last > firstPiece && textAt(content, last) === null) last -= 1;
  let previous: number | null = first - 1;
  while (previous >= 0 && textAt(content, previous) === null) previous -= 1;
  if (previous < 0) previous = null;
  let next: number | null = stop;
  while (next < content.length && textAt(content, next) === null) next += 1;
  if (next >= content.length) next = null;
  // Without a word before, the window opens at the first item there is.
  let from = previous ?? 0;
  while (previous === null && content[from]?.kind !== "item" && from < firstPiece) from += 1;
  const stopAt = next === null ? content.length : next + 1;
  const items = content.slice(from, stopAt).filter((e): e is Item => e.kind === "item");
  return {
    from,
    stop: stopAt,
    first: firstPiece,
    last,
    previous,
    next,
    floor: Math.min(...items.map((e) => e.sourceStart)),
    ceiling: Math.max(...items.map(end)),
  };
}

/** How far the edge may go: its own word's other end on one side, the neighbour's far end on the other. */
export function edgeRange(content: Content, bounds: Bounds, edge: Edge): [number, number] {
  const first = textAt(content, bounds.first) as Item;
  const last = textAt(content, bounds.last) as Item;
  if (edge === "start") {
    const previous = bounds.previous === null ? null : textAt(content, bounds.previous);
    return [previous === null ? bounds.floor : previous.sourceStart, end(first)];
  }
  const next = bounds.next === null ? null : textAt(content, bounds.next);
  return [last.sourceStart, next === null ? bounds.ceiling : end(next)];
}

/**
 * The edit that moves the word's `edge` to `seconds`, clamped, with the
 * neighbour on that side giving up what it overlaps and the pauses between
 * remade to fill what opens.
 */
export function retime(content: Content, bounds: Bounds, edge: Edge, seconds: number): RetimeOp {
  const [lo, hi] = edgeRange(content, bounds, edge);
  const at = ms(Math.min(Math.max(seconds, lo), hi));
  const times = new Map<number, { start: number; stop: number }>();
  const put = (index: number | null, start?: number, stop?: number) => {
    if (index === null) return;
    const item = textAt(content, index) as Item;
    const was = times.get(index) ?? { start: item.sourceStart, stop: end(item) };
    times.set(index, { start: start ?? was.start, stop: stop ?? was.stop });
  };
  if (edge === "start") {
    put(bounds.first, at);
    const previous = bounds.previous === null ? null : textAt(content, bounds.previous);
    if (previous !== null && end(previous) > at) put(bounds.previous, undefined, at);
  } else {
    put(bounds.last, undefined, at);
    const next = bounds.next === null ? null : textAt(content, bounds.next);
    if (next !== null && next.sourceStart < at) put(bounds.next, at);
  }

  // Rebuild the window: each text item at its time; between two, any
  // paragraph that opened there, then one pause over whatever gap is left.
  const entries: Entry[] = [];
  let reached = bounds.floor;
  let paragraphs: Entry[] = [];
  let pauseMuted = false;
  const fill = (until: number, source: string) => {
    entries.push(...paragraphs);
    paragraphs = [];
    if (until > reached + TIME_EPS_S) {
      entries.push({ kind: "item", source, sourceStart: ms(reached), length: ms(until - reached), text: "", muted: pauseMuted, confidence: null });
    }
    pauseMuted = false;
  };
  let source = "0";
  for (let index = bounds.from; index < bounds.stop; index += 1) {
    const entry = content[index] as Entry;
    if (entry.kind === "paragraph") {
      paragraphs.push(entry);
      continue;
    }
    source = entry.source;
    if (entry.text === "") {
      pauseMuted ||= entry.muted;
      continue;
    }
    const time = times.get(index);
    const start = time?.start ?? entry.sourceStart;
    const stop = time?.stop ?? end(entry);
    fill(start, entry.source);
    // A word re-timed by hand is sure, as a retyped one is (#83).
    entries.push(time === undefined ? entry : { ...entry, sourceStart: start, length: ms(stop - start), confidence: 1 });
    reached = Math.max(reached, stop);
  }
  // Up to where the window's last entry reached, as it did before.
  fill(bounds.ceiling, source);
  return { kind: "retime", start: bounds.from, stop: bounds.stop, entries };
}
