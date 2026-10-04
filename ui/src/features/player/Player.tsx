import { type RefObject, useEffect, useRef, useState } from "react";

import { MuteGate } from "@/features/bleep/liveMute";
import type { Span } from "@/features/edit/editing";

import { Button } from "@/components/ui/button";
import { fromThrown, showError } from "@/features/errors/appError";
import { durationLabel } from "@/features/library/describe";
import type { RecordingRow } from "@/features/library/types";
import { sessionToken } from "@/features/session/session";
import { type Reading, wordAtOffset } from "@/features/transcript/document";
import { offsetAtPoint } from "@/lib/offsetAtPoint";
import { PLAYER_HEIGHT, Playhead } from "./playhead";
import { SpeedControl } from "./SpeedControl";
import { readVideoShown, saveVideoShown } from "./video";
import { Waveform } from "./Waveform";

/**
 * The recording's address, by its library id (#59). A media element sends no
 * headers, so the token rides in the query, which the server accepts on this
 * one route only.
 */
export function mediaSrc(recordingId: number, sound = false): string {
  const token = `t=${encodeURIComponent(sessionToken() ?? "")}`;
  return `/api/recording/${recordingId}/media?${token}${sound ? "&sound=true" : ""}`;
}

// MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED: the browser will not open the file at
// all, as WebKit refused an AV1 one (#110). Not a decode error part-way in.
const NOT_SUPPORTED = 4;

/**
 * Play, and put any refusal in front of the reader, except the one that is no
 * failure: a pause, or a newer seek, that lands before playing starts rejects
 * the play() it interrupted with an AbortError. Seen in chromium on
 * 2026-10-02, a word clicked and paused at once put "The play() request was
 * interrupted by a call to pause()" in the error dialog.
 */
function play(element: HTMLMediaElement): void {
  element.play().catch((thrown: unknown) => {
    if (thrown instanceof DOMException && thrown.name === "AbortError") return;
    showError(fromThrown(thrown));
  });
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

/** What the page can ask of the player, beyond a click on a word. */
export type PlayerControls = {
  /** Play from `from` and stop at `to`, both in seconds: audition one span (#84). */
  hear: (from: number, to: number) => void;
};

type Props = {
  recording: RecordingRow;
  reading: Reading;
  /** The transcript's <article>, whose paragraphs the playhead paints. */
  article: RefObject<HTMLElement | null>;
  /** Spans to play silent, as a render of the edit list would (#84). */
  muteSpans?: readonly Span[] | null;
  /** Filled in with this player's controls while it is mounted. */
  controls?: RefObject<PlayerControls | null>;
};

/**
 * The recording under the transcript (#60): click a word to hear it, and the
 * word being said is highlighted as it plays, with the view following it until
 * the reader scrolls away.
 *
 * A screen recording plays in a <video> on the same playhead, so the picture,
 * the words and the waveform move together (#80); anything else in an <audio>,
 * with no empty picture box.
 */
export function Player({ recording, reading, article, muteSpans = null, controls }: Props) {
  const media = useRef<HTMLMediaElement>(null);
  // A file this browser will not open plays from a copy of its sound instead,
  // which the server makes once and keeps (#110).
  const [soundOnly, setSoundOnly] = useState(false);
  const hasVideo = recording.video_codec !== null && !soundOnly;
  const [videoShown, setVideoShown] = useState(() => readVideoShown());
  const [playing, setPlaying] = useState(false);
  const [noPicture, setNoPicture] = useState(false);
  const clock = useRef<HTMLSpanElement>(null);
  const playhead = useRef<Playhead | null>(null);
  const [following, setFollowing] = useState(true);
  // Views that move with the playhead's frame: the waveform's cursor (#61).
  const [frames] = useState(() => new Set<(seconds: number) => void>());

  // Where an audition stops, in seconds, while one plays (#84).
  const stopAt = useRef<number | null>(null);

  /** Hear `seconds`: the one seek a word, the waveform and anything later share. */
  const seek = (seconds: number) => {
    const element = media.current;
    if (element === null) return;
    // Any seek ends an audition; `hear` sets its stop again after its own.
    stopAt.current = null;
    element.currentTime = seconds;
    playhead.current?.follow();
    play(element);
  };
  const seekRef = useRef(seek);
  seekRef.current = seek;
  // The live mute (#84), one per media element, with the spans it follows.
  const gate = useRef<MuteGate | null>(null);
  const spans = useRef<readonly Span[]>(muteSpans ?? []);

  useEffect(() => {
    spans.current = muteSpans ?? [];
    gate.current?.setSpans(spans.current);
  }, [muteSpans]);

  useEffect(() => {
    if (controls === undefined) return;
    controls.current = {
      hear: (from, to) => {
        seekRef.current(from);
        stopAt.current = to;
      },
    };
    return () => {
      controls.current = null;
    };
  }, [controls]);

  useEffect(() => {
    const element = media.current;
    const root = article.current;
    if (element === null || root === null) return;
    const texts: Text[] = [];
    for (const p of root.querySelectorAll<HTMLElement>("p[data-turn]")) {
      if (p.firstChild instanceof Text) texts[Number(p.dataset["turn"])] = p.firstChild;
    }
    const mute = new MuteGate(element);
    mute.setSpans(spans.current);
    gate.current = mute;
    const head = new Playhead({
      media: element,
      reading,
      texts,
      onFollowing: setFollowing,
      onFrame: (seconds) => {
        mute.update(seconds);
        // An audition ends where it was asked to, on the frame that reaches it.
        if (stopAt.current !== null && seconds >= stopAt.current) {
          stopAt.current = null;
          element.pause();
        }
        for (const frame of frames) frame(seconds);
      },
    });
    playhead.current = head;
    // Made again whenever the words change (an edit, #66), which can happen
    // mid-play: the new loop starts at once rather than at the next `play`.
    if (!element.paused) head.start();

    const started = () => {
      mute.update(element.currentTime);
      head.start();
      setPlaying(true);
    };
    const stopped = () => {
      head.stop();
      setPlaying(false);
    };
    // A video track the browser cannot draw (ProRes in Chromium, measured for
    // #59) plays its sound over a blank box and raises no error, so say so.
    const loaded = () => {
      if (element instanceof HTMLVideoElement) setNoPicture(element.videoWidth === 0);
    };
    const seeked = () => {
      mute.update(element.currentTime);
      if (element.paused) head.paint();
    };
    // Frames stop in a hidden tab and the sound does not: the element's own
    // clock, a few times a second, keeps the mute in step there.
    const ticked = () => mute.update(element.currentTime);
    const failed = () => {
      const code = element.error?.code ?? 0;
      if (code === NOT_SUPPORTED && !soundOnly) {
        setSoundOnly(true);
        return;
      }
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

    element.addEventListener("play", started);
    element.addEventListener("pause", stopped);
    element.addEventListener("ended", stopped);
    element.addEventListener("seeked", seeked);
    element.addEventListener("timeupdate", ticked);
    element.addEventListener("error", failed);
    element.addEventListener("loadedmetadata", loaded);
    root.addEventListener("click", click);
    window.addEventListener("wheel", scrolledByHand, { passive: true });
    window.addEventListener("touchmove", scrolledByHand, { passive: true });
    window.addEventListener("keydown", key);
    return () => {
      element.removeEventListener("play", started);
      element.removeEventListener("pause", stopped);
      element.removeEventListener("ended", stopped);
      element.removeEventListener("seeked", seeked);
      element.removeEventListener("timeupdate", ticked);
      element.removeEventListener("error", failed);
      element.removeEventListener("loadedmetadata", loaded);
      root.removeEventListener("click", click);
      window.removeEventListener("wheel", scrolledByHand);
      window.removeEventListener("touchmove", scrolledByHand);
      window.removeEventListener("keydown", key);
      head.dispose();
      playhead.current = null;
      mute.dispose();
      gate.current = null;
    };
  }, [reading, article, recording.id, frames, soundOnly]);

  // The time, written by the playhead's own frame, for when the picture and
  // its controls are folded away.
  useEffect(() => {
    const tick = (seconds: number) => {
      const duration = media.current?.duration ?? Number.NaN;
      if (clock.current === null) return;
      const total = Number.isFinite(duration) ? ` / ${durationLabel(duration)}` : "";
      clock.current.textContent = `${durationLabel(seconds)}${total}`;
    };
    frames.add(tick);
    return () => {
      frames.delete(tick);
    };
  }, [frames]);

  // The page's scroll padding at the bottom is this bar's height, so anything
  // the browser scrolls into view, a word found with Cmd+F above all, centres
  // in the part of the window the bar leaves uncovered (#230). Without it a
  // match centred in the whole window sat under the picture: the bar is 327 of
  // 600 px tall, 371 of 725 and 422 of 870 with a 640x360 picture showing.
  const bar = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const element = bar.current;
    if (element === null) return;
    const root = document.documentElement;
    const resized = new ResizeObserver(() => {
      root.style.setProperty(PLAYER_HEIGHT, `${element.getBoundingClientRect().height}px`);
    });
    resized.observe(element);
    return () => {
      resized.disconnect();
      root.style.removeProperty(PLAYER_HEIGHT);
    };
  }, []);

  const attach = (element: HTMLMediaElement | null) => {
    media.current = element;
  };
  const src = mediaSrc(recording.id, soundOnly);

  return (
    <div
      ref={bar}
      className="sticky bottom-0 mt-8 flex flex-col gap-2 border-t bg-background/95 py-3 backdrop-blur"
    >
      {hasVideo && (
        // Folded away with display: none, which leaves the element playing.
        <div className={videoShown ? undefined : "hidden"}>
          <video
            ref={attach}
            src={src}
            controls
            playsInline
            preload="metadata"
            className="mx-auto max-h-[35vh] w-full rounded-md bg-black"
            aria-label="Recording"
          />
          {noPicture && (
            <p className="text-sm text-muted-foreground">
              This browser cannot show this recording's picture ({recording.video_codec}). The sound
              plays.
            </p>
          )}
        </div>
      )}
      {soundOnly && (
        <p className="text-sm text-muted-foreground">
          This browser cannot open this recording's file, so a copy of its sound is playing.
        </p>
      )}
      <Waveform
        recordingId={recording.id}
        media={media}
        frames={frames}
        onSeek={(seconds) => seekRef.current(seconds)}
      />
      <div className="flex items-center gap-3">
        {hasVideo ? (
          <>
            {!videoShown && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  const element = media.current;
                  if (element === null) return;
                  if (element.paused) play(element);
                  else element.pause();
                }}
              >
                {playing ? "Pause" : "Play"}
              </Button>
            )}
            <span
              ref={clock}
              className={`flex-1 text-sm text-muted-foreground tabular-nums ${videoShown ? "invisible" : ""}`}
            />
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setVideoShown(!videoShown);
                saveVideoShown(!videoShown);
              }}
            >
              {videoShown ? "Hide picture" : "Show picture"}
            </Button>
          </>
        ) : (
          <audio
            ref={attach}
            src={src}
            controls
            preload="metadata"
            className="h-10 flex-1"
            aria-label="Recording"
          />
        )}
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
