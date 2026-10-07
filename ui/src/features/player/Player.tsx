import { Pause, Play } from "lucide-react";
import { type RefObject, useCallback, useEffect, useRef, useState } from "react";

import { MuteGate } from "@/features/bleep/liveMute";
import type { Span } from "@/features/edit/editing";

import { Button } from "@/components/ui/button";
import { fromThrown, showError } from "@/features/errors/appError";
import { durationLabel } from "@/features/library/describe";
import type { RecordingRow } from "@/features/library/types";
import { sessionToken } from "@/features/session/session";
import { FIELD_BUTTON } from "@/features/shell/field";
import { type Reading, wordAtOffset } from "@/features/transcript/document";
import { offsetAtPoint } from "@/lib/offsetAtPoint";
import { PLAYER_HEIGHT, Playhead } from "./playhead";
import { applySpeed, readSpeed, saveSpeed, type Speed } from "./speed";
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
// somewhere else, so the view stops following the playhead. Not Space: in the
// reader it plays and pauses (readerKeys.ts) and scrolls nothing.
const SCROLL_KEYS = new Set(["PageUp", "PageDown", "ArrowUp", "ArrowDown", "Home", "End"]);

const MEDIA_ERRORS: Record<number, string> = {
  1: "loading was stopped",
  2: "the network failed while loading it",
  3: "the browser could not decode it",
  4: "the browser cannot play this kind of file",
};

/** What a page can ask of the player beyond a click on a word: the reader's Hear, and all of Review. */
export type PlayerControls = {
  /** Play from `from` and stop at `to`, both in seconds: audition one span (#84). */
  hear: (from: number, to: number) => void;
  /** Play, or pause; playing again starts `backS` seconds before where it stopped (Review's Tab). */
  toggle: (backS?: number) => void;
  pause: () => void;
  isPlaying: () => boolean;
  /** Play at `speed` and keep it for later launches (#81). */
  setSpeed: (speed: Speed) => void;
  speed: () => Speed;
};

type Props = {
  recording: RecordingRow;
  reading: Reading;
  /** The transcript's <article>, whose paragraphs the playhead paints. Review has none. */
  article?: RefObject<HTMLElement | null>;
  /** Spans to play silent, as a render of the edit list would (#84). */
  muteSpans?: readonly Span[] | null;
  /** Filled in with this player's controls while it is mounted. */
  controls?: RefObject<PlayerControls | null>;
  /** On a touch screen, a tap on a word selects it for the selection toolbar rather than seeking (Task 3). */
  selectOnTap?: boolean;
};

/**
 * The recording under the transcript (#60), as the blue rail of the Hashiya
 * shell: play, the time, the waveform as the one scrubber, the speed. Click a
 * word to hear it; the word being said is highlighted as it plays, with the
 * view following it until the reader scrolls away. The browser's own audio
 * bar is gone (critique: "two scrubbers").
 *
 * A screen recording plays in a <video> on the same playhead (#80), shown
 * above the rail and folded away with display: none, which keeps it playing.
 */
export function Player({ recording, reading, article, muteSpans = null, controls, selectOnTap = false }: Props) {
  const media = useRef<HTMLMediaElement>(null);
  // A file this browser will not open plays from a copy of its sound instead (#110).
  const [soundOnly, setSoundOnly] = useState(false);
  const hasVideo = recording.video_codec !== null && !soundOnly;
  const [videoShown, setVideoShown] = useState(() => readVideoShown());
  const [playing, setPlaying] = useState(false);
  const [noPicture, setNoPicture] = useState(false);
  const [speed, setSpeedState] = useState<Speed>(() => readSpeed());
  const clock = useRef<HTMLSpanElement>(null);
  const playhead = useRef<Playhead | null>(null);
  const [following, setFollowing] = useState(true);
  // Views that move with the playhead's frame: the waveform's cursor (#61).
  const [frames] = useState(() => new Set<(seconds: number) => void>());
  // Where an audition stops, in seconds, while one plays (#84).
  const stopAt = useRef<number | null>(null);

  const changeSpeed = useCallback((next: Speed) => {
    setSpeedState(next);
    saveSpeed(next);
  }, []);
  const speedNow = useRef(speed);
  speedNow.current = speed;

  useEffect(() => {
    if (media.current !== null) applySpeed(media.current, speed);
  }, [speed, soundOnly]);

  /** Move the one playhead to `seconds` and keep the view with it; any move ends an audition. */
  const scrub = (seconds: number) => {
    const element = media.current;
    if (element === null) return;
    // `hear` sets its stop again after its own seek.
    stopAt.current = null;
    element.currentTime = seconds;
    playhead.current?.follow();
  };
  /** Hear `seconds`: the one seek a word, a click on the waveform and anything later share. */
  const seek = (seconds: number) => {
    scrub(seconds);
    if (media.current !== null) play(media.current);
  };
  const seekRef = useRef(seek);
  seekRef.current = seek;
  const scrubRef = useRef(scrub);
  scrubRef.current = scrub;
  /** Play, or pause; resuming starts `backS` seconds earlier. The rail's button and Review's Tab both. */
  const toggle = (backS = 0) => {
    const element = media.current;
    if (element === null) return;
    if (!element.paused) {
      element.pause();
      return;
    }
    stopAt.current = null;
    if (backS > 0) element.currentTime = Math.max(0, element.currentTime - backS);
    play(element);
  };
  const toggleRef = useRef(toggle);
  toggleRef.current = toggle;
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
      toggle: (backS = 0) => toggleRef.current(backS),
      pause: () => media.current?.pause(),
      isPlaying: () => media.current !== null && !media.current.paused,
      setSpeed: changeSpeed,
      speed: () => speedNow.current,
    };
    return () => {
      controls.current = null;
    };
  }, [controls, changeSpeed]);

  useEffect(() => {
    const element = media.current;
    const root = article?.current ?? null;
    if (element === null) return;
    const texts: Text[] = [];
    if (root !== null) {
      for (const p of root.querySelectorAll<HTMLElement>("p[data-turn]")) {
        if (p.firstChild instanceof Text) texts[Number(p.dataset["turn"])] = p.firstChild;
      }
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
      // On a touch screen a tap selects the word, so the selection toolbar
      // can offer Correct and Hear (Hashiya spec, Reader); a Mac click seeks.
      if (selectOnTap && window.matchMedia("(pointer: coarse)").matches) {
        selectWordAt(reading, texts, word);
        return;
      }
      const at = reading.words.start[word];
      if (at !== undefined) seekRef.current(at);
    };
    const scrolledByHand = () => head.unfollow();
    const key = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing = target?.closest("input, textarea, select, audio, video, button, [contenteditable], [role=slider]");
      if (SCROLL_KEYS.has(event.key) && typing == null) head.unfollow();
    };

    element.addEventListener("play", started);
    element.addEventListener("pause", stopped);
    element.addEventListener("ended", stopped);
    element.addEventListener("seeked", seeked);
    element.addEventListener("timeupdate", ticked);
    element.addEventListener("error", failed);
    element.addEventListener("loadedmetadata", loaded);
    root?.addEventListener("click", click);
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
      root?.removeEventListener("click", click);
      window.removeEventListener("wheel", scrolledByHand);
      window.removeEventListener("touchmove", scrolledByHand);
      window.removeEventListener("keydown", key);
      head.dispose();
      playhead.current = null;
      mute.dispose();
      gate.current = null;
    };
  }, [reading, article, recording.id, frames, soundOnly, selectOnTap]);

  // The time, written by the playhead's own frame.
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

  // The page's scroll padding at the bottom is this rail's height (#230), and
  // the playhead's follow band ends where it starts (#231).
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
  // The recording's length as the library knows it, until the media says it.
  const clockLabel = durationLabel(recording.duration_s) ?? "0:00";

  return (
    <div ref={bar} role="region" aria-label="Player" className="sticky bottom-0 z-20 pb-[env(safe-area-inset-bottom)]">
      {hasVideo && (
        <div className={videoShown ? "border-t bg-background/95 px-3 py-2 backdrop-blur sm:px-6" : "hidden"}>
          <video ref={attach} src={src} playsInline preload="metadata" className="mx-auto max-h-[35vh] w-full rounded-md bg-black" aria-label="Recording" />
          {noPicture && (
            <p className="text-sm text-muted-foreground">
              This browser cannot show this recording's picture ({recording.video_codec}). The sound plays.
            </p>
          )}
        </div>
      )}
      {soundOnly && (
        <p className="bg-field px-4 pt-2 text-sm text-field-muted">
          This browser cannot open this recording's file, so a copy of its sound is playing.
        </p>
      )}
      {!hasVideo && <audio ref={attach} src={src} preload="metadata" aria-label="Recording" className="hidden" />}
      <div className="bg-field text-field-foreground">
        <div className="mx-auto flex h-14 w-full max-w-6xl items-center gap-2 px-2 sm:gap-3 sm:px-6">
          {/* The rail's one gold primary: the default variant, which is gold. */}
          <Button
            size="icon"
            aria-label={playing ? "Pause" : "Play"}
            onClick={() => toggleRef.current()}
            className="size-11 shrink-0 rounded-full"
          >
            {playing ? <Pause aria-hidden className="size-5" /> : <Play aria-hidden className="size-5" />}
          </Button>
          {/* Wide enough for its longest text from the first paint, so the waveform
              beside it does not shrink when playing writes the length in. */}
          <span
            ref={clock}
            style={{ minWidth: `${2 * clockLabel.length + 3}ch` }}
            className="hidden shrink-0 text-sm text-field-muted tabular-nums sm:inline"
          >
            {`0:00 / ${clockLabel}`}
          </span>
          <Waveform recordingId={recording.id} media={media} frames={frames} onSeek={(seconds) => seekRef.current(seconds)} onScrub={(seconds) => scrubRef.current(seconds)} />
          <SpeedControl speed={speed} onSpeed={changeSpeed} />
          {hasVideo && (
            <Button
              variant="ghost"
              className={`h-11 shrink-0 ${FIELD_BUTTON}`}
              onClick={() => {
                setVideoShown(!videoShown);
                saveVideoShown(!videoShown);
              }}
            >
              {videoShown ? "Hide picture" : "Show picture"}
            </Button>
          )}
          {!following && (
            <Button
              variant="ghost"
              className={`h-11 shrink-0 ${FIELD_BUTTON}`}
              onClick={() => playhead.current?.follow()}
            >
              Follow playback
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

/** Select word `word` in its paragraph's text, without the space in front of it. */
function selectWordAt(reading: Reading, texts: Text[], word: number): void {
  const { turn, offset, length } = reading.words;
  const text = texts[turn[word] ?? -1];
  if (text === undefined) return;
  const from = offset[word] ?? 0;
  const to = from + (length[word] ?? 0);
  const lead = /^\s*/.exec(text.data.slice(from, to))?.[0].length ?? 0;
  const range = document.createRange();
  range.setStart(text, from + lead);
  range.setEnd(text, to);
  const selection = window.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(range);
}
