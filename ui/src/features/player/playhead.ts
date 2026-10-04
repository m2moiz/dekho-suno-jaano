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
// The band also ends where the player bar starts, whichever is higher: with a
// picture showing, the bar starts at 45% of an 800x600 window, and a word
// between there and 75% played on under the picture (#231).
const BAND_TOP = 0.15;
const BAND_BOTTOM = 0.75;
const TARGET = 0.35;

// The custom property on <html> that holds the player bar's height, written by
// the Player and read by the page's scroll padding in index.css (#230) and by
// the follow band here (#231).
export const PLAYER_HEIGHT = "--dsj-player-height";

/** The player bar's height in px, 0 when no player has written it. */
function playerHeight(): number {
  const value = Number.parseFloat(document.documentElement.style.getPropertyValue(PLAYER_HEIGHT));
  return Number.isFinite(value) ? value : 0;
}

export type PlayheadOptions = {
  media: HTMLMediaElement;
  reading: Reading;
  /** The paragraphs' text nodes, by turn: the article's `p[data-turn]` children. */
  texts: Text[];
  /** Told when following stops (the reader scrolled away) or starts again. */
  onFollowing: (following: boolean) => void;
  /**
   * Told the media's time on every frame it paints, so another view of the
   * same clock (the waveform's cursor, #61) moves in the same frame and owns
   * no time of its own.
   */
  onFrame?: (seconds: number) => void;
};

export class Playhead {
  private readonly media: HTMLMediaElement;
  private readonly reading: Reading;
  private readonly texts: Text[];
  private readonly onFollowing: (following: boolean) => void;
  private readonly onFrame: (seconds: number) => void;
  private readonly range: Range;
  private readonly highlight: Highlight;
  private frame = 0;
  private shown = -1;
  private following = true;

  constructor({ media, reading, texts, onFollowing, onFrame }: PlayheadOptions) {
    this.media = media;
    this.reading = reading;
    this.texts = texts;
    this.onFollowing = onFollowing;
    this.onFrame = onFrame ?? (() => undefined);
    this.range = document.createRange();
    this.highlight = new Highlight();
    // Over the unsure-word tint (#62) where the two meet: where you are wins.
    this.highlight.priority = 1;
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
    const seconds = this.media.currentTime;
    this.show(wordAtTime(this.reading.words, seconds));
    this.onFrame(seconds);
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
    const top = height * BAND_TOP;
    // Never shorter than the word, or a word that cannot fit would be
    // scrolled again on every frame.
    const bottom = Math.max(Math.min(height * BAND_BOTTOM, height - playerHeight()), top + rect.height);
    if (rect.top >= top && rect.bottom <= bottom) return;
    // TARGET, unless the word would end under the player there: then the
    // middle of what the player leaves.
    const target = height * TARGET + rect.height <= bottom ? height * TARGET : (top + bottom - rect.height) / 2;
    window.scrollBy({ top: rect.top - target, behavior: "smooth" });
  }
}
