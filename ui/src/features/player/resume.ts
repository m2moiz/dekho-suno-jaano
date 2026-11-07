// Where a recording was left playing, kept on its library row (#69), so
// reopening it picks up there instead of at the start. Read from the row the
// page already has (`playhead_s`); written through PUT
// /api/recordings/{id}/playhead when play pauses, every SAVE_EVERY_S while it
// plays, and as the page goes away, with keepalive so that last one lands.

import { api } from "@/api/client";
import { sessionToken } from "@/features/session/session";

// Often enough that a crash loses little; rare enough that a 90-minute play
// writes a few hundred rows, not thousands.
export const SAVE_EVERY_S = 10;

// Within this many seconds of either end there is nothing to come back to.
const EDGE_S = 2;

/**
 * The time to open `duration` seconds of media at, given the row's `playhead_s`:
 * null when it should start from the beginning (never played, left at the
 * very start, or played to the end).
 */
export function resumeAt(playheadS: number | null, duration: number): number | null {
  if (playheadS === null || !Number.isFinite(playheadS) || playheadS < EDGE_S) return null;
  if (Number.isFinite(duration) && playheadS > duration - EDGE_S) return null;
  return playheadS;
}

/** Keep `seconds` as where recording `recordingId` was left. Failure is logged, never shown. */
export function savePlayhead(recordingId: number, seconds: number, { keepalive = false } = {}): Promise<void> {
  if (!Number.isFinite(seconds) || seconds < 0) return Promise.resolve();
  const body = { seconds };
  return api
    .PUT("/api/recordings/{recording_id}/playhead", {
      params: { path: { recording_id: String(recordingId) } },
      body,
      ...(keepalive ? { keepalive: true } : {}),
    })
    .then(({ error }) => {
      if (error !== undefined) console.warn("dsj ui could not keep the playhead", error);
    })
    .catch((thrown: unknown) => {
      console.warn("dsj ui could not keep the playhead", thrown);
    });
}

/**
 * Keep the playhead of `media`, which plays recording `recordingId`, until
 * the returned function is called: on pause, every SAVE_EVERY_S of play, and
 * when the page hides. Nothing is written while the time stays where it was.
 */
export function keepPlayhead(recordingId: number, media: HTMLMediaElement, win: Window = window): () => void {
  let kept = Number.NaN;
  let lastSavedAt = 0;
  const save = (keepalive = false) => {
    const now = media.currentTime;
    if (now === kept) return;
    kept = now;
    void savePlayhead(recordingId, now, { keepalive });
  };
  const paused = () => save();
  const ticked = () => {
    if (media.paused) return;
    if (media.currentTime - lastSavedAt >= SAVE_EVERY_S || media.currentTime < lastSavedAt) {
      lastSavedAt = media.currentTime;
      save();
    }
  };
  const hidden = () => {
    // The token is on the client's own requests; the keepalive one is the same request.
    if (sessionToken() !== null) save(true);
  };
  media.addEventListener("pause", paused);
  media.addEventListener("timeupdate", ticked);
  win.addEventListener("pagehide", hidden);
  return () => {
    media.removeEventListener("pause", paused);
    media.removeEventListener("timeupdate", ticked);
    win.removeEventListener("pagehide", hidden);
    save();
  };
}
