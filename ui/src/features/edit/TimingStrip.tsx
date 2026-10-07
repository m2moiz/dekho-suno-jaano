import { type KeyboardEvent, type PointerEvent, type RefObject, useEffect, useRef, useState } from "react";

import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { ApiError, fromBody, fromThrown, showError } from "@/features/errors/appError";
import type { PlayerControls } from "@/features/player/Player";
import type { Content, Editor, Item } from "@/lib/editOps";
import { TOUCH, useMediaQuery } from "@/lib/media";
import { type Bounds, boundsOf, type Edge, retime } from "./bounds";
import type { EditReading } from "./readContent";

// How much of the recording shows either side of the word and its
// neighbours, in seconds, so an edge can be dragged a little past them.
const MARGIN_S = 0.25;
// One arrow key press moves an edge this far; with Shift, ten times as far.
const NUDGE_S = 0.01;
// dsj.media.ENVELOPE_RATE: the waveform route's buckets a second (#61).
const ENVELOPE_RATE = 50;

type Props = {
  editor: Editor;
  content: Content;
  edit: EditReading;
  /** The word whose edges are dragged, as an index into the reading's words. */
  word: number;
  recordingId: number;
  controls: RefObject<PlayerControls | null>;
  onClose: () => void;
};

function itemAt(content: Content, index: number | null): Item | null {
  if (index === null) return null;
  const entry = content[index];
  return entry?.kind === "item" ? entry : null;
}

function usePeaks(recordingId: number): Int8Array | null {
  const [peaks, setPeaks] = useState<Int8Array | null>(null);
  useEffect(() => {
    let live = true;
    const route = `/api/recording/${recordingId}/waveform`;
    api
      .GET("/api/recording/{recording_id}/waveform", {
        params: { path: { recording_id: String(recordingId) } },
        parseAs: "arrayBuffer",
      })
      .then(({ data, error, response }) => {
        if (data === undefined) throw new ApiError(fromBody(error, response, route));
        if (live) setPeaks(new Int8Array(data));
      })
      .catch((thrown: unknown) => {
        if (live) showError(fromThrown(thrown, route));
      });
    return () => {
      live = false;
    };
  }, [recordingId]);
  return peaks;
}

/**
 * One word's edges on a stretch of the waveform, to drag when the recogniser
 * put them in the wrong place (#85). A drag is one undo step (#66's
 * gestures); its neighbour gives up what the edge moves into.
 */
export function TimingStrip({ editor, content, edit, word, recordingId, controls, onClose }: Props) {
  const bounds = boundsOf(content, edit.first[word] ?? 0, edit.stop[word] ?? 0);
  const first = itemAt(content, bounds.first) as Item;
  const last = itemAt(content, bounds.last) as Item;
  const start = first.sourceStart;
  const end = last.sourceStart + last.length;
  const view = { from: Math.max(0, bounds.floor - MARGIN_S), to: bounds.ceiling + MARGIN_S };
  const strip = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const drag = useRef<{ edge: Edge; base: Content; bounds: Bounds; length: number } | null>(null);
  const peaks = usePeaks(recordingId);
  // 44 px buttons where the Selection toolbar has them (F15).
  const touch = useMediaQuery(TOUCH);
  const left = (seconds: number) => `${((seconds - view.from) / (view.to - view.from)) * 100}%`;
  const width = (from: number, to: number) => `${((to - from) / (view.to - view.from)) * 100}%`;
  const text = edit.reading.turns[edit.reading.words.turn[word] ?? 0]?.text.slice(
    edit.reading.words.offset[word] ?? 0,
    (edit.reading.words.offset[word] ?? 0) + (edit.reading.words.length[word] ?? 0),
  ).trim();

  // Focus goes into the strip when it opens on a word, to its start edge, so
  // the arrow keys move it at once (Task 3 review: it opened out of reach).
  useEffect(() => {
    strip.current?.querySelector<HTMLElement>("[role=slider]")?.focus({ preventScroll: true });
  }, [word]);

  useEffect(() => {
    const element = canvas.current;
    if (element === null || peaks === null) return;
    const scale = window.devicePixelRatio || 1;
    element.width = Math.round(element.clientWidth * scale);
    element.height = Math.round(element.clientHeight * scale);
    const context = element.getContext("2d");
    if (context === null) return;
    context.clearRect(0, 0, element.width, element.height);
    context.fillStyle = getComputedStyle(element).color;
    const middle = element.height / 2;
    for (let x = 0; x < element.width; x += 1) {
      const bucket = Math.floor((view.from + ((view.to - view.from) * x) / element.width) * ENVELOPE_RATE);
      const lo = peaks[2 * bucket] ?? 0;
      const hi = peaks[2 * bucket + 1] ?? 0;
      const top = middle - (hi / 128) * middle;
      context.fillRect(x, top, 1, Math.max(scale, middle - (lo / 128) * middle - top));
    }
  }, [peaks, view.from, view.to]);

  const secondsAt = (clientX: number) => {
    const box = strip.current?.getBoundingClientRect();
    if (box === undefined || box.width === 0) return view.from;
    return view.from + ((clientX - box.left) / box.width) * (view.to - view.from);
  };

  const begin = (edge: Edge) => (event: PointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    const base = editor.content;
    const at = boundsOf(base, edit.first[word] ?? 0, edit.stop[word] ?? 0);
    drag.current = { edge, base, bounds: at, length: at.stop - at.from };
    editor.beginGesture();
  };
  const move = (event: PointerEvent<HTMLDivElement>) => {
    const now = drag.current;
    if (now === null) return;
    // Always from the list as the drag found it, so the edge follows the
    // pointer, and in place of what the last move wrote.
    const op = retime(now.base, now.bounds, now.edge, secondsAt(event.clientX));
    editor.applyEdit({ ...op, stop: now.bounds.from + now.length });
    now.length = op.entries.length;
  };
  const finish = () => {
    if (drag.current === null) return;
    drag.current = null;
    editor.endGesture();
  };
  const nudge = (edge: Edge) => (event: KeyboardEvent<HTMLDivElement>) => {
    const step = (event.shiftKey ? 10 : 1) * NUDGE_S;
    const by = event.key === "ArrowLeft" ? -step : event.key === "ArrowRight" ? step : 0;
    if (by === 0) return;
    event.preventDefault();
    editor.applyEdit(retime(editor.content, bounds, edge, (edge === "start" ? start : end) + by));
  };

  const handle = (edge: Edge, seconds: number) => (
    <div
      role="slider"
      tabIndex={0}
      aria-label={`${edge === "start" ? "Start" : "End"} of ${text}`}
      aria-valuemin={Math.round(view.from * 1000) / 1000}
      aria-valuemax={Math.round(view.to * 1000) / 1000}
      aria-valuenow={Math.round(seconds * 1000) / 1000}
      aria-valuetext={`${seconds.toFixed(2)} s`}
      className="absolute inset-y-0 z-10 -ml-1.5 w-3 cursor-ew-resize touch-none rounded-sm bg-primary/80 outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
      style={{ left: left(seconds) }}
      onPointerDown={begin(edge)}
      onPointerMove={move}
      onPointerUp={finish}
      onPointerCancel={finish}
      onKeyDown={nudge(edge)}
    />
  );

  const box = (item: Item | null, own: boolean) =>
    item === null ? null : (
      <div
        aria-hidden
        className={`absolute inset-y-2 rounded-sm ${own ? "bg-primary/25" : "bg-muted-foreground/20"}`}
        style={{ left: left(item.sourceStart), width: width(item.sourceStart, item.sourceStart + item.length) }}
      />
    );

  return (
    <section
      aria-label="Word timing"
      className="rounded-lg border bg-card p-3 text-sm text-card-foreground shadow-lg shadow-black/15"
      onKeyDown={(event) => {
        // Esc closes the strip, and only the strip: not the reader's selection too.
        if (event.key !== "Escape") return;
        event.stopPropagation();
        onClose();
      }}
    >
      <div className="mb-2 flex items-center gap-3">
        <span>
          <span dir="auto" className="font-medium">
            {text}
          </span>{" "}
          <span className="text-muted-foreground tabular-nums">
            {start.toFixed(2)} to {end.toFixed(2)} s
          </span>
        </span>
        <span className="text-xs text-muted-foreground">Drag an edge, or focus it and press ← →.</span>
        <Button
          variant="outline"
          size="sm"
          className={`ml-auto ${touch ? "h-11 px-3" : ""}`}
          onClick={() => controls.current?.hear(Math.max(0, start - 0.5), end + 0.5)}
        >
          Hear
        </Button>
        <Button variant="outline" size="sm" className={touch ? "h-11 px-3" : ""} onClick={onClose}>
          Done
        </Button>
      </div>
      <div ref={strip} className="relative h-16 w-full select-none">
        <canvas ref={canvas} aria-hidden className="absolute inset-0 h-full w-full text-muted-foreground/60" />
        {box(itemAt(content, bounds.previous), false)}
        {box(itemAt(content, bounds.next), false)}
        <div
          aria-hidden
          className="absolute inset-y-1 rounded-sm bg-primary/25"
          style={{ left: left(start), width: width(start, end) }}
        />
        {handle("start", start)}
        {handle("end", end)}
      </div>
    </section>
  );
}
