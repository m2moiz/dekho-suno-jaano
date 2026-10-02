// The playhead: which word is being said, painted over the plain text (#60).
//
// Not React state (#57 section 7): one requestAnimationFrame loop reads the
// media element's own currentTime, finds the word by binary search, and moves
// one Range inside one Highlight registered as `::highlight(dsj-playhead)`. No
// element is created or changed, and nothing re-renders, so a frame costs the
// same at minute 1 and at minute 100.
//
// The loop runs only while the media plays; a seek while paused paints once.

import { type Reading, wordAtTime } from "@/features/transcript/document";

export const HIGHLIGHT = "dsj-playhead";

// The tick's own cost in ms, the last RING ticks, for the perf check
// (ui/tests/perf/reader.spec.ts) to read as `window.dsjPlayheadTicks()`. Two
// clock reads and one store a frame; there is no other way to time a function
// inside the built bundle from outside it.
const RING = 1024;
const ticks = new Float64Array(RING);
let ticked = 0;
declare global {
  interface Window {
    dsjPlayheadTicks?: () => number[];
  }
}
window.dsjPlayheadTicks = () => Array.from(ticks.subarray(0, Math.min(ticked, RING)));

// Where a followed word may sit, as fractions of the window's height: inside
// this band the view stays put; outside it the view moves the word to TARGET.
// The bottom edge leaves room for the player bar.
const BAND_TOP = 0.15;
const BAND_BOTTOM = 0.75;
const TARGET = 0.35;

export type PlayheadOptions = {
  media: HTMLMediaElement;
  reading: Reading;
  /** The paragraphs' text nodes, by turn: the article's `p[data-turn]` children. */
  texts: Text[];
  /** Told when following stops (the reader scrolled away) or starts again. */
  onFollowing: (following: boolean) => void;
};

export class Playhead {
  private readonly media: HTMLMediaElement;
  private readonly reading: Reading;
  private readonly texts: Text[];
  private readonly onFollowing: (following: boolean) => void;
  private readonly range: Range;
  private readonly highlight: Highlight;
  private frame = 0;
  private shown = -1;
  private following = true;

  constructor({ media, reading, texts, onFollowing }: PlayheadOptions) {
    this.media = media;
    this.reading = reading;
    this.texts = texts;
    this.onFollowing = onFollowing;
    this.range = document.createRange();
    this.highlight = new Highlight();
    CSS.highlights.set(HIGHLIGHT, this.highlight);
  }

  /** Follow the playhead from now on, and bring the current word into view. */
  follow(): void {
    if (!this.following) {
      this.following = true;
      this.onFollowing(true);
    }
    this.reveal();
  }

  /** The reader scrolled by hand: leave the view where they put it. */
  unfollow(): void {
    if (this.following) {
      this.following = false;
      this.onFollowing(false);
    }
  }

  isFollowing(): boolean {
    return this.following;
  }

  /** Start the loop. Idempotent. */
  start(): void {
    if (this.frame === 0) this.frame = requestAnimationFrame(this.tick);
  }

  /** Stop the loop, and paint where the media now is. */
  stop(): void {
    cancelAnimationFrame(this.frame);
    this.frame = 0;
    this.paint();
  }

  /** Paint once, for a seek while paused. */
  paint(): void {
    this.show(wordAtTime(this.reading.words, this.media.currentTime));
  }

  dispose(): void {
    cancelAnimationFrame(this.frame);
    this.frame = 0;
    if (CSS.highlights.get(HIGHLIGHT) === this.highlight) CSS.highlights.delete(HIGHLIGHT);
  }

  private readonly tick = (): void => {
    const began = performance.now();
    this.paint();
    ticks[ticked % RING] = performance.now() - began;
    ticked += 1;
    this.frame = requestAnimationFrame(this.tick);
  };

  private show(word: number): void {
    if (word === this.shown) return;
    this.shown = word;
    this.highlight.clear();
    if (word < 0) return;
    const { turn, offset, length } = this.reading.words;
    const text = this.texts[turn[word] ?? -1];
    if (text === undefined) return;
    const from = offset[word] ?? 0;
    const to = from + (length[word] ?? 0);
    // Paint the word, not the space in front of it.
    const lead = /^\s*/.exec(text.data.slice(from, to))?.[0].length ?? 0;
    this.range.setStart(text, from + lead);
    this.range.setEnd(text, to);
    this.highlight.add(this.range);
    if (this.following) this.reveal();
  }

  private reveal(): void {
    if (this.shown < 0) return;
    const rect = this.range.getBoundingClientRect();
    const height = window.innerHeight;
    if (rect.top >= height * BAND_TOP && rect.bottom <= height * BAND_BOTTOM) return;
    window.scrollBy({ top: rect.top - height * TARGET, behavior: "smooth" });
  }
}
