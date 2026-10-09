import { type KeyboardEvent, type PointerEvent, type RefObject, useEffect, useRef, useState } from "react";

import { api } from "@/api/client";
import { ApiError, fromBody, fromThrown, showError } from "@/features/errors/appError";
import { durationLabel } from "@/features/library/describe";

// The shape of the recording's sound (#61), drawn from the envelope the server
// computed (dsj.media.envelope), so the browser never loads the audio to draw
// it: an hour of 16 kHz float samples would be about 230 MB in the tab. No
// waveform library: wavesurfer.js and peaks.js each bring a player and a clock
// of their own, and this is one loop over columns.

/**
 * Each canvas column's lowest and highest value: the min and max over the
 * envelope buckets that fall in it. `peaks` is min, max pairs.
 */
export function columns(peaks: Int8Array, width: number): { lo: Int8Array; hi: Int8Array } {
  const buckets = Math.floor(peaks.length / 2);
  const lo = new Int8Array(width);
  const hi = new Int8Array(width);
  for (let x = 0; x < width; x += 1) {
    const from = Math.floor((x * buckets) / width);
    const to = Math.max(from + 1, Math.floor(((x + 1) * buckets) / width));
    let low = 127;
    let high = -128;
    for (let i = from; i < Math.min(to, buckets); i += 1) {
      low = Math.min(low, peaks[2 * i] ?? 0);
      high = Math.max(high, peaks[2 * i + 1] ?? 0);
    }
    lo[x] = high < low ? 0 : low;
    hi[x] = high < low ? 0 : high;
  }
  return { lo, hi };
}

function draw(canvas: HTMLCanvasElement, peaks: Int8Array): void {
  const scale = window.devicePixelRatio || 1;
  const width = Math.round(canvas.clientWidth * scale);
  const height = Math.round(canvas.clientHeight * scale);
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  if (context === null || width === 0) return;
  // Scaled to the loudest moment, so quiet speech still has a shape.
  let loudest = 1;
  for (const value of peaks) loudest = Math.max(loudest, Math.abs(value));
  const { lo, hi } = columns(peaks, width);
  const middle = height / 2;
  context.clearRect(0, 0, width, height);
  context.fillStyle = getComputedStyle(canvas).color;
  for (let x = 0; x < width; x += 1) {
    const top = middle - ((hi[x] ?? 0) / loudest) * middle;
    const bottom = middle - ((lo[x] ?? 0) / loudest) * middle;
    context.fillRect(x, top, 1, Math.max(scale, bottom - top));
  }
}

type Props = {
  recordingId: number;
  media: RefObject<HTMLMediaElement | null>;
  /** Where the playhead tells this view the time, every frame it paints (#60). */
  frames: Set<(seconds: number) => void>;
  /** Move the one playhead there and play: the same seek a click on a word makes. */
  onSeek: (seconds: number) => void;
  /** Move the one playhead there without starting playback: a key press, a drag in progress. */
  onScrub: (seconds: number) => void;
};

// One arrow key press moves this far; with Shift, SHIFT_STEP_S.
const STEP_S = 5;
const SHIFT_STEP_S = 30;

/**
 * The recording's shape as the only scrubber (Hashiya spec, Reader: "the
 * waveform as the only scrubber with the played part tinted gold"). Two
 * canvases drawn once, the second in gold and cut by clip-path to the played
 * part, so a frame moves one clip and draws nothing. A slider to the keyboard
 * and to a screen reader (critique: "waveform unreachable by keyboard").
 *
 * The played canvas is text-gold on the rail's bg-field, the one ground the
 * full gold reads on (index.css, --gold-ink).
 *
 * Hand-built rather than a shadcn slider: a slider picks a value from a track
 * it draws itself, and this one is the drawing of the recording, with the
 * playhead's frame moving its cursor outside React.
 */
export function Waveform({ recordingId, media, frames, onSeek, onScrub }: Props) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const played = useRef<HTMLCanvasElement>(null);
  const cursor = useRef<HTMLDivElement>(null);
  const slider = useRef<HTMLDivElement>(null);
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

  // Drawn again when the canvas changes size or the colours change scheme.
  useEffect(() => {
    const base = canvas.current;
    const gold = played.current;
    if (base === null || gold === null || peaks === null) return;
    const redraw = () => {
      draw(base, peaks);
      draw(gold, peaks);
    };
    redraw();
    const resized = new ResizeObserver(redraw);
    resized.observe(base);
    const themed = new MutationObserver(redraw);
    themed.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    const scheme = window.matchMedia("(prefers-color-scheme: dark)");
    scheme.addEventListener("change", redraw);
    return () => {
      resized.disconnect();
      themed.disconnect();
      scheme.removeEventListener("change", redraw);
    };
  }, [peaks]);

  // The cursor and the gold clip move with the playhead's own frame, never
  // with React state. The slider's value is written at most once a second; its
  // length and text are also written the moment the duration is known, so a
  // screen reader has them before the first frame.
  useEffect(() => {
    let lastSecond = -1;
    const describeAt = (seconds: number) => {
      const duration = media.current?.duration ?? Number.NaN;
      if (!Number.isFinite(duration) || duration <= 0 || slider.current === null) return;
      slider.current.setAttribute("aria-valuenow", String(Math.floor(seconds)));
      slider.current.setAttribute("aria-valuemax", String(Math.round(duration)));
      slider.current.setAttribute("aria-valuetext", `${durationLabel(seconds) ?? "0:00"} of ${durationLabel(duration) ?? "0:00"}`);
    };
    const move = (seconds: number) => {
      const duration = media.current?.duration ?? Number.NaN;
      if (!Number.isFinite(duration) || duration <= 0) return;
      const share = Math.min(seconds, duration) / duration;
      const width = cursor.current?.parentElement?.clientWidth ?? 0;
      if (cursor.current !== null) cursor.current.style.transform = `translateX(${share * width}px)`;
      if (played.current !== null) played.current.style.clipPath = `inset(0 ${(1 - share) * 100}% 0 0)`;
      const second = Math.floor(seconds);
      if (second !== lastSecond) {
        lastSecond = second;
        describeAt(seconds);
      }
    };
    // Media events do not bubble, so they are caught on the way down; the
    // element can be swapped for a sound-only copy (#110), which a listener on
    // one element would miss.
    const known = (event: Event) => {
      if (event.target === media.current) describeAt(media.current?.currentTime ?? 0);
    };
    describeAt(media.current?.currentTime ?? 0);
    window.addEventListener("durationchange", known, true);
    window.addEventListener("loadedmetadata", known, true);
    frames.add(move);
    return () => {
      frames.delete(move);
      window.removeEventListener("durationchange", known, true);
      window.removeEventListener("loadedmetadata", known, true);
    };
  }, [frames, media]);

  const key = (event: KeyboardEvent<HTMLDivElement>) => {
    const element = media.current;
    // A chord (Cmd+Left, Ctrl+Right, Option+arrow) belongs to the browser or the Mac.
    if (element === null || event.ctrlKey || event.metaKey || event.altKey) return;
    const duration = Number.isFinite(element.duration) ? element.duration : Number.POSITIVE_INFINITY;
    const step = event.shiftKey ? SHIFT_STEP_S : STEP_S;
    const to =
      event.key === "ArrowRight" || event.key === "ArrowUp"
        ? element.currentTime + step
        : event.key === "ArrowLeft" || event.key === "ArrowDown"
          ? element.currentTime - step
          : event.key === "Home"
            ? 0
            : event.key === "End" && Number.isFinite(duration)
              ? duration
              : null;
    if (to === null) return;
    event.preventDefault();
    onScrub(Math.min(Math.max(0, to), duration));
  };

  // A press that began on the slider and has not been released.
  const dragging = useRef(false);
  /** The time under the pointer, clamped to the recording; null before the length is known. */
  const secondsAt = (event: PointerEvent<HTMLDivElement>): number | null => {
    const duration = media.current?.duration ?? Number.NaN;
    if (!Number.isFinite(duration)) return null;
    const box = event.currentTarget.getBoundingClientRect();
    return Math.min(Math.max(0, (event.clientX - box.left) / box.width), 1) * duration;
  };

  return (
    <div
      ref={slider}
      role="slider"
      tabIndex={0}
      aria-label="Position"
      aria-valuemin={0}
      aria-valuemax={0}
      aria-valuenow={0}
      className="relative h-11 min-w-0 flex-1 cursor-pointer touch-none rounded-md"
      onKeyDown={key}
      onPointerDown={(event) => {
        // The primary button or a touch; the capture keeps a drag that leaves the rail.
        if (event.button !== 0) return;
        event.currentTarget.setPointerCapture?.(event.pointerId);
        dragging.current = true;
        const at = secondsAt(event);
        if (at !== null) onScrub(at);
      }}
      onPointerMove={(event) => {
        if (!dragging.current) return;
        const at = secondsAt(event);
        if (at !== null) onScrub(at);
      }}
      onPointerUp={(event) => {
        if (!dragging.current) return;
        dragging.current = false;
        const at = secondsAt(event);
        if (at !== null) onSeek(at);
      }}
      onPointerCancel={() => {
        dragging.current = false;
      }}
    >
      <canvas ref={canvas} aria-label="Waveform" className="h-full w-full text-field-wave" />
      <div ref={cursor} aria-hidden className="pointer-events-none absolute inset-y-1 left-0 w-0.5 rounded bg-gold" />
      <canvas
        ref={played}
        aria-hidden
        className="pointer-events-none absolute inset-0 h-full w-full text-gold"
        style={{ clipPath: "inset(0 100% 0 0)" }}
      />
    </div>
  );
}
