// Hearing a bleep before rendering it (#84): while the recording plays, the
// media element is muted across every span a render would silence.
//
// The spans are dsj.hatao.spans_to_mute's own, sent with every save of the
// edit list (dsj/ui/routes/marks.py), so the page never decides what to mute.
// This only follows the clock: the playhead's frame loop asks `update` with
// the time on every frame (#60), and the element's own `seeked`, `play` and
// `timeupdate` events ask too, the last for a tab the browser has hidden,
// where frames stop and sound does not.
//
// A frame comes every 16.7 ms at 60 Hz, so the gate mutes a frame early: it
// asks whether the stretch until the next frame reaches a span, not only
// whether now is inside one. Each span already reaches PAD_S (0.1 s) past its
// word, so a frame's lateness on the way out stays inside the pad.

import type { Span } from "@/features/edit/editing";

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

export class MuteGate {
  private spans: readonly Span[] = [];
  // True while this gate, not the person, has the element muted.
  private muting = false;
  private readonly media: HTMLMediaElement;

  constructor(media: HTMLMediaElement) {
    this.media = media;
  }

  setSpans(spans: readonly Span[]): void {
    this.spans = spans;
    this.update(this.media.currentTime);
  }

  /** Mute or unmute for the recording at `seconds`, and the frame to come. */
  update(seconds: number): void {
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

  /** Whether the gate is holding the sound off now. */
  isMuting(): boolean {
    return this.muting;
  }

  dispose(): void {
    if (this.muting) this.media.muted = false;
    this.muting = false;
  }
}
