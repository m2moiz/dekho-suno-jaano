// Hearing a bleep before rendering it (#84): while the recording plays, its
// sound goes through a gain that is 0 across every span a render would
// silence, and fades into and out of it as the render does (#225).
//
// The spans are dsj.hatao.spans_to_mute's own, sent with every save of the
// edit list (dsj/ui/routes/marks.py), so the page never decides what to mute.
// This only follows the clock: the playhead's frame loop asks `update` with
// the time on every frame (#60), and the element's own `seeked`, `play` and
// `timeupdate` events ask too, the last for a tab the browser has hidden,
// where frames stop and sound does not.
//
// A frame comes every 16.7 ms at 60 Hz, too coarse for a 5 ms fade, so a frame
// does not switch the sound itself. Each fade is scheduled ahead on the audio
// clock, as a curve on a Web Audio GainNode, at the moment the recording's
// clock says it is due: the sound fades on the sample, between frames, and in
// a hidden tab. A seek, a pause, a new speed or new spans start the schedule
// again from the time they leave.
//
// Not in WebKit, whose sound runs ahead of its own clock once it is taken into
// Web Audio (`fadesInWebAudio`). There, as before #225, a frame switches the
// element's `muted`, a frame early: it asks whether the stretch until the next
// frame reaches a span, not only whether now is inside one. Each span already
// reaches PAD_S (0.1 s) past its word, so a frame's lateness on the way out
// stays inside the pad.

import type { Span } from "@/features/edit/editing";

/**
 * How long a render fades the sound out before a span and back in after it,
 * in seconds: dsj/media.py `MUTE_FADE_S` (#221), which tests/test_media.py
 * holds this to.
 */
export const MUTE_FADE_S = 0.005;

// How far ahead of the recording's clock the fades are scheduled, in seconds
// at 1x. Longer than the gap between two `timeupdate` events, about 0.25 s,
// which are all a hidden tab gets.
const AHEAD_S = 2;

// Where the recording's clock is, read against the audio clock, jumps when it
// is seeked and stalls for up to a few frames as it starts to play, and the two
// clocks are read only once a frame, the audio clock to its last 128 samples
// (2.7 ms at 48 kHz). So a reading more than JUMP_S from where the schedule
// says the recording is starts the schedule again at once; one nearer than
// that is noise or a stall settling, and only the median of the last SETTLE
// readings moves the schedule, by itself, once it is more than DRIFT_S out.
// Measured on 3 Oct 2026 in Chromium (#225): a start whose last stalled frame
// left the schedule 5.5 ms late, and readings spread over 2.6 ms once playing.
const JUMP_S = 0.05;
const SETTLE = 8;
const DRIFT_S = 0.002;

// Points on each fade's curve. The GainNode draws straight lines between
// them, which on a 5 ms raised cosine stay within 0.1% of it.
const CURVE_POINTS = 32;

/**
 * The gain a render gives the sound at `seconds`: 0 inside a span, 1 from
 * MUTE_FADE_S beyond it, and a raised cosine between, as dsj/media.py
 * `_silence` works it out per sample. Spans whose fades meet multiply, as a
 * render's filters do one after the other.
 */
export function gainAt(spans: readonly Span[], seconds: number): number {
  let gain = 1;
  for (const [a, b] of spans) {
    if (seconds <= a - MUTE_FADE_S || seconds >= b + MUTE_FADE_S) continue;
    const ramp = Math.min(Math.max((a - seconds) / MUTE_FADE_S, (seconds - b) / MUTE_FADE_S, 0), 1);
    gain *= (1 - Math.cos(Math.PI * ramp)) / 2;
  }
  return gain;
}

/** The stretches where the gain changes, in order: each span's two fades, joined where they meet. */
export function fades(spans: readonly Span[]): Span[] {
  const out: [number, number][] = [];
  for (const [a, b] of spans) {
    for (const [from, to] of [[a - MUTE_FADE_S, a], [b, b + MUTE_FADE_S]] as const) {
      const last = out.at(-1);
      if (last !== undefined && from <= last[1]) {
        last[0] = Math.min(last[0], from);
        last[1] = Math.max(last[1], to);
      } else {
        out.push([from, to]);
      }
    }
  }
  return out;
}

// One display frame, in seconds of the recording at 1x.
const FRAME_S = 1 / 60;

/** The span that [from, to] reaches into, or -1. `spans` are in order and do not overlap. */
export function spanReached(spans: readonly Span[], from: number, to: number): number {
  let lo = 0;
  let hi = spans.length - 1;
  // The last span that starts at or before `to`.
  let found = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if ((spans[mid]?.[0] ?? Infinity) <= to) {
      found = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  return found >= 0 && (spans[found]?.[1] ?? -Infinity) > from ? found : -1;
}

/**
 * Whether this browser's sound stays on its own clock in Web Audio, so the
 * fades can be scheduled from it. WebKit's does not: measured on 3 Oct 2026
 * (#225) with a tone whose height steps at known times, every fade landed
 * 280.7 to 282.0 ms late over four runs in Playwright 1.63's WebKit 26.6, and
 * within 1.4 ms of where a render puts it in its Chromium 153 and in
 * agent-browser's Chromium 151. The sound there runs that far ahead of the
 * words and the picture too, so WebKit keeps the element's own output.
 */
export function fadesInWebAudio(vendor: string = navigator.vendor): boolean {
  return !vendor.startsWith("Apple");
}

/** The part of Web Audio the gate uses: a clock, and the gain the sound passes through. */
export type Route = {
  context: Pick<BaseAudioContext, "currentTime" | "state"> & { resume: () => Promise<void> };
  gain: Pick<AudioParam, "cancelScheduledValues" | "setValueAtTime" | "setValueCurveAtTime">;
  /** Take the sound out of the gain, once its element has left the page. */
  release: () => void;
};

// One audio clock for the page, and each media element's route through it:
// an element's sound can be taken into Web Audio only once.
let shared: AudioContext | null = null;
const routes = new WeakMap<HTMLMediaElement, Route>();

/** `media`'s sound, through a gain, to the speakers: made the first time a span is played over. */
export function webAudioRoute(media: HTMLMediaElement): Route {
  const found = routes.get(media);
  if (found !== undefined) return found;
  shared ??= new AudioContext();
  const context = shared;
  const source = context.createMediaElementSource(media);
  const node = context.createGain();
  source.connect(node).connect(context.destination);
  const route: Route = {
    context,
    gain: node.gain,
    release: () => {
      source.disconnect();
      node.disconnect();
      routes.delete(media);
    },
  };
  routes.set(media, route);
  return route;
}

function median(values: readonly number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = sorted.length >> 1;
  return sorted.length % 2 === 1 ? (sorted[mid] ?? 0) : ((sorted[mid - 1] ?? 0) + (sorted[mid] ?? 0)) / 2;
}

/** Where the schedule was last started: the audio clock and the recording's, and the speed. */
type Anchor = { audio: number; media: number; rate: number };

export class MuteGate {
  private spans: readonly Span[] = [];
  private stretches: Span[] = [];
  private route: Route | null = null;
  // True while the frame gate, not the person, has the element muted.
  private muting = false;
  // While playing, where the schedule started, and how far into the recording
  // its fades are scheduled. Null while paused or not yet scheduled.
  private anchor: Anchor | null = null;
  private scheduledTo = 0;
  // The last SETTLE readings of how far the recording's clock is from the schedule's.
  private readings: number[] = [];
  private readonly media: HTMLMediaElement;
  // Null where the gate switches `muted` on each frame instead (`fadesInWebAudio`).
  private readonly makeRoute: ((media: HTMLMediaElement) => Route) | null;

  constructor(
    media: HTMLMediaElement,
    makeRoute: ((media: HTMLMediaElement) => Route) | null = fadesInWebAudio() ? webAudioRoute : null,
  ) {
    this.media = media;
    this.makeRoute = makeRoute;
  }

  setSpans(spans: readonly Span[]): void {
    this.spans = spans;
    this.stretches = fades(spans);
    this.anchor = null;
    this.update(this.media.currentTime);
  }

  /** Keep the gain on the render's for the recording at `seconds`, and for what plays next. */
  update(seconds: number): void {
    if (this.makeRoute === null) {
      this.switchMuted(seconds);
      return;
    }
    const playing = !this.media.paused;
    // No sound goes through Web Audio until a span is played over: a recording
    // with nothing to mute plays as it always has.
    if (this.route === null) {
      if (!playing || this.spans.length === 0) return;
      this.route = this.makeRoute(this.media);
    }
    const { context, gain } = this.route;
    const now = context.currentTime;
    if (!playing) {
      gain.cancelScheduledValues(now);
      gain.setValueAtTime(gainAt(this.spans, seconds), now);
      this.anchor = null;
      return;
    }
    // A clock made before the page was clicked starts suspended, and plays nothing.
    if (context.state === "suspended") void context.resume();
    const rate = this.media.playbackRate || 1;
    const anchor = this.anchor;
    const off = anchor !== null && anchor.rate === rate ? seconds - anchor.media - (now - anchor.audio) * rate : Number.NaN;
    if (!(Math.abs(off) <= JUMP_S)) {
      this.restart(now, seconds, rate);
    } else if (anchor !== null) {
      this.readings.push(off);
      if (this.readings.length > SETTLE) this.readings.shift();
      const settled = median(this.readings);
      if (this.readings.length === SETTLE && Math.abs(settled) > DRIFT_S && !this.fading(seconds)) {
        const kept = this.readings.map((x) => x - settled);
        this.restart(now, anchor.media + settled + (now - anchor.audio) * rate, rate);
        this.readings = kept;
      }
    }
    this.schedule(seconds + AHEAD_S * rate);
  }

  /** Mute or unmute the element for the recording at `seconds`, and the frame to come. */
  private switchMuted(seconds: number): void {
    const ahead = this.media.paused ? 0 : FRAME_S * (this.media.playbackRate || 1);
    const inside = spanReached(this.spans, seconds, seconds + ahead) >= 0;
    if (inside && !this.muting) {
      // A person's own mute is theirs: the gate leaves it, and never undoes it.
      if (this.media.muted) return;
      this.media.muted = true;
      this.muting = true;
    } else if (!inside && this.muting) {
      this.media.muted = false;
      this.muting = false;
    }
  }

  /** Whether a fade is under way at `seconds`, or within JUMP_S of it. */
  private fading(seconds: number): boolean {
    return this.stretches.some(([from, to]) => from - JUMP_S < seconds && seconds < to + JUMP_S);
  }

  /** Drop everything scheduled and start again from `seconds` of the recording at `now` on the audio clock. */
  private restart(now: number, seconds: number, rate: number): void {
    const gain = this.route?.gain;
    if (gain === undefined) return;
    gain.cancelScheduledValues(now);
    const inFade = this.stretches.some(([from, to]) => from <= seconds && seconds < to);
    // Inside a fade, its curve, scheduled from now, sets the gain itself.
    if (!inFade) gain.setValueAtTime(gainAt(this.spans, seconds), now);
    this.anchor = { audio: now, media: seconds, rate };
    this.scheduledTo = seconds;
    this.readings = [];
  }

  /** Put every fade that is due before `until`, in the recording's clock, on the audio clock. */
  private schedule(until: number): void {
    const gain = this.route?.gain;
    const anchor = this.anchor;
    if (gain === undefined || anchor === null) return;
    for (const [from, to] of this.stretches) {
      if (to <= this.scheduledTo) continue;
      if (from >= until) break;
      const start = Math.max(from, this.scheduledTo);
      const curve = new Float32Array(CURVE_POINTS + 1);
      for (let i = 0; i <= CURVE_POINTS; i++) curve[i] = gainAt(this.spans, start + ((to - start) * i) / CURVE_POINTS);
      gain.setValueCurveAtTime(curve, anchor.audio + (start - anchor.media) / anchor.rate, (to - start) / anchor.rate);
      this.scheduledTo = to;
    }
  }

  dispose(): void {
    if (this.muting) this.media.muted = false;
    this.muting = false;
    if (this.route !== null) {
      const now = this.route.context.currentTime;
      this.route.gain.cancelScheduledValues(now);
      this.route.gain.setValueAtTime(1, now);
      // Gone from the page, the element can never play again: let it go.
      if (!this.media.isConnected) this.route.release();
    }
    this.route = null;
    this.anchor = null;
  }
}
