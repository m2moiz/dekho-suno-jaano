import { type RefObject, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { fromThrown, showError } from "@/features/errors/appError";
import type { RecordingRow } from "@/features/library/types";
import { sessionToken } from "@/features/session/session";
import { type Reading, wordAtOffset } from "@/features/transcript/document";
import { offsetAtPoint } from "@/lib/offsetAtPoint";
import { Playhead } from "./playhead";
import { SpeedControl } from "./SpeedControl";
import { Waveform } from "./Waveform";

/**
 * The recording's address, by its library id (#59). A media element sends no
 * headers, so the token rides in the query, which the server accepts on this
 * one route only.
 */
export function mediaSrc(recordingId: number): string {
  return `/api/recording/${recordingId}/media?t=${encodeURIComponent(sessionToken() ?? "")}`;
}

// Keys that scroll the page. Pressing one means the reader wants to look
// somewhere else, so the view stops following the playhead.
const SCROLL_KEYS = new Set(["PageUp", "PageDown", "ArrowUp", "ArrowDown", "Home", "End", " "]);

const MEDIA_ERRORS: Record<number, string> = {
  1: "loading was stopped",
  2: "the network failed while loading it",
  3: "the browser could not decode it",
  4: "the browser cannot play this kind of file",
};

type Props = {
  recording: RecordingRow;
  reading: Reading;
  /** The transcript's <article>, whose paragraphs the playhead paints. */
  article: RefObject<HTMLElement | null>;
};

/**
 * The recording under the transcript (#60): click a word to hear it, and the
 * word being said is highlighted as it plays, with the view following it until
 * the reader scrolls away.
 */
export function Player({ recording, reading, article }: Props) {
  const media = useRef<HTMLAudioElement>(null);
  const playhead = useRef<Playhead | null>(null);
  const [following, setFollowing] = useState(true);
  // Views that move with the playhead's frame: the waveform's cursor (#61).
  const [frames] = useState(() => new Set<(seconds: number) => void>());

  /** Hear `seconds`: the one seek a word, the waveform and anything later share. */
  const seek = (seconds: number) => {
    const element = media.current;
    if (element === null) return;
    element.currentTime = seconds;
    playhead.current?.follow();
    element.play().catch((thrown: unknown) => showError(fromThrown(thrown)));
  };
  const seekRef = useRef(seek);
  seekRef.current = seek;

  useEffect(() => {
    const element = media.current;
    const root = article.current;
    if (element === null || root === null) return;
    const texts: Text[] = [];
    for (const p of root.querySelectorAll<HTMLElement>("p[data-turn]")) {
      if (p.firstChild instanceof Text) texts[Number(p.dataset["turn"])] = p.firstChild;
    }
    const head = new Playhead({
      media: element,
      reading,
      texts,
      onFollowing: setFollowing,
      onFrame: (seconds) => {
        for (const frame of frames) frame(seconds);
      },
    });
    playhead.current = head;

    const play = () => head.start();
    const pause = () => head.stop();
    const seeked = () => {
      if (element.paused) head.paint();
    };
    const failed = () => {
      const code = element.error?.code ?? 0;
      const detail = element.error?.message ? ` ${element.error.message}` : "";
      showError({
        error: "MediaError",
        message: `The recording could not be played: ${MEDIA_ERRORS[code] ?? `media error ${code}`}.${detail}`,
        // The path only: the query holds the token, and this text is copied.
        request: `/api/recording/${recording.id}/media`,
      });
    };
    const click = (event: MouseEvent) => {
      // A drag that selected text is a selection, not a seek.
      if (event.button !== 0 || window.getSelection()?.isCollapsed === false) return;
      const hit = offsetAtPoint(event);
      if (hit === null) return;
      const word = wordAtOffset(reading, hit.turn, hit.offset);
      const at = reading.words.start[word];
      if (at !== undefined) seekRef.current(at);
    };
    const scrolledByHand = () => head.unfollow();
    const key = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing = target?.closest("input, textarea, select, audio, video, button, [contenteditable]");
      if (SCROLL_KEYS.has(event.key) && typing == null) head.unfollow();
    };

    element.addEventListener("play", play);
    element.addEventListener("pause", pause);
    element.addEventListener("ended", pause);
    element.addEventListener("seeked", seeked);
    element.addEventListener("error", failed);
    root.addEventListener("click", click);
    window.addEventListener("wheel", scrolledByHand, { passive: true });
    window.addEventListener("touchmove", scrolledByHand, { passive: true });
    window.addEventListener("keydown", key);
    return () => {
      element.removeEventListener("play", play);
      element.removeEventListener("pause", pause);
      element.removeEventListener("ended", pause);
      element.removeEventListener("seeked", seeked);
      element.removeEventListener("error", failed);
      root.removeEventListener("click", click);
      window.removeEventListener("wheel", scrolledByHand);
      window.removeEventListener("touchmove", scrolledByHand);
      window.removeEventListener("keydown", key);
      head.dispose();
      playhead.current = null;
    };
  }, [reading, article, recording.id, frames]);

  return (
    <div className="sticky bottom-0 mt-8 flex flex-col gap-2 border-t bg-background/95 py-3 backdrop-blur">
      <Waveform
        recordingId={recording.id}
        media={media}
        frames={frames}
        onSeek={(seconds) => seekRef.current(seconds)}
      />
      <div className="flex items-center gap-3">
        <audio
          ref={media}
          src={mediaSrc(recording.id)}
          controls
          preload="metadata"
          className="h-10 flex-1"
          aria-label="Recording"
        />
        <SpeedControl media={media} />
        {!following && (
          <Button variant="outline" size="sm" onClick={() => playhead.current?.follow()}>
            Follow playback
          </Button>
        )}
      </div>
    </div>
  );
}
