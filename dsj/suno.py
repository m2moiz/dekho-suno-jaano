"""Transcribe a media file to a timestamped index, with live progress.

The transcript is dsj' index into the video, so this is the one step that
must not fail quietly. Progress is reported two ways at once: a live line on
the terminal, and a JSON status file that a detached run can be inspected
through. Background jobs are the normal case here -- an hour of audio is not
something you sit and watch -- and a run you cannot inspect is a run you cannot
trust.
"""

from __future__ import annotations

__all__ = [
    "CHUNK_S",
    "DEFAULT_MODEL",
    "DEFAULT_WHISPER_MODEL",
    "ENGINES",
    "LOOP_REASON",
    "LOUDNESS_FRAME_S",
    "NO_SPEECH_REASON",
    "OVERLAP_S",
    "RETRY_LOOPS",
    "STALL_S",
    "Progress",
    "Terminated",
    "clock",
    "is_loop",
    "main",
    "render_bar",
    "reports_progress",
    "roman_urdu",
    "silences",
    "transcribe",
]

import json
import logging
import os
import re
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import numpy as np

# Imported as media_mod because the parameter it serves is named `media` and
# would shadow the module inside the function body.
from dsj import filetag
from dsj import media as media_mod
from dsj.asr import ENGINES, Transcription, get_engine, with_char_offsets
from dsj.atomic import atomic_write_text

# Names only -- both engine modules keep their backends lazy, so pulling
# these in costs nothing to a run that never asks for the engine, and it
# keeps `--help` able to print the defaults.
from dsj.parakeet import DEFAULT_MODEL
from dsj.whisper import DEFAULT_WHISPER_MODEL, redecoder
from dsj.whisper import SAMPLE_RATE as WHISPER_SAMPLE_RATE

if TYPE_CHECKING:
    from numpy.typing import NDArray

    from dsj.alignment import AlignedToken

# The transcript is JSON, so its two nested shapes are plain dicts rather than
# dataclasses -- json.dumps is the only consumer here, and a schema class would
# have to be flattened right back. Naming them keeps the signatures below
# honest about which dict is which without pretending to more structure than
# the on-disk document has.
type Sentence = dict[str, Any]
type Payload = dict[str, Any]

# Module logger, not print: transcribe() is the import surface the frame-
# retrieval half will call, and a library that writes to stderr unasked is a
# library that cannot be embedded. main() attaches the stderr handler, so the
# CLI behaves exactly as before.
logger = logging.getLogger("dsj.suno")

# parakeet-mlx defaults chunk_duration to None, which feeds the whole file to
# Metal in one buffer. An hour of audio asks for ~14.5GB against a ~9.5GB max
# buffer and dies. Chunking is not optional at meeting length -- and it is also
# what makes chunk_callback fire, so progress reporting depends on it too.
CHUNK_S = 120.0
OVERLAP_S = 15.0

# How long ffmpeg's position may stand still before the heartbeat says so (#164).
# On 2026-09-22 an extraction sat at 4:20 of 27:52 for 15 minutes 23 seconds and
# then finished, while the status kept reading `extracting` with nothing to show
# that it had stopped moving. Healthy extraction runs about a thousand times
# realtime and reports twice a second, so a minute without one advance is
# nothing a healthy run does. It is reported, never acted on: why that one
# stalled is not known, and killing a job that would have finished is worse
# than saying it has stopped.
STALL_S = 60.0


@dataclass
class Progress:
    """One sample of how far a transcription has got, and how fast."""

    audio_done_s: float
    audio_total_s: float
    elapsed_s: float
    # Audio already transcribed by an earlier run. Without it a resumed job
    # reports a fictional 300x, because it credits this run's clock with work a
    # previous one paid for -- and the ETA built on that speed is wrong by the
    # same factor, in the optimistic direction.
    resumed_from_s: float = 0.0

    @property
    def fraction(self) -> float:
        """Share of the audio transcribed so far, 0.0 when the total is unknown."""
        return self.audio_done_s / self.audio_total_s if self.audio_total_s else 0.0

    @property
    def speed(self) -> float:
        """Realtime multiple: seconds of audio per second of wall clock.

        Measured over this run's own work, so it stays a truthful estimate of
        what the remaining audio will cost.
        """
        done = self.audio_done_s - self.resumed_from_s
        return done / self.elapsed_s if self.elapsed_s else 0.0

    @property
    def eta_s(self) -> float | None:
        """Seconds of wall clock left at the current speed, or None if not moving yet."""
        if self.speed <= 0:
            return None
        return (self.audio_total_s - self.audio_done_s) / self.speed


def clock(seconds: float | None) -> str:
    """Render a duration as m:ss, or h:mm:ss once it passes an hour.

    None is "--:--" and NOT "0:00": a run whose total duration ffprobe could
    not determine has no elapsed time to show, and printing zero would claim it
    finished instantly.
    """
    if seconds is None:
        return "--:--"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def render_bar(p: Progress, state: str, width: int = 24) -> str:
    """Render one progress line: phase, bar, audio clocks, speed and ETA."""
    filled = int(p.fraction * width)
    bar = "#" * filled + "-" * (width - filled)
    return (
        f"{state:>10} [{bar}] {p.fraction * 100:3.0f}%  "
        f"{clock(p.audio_done_s)}/{clock(p.audio_total_s)} audio  "
        f"elapsed {clock(p.elapsed_s)}  eta {clock(p.eta_s)}  {p.speed:.1f}x"
    )


def _make_chunk_callback(
    rate: float,
    clock: Callable[[], float],
    emit: Callable[[Progress], None],
    resumed_from_s: float = 0.0,
) -> Callable[[float, float], None]:
    """Build the per-chunk progress callback.

    `current` and `full` arrive in SAMPLES, not seconds -- the sample counts
    parakeet-mlx passes its own callback, which dsj/chunking.py preserves.
    Upstream only ever feeds them to a ratio, so the units never mattered there.
    Dividing by `rate` is the whole point of this function, and a ratio-only
    assertion cannot see whether it happened, because the units cancel.
    """

    def chunk_callback(current: float, full: float) -> None:
        emit(Progress(current / rate, full / rate, clock(), resumed_from_s))

    return chunk_callback


def _text_from_tokens(transcription: Transcription) -> Transcription:
    """`transcription` with each sentence's `text` rebuilt as its tokens joined.

    dsj writes every sentence twice, as `text` and as `tokens`, and at a chunk
    seam the two disagreed. The vendored splitter glues `text` in the order the
    merge emitted the words (dsj/alignment.py:149), then AlignedSentence sorts
    the tokens by time (:76) and leaves `text` alone. Measured on three real
    transcripts (#106): 16 of 480, 23 of 664 and 32 of 1038 sentences, every one
    at a seam and every one the same words in another order. A reader saw one
    order and a click on a word played the other.

    The tokens win because they carry the times, and time order is what the
    file promises everywhere else (see _in_time_order). The cost is that about
    1% of sentences read slightly scrambled at a seam, which is what the
    alignment says happened there. Done here rather than in alignment.py,
    which tests/test_chunking.py holds to the upstream copy.

    whisper passes through too. Its segment text was stripped while each word
    kept its leading space (dsj/whisper.py:_sentences_from), so every whisper
    sentence was one character short of its words joined; now it is not, and
    the sentences of every engine glue with nothing. A segment with no words
    gets an empty `text`, which is also what mlx-whisper leaves in the empty
    and zero-length segments it clears (mlx_whisper/transcribe.py:506-514).

    The top-level `text` is rebuilt from the sentences to match.
    """
    sentences = [
        s | {"text": "".join(str(t["w"]) for t in s["tokens"])}
        for s in transcription.sentences
    ]
    return Transcription(
        text="".join(str(s["text"]) for s in sentences).strip(), sentences=sentences
    )


def _in_whole_milliseconds(transcription: Transcription) -> Transcription:
    """`transcription` with each sentence's `start` and `end` in whole milliseconds.

    #174 rounded every token's `t` and `e` to the millisecond, but the sentences
    built from the same times kept their float noise, so a first token could
    sit about 1e-14 s before the sentence it belongs to (#175). The bounds are
    also widened to cover the words, so `start <= first t` and `end >= last e`
    hold whatever an engine's own segment bounds say. Done where both engine
    branches meet, before the sort, so the sort compares the rounded times.
    """
    sentences: list[Sentence] = []
    for s in transcription.sentences:
        start, end = round(s["start"], 3), round(s["end"], 3)
        tokens = s["tokens"]
        if tokens:
            start = min(start, min(t["t"] for t in tokens))
            end = max(end, max(t.get("e", t["t"]) for t in tokens))
        sentences.append({**s, "start": start, "end": end})
    return transcription._replace(sentences=sentences)


def _in_time_order(transcription: Transcription) -> Transcription:
    """`transcription` with its sentences earliest first, and `text` rebuilt to match.

    Returned untouched when the sentences already run forwards, which is every
    recording short enough to decode in one piece and every engine that makes
    one pass over the file.

    The disorder this repairs is made at a chunk seam. The overlap merge splices
    two independently timed decodes of the same audio and checks no join
    (dsj/alignment.py:242 and :336), so a word the earlier chunk timed can be
    emitted after a word the later chunk timed. Measured on scratch/meeting.wav
    by scratch/seam_probe.py, which captures every chunk the real engine decodes
    and every list the merge returns: 31 backwards steps in 14,394 merged tokens,
    reaching the transcript as 3 backwards sentences in 664. Reproduced against
    the transcripts on disk by scratch/order_probe.py: 8 in 1038, 3 in 664, 4 in
    480, 0 in every recording under one chunk.

    This is a fix at the symptom, deliberately. The cause is the merge, and
    tests/test_chunking.py holds that merge to the one dsj vendored from
    parakeet-mlx, so repairing it there is a divergence from upstream rather
    than a bug fix. Tightening the merge's own pairing tolerance, which is what
    lets it splice a full stop onto a different full stop seconds away, does not
    reach it either: scratch/seam_replay.py over the same capture counts 31
    backwards steps at the shipped 7.5s, 7 at 1.0s and 2 at 0.1s. So the order
    is put right here and the mistimed word is left mistimed: a sentence at a
    seam sorts to where its earliest token claims it began, which is up to
    5.72s before it was actually said.

    Stable, so sentences sharing a start keep the order the engine gave them.

    `text` is re-glued with nothing: after _text_from_tokens every sentence,
    whatever the engine, carries its own leading space.

    Args:
        transcription: What an engine returned, in the order it returned it.
    """
    starts = [cast("float", s["start"]) for s in transcription.sentences]
    if starts == sorted(starts):
        return transcription
    ordered = sorted(transcription.sentences, key=lambda s: cast("float", s["start"]))
    return Transcription(
        text="".join(str(s["text"]) for s in ordered).strip(), sentences=ordered
    )


# A word for is_loop: letters and digits, with one inner apostrophe allowed, so
# "don't" is one word and punctuation is never one. The pattern
# scratch/real_bench.py measured the rule with.
_WORD = re.compile(r"[^\W_]+(?:'[^\W_]+)?")

LOOP_REASON = "repetition loop"


def is_loop(text: str) -> bool:
    """A repetition loop: more than six words, and at most a third of them distinct.

    Words are compared lowercased with punctuation stripped. Never fewer than two
    distinct are allowed, so up to nine words the rule is "more than six words,
    at most two distinct", which is what whisper's worst loops are: one Urdu
    letter repeated 100 to 200 times across a whole window (#140).

    A third is a measured cutoff, not a guess. Measured 2026-09-23 over four
    whisper transcripts of the owner's recordings, a parakeet transcript of an
    English call and whisper's transcript of #148's public fixture: every loop
    is at most 29% distinct (6 of 21), and every other sentence of more than six
    words is at least 43% distinct (3 of 7), so any cutoff between the two
    catches the same sentences. A third sits inside that range with room on
    both sides. scratch/real_bench.py imports this, so the benchmark and the
    product count loops by one rule.
    """
    words = [w.lower() for w in _WORD.findall(text)]
    return len(words) > 6 and len(set(words)) <= max(2, len(words) / 3)


def _without_loops(transcription: Transcription) -> tuple[Transcription, list[dict[str, Any]]]:
    """`transcription` with its repetition loops taken out, and where they were.

    whisper sometimes decodes a whole window as one letter or a short phrase
    repeated (#140), and the loop text says nothing about what was there. On
    the owner's recordings the audio under the loops is as loud as the speech
    around them, so most mark speech whisper failed to read. The one measured
    over silence, on #148's public fixture, is taken out before this by
    _without_silence and reported as no speech (#181). Left in, a
    reader gets 200 copies of a letter, and a search or a summary counts them
    as words. Simply dropped, the reader would see a gap and could not tell a
    failed stretch from a quiet one.

    So each loop sentence leaves `sentences` and becomes one entry of the
    payload's `unclear` list: its `start` and `end`, `reason`, and how many
    words the loop had. Its text is not kept. Done after _in_time_order, so
    `unclear` runs earliest first too, and `text` is rebuilt from what is left.
    Under parakeet and sherpa the rule catches nothing, measured on the English
    call above, and the transcription passes through untouched.
    """
    kept: list[Sentence] = []
    unclear: list[dict[str, Any]] = []
    for s in transcription.sentences:
        text = str(s["text"])
        if is_loop(text):
            unclear.append(
                {
                    "start": s["start"],
                    "end": s["end"],
                    "reason": LOOP_REASON,
                    "words": len(_WORD.findall(text)),
                }
            )
        else:
            kept.append(s)
    if not unclear:
        return transcription, unclear
    return (
        Transcription(text="".join(str(s["text"]) for s in kept).strip(), sentences=kept),
        unclear,
    )


# Text over silence (#181). whisper writes words where nobody speaks: about 220
# over the 60 s of -60 dB noise in #148's fixture, at every anomaly-switch
# setting. So after decoding, a run of LOUDNESS_FRAME_S frames all quieter than
# SILENCE_DB that lasts SILENCE_MIN_S or more is silence, and a word that starts
# more than SILENCE_EDGE_S inside one is taken out.
#
# Measured 2026-10-02 by scratch/speech_loudness.py over 41 transcripts and
# 84,153 words of #148's fixture and the owner's five recordings, no model run
# (numbers on #181):
#
# - The fixture's gaps are -60.0 dB RMS, loudest 0.1 s frame -59.7.
#   SILENCE_DB is 4.7 dB above that.
# - Inside the fixture's real speech no run of frames below -55 dB lasts longer
#   than 0.5 s, so SILENCE_MIN_S is ten times the longest. The loudest frame
#   within 1 s of a word's start is -21.1 dB or louder for 99.9% of its words.
# - On the owner's files the rule finds runs on one file only, 094234, all in
#   a passage from 19:51 to 25:34 whose frames have a median of -75 dB, where
#   whisper's words repeat (1 to 16 distinct among 7 to 67 per transcript).
#   -50 dB, or 3 s, would already take 12 or 13 words on 101117 from quiet runs
#   of 3.5 to 5.9 s that nothing shows to be empty.
# - Edges: whisper starts a real word up to 0.52 s before the speech it belongs
#   to (17 words at the fixture's gap ends across 10 transcripts, 11 of them the
#   next clip's first word), so a word that close to an edge stays.
# - Every level above is the source media decoded to float, 16 kHz mono, and
#   transcribe() reads it the same way (#193). The owner's files are stereo,
#   and the 16-bit wav dsj extracts from them reads 3.01 dB quieter, enough to
#   find silences on 101117 that are not there.
LOUDNESS_FRAME_S = 0.1
SILENCE_DB = -55.0
SILENCE_MIN_S = 5.0
SILENCE_EDGE_S = 1.0
NO_SPEECH_REASON = "no speech"


def silences(
    frame_db: NDArray[np.float64], frame_s: float = LOUDNESS_FRAME_S
) -> list[tuple[float, float]]:
    """Every run of frames below SILENCE_DB lasting SILENCE_MIN_S or more, as (start, end) seconds.

    `frame_db` is dsj.media.loudness's output, one dBFS value per `frame_s`.
    """
    quiet = np.concatenate([[False], frame_db < SILENCE_DB, [False]]).astype(np.int8)
    edges = np.flatnonzero(np.diff(quiet))
    min_frames = round(SILENCE_MIN_S / frame_s)
    return [
        (round(float(a * frame_s), 3), round(float(b * frame_s), 3))
        for a, b in zip(edges[::2].tolist(), edges[1::2].tolist(), strict=True)
        if b - a >= min_frames
    ]


def _without_silence(
    transcription: Transcription, stretches: list[tuple[float, float]]
) -> tuple[Transcription, list[dict[str, Any]]]:
    """`transcription` without the words whisper wrote over silence, and where they were.

    A token whose `t` lies more than SILENCE_EDGE_S inside one of `stretches`
    leaves its sentence; a sentence left with no tokens leaves `sentences`, and
    one left with some is rebuilt from them, its `text`, bounds and
    `charOffset`s included. Each stretch that lost a token becomes one entry of
    the payload's `unclear` list: its `start` and `end`, `reason` "no speech",
    and how many words were taken from it. That is what tells it apart from a
    repetition loop, which marks loud audio whisper failed to read (#140).

    Done before _without_loops: a loop over silence (the fixture's 60 s gap) is
    a stretch with no speech, not a stretch whisper could not read, so it is
    reported as the first. A loop over loud audio is still a loop.
    """
    inner = [(a + SILENCE_EDGE_S, b - SILENCE_EDGE_S) for a, b in stretches]
    words = [0] * len(stretches)
    hit = [False] * len(stretches)
    kept: list[Sentence] = []
    changed = False
    for s in transcription.sentences:
        tokens: list[dict[str, Any]] = s["tokens"]
        keep: list[dict[str, Any]] = []
        for t in tokens:
            where = next((i for i, (a, b) in enumerate(inner) if a <= t["t"] < b), None)
            if where is None:
                keep.append(t)
            else:
                hit[where] = True
                words[where] += len(_WORD.findall(str(t["w"])))
        if len(keep) == len(tokens):
            kept.append(s)
            continue
        changed = True
        if keep:
            kept.append(
                s
                | {
                    "start": min(t["t"] for t in keep),
                    "end": max(t.get("e", t["t"]) for t in keep),
                    "text": "".join(str(t["w"]) for t in keep),
                    "tokens": with_char_offsets(keep),
                }
            )
    unclear = [
        {"start": a, "end": b, "reason": NO_SPEECH_REASON, "words": n}
        for (a, b), n, h in zip(stretches, words, hit, strict=True)
        if h
    ]
    if not changed:
        return transcription, unclear
    return (
        Transcription(text="".join(str(s["text"]) for s in kept).strip(), sentences=kept),
        unclear,
    )


# Decoding a loop span again (#183). A loop is not a fixed property of the
# audio: two identical runs on 094234 gave 86 and 343 loop seconds (#100). So
# after a whisper run, the part of each loop's span that is not silence and
# that no other sentence covers is cut out with RETRY_PAD_S either side and
# decoded alone, first with RETRY_PLAIN, then, only if that loops or returns
# RETRY_MIN_WORDS words or fewer, with RETRY_WARM. The first result with no
# loop sentence and more than RETRY_MIN_WORDS words inside that part replaces
# the loop; a span both fail stays a loop and goes to `unclear` as before.
# Under --roman-urdu the two are language ur with no prompt at temperature 0,
# and the Roman prompt at temperature 0.4.
#
# Measured 2026-10-02 by scratch/redecode_probe.py (#183): 38 loop spans, 818
# loop seconds, of four 120 s anchored turbo transcripts of the owner's
# recordings 101117, 094234 (two runs) and 171500. Each option alone recovered
# 18 to 24 spans; plain then warm recovered 29 spans and 665 s (81%). Plain
# first because it recovered the most on its own (24 spans, 531 s); warm
# second because on 171500, mostly English, plain looped on 4 of 9 spans where
# the prompted settings did not. Each retry took 1 to 10 s on a 30 s clip.
# The same four transcripts through this code (scratch/retry_loops_run.py):
# 26 of the 37 spans it retried recovered, 551 of their 787 loop seconds,
# 1,494 words added, 42 to 129 s of wall time a file, and no sentence overlap
# added. Fewer than the probe, for two measured reasons: two spans the probe
# counted were almost wholly inside a neighbour (0.4 and 3.8 s left unread),
# so its words there were duplicates; and warm samples at temperature 0.4, so
# a span it reads on one run it can miss on the next (two did on 171500, one
# went the other way). Not yet measured: whether the recovered text is right
# (#182 is the check).
#
# parakeet and sherpa never retry: is_loop catches nothing they write, and
# neither has a second set of settings to try. RETRY_LOOPS = False turns it
# off.
RETRY_LOOPS = True
RETRY_PAD_S = 2.0
RETRY_MIN_WORDS = 5
RETRY_PLAIN: dict[str, Any] = {"initial_prompt": None, "temperature": 0.0}
RETRY_WARM: dict[str, Any] = {"temperature": 0.4}

type Decode = Callable[[float, float, dict[str, Any]], list[Sentence]]


def _within(sentences: list[Sentence], start: float, end: float) -> list[Sentence]:
    """`sentences` cut to the words that start in [start, end), each ending by `end`.

    A retry decodes RETRY_PAD_S either side of the span so whisper hears the
    words around it whole, and those words are already in the sentences on
    either side. Kept, they would be written twice.
    """
    out: list[Sentence] = []
    for s in sentences:
        tokens = [
            t | {"e": min(cast("float", t.get("e", t["t"])), end)}
            for t in cast("list[dict[str, Any]]", s["tokens"])
            if start <= t["t"] < end
        ]
        if tokens:
            out.append(
                {
                    "start": min(t["t"] for t in tokens),
                    "end": max(t["e"] for t in tokens),
                    "text": "".join(str(t["w"]) for t in tokens),
                    "tokens": with_char_offsets(tokens),
                }
            )
    return out


def _unread(start: float, end: float, others: list[Sentence]) -> tuple[float, float]:
    """The part of [start, end) that no sentence in `others` covers, as (lo, hi).

    A loop's span can share seconds with a neighbour. Before #190 every
    anchored seam made one: a loop at the end of one window lay inside the
    next window's first sentence (#183: on #148's fixture, 221 words timed
    into 803.94 to 803.98 s, inside a sentence from 798.0 to 825.3 s), and
    whisper's sentences can still run into a loop's span from either side.
    Those seconds were read already. A
    neighbour that runs into the span from before moves `lo` to its end; one
    that starts inside the span moves `hi` to its start. `lo >= hi` means
    nothing is left to read. `others` must be sorted by start.
    """
    lo, hi = start, end
    for o in others:
        if o["start"] <= lo < o["end"]:
            lo = cast("float", o["end"])
    for o in others:
        if lo < o["start"] < hi:
            hi = cast("float", o["start"])
    return lo, hi


def _retried(
    transcription: Transcription,
    stretches: list[tuple[float, float]],
    decoder: Callable[[], Decode],
    report: Callable[[Progress, str], None],
) -> Transcription:
    """`transcription` with each loop decoded again, and replaced where the retry reads.

    Done after _without_silence and before _without_loops: a loop over silence
    has already left as no speech, and a loop sentence whose span still crosses
    a silent stretch is not retried either, so no retry can write over silence.
    `decoder` is called once, and only when there is a loop to retry, because
    it loads the audio.

    Only the part of a loop's span that no other sentence covers is read again
    (_unread), and the replacement is cut to it (_within), so a retried word
    never lands inside a neighbour and nothing is written twice. A loop with no
    such part is not retried and stays a loop. The result is put back in time
    order all the same.

    Reports state "retrying" once before the first span and once after each,
    counting the seconds to be read again, so a long run does not look stuck.
    """
    inner = [(a + SILENCE_EDGE_S, b - SILENCE_EDGE_S) for a, b in stretches]
    sentences = transcription.sentences
    loops = [is_loop(str(s["text"])) for s in sentences]
    read = [s for s, looped in zip(sentences, loops, strict=True) if not looped]
    todo: list[tuple[int, float]] = []
    for i, s in enumerate(sentences):
        if not loops[i] or any(s["start"] < b and a < s["end"] for a, b in inner):
            continue
        lo, hi = _unread(s["start"], s["end"], read)
        if lo < hi:
            todo.append((i, hi - lo))
    if not todo:
        return transcription
    total = sum(length for _, length in todo)
    started = time.monotonic()
    report(Progress(0.0, total, 0.0), "retrying")
    decode = decoder()
    done = 0.0
    replaced: dict[int, list[Sentence]] = {}
    for i, length in todo:
        # Against the replacements made so far too: two loops can share seconds.
        others = sorted(read + [r for got in replaced.values() for r in got],
                        key=lambda o: cast("float", o["start"]))
        lo, hi = _unread(sentences[i]["start"], sentences[i]["end"], others)
        for options in (RETRY_PLAIN, RETRY_WARM) if lo < hi else ():
            decoded = decode(lo - RETRY_PAD_S, hi + RETRY_PAD_S, options)
            got = _within(decoded, lo, hi)
            looped = any(is_loop("".join(str(t["w"]) for t in s["tokens"])) for s in decoded)
            words = sum(len(_WORD.findall(str(s["text"]))) for s in got)
            if not looped and words > RETRY_MIN_WORDS:
                replaced[i] = got
                break
        done += length
        report(Progress(done, total, time.monotonic() - started), "retrying")
    if not replaced:
        return transcription
    kept = [r for i, s in enumerate(sentences) for r in replaced.get(i, [s])]
    return _in_time_order(
        Transcription(text="".join(str(s["text"]) for s in kept).strip(), sentences=kept)
    )


def _without_overlaps(transcription: Transcription, *, merge: bool) -> Transcription:
    """`transcription` with every token inside its sentence, and no two sentences overlapping.

    The last step before the payload is written. Under every engine it makes
    sure a sentence ends by the time the next one starts, and checks that each
    token's `t` and `e` lie within its own sentence's bounds. `merge`, which
    transcribe() sets for whisper only, picks how an overlap is undone.

    whisper: two overlapping sentences are written as one, their tokens in time
    order: every word and every time kept as decoded, where moving or clipping
    times would write times no decoder gave. whisper's anchored windows wrote
    the same speech twice at their seams (#190); _owned in dsj/whisper.py now
    gives each second to one window, and on #148's fixture and the owner's
    101117 whisper reached here with nothing to merge. A merge is logged.

    parakeet and sherpa: split, never merged (#192, _split_at_seams). Their
    vendored chunk merge can time a word seconds early at a seam
    (_in_time_order), so the sentence holding it starts inside the one before.
    Merging those put two speakers' words in one sentence under one label
    (tests/test_suno.py's seam case went from labels [0, 1, 1] to [1]).

    A token outside its sentence raises, under every engine, because no path
    here makes one: the engines' bounds are widened to their tokens
    (_in_whole_milliseconds), and every later step that moves or drops tokens
    rebuilds the bounds from the ones left. One appearing means a step was
    broken, and a test should stop there rather than write a file whose words
    point outside their sentence.

    Raises:
        RuntimeError: if a token lies outside its sentence.
    """
    if not merge:
        sentences, split = _split_at_seams(transcription.sentences)
        _tokens_inside(sentences)
        if not split:
            return transcription
        return Transcription(
            text="".join(str(s["text"]) for s in sentences).strip(), sentences=sentences
        )
    ordered = sorted(transcription.sentences, key=lambda s: cast("float", s["start"]))
    out: list[Sentence] = []
    merged = 0
    for s in ordered:
        if out and s["start"] < out[-1]["end"]:
            prev = out[-1]
            tokens = sorted([*prev["tokens"], *s["tokens"]], key=lambda t: cast("float", t["t"]))
            out[-1] = prev | {
                "start": min(prev["start"], s["start"]),
                "end": max(prev["end"], s["end"]),
                "text": "".join(str(t["w"]) for t in tokens),
                "tokens": with_char_offsets(tokens),
            }
            merged += 1
        else:
            out.append(s)
    _tokens_inside(out)
    if not merged:
        return transcription._replace(sentences=out)
    logger.info("%d overlapping sentence pairs written as one", merged)
    return Transcription(text="".join(str(s["text"]) for s in out).strip(), sentences=out)


def _split_at_seams(sentences: list[Sentence]) -> tuple[list[Sentence], int]:
    """`sentences` earliest first with each overlapping pair split apart, and how many splits.

    Two overlapping sentences keep their own tokens except the fewest that must
    change sentence for the first to end by the time the second starts. Their
    tokens are laid out in time order and cut once, between two tokens where
    nothing before the cut ends after the first token past it; of those cuts,
    the one that moves the fewest tokens wins, and between equals the one at
    the widest pause, where a sentence most likely ended. No time changes and
    no sentence disappears, so each still gets its own speaker vote.

    The fewest, not a cut at the overlap's midpoint, because the usual fault is
    one token. On scratch/clip360.wav it is a full stop timed 3 s before the
    rest of its sentence, inside the one before: the cut moves that full stop
    and nothing else, where a cut at the overlap's midpoint also moved 6 tokens
    of the earlier sentence. Measured 2026-10-02 on three older long parakeet
    transcripts (17, 33 and 19 overlapping pairs): 19, 40 and 15 tokens end in
    another sentence this way, against 57, 104 and 77 at the midpoint, and 0
    pairs are left either way.

    A pair is left as decoded, and logged, where no cut exists: two of its
    words overlap each other, so separating them would move a time. Never seen
    on those transcripts. The splits are capped at the number of tokens, so
    the loop ends.
    """
    out = sorted(sentences, key=lambda s: cast("float", s["start"]))
    budget = sum(len(s["tokens"]) for s in out)
    split = left = 0
    i = 0
    while i + 1 < len(out):
        a, b = out[i], out[i + 1]
        cut = _seam_cut(a, b) if a["end"] > b["start"] and split < budget else None
        if cut is None:
            left += a["end"] > b["start"]
            i += 1
            continue
        out[i], out[i + 1] = cut
        # Nothing ahead of `a` moves: it ends by `a`'s start, and every token
        # re-cut here starts at or after that.
        out[i:] = sorted(out[i:], key=lambda s: cast("float", s["start"]))
        split += 1
    if split:
        logger.info("%d overlapping sentence pairs split at the seam", split)
    if left:
        logger.warning("%d overlapping sentence pair left as decoded: no cut separates them", left)
    return out, split


def _seam_cut(a: Sentence, b: Sentence) -> tuple[Sentence, Sentence] | None:
    """`a` and `b` re-cut so `a` ends by the time `b` starts, or None if no cut can."""
    tokens = sorted(
        [(t, False) for t in a["tokens"]] + [(t, True) for t in b["tokens"]],
        key=lambda tb: cast("float", tb[0]["t"]),
    )
    # Tokens of b before the cut, and of a after it, change sentence.
    moved = sum(1 for _, of_b in tokens if not of_b)
    ends = 0.0
    best: tuple[int, float, int] | None = None
    for k in range(1, len(tokens)):
        token, of_b = tokens[k - 1]
        moved += 1 if of_b else -1
        ends = max(ends, cast("float", token.get("e", token["t"])))
        pause = cast("float", tokens[k][0]["t"]) - ends
        if pause >= 0 and (best is None or (moved, -pause) < best[:2]):
            best = (moved, -pause, k)
    if best is None:
        return None
    k = best[2]
    return _with_tokens(a, [t for t, _ in tokens[:k]]), _with_tokens(b, [t for t, _ in tokens[k:]])


def _with_tokens(sentence: Sentence, tokens: list[dict[str, Any]]) -> Sentence:
    """`sentence` holding `tokens`, already in time order, with its bounds and text rebuilt."""
    return sentence | {
        "start": tokens[0]["t"],
        "end": max(cast("float", t.get("e", t["t"])) for t in tokens),
        "text": "".join(str(t["w"]) for t in tokens),
        "tokens": with_char_offsets(tokens),
    }


def _tokens_inside(sentences: list[Sentence]) -> None:
    """Raise if any token lies outside its own sentence (_without_overlaps says why)."""
    for s in sentences:
        for t in s["tokens"]:
            if not s["start"] <= t["t"] <= t.get("e", t["t"]) <= s["end"]:
                raise RuntimeError(
                    f"token at {t['t']} s lies outside its sentence "
                    f"({s['start']} to {s['end']} s); a step before the payload broke its bounds"
                )


def _token(token: AlignedToken, measured: bool) -> dict[str, Any]:
    """One token as the transcript writes it: `t` and `w`, and `e` and `c` if measured.

    `measured` is the engine's MEASURES_END_AND_CONFIDENCE. Both chunk engines
    set it: parakeet's and sherpa's decoders each time every token and score it
    (dsj/sherpa.py says how sherpa's score differs). An engine that could only
    guess either would leave it False, so a guess is never written as though it
    were measured.

    Both new values are rounded to 3 places, for file size, which is also what
    parakeet-mlx's own JSON writer does (parakeet_mlx/cli.py:143-150). Measured
    on the 2,902 real parakeet tokens in scratch/gate_resumed.json.ckpt, the two
    keys grow the sentences 121% unrounded and 70% rounded. Nothing is lost on
    `e`: every start and end there sits on a 10 ms grid, so what goes is the
    float noise of `start + duration`, which 784 of the 2,902 ends carry. On
    `c` a thousandth is far finer than any tint threshold, though about half of
    parakeet's tokens then read 1.0 (1,413 of the 2,902).

    `t` is rounded the same way, and `e` is never written below it (#174). With
    only `e` rounded, a zero-length token whose start carried float noise wrote
    `"t": 107.60000000000001, "e": 107.6`: 1 of 806 parakeet tokens and 6 of 745
    sherpa ones on a 3-minute clip, each a negative length to anything that
    takes `e - t`. Rounding is monotonic, so the tokens, already sorted by their
    unrounded starts, stay in order; two that were a hair apart can now share
    a `t`, which the stable sorts downstream leave as they were.
    """
    t = round(token.start, 3)
    out: dict[str, Any] = {"t": t, "w": token.text}
    if measured:
        out["e"] = max(round(token.end, 3), t)
        out["c"] = round(token.confidence, 3)
    return out


def _with_speaker(sentence: Sentence, speaker: int) -> Sentence:
    """The same sentence with `speaker` inserted directly after `end`.

    Rebuilt rather than assigned into so the label reads before the token list
    instead of after it -- a sentence's tokens are most of its bytes, and a
    human scrolling the file should not have to cross them to find who spoke.
    Anchored on an existing key rather than on a literal key list, so adding a
    field to the payload above does not silently drop it here.
    """
    out: Sentence = {}
    for key, value in sentence.items():
        out[key] = value
        if key == "end":
            out["speaker"] = speaker
    return out


def _with_speakers(
    payload: Payload, sentences: list[Sentence], labels: list[str], provenance: str
) -> Payload:
    """The same payload, labelled, with the new keys up near the top.

    `speakers` is the legend for every `speaker` index below it and is read
    once; behind half a megabyte of sentences it would be the last thing an
    agent reaching the end of the file finds it needed at the start.
    """
    out: Payload = {}
    for key, value in payload.items():
        out[key] = sentences if key == "sentences" else value
        if key == "model":
            out["speakers"] = labels
            # Its ABSENCE is load-bearing: without it "diarization was not run"
            # and "diarization ran and found one speaker" are the same document.
            out["diarization"] = provenance
    return out


def _label_speakers(
    payload: Payload,
    audio: Path,
    out: Path,
    total_s: float,
    report: Callable[[Progress, str], None],
    require: bool,
) -> Payload:
    """Diarize `audio` and rewrite `out` labelled, or leave both untouched.

    Called only after the unlabelled transcript is already on disk, which is
    what makes optionality structural rather than a matter of catching the
    right exceptions: every way this can fail leaves the correct, complete,
    unlabelled output exactly where it was.

    Returns the payload to hand back to the caller -- the labelled one when the
    pass ran, the one passed in when it did not.
    """
    from dsj import diarize as diarize_mod
    from dsj.merge import label_sentences

    started = time.monotonic()
    # Two events, not a bar. senko exposes no per-chunk callback, so there is
    # no intermediate progress to report and inventing some would be a lie.
    report(Progress(0.0, total_s, 0.0), "diarizing")
    try:
        result = diarize_mod.speaker_turns(audio)
    except diarize_mod.DiarizationUnavailable as exc:
        if require:
            raise
        # Named on stderr rather than swallowed: the transcript is correct, but
        # a user who asked for speaker labels and silently got none would have
        # no way to tell that from a recording with one speaker.
        logger.warning("diarization skipped: %s", exc)
        return payload
    except Exception as exc:
        # Not something the boundary foresaw, so it keeps its own type; but the
        # transcript above it is complete, and exiting 1 over it would make a
        # script or agent driving dsj throw a finished transcript away. senko's
        # clustering dying inside numba's cache save (#186) was the case that
        # did. Only the diarizer's call is covered: a bug in the merge below
        # still takes the run down. Exception, not BaseException, so Ctrl-C
        # still stops the run.
        if require:
            raise
        logger.warning(
            "speaker labelling failed, transcript left unlabelled: %s: %s",
            type(exc).__name__,
            exc,
        )
        return payload

    speakers = label_sentences(payload["sentences"], result.turns)
    labelled = _with_speakers(
        payload,
        # strict=True: a length mismatch between sentences and their labels is a
        # merge bug, and silently truncating to the shorter one would hide it.
        [_with_speaker(s, k) for s, k in zip(payload["sentences"], speakers, strict=True)],
        result.labels,
        result.provenance,
    )
    # The second atomic write to the same path. The extra ~500KB buys there
    # being no instant in which `out` is absent or partial; holding the payload
    # to write once would put the whole ASR run behind this optional pass.
    atomic_write_text(out, json.dumps(labelled))
    report(Progress(total_s, total_s, time.monotonic() - started), "diarizing")
    return labelled


class Terminated(KeyboardInterrupt):
    """SIGTERM, raised where the run is, so `kill` stops it the way Ctrl-C does (#143).

    A KeyboardInterrupt so that everything already written to survive Ctrl-C
    survives `kill` too: the temp file cleanup in atomic.py, the checkpoint the
    chunk loop banked, the temporary directory the extracted audio sits in.
    Python's default for SIGTERM is to end the process on the spot, which skips
    all of it, and the status file kept saying `running` about a process that no
    longer existed (#143, observed 2026-09-22).

    Here and not in the CLI, which installs the handler that raises it, because
    transcribe() is what writes `interrupted` and has to name the signal (#103).
    """


def roman_urdu(
    engine: str, language: str | None, prompt: str | None
) -> tuple[str, str, str, float]:
    """What `--roman-urdu` turns a run's engine, language and prompt into, and its `anchor_s`.

    One definition for `dsj suno` and for a run started from `dsj ui` (#113),
    because transcribe() knows nothing of Roman Urdu: an app that passed only
    `language="ur"` would get a worse Urdu transcript than the terminal, with
    nothing to say so. Sugar over the flags under it rather than a mode, so an
    explicit language or prompt beside it still wins. The prompt is measured,
    not invented, and so is the window it is re-seeded every (dsj/whisper.py).
    parakeet becomes whisper; sherpa is left alone, and transcribe() then
    refuses the whisper options it does not take.
    """
    from dsj.whisper import ANCHOR_CHUNK_S, ROMAN_URDU_PROMPT

    return (
        "whisper" if engine == "parakeet" else engine,
        language or "ur",
        prompt or ROMAN_URDU_PROMPT,
        ANCHOR_CHUNK_S,
    )


def reports_progress(engine: str, prompt: str | None, anchor_s: float | None) -> bool:
    """Whether a run reports progress before it finishes.

    parakeet and sherpa report after every chunk. whisper reports once at 0%
    and then nothing until it is done, because mlx-whisper takes no progress
    callback, except on an anchored run (`anchor_s` and `prompt`, which
    `--roman-urdu` sets), which cuts the audio itself and reports per window.
    A page showing a run must know which, or a bar waiting on whisper reads as
    stuck (#113).
    """
    return engine != "whisper" or (anchor_s is not None and prompt is not None)


def _write_last_status(status_path: Path | None, document: dict[str, object]) -> None:
    """Write the document a run ends on when it does not reach `done`.

    Atomic for the same reason as the heartbeat, and more so: the watcher
    polling for exactly this document is in a tight read loop, which makes it
    the reader most likely to land inside a torn write. Not into a directory
    that does not exist: transcribe() refuses that status path up front, and
    writing here would raise over its refusal (#197).
    """
    if status_path is not None and status_path.parent.is_dir():
        atomic_write_text(status_path, json.dumps(document))


def transcribe(
    media: Path,
    out: Path,
    model_id: str | None = None,
    status_path: Path | None = None,
    on_progress: Callable[[Progress, str], None] | None = None,
    resume: bool = True,
    diarize: bool = True,
    require_diarize: bool = False,
    engine: str = "parakeet",
    language: str | None = None,
    prompt: str | None = None,
    anchor_s: float | None = None,
) -> Payload:
    """Transcribe `media`, writing a sentence+token timestamped JSON to `out`.

    `media` is any file ffmpeg can open -- the .mov straight off the screen
    recorder is the normal case. Audio is extracted to a temp file first,
    unless the input is already in the shape the model consumes.

    Returns the parsed result. `status_path` receives a JSON heartbeat during
    both phases so a detached run stays observable.

    An interrupted run leaves a checkpoint beside `out`, and the next run
    continues from its last completed chunk. The checkpoint stays until speaker
    labelling is over, so a run interrupted while labelling resumes past the
    last chunk and goes straight back to labelling. `resume=False` ignores and
    removes any checkpoint and transcribes the whole file.

    Sentences are then labelled with who spoke them, which is a pass over an
    output that is already correct without it: any failure degrades to the
    unlabelled transcript and returns normally. `diarize=False` skips it and
    emits the unlabelled schema exactly; `require_diarize=True` makes a failure
    fatal for a caller who would rather have nothing than an unlabelled index.

    `engine` picks the ASR backend. "parakeet" is the default and everything
    above describes it. "whisper" exists for the languages parakeet does not
    have -- see dsj/whisper.py -- and differs in two ways worth knowing
    before you choose it: it owns its own window loop, so nothing is banked
    until it has decoded the whole recording, and only an anchored run
    (`anchor_s` and `prompt`, which `--roman-urdu` sets) reports progress
    between start and finish, once per window. Its finished result is banked
    beside `out` until labelling is over, so an interrupt after the decode
    costs no decode on the next run. `language` and `prompt` are whisper's;
    parakeet takes neither.
    `model_id` defaults to whichever engine's model, so it is usually left
    alone.

    A run that raises ends its status file on `{"state": "failed", "pid",
    "error"}`, and one stopped by Ctrl-C or `kill` on `{"state":
    "interrupted", "pid", "signal"}` plus where it had got to, then the
    exception propagates. Written here, not by the CLI, so a caller that
    imports this function is told too (#103): before, only `dsj suno` wrote
    them, and an in-process run that crashed left its last `running` frame
    on disk for good.
    """
    # The last frame reported, for the `interrupted` document: tracked behind
    # the heartbeat write and ahead of the caller's callback, the order the CLI
    # tracked it in when it wrote this document, so the bytes are unchanged.
    last: list[tuple[Progress, str]] = []

    def track(p: Progress, state: str) -> None:
        last[:] = [(p, state)]
        if on_progress:
            on_progress(p, state)

    try:
        return _transcribe(
            media, out, model_id, status_path, track, resume, diarize,
            require_diarize, engine, language, prompt, anchor_s,
        )
    except Exception as exc:
        # Recorded and re-raised: a watcher has no other way to tell "died"
        # from "not started yet", and the caller still gets the exception.
        _write_last_status(
            status_path,
            {"state": "failed", "pid": os.getpid(), "error": f"{type(exc).__name__}: {exc}"},
        )
        raise
    except KeyboardInterrupt as exc:
        # Ctrl-C and `kill`. KeyboardInterrupt is not an Exception, so it needs
        # its own branch; without one the heartbeat said `running` forever (#143).
        stopped: dict[str, object] = {
            "state": "interrupted",
            "pid": os.getpid(),
            "signal": "SIGTERM" if isinstance(exc, Terminated) else "SIGINT",
        }
        # Where it had got to, with the phase that number belongs to: an
        # extracting frame's audio_done_s counts extraction, not transcript.
        if last:
            p, state = last[0]
            stopped |= {
                "during": state,
                "audio_done_s": p.audio_done_s,
                "audio_total_s": p.audio_total_s,
            }
        _write_last_status(status_path, stopped)
        raise


def _transcribe(
    media: Path,
    out: Path,
    model_id: str | None,
    status_path: Path | None,
    on_progress: Callable[[Progress, str], None],
    resume: bool,
    diarize: bool,
    require_diarize: bool,
    engine: str,
    language: str | None,
    prompt: str | None,
    anchor_s: float | None,
) -> Payload:
    """transcribe()'s body: everything it documents but the status a run ends on."""
    if engine not in ENGINES:
        raise ValueError(f"unknown engine {engine!r}, expected one of {', '.join(ENGINES)}")
    if engine == "parakeet" and (language is not None or prompt is not None):
        raise ValueError(
            "--language and --prompt are whisper's; parakeet takes neither. "
            "Add --engine whisper, or drop them."
        )
    # Before the engine loads or a second of audio is decoded (#191). The first
    # write to `out` comes at parakeet's first checkpoint, and whisper's only
    # at the very end: on 2026-10-02 a whisper run decoded for 441 s and then
    # died on a temp file the user never named. Refused, not created, as
    # dikhao refuses a frame into a missing directory: a typo in `-o` would
    # otherwise put the transcript somewhere nobody looks.
    if not out.parent.is_dir():
        raise FileNotFoundError(
            f"cannot write {out}: the directory {out.parent} does not exist. "
            f"Create it first (mkdir -p {out.parent}) or pass another -o."
        )
    # The same for the heartbeat (#197). Its first write came after the model
    # loaded and a chunk decoded, and the handler that writes "failed" then
    # failed again writing into the same missing directory.
    if status_path is not None and not status_path.parent.is_dir():
        raise FileNotFoundError(
            f"cannot write the status file {status_path}: the directory "
            f"{status_path.parent} does not exist. Create it first "
            f"(mkdir -p {status_path.parent}) or pass another --status."
        )
    # Resolves the engine module and raises EngineUnavailable with the remedy
    # if its backend cannot import here. After this call, everything
    # engine-specific is an attribute of `eng_mod` -- this function never
    # imports a backend itself, which is what the AST boundary test enforces.
    spec, eng_mod = get_engine(engine)

    from dsj.checkpoint import (
        checkpoint_path_for,
        fingerprint,
        read_checkpoint,
        read_transcription,
        whisper_fingerprint,
        write_checkpoint,
        write_transcription,
    )
    from dsj.chunking import transcribe_chunked

    started = time.monotonic()
    # Load first: the extraction target rate is a property of the loaded
    # engine, not a constant we get to assume. The whisper engine skips the
    # load entirely -- its rate is fixed and its model loads inside its own
    # call, so an engine the user did not ask for never costs a model load.
    #
    # `spec.kind` IS the engine test from here down, read once: the chunk
    # branch below cannot run without `loaded`, and reading the engine string
    # a second time would let the two disagree.
    loaded: Any = None
    if spec.kind == "file":
        model_id = model_id or DEFAULT_WHISPER_MODEL
        rate = WHISPER_SAMPLE_RATE
    else:
        model_id = model_id or cast("str", eng_mod.DEFAULT_MODEL)
        loaded = eng_mod.load(model_id)
        rate = int(loaded.sample_rate)

    def write_status(p: Progress, state: str, stalled_s: float | None = None) -> None:
        if status_path is None:
            return
        payload = asdict(p) | {
            "state": state,
            # The writer, so a reader can ask the process table whether the job
            # behind a `running` frame still exists, and stop that job alone
            # rather than every `dsj suno` on the machine (#138). Without it, a
            # killed run and a slow one read the same until someone ran `ps`.
            "pid": os.getpid(),
            "fraction": round(p.fraction, 4),
            "speed": round(p.speed, 2),
            "eta_s": p.eta_s,
        }
        # Present only while it applies, so a reader tests for the key.
        if stalled_s is not None:
            payload["stalled_s"] = round(stalled_s, 1)
        # Not fsynced: a reader is protected by the rename alone, and a
        # heartbeat lost to a power cut costs nothing to regenerate.
        atomic_write_text(status_path, json.dumps(payload))

    def report(p: Progress, state: str, stalled_s: float | None = None) -> None:
        write_status(p, state, stalled_s)
        on_progress(p, state)

    stream = media_mod.probe(media)

    with tempfile.TemporaryDirectory(prefix="dsj-") as tmp:
        if media_mod.needs_conversion(stream, rate):
            # Per-phase clock. Extraction runs three orders of magnitude faster
            # than realtime and the transcription that follows around 20x;
            # sharing one elapsed would make both speeds meaningless.
            extract_started = time.monotonic()
            # ffmpeg keeps reporting while its position stands still, which is
            # what made the 2026-09-22 stall look like a slow run: every frame
            # was fresh, and each one named the same second.
            furthest_s = -1.0
            moved_at = extract_started

            def on_extract(done_s: float) -> None:
                nonlocal furthest_s, moved_at
                now = time.monotonic()
                if done_s > furthest_s:
                    furthest_s, moved_at = done_s, now
                still_s = now - moved_at
                report(
                    Progress(done_s, stream.duration_s, now - extract_started),
                    "extracting",
                    still_s if still_s >= STALL_S else None,
                )

            audio = media_mod.extract_audio(
                media, Path(tmp) / "audio.wav", rate, on_progress=on_extract
            )
        else:
            audio = media

        # Read from `media`, never from the extracted wav: SILENCE_DB was placed
        # on the float decode of the source, and ffmpeg mixes stereo to mono at
        # 0.5 + 0.5 for the wav's 16 bits but 0.707 + 0.707 for float, so every
        # frame of a stereo recording reads 3.01 dB quieter in the wav (#193).
        # On the owner's stereo files that found two silences on 101117 that
        # #181 measured are not there. A mono source decodes the same either
        # way. Before the decode, not after it: one cheap pass (measured 0.13 s
        # for the fixture's 14 minutes of wav, 0.6 s and 1.6 s for 13 and 28
        # minutes of m4a, 0.5 s for a 1.5 GB, 10 minute .mov), and audio ffmpeg
        # cannot read fails here rather than after an hour of whisper.
        stretches = silences(media_mod.loudness(media, LOUDNESS_FRAME_S))

        # Beside `out`, for every engine: the chunk engines bank tokens there
        # after every chunk, whisper its finished result (dsj/checkpoint.py).
        ckpt_path = checkpoint_path_for(out)
        resumed_from_s = 0.0
        # The recording's length as this run's transcription frames report it,
        # kept so the done frame can report the same number (#52). It starts as
        # ffprobe's duration, which an unanchored whisper run keeps; an
        # anchored one and the chunk branch below replace it with the decoded
        # length, which is what their running frames divide by (#173).
        audio_total_s = stream.duration_s
        if spec.kind == "file":
            from dsj.whisper import fingerprint_fields as whisper_fields
            from dsj.whisper import transcribe_whisper

            # whisper owns its window loop and exposes no per-window hook, so
            # nothing is banked while it decodes; its finished result is, at
            # the checkpoint's path, before the loop retry and the labelling
            # that follow it (#171). Before that, an hour of whisper was lost
            # to an interrupt that came after the decode had finished.
            whisper_fp = whisper_fingerprint(
                media, model_id, whisper_fields(language, prompt, anchor_s)
            )
            banked_result: Transcription | None = None
            if resume:
                banked_result = read_transcription(
                    ckpt_path,
                    whisper_fp,
                    on_reject=lambda why: logger.warning(
                        "checkpoint ignored, transcribing from the start: %s", why
                    ),
                )
            else:
                ckpt_path.unlink(missing_ok=True)

            if banked_result is not None:
                # The whole recording was decoded by an earlier run, so this
                # one credits itself with none of it and ends at 0.0x, as a
                # parakeet run resumed from a finished checkpoint does.
                logger.info("whisper's result was banked by an earlier run; not decoding again")
                transcription = banked_result
                resumed_from_s = audio_total_s
            else:
                # Said out loud rather than left as a silently absent
                # feature, because a resumable engine and a non-resumable one
                # look identical until the run is killed.
                if resume:
                    logger.info(
                        "whisper banks nothing until its transcription is finished; "
                        "an interrupt before then starts over"
                    )
                report(Progress(0.0, stream.duration_s, 0.0), "running")
                whisper_started = time.monotonic()

                # The anchored path cuts the audio itself, so it can say where
                # it has got to. Unanchored there is still one report at 0%
                # and nothing until the end: mlx-whisper takes no progress
                # callback, and a bar that moved without evidence would be a
                # bar that lies.
                whisper_progress: Callable[[float, float], None] | None = None
                if reports_progress(engine, prompt, anchor_s):

                    def _whisper_progress(done_s: float, total_s: float) -> None:
                        nonlocal audio_total_s
                        audio_total_s = total_s
                        report(
                            Progress(done_s, total_s, time.monotonic() - whisper_started),
                            "running",
                        )

                    whisper_progress = _whisper_progress

                transcription = transcribe_whisper(
                    audio,
                    model_id=model_id,
                    language=language,
                    prompt=prompt,
                    anchor_s=anchor_s,
                    on_progress=whisper_progress,
                )
                write_transcription(ckpt_path, whisper_fp, media, transcription)
        else:
            audio_data = loaded.load_audio(audio)
            audio_total_s = len(audio_data) / rate

            # Fingerprinted on `media`, never on `audio`: for a .mov those
            # differ, and `audio` is a temp wav made fresh on every run, so a
            # checkpoint keyed to it would name ffmpeg's output rather than the
            # recording the user handed us.
            fp = fingerprint(
                media, len(audio_data), model_id, CHUNK_S, OVERLAP_S,
                engine_fields=cast("dict[str, str]", eng_mod.fingerprint_fields()),
            )

            start_tokens: list[AlignedToken] = []
            skip_before = 0
            if resume:
                # A warning, not silence: a checkpoint that exists and is not
                # used costs the whole run, and before #118 a rename did exactly
                # that with nothing on stderr to say so.
                found = read_checkpoint(
                    ckpt_path,
                    fp,
                    on_reject=lambda why: logger.warning(
                        "checkpoint ignored, transcribing from the start: %s", why
                    ),
                )
                if found is not None:
                    skip_before, start_tokens = found
                    logger.info(
                        "resuming from %s (%d tokens banked)",
                        clock(skip_before / rate),
                        len(start_tokens),
                    )
            else:
                ckpt_path.unlink(missing_ok=True)

            resumed_from_s = skip_before / rate

            # Per-phase clock, as above: transcription runs at a different order
            # of magnitude from extraction, so they cannot share an elapsed.
            transcribe_started = time.monotonic()
            chunk_callback = _make_chunk_callback(
                rate,
                lambda: time.monotonic() - transcribe_started,
                lambda p: report(p, "running"),
                resumed_from_s,
            )
            banked = ckpt_path

            def on_chunk(
                done_through: int, next_start: int, total: int, merged: list[AlignedToken]
            ) -> None:
                # Checkpointed with next_start, never done_through: chunks
                # overlap, so a chunk's end is past the following chunk's start
                # and resuming from it would skip a whole chunk of audio.
                #
                # Banked before it is reported, so an observer that sees 40% can
                # never be ahead of what a restart could actually recover.
                write_checkpoint(banked, fp, next_start, merged)
                chunk_callback(done_through, total)

            result = transcribe_chunked(
                loaded,
                audio_data,
                chunk_s=CHUNK_S,
                overlap_s=OVERLAP_S,
                start_tokens=start_tokens,
                skip_before=skip_before,
                on_chunk=on_chunk,
            )
            # Read off the engine module, like everything engine-specific here:
            # parakeet and sherpa share this branch and differ on exactly this.
            measured = cast("bool", eng_mod.MEASURES_END_AND_CONFIDENCE)
            transcription = Transcription(
                text=result.text,
                sentences=[
                    {
                        "start": s.start,
                        "end": s.end,
                        "text": s.text,
                        "tokens": with_char_offsets([_token(t, measured) for t in s.tokens]),
                    }
                    for s in result.sentences
                ],
            )

        # Both engine branches meet here, which is why the text and the order
        # are put right here and not in either of them: parakeet and sherpa
        # reach it through the chunk loop above, whisper through its own window
        # loop, and both can emit a sentence that starts before the one printed
        # ahead of it. Text first, so the order is rebuilt from the final text.
        # Silence before loops, so a loop over silence is reported as no
        # speech (#181), and before the retry, so no loop over silence is
        # decoded again (#183); both last, so `unclear` comes out in the same order as
        # `sentences`.
        transcription, no_speech = _without_silence(
            _in_time_order(_in_whole_milliseconds(_text_from_tokens(transcription))),
            stretches,
        )
        # whisper's loops get one more decode each before they are given up
        # on (#183); the chunk engines write none to retry.
        if spec.kind == "file" and RETRY_LOOPS:
            whisper_model = model_id
            transcription = _retried(
                transcription,
                stretches,
                lambda: redecoder(
                    audio, model_id=whisper_model, language=language, prompt=prompt
                ),
                report,
            )
        transcription, loops = _without_loops(transcription)
        # After the loops leave, so a loop never merges into a real sentence
        # and hides from is_loop. whisper merges overlapping sentences (#190);
        # parakeet and sherpa split them, never merge (#192).
        transcription = _without_overlaps(transcription, merge=spec.kind == "file")
        unclear = sorted(no_speech + loops, key=lambda u: cast("float", u["start"]))

        payload: Payload = {
            # The source the user handed us, never the temp wav -- this JSON is
            # an index into that file and has to keep pointing at it.
            "audio": str(media),
            # Which engine wrote it (#172). The model id alone did not say:
            # under sherpa it is whatever directory the run was given, and a
            # token's `c` means something different under each engine, so a
            # reader tinting by it has to know which. Ahead of `model`, so the
            # speaker keys still land straight after `model` (_with_speakers).
            "engine": engine,
            "model": model_id,
            "text": transcription.text,
            # Always written, `[]` when nothing was taken out, so that a
            # transcript without the key reads as one written before the loop
            # check existed rather than one the check passed. Two reasons:
            # "repetition loop" (#140) and "no speech" (#181). Ahead of
            # `sentences`, which is most of the file's bytes.
            "unclear": unclear,
            "sentences": transcription.sentences,
        }
        # Atomic for the same reason as the heartbeat, and more: `out` is what
        # every downstream tool reads, and a truncated transcript does not
        # announce itself -- it merely looks short.
        atomic_write_text(out, json.dumps(payload))

        # `audio` and not `media`: media.py has already produced the 16 kHz
        # mono pcm_s16le wav senko wants, and it only exists until this `with`
        # block ends. A .mov handed straight to the diarizer is a second
        # normalization path to keep correct.
        if diarize:
            payload = _label_speakers(
                payload, audio, out, stream.duration_s, report, require_diarize
            )

        # After the last write to `out`, never after the first: labelling
        # rewrites it, and the tag has to hold the bytes that stayed (#119).
        # Onto `media`, the recording the user handed us, never the temp wav.
        filetag.tag_transcript(media, out)

        # Removed once labelling is over, not as soon as `out` is written
        # (#101). whisper's banked result goes at the same moment and for the
        # same reason (#171); the rest of this comment is about the chunk
        # engines' checkpoint. The unlabelled transcript carries no fingerprint, so the next
        # run cannot tell it is finished, or for this media and model; only the
        # checkpoint can. It used to go first, on the reasoning that a crash in
        # labelling would strand a stale checkpoint and the next run would
        # resume audio it had already transcribed. It is not stale: by now it
        # banks every token through the end of the audio (next_start is the
        # total), so resuming it skips every chunk, decodes nothing, rebuilds
        # this same transcript from the banked tokens and goes straight to
        # labelling. Deleting it early is what cost the whole transcription:
        # reproduced with `kill` and `kill -9` during labelling, the rerun
        # started again from 0:00.
        #
        # After the write, not before, for the same reason: a crash between
        # the two costs one redundant resume rather than the whole run.
        ckpt_path.unlink(missing_ok=True)

        elapsed = time.monotonic() - started
        # The length of the recording, the total every running frame reported,
        # so the field keeps one meaning to the last frame (#52). It used to be
        # the end of the last sentence, a different fact: a 240 s recording
        # with no speech finished at 0.0 s and 0%, and a resumed run's speed
        # went negative (-3.71 measured), because `resumed_from_s` kept the
        # real position. The decoded length on the chunk path rather than
        # ffprobe's for the same reason: `resumed_from_s` is counted in decoded
        # samples, so a run resumed from a finished checkpoint (#101) ends at
        # exactly 0.0x, not a hair below it.
        report(Progress(audio_total_s, audio_total_s, elapsed, resumed_from_s), "done")
        return payload


def main(argv: list[str] | None = None) -> int:
    """Run the transcribe CLI.

    A shim onto `dsj.cli`, which owns every flag in the project so that the
    console script and `python -m dsj.suno` cannot drift apart. Kept
    as a function returning an int because that is the contract its tests --
    and any embedder -- already rely on.

    Returns:
        A process exit code.
    """
    from dsj.cli import run

    return run(["suno", *(sys.argv[1:] if argv is None else argv)])


if __name__ == "__main__":
    raise SystemExit(main())
