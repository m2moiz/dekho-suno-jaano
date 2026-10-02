// Playback speed, 0.5x to 2x, kept between launches (#81).
//
// In a cookie, as the theme is (ui/src/features/theme/theme.ts), not in
// localStorage: every `dsj ui` binds a new port and localStorage is kept per
// port, while a cookie on 127.0.0.1 is shared by them all (#116).
//
// Quarter steps from half speed to double. transcribee's list, the model #81
// names, is 0.5, 0.7, 1.0, 1.2, 1.5, 1.7, 2.0 (ui-common/editor/player.tsx:482,
// read 2026-10-02): the same seven steps, written to one decimal place.

export const SPEEDS = [0.5, 0.75, 1, 1.25, 1.5, 1.75, 2] as const;
export type Speed = (typeof SPEEDS)[number];

export const COOKIE = "dsj-speed";
// A year, renewed on every change, as the theme's.
const MAX_AGE_S = 60 * 60 * 24 * 365;

function isSpeed(value: number): value is Speed {
  return (SPEEDS as readonly number[]).includes(value);
}

/** The saved speed, or 1 when nothing (or nothing sensible) is saved. */
export function readSpeed(doc: Document = document): Speed {
  const found = new RegExp(`(?:^|; )${COOKIE}=([^;]*)`).exec(doc.cookie)?.[1];
  const value = Number(found);
  return found !== undefined && isSpeed(value) ? value : 1;
}

/** Keep `speed` for every later launch. */
export function saveSpeed(speed: Speed, doc: Document = document): void {
  doc.cookie = `${COOKIE}=${speed}; path=/; max-age=${MAX_AGE_S}; SameSite=Strict`;
}

/**
 * Play `media` at `speed`, voice at its own pitch. preservesPitch is true by
 * default and unprefixed from Safari 17.2, Chrome 86 and Firefox 101 (MDN
 * browser-compat-data 8.1.2, read 2026-10-02), so it is set rather than
 * trusted: the same Safari floor as the Highlight API the reader already needs.
 * The default rate too, because loading a source resets the rate to it.
 */
export function applySpeed(media: HTMLMediaElement, speed: Speed): void {
  media.preservesPitch = true;
  media.defaultPlaybackRate = speed;
  media.playbackRate = speed;
}

export function speedLabel(speed: number): string {
  return `${speed}×`;
}
