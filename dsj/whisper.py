"""whisper, for the audio parakeet cannot read.

`parakeet-tdt-0.6b-v3` is the default engine and stays the default: it runs at
~13x realtime and does not invent words over silence. What it does not have is
Urdu -- its 25 languages are European, and `ur` is not among the model card's
tags. A voice note that mixes Urdu and English comes back as nothing usable.

whisper-large-v3-turbo does read it, at a cost: about 1.7 to 3x realtime on
Urdu with `--roman-urdu`, about 5 to 6x on English, on a 16 GB M2 running one
whisper at a time, model load included. Each figure, with its file, command,
commit and the memory free while it ran, is in one place:
.agents/skills/dsj/references/engines.md, "whisper speed". Memory pressure
alone has moved it threefold on this Mac (#139), so quote it with the machine
state or not at all.

parakeet runs at ~13x. That gap, and whisper's habit of inventing words, is why
this is a flag and not a replacement.

ROMAN URDU IS A PROMPT, NOT A SETTING. whisper transcribes Urdu in Urdu script
by default. Seeding the decoder with a Roman Urdu `initial_prompt` makes it emit
Roman instead, and it carries across windows through whisper's own
condition-on-previous-text. On #148's public fixture `--roman-urdu` leaves 3%
of the text in Urdu script (#33's row below), and a slow test in
tests/test_urdu_fixture.py fails if that share goes above 15%.

THAT ONLY HOLDS FOR SHORT AUDIO, and not because the seed reaches only the
first window and nothing past it. `initial_prompt` is folded into an
accumulated buffer that condition-on-previous-text threads into every later
window; decoding.py:501-503 keeps only the last `n_ctx // 2 - 1` tokens of
that buffer, so the seed at its front rides along for as many windows as real
speech takes to fill the budget, then is evicted whole and oldest-first, not
faded gradually. A low-confidence window can also force an earlier reset
(transcribe.py's `prompt_reset_since`), dropping the seed sooner than the
token budget alone would -- confirmed against the installed library, see
#100. Over four recordings on 20 Sep 2026, 13 to 86 minutes, the share
returned in Urdu script despite the prompt was 41%, 80%, 97% and 99%, worst on
the longest; scratch/urdu_script_share.py reproduces the first three, and the
fourth file's transcript no longer exists (#137). `anchor_s` re-seeds the
prompt per window and bounds how far this can drift; `--roman-urdu` sets it.
See `_anchored`.

That trick is model-specific, and the difference is not subtle. Measured on
#148's public fixture (854s, 1,293 English words in the hand-checked
reference), one run each, one whisper at a time on a 16 GB M2 (#33,
2026-10-02):

- whisper-large-v3-turbo, `--roman-urdu`: 89.6% of the reference's English
  words recovered, 3% of the text in Urdu script, 3.41x realtime.
- whisper-large-v3-mlx, the full model, `--roman-urdu`: 59.4%, 63%, 0.50x, with 23% of
  memory free and 12.1 GB of swap in use while it ran.

`just urdu-fixture`, then
`dsj suno scratch/urdu_cs/podcast.wav --roman-urdu --no-diarize --model <id>`.
The full model writes most of its text in Urdu script whatever the prompt
says, at 4 and 8 bits too, so the default here is turbo (DEFAULT_WHISPER_MODEL);
changing it means re-running that comparison rather than assuming.
"""

from __future__ import annotations

__all__ = [
    "ANCHOR_CHUNK_S",
    "ANCHOR_OVERLAP_S",
    "DEFAULT_WHISPER_MODEL",
    "HALLUCINATION_SILENCE_S",
    "INSTALL_HINT",
    "ROMAN_URDU_PROMPT",
    "SAMPLE_RATE",
    "VAD_SEGMENTS",
    "WhisperUnavailable",
    "available",
    "fingerprint_fields",
    "redecoder",
    "speech_segments",
    "transcribe_whisper",
]

import math
import statistics
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import numpy as np

from dsj.asr import Transcription, with_char_offsets

# turbo, on #33's measurement (module docstring): on #148's fixture with
# `--roman-urdu` it recovered 89.6% of the English words with 3% of its text in
# Urdu script, at 3.41x realtime; the full whisper-large-v3 recovered 59.4%
# with 63% in Urdu script, at 0.50x. The full model's 4-bit and 8-bit builds
# stayed at 61 to 67% Urdu script, so precision is not what separates them.
DEFAULT_WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"

# whisper's own front end resamples to 16 kHz mono whatever it is handed, so
# this is not a preference: handing it anything else means paying for a second
# resample of an hour of audio inside a library that will not report progress.
SAMPLE_RATE = 16000

# The window the Roman Urdu prompt is re-seeded at, and how much of it is
# decoded twice. 120s is the best window measured (#100, 2026-10-02): fifteen
# turbo runs on the owner's two drift recordings, 101117 and 094234, through
# scratch/whisper_sweep.py, which sets this constant before `dsj suno <file>
# --roman-urdu` runs. Of the windows tried (120, 60, 30s), 120s gave the most
# words on both files and the fewest loop seconds on 101117. 30s cut Urdu
# script to under 13% on both, and lost 10 to 22% of the words and about
# doubled the loop seconds doing it; 60s sat between, its two runs 18 points
# apart. Unaided, the Roman bias died 22 to 105s into four recordings, so a
# 120s window does drift in its back half (47 to 59% Urdu script on 101117, 39
# to 44% on 094234). That is accepted: the owner decided on 2026-10-02 that
# Urdu script in the output is fine, and the target is complete text, not
# Roman spelling. The overlap
# is there so a word spoken across a boundary is whole in at least one window;
# `_owned` gives each second of it to exactly one of them (#190). `_anchored` also
# requires `ANCHOR_CHUNK_S > ANCHOR_OVERLAP_S >= 1.0`; see its own validation.
ANCHOR_CHUNK_S = 120.0
ANCHOR_OVERLAP_S = 6.0

# mlx-whisper's `hallucination_silence_threshold`, passed to both calls below.
# None, its own default, leaves the switch off, and off is the measured choice
# (#99, 2026-10-02). The switch drops a segment whose first words score as
# unlikely, too short or too long and that sits between gaps in the word
# timestamps; it never looks at loudness. At 2 s it removed the repetition
# loops on recording-20260920-101117 and 1,000 to 1,400 real words with them,
# and cut English recall on #148's public fixture from 87.8% to 82.5% (78.8%
# at 5 s). It did nothing for text invented over the fixture's 60 s silent
# gap: about 220 words at every setting. Loops are taken out after decoding
# instead (#140). Kept as a constant, and plumbed through, so the setting can
# be measured again: scratch/whisper_sweep.py sets it from outside per run.
HALLUCINATION_SILENCE_S: float | None = None

# Silero's speech detector in front of whisper (#236), and OFF: nothing ships
# on until #236's measurement says so. On, every whisper mode cuts the file at
# speech first and decodes only the clips `speech_segments` makes of it, so
# whisper is never handed a long silence to write over (#181's 220 words over
# a 60 s gap). Needs the `vad` extra (silero-vad, model inside the package).
# scratch/accuracy/run.py turns it on per run, as it does ANCHOR_CHUNK_S.
VAD_SEGMENTS: bool = False
# The longest clip whisper is handed. WhisperX, arXiv 2303.00747 Table 3: a
# 30 s cut-and-merge beat 15 s on TED-LIUM (WER 9.70 against 9.72), "maximum
# context yields the most accurate transcription"; 30 s is also whisper's own
# window, so a clip never spills into a second one.
VAD_MAX_S = 30.0
# Speech padded by this much each side, so a cut never clips the first or last
# syllable (faster-whisper #925 saw first syllables lost at tight padding).
# No published ablation exists: Silero's default is 30 ms and faster-whisper
# overrides it to 400 ms. 300 ms sits just under faster-whisper's, unmeasured
# here beyond the recall check on #236.
VAD_PAD_MS = 300
# Silero's own default; its docstring calls 0.5 "pretty good for most
# datasets". Not measured on Urdu by anyone (#236, "Not known" 2); the recall
# check on #236 is the only evidence that it does not drop quiet Urdu speech.
VAD_THRESHOLD = 0.5
# A pause must last this long before speech is split at it. Silero's default
# is 100 ms, faster-whisper's 2000 ms. Splits only decide where a clip may end,
# since the merge keeps the pauses inside a clip, so shorter means more places
# to cut; 500 ms keeps those to pauses between phrases rather than between
# words. A choice, not a measurement (#236).
VAD_MIN_SILENCE_MS = 500
# Speech shorter than this is dropped as a click. Silero's default, kept: a
# shorter floor admits noise, a longer one risks a one-word "haan" (#236).
VAD_MIN_SPEECH_MS = 250
# Silero scores 512-sample frames at 16 kHz (utils_vad.get_speech_timestamps).
VAD_FRAME_S = 512 / 16000

# How long a word after a pause may last before its start is moved up to it
# (#222): twice the median word length of its segment, the median taken as no
# more than this. Both are mlx-whisper's own, from the clamp it applies to a word
# beside a full stop, question mark or exclamation mark (add_word_timestamps in
# mlx_whisper/timing.py, 0.4.3); `_pause_free_starts` applies it beside any
# pause the aligner gave to the word after it, with or without punctuation.
LONG_WORD_MEDIAN_CAP_S = 0.7

# From a clone the hint cannot be a whole `uv sync` line: `uv sync` uninstalls
# every extra it is not given, so `uv sync --extra whisper` alone would take
# parakeet and the diarizer away (#170). It names the flag to add instead.
INSTALL_HINT = (
    '`uv tool install "dsj[whisper] @ git+https://github.com/m2moiz/dekho-suno-jaano"`,'
    " or from a clone add `--extra whisper` to the `uv sync` line you already use"
    " (`uv sync` uninstalls every extra it is not given)"
)

# Not a magic incantation -- a worked example of the output wanted, which is
# what an initial_prompt is for. It carries a mid-sentence English word on
# purpose ("duty free", "okay"), because the target is code-switched speech and
# a prompt of pure Urdu biases against leaving English in Latin where it was
# said in English.
ROMAN_URDU_PROMPT = (
    "Yeh Roman Urdu transcript hai. Mujhe maloom nahin tha ke aap ne mehsoos kiya ya nahin. "
    "Is mulk mein zyada tar cheezein duty free hain, okay?"
)


def available() -> str | None:
    """None if mlx-whisper would import; otherwise the reason it will not.

    The registry (dsj.asr.get_engine) calls this before any transcription
    starts, so a phone asking for whisper fails in a second with a remedy
    rather than mid-pipeline. find_spec, never an import: this must stay
    cheap and must not crash on the machines it exists to report about.
    """
    import sys
    from importlib.util import find_spec

    # sys.modules first: an already-imported backend is available by
    # definition, and find_spec raises on a module a test has stubbed into
    # sys.modules with no __spec__.
    if "mlx_whisper" in sys.modules:
        return None
    if find_spec("mlx_whisper") is None:
        return f"mlx-whisper is not installed. Install it with {INSTALL_HINT}."
    return None


class WhisperUnavailable(RuntimeError):
    """The whisper engine was asked for and mlx-whisper is not installed."""


def fingerprint_fields(
    language: str | None, prompt: str | None, anchor_s: float | None
) -> dict[str, str]:
    """Everything besides the recording and the model that changes what whisper writes.

    The key a banked whisper result is matched on (#171), as parakeet's and
    sherpa's fingerprint_fields key their checkpoints. A prompt biases spelling
    and script, a language skips detection, an anchor cuts the audio into
    re-prompted windows (`_anchored`), and the anomaly threshold drops
    segments: a result decoded under any other value of one of them is a
    different transcript. The anchor is the one `transcribe_whisper` acts on,
    so `anchor_s` without a prompt reads as no anchor, which is what it is.
    Values are strings because the fingerprint is compared as JSON.
    """
    from importlib.metadata import version

    # Under the speech detector no anchored windows are cut (`_vad_decoded`).
    anchored = anchor_s is not None and prompt is not None and not VAD_SEGMENTS
    fields = {
        "mlx_whisper_version": version("mlx-whisper"),
        "language": str(language),
        "prompt": str(prompt),
        "anchor_s": str(anchor_s) if anchored else "None",
        "anchor_overlap_s": str(ANCHOR_OVERLAP_S) if anchored else "None",
        "hallucination_silence_s": str(HALLUCINATION_SILENCE_S),
    }
    if not VAD_SEGMENTS:
        # No VAD keys at all when it is off, so a result banked before #236
        # still matches: fingerprints are compared whole (dsj/checkpoint.py).
        return fields
    return fields | {
        "silero_vad_version": version("silero-vad"),
        "vad_max_s": str(VAD_MAX_S),
        "vad_pad_ms": str(VAD_PAD_MS),
        "vad_threshold": str(VAD_THRESHOLD),
        "vad_min_silence_ms": str(VAD_MIN_SILENCE_MS),
        "vad_min_speech_ms": str(VAD_MIN_SPEECH_MS),
    }


def _sentences_from(segments: list[dict[str, Any]], offset: float) -> list[dict[str, Any]]:
    """Turn whisper's segments into payload sentences, shifted by `offset` seconds.

    The word text is kept exactly as whisper emits it, leading space and all,
    which is how parakeet's tokens arrive too. `text` here is whisper's own,
    stripped; dsj/suno.py rebuilds it from the words (#106), and `charOffset`
    is counted over those same words, so it indexes the text that is written.

    Each word's `end` and `probability` become `e` and `c`, the keys and the
    3-place rounding parakeet's tokens use (dsj/suno.py:_token). Neither is a
    decode-time measurement the way parakeet's end is. whisper times a word
    after decoding it, by DTW over cross-attention (mlx_whisper/timing.py:157
    in 0.4.3), then clamps words it judges too long (:248-258 and :285-325);
    `t` comes from the same alignment, so a word's two ends are equally
    inferred. The probability is the mean, over the word's sub-word tokens, of
    the probability the model gave each one (:173-176). payload.md says which
    engine measures and which infers.

    The words are sorted by start before anything is built from them (#167).
    whisper decodes left to right, so they normally arrive in order already
    and no transcript has been seen otherwise; the sort is what makes the
    README's time-order promise hold here by code rather than by habit, as
    AlignedSentence's sort does for parakeet. It has to come first: the
    sentence's `text` is these words joined (#106), and `charOffset` indexes
    that text. Stable, so words sharing a start keep whisper's order.

    `t` is rounded to 3 places as `e` is, and `e` is never written below it
    (#174): with only `e` rounded, a zero-length word whose shifted start
    carried float noise ended before it began. Rounding after the sort cannot
    reorder the words, because it never moves one start past another.

    A word the aligner started in the pause before it is started at the word
    instead (#222, `_pause_free_starts`), and never past the next word's start,
    so that cannot reorder them either.
    """
    ordered = [
        sorted(
            cast("list[dict[str, Any]]", segment.get("words") or []),
            key=lambda w: float(w["start"]),
        )
        for segment in segments
    ]
    out: list[dict[str, Any]] = []
    for segment, words, starts in zip(segments, ordered, _pause_free_starts(ordered), strict=True):
        tokens: list[dict[str, Any]] = []
        for w, start in zip(words, starts, strict=True):
            t = round(start + offset, 3)
            tokens.append(
                {
                    "t": t,
                    "w": str(w["word"]),
                    "e": max(round(float(w["end"]) + offset, 3), t),
                    "c": round(float(w["probability"]), 3),
                }
            )
        out.append(
            {
                "start": float(segment["start"]) + offset,
                "end": float(segment["end"]) + offset,
                "text": str(segment["text"]).strip(),
                "tokens": with_char_offsets(tokens),
            }
        )
    return out


def _pause_free_starts(segments: list[list[dict[str, Any]]]) -> list[list[float]]:
    """Each word's start, moved off the pause before it where the aligner put it there (#222).

    `segments` holds the words of each segment of one whisper call, in order,
    on the call's own clock, which starts at 0.

    whisper times words after decoding, by aligning the written tokens to the
    audio, and gives each word the frames from the previous word's end to its
    own end: a word's start is the previous word's end. The pause between two
    words goes to a full stop if one was written there, and mlx-whisper then
    caps the word after it at LONG_WORD_MEDIAN_CAP_S's ceiling. With no
    punctuation the pause goes to the word after it, whole, and nothing caps
    it. `--language ur` writes almost no punctuation: 0.9% of tokens ended in a
    mark over six `--language ur` transcripts of the owner's recordings, 24.8%
    over two plain ones. On #152's synthetic English words, 1.5 s apart,
    `--roman-urdu` started a word a median 1.56 s before it was said, plain
    whisper 0.39 s, and `dsj hatao`, which caps a mute at MAX_WORD_S from the
    start, muted the pause and stopped before the word. The prompt and the
    anchored windows play no part: `--language ur` alone did the same, the
    prompt alone did not, and 30, 60 and 120 s windows all did.

    So a word whose start is the previous word's end, and which runs longer
    than twice its segment's median word length (the median taken as at most
    LONG_WORD_MEDIAN_CAP_S), starts that ceiling before its end: mlx-whisper's
    own rule, applied where its punctuation test cannot see the pause. The
    previous word can be the last of the segment before, since whisper also
    writes a run of one-word segments, and the first word of the decode
    follows its start, 0. Measured by scratch/bleep_recall/word_starts.py; the
    numbers are on #222. A word with a gap before it was already placed after
    the pause, and is left alone. The median is the segment's, not the
    decode's: a loop's words can last hundredths of a second (221 words in
    0.16 s on #148's fixture, `_owned`), and would pull a decode's median, and
    the ceiling with it, down onto ordinary words.
    """
    out: list[list[float]] = []
    previous = 0.0
    for words in segments:
        spoken = [float(w["end"]) - float(w["start"]) for w in words]
        spoken = [length for length in spoken if length > 0]
        longest = 2 * min(LONG_WORD_MEDIAN_CAP_S, statistics.median(spoken)) if spoken else 0.0
        starts: list[float] = []
        for i, w in enumerate(words):
            start, end = float(w["start"]), float(w["end"])
            # whisper rounds word times to the hundredth, so a start handed the
            # previous end is equal to it; the tolerance is half that grain.
            if spoken and abs(start - previous) < 0.005 and end - start > longest:
                following = float(words[i + 1]["start"]) if i + 1 < len(words) else end
                start = min(end - longest, following)
            previous = end
            starts.append(start)
        out.append(starts)
    return out


def _anchored(
    transcribe: Callable[..., dict[str, Any]],
    audio: Path,
    *,
    model_id: str,
    language: str | None,
    prompt: str,
    anchor_s: float,
    overlap_s: float,
    on_progress: Callable[[float, float], None] | None,
) -> list[dict[str, Any]]:
    """Transcribe in windows, re-seeding `prompt` at the head of each one.

    This exists because of a measurement, not a preference. `initial_prompt`
    is folded into an accumulated buffer that whisper's own
    condition-on-previous-text threads into every later window, but mlx-whisper
    keeps only the tail of that buffer -- decoding.py:501-503, confirmed
    against the installed library, see #100 -- so the seed rides along for as
    many windows as real speech takes to fill the budget, then is evicted
    whole, oldest tokens first, not faded gradually. A low-confidence window
    can also force an earlier reset, dropping the seed sooner than the token
    budget alone would. On a voice note that is invisible -- the bias it set
    still holds. On an hour it is fatal: one window returning Urdu script,
    which a repetition loop produces on its own (#140 measured those over
    speech-level audio, not silence), becomes the
    prompt for the next, and the run never comes back. Measured over four
    recordings on 20 Sep 2026, the share of each transcript returned in Urdu
    script despite `--roman-urdu` was 41%, 80%, 97% and 99%, worst on the
    longest file (scratch/urdu_script_share.py reproduces three of the four;
    the fourth transcript was deleted, #137).

    Cutting the audio up and prompting each piece bounds that: drift can spread
    within one window and no further. What it costs is the cross-window
    continuity whisper would otherwise carry, which is why the windows overlap
    and are not shorter: at 30s the same recordings lost 10 to 22% of their
    words (#100, measured beside ANCHOR_CHUNK_S).

    `condition_on_previous_text=False` is not the fix it looks like:
    mlx-whisper resets its prompt to `len(all_tokens)`, which drops the seed
    along with the drifted text and leaves later windows unprompted entirely.

    Raises:
        ValueError: if `anchor_s`/`overlap_s` cannot produce a positive step, or
            `overlap_s` is too short for the short-fragment check below to stay
            safe. Both are invariants a future re-measurement of
            `ANCHOR_CHUNK_S`/`ANCHOR_OVERLAP_S` (#100) could break silently
            without this.
    """
    if anchor_s <= overlap_s:
        raise ValueError(
            f"anchor_s ({anchor_s}) must be greater than overlap_s ({overlap_s}): "
            f"otherwise each window's step is zero or negative, so every window "
            f"after the first either never runs or only re-decodes audio already "
            f"covered, silently returning no new transcript for the rest of the file."
        )
    if overlap_s < 1.0:
        raise ValueError(
            f"overlap_s ({overlap_s}) must be at least 1.0s. The short-fragment "
            f"check below drops a final window under a second on the assumption "
            f"that it is wholly inside the previous window's overlap and was "
            f"already transcribed; a shorter overlap breaks that assumption and "
            f"can leave a sliver of real audio at the end of a file untranscribed."
        )

    from mlx_whisper.audio import (
        load_audio as _load_audio,  # pyright: ignore[reportUnknownVariableType]  # mlx has no stubs
    )

    data = cast("Any", _load_audio)(str(audio), sr=SAMPLE_RATE)
    total = len(data)
    window = int(anchor_s * SAMPLE_RATE)
    step = int((anchor_s - overlap_s) * SAMPLE_RATE)

    starts: list[int] = []
    for start in range(0, total, step):
        end = min(start + window, total)
        # Under a second of audio is a feature window whisper cannot fill, and
        # is in any case the tail of the previous window's overlap.
        if end - start < SAMPLE_RATE:
            break
        starts.append(start)
        if end >= total:
            break

    windows: list[list[dict[str, Any]]] = []
    for start in starts:
        end = min(start + window, total)
        result = transcribe(
            data[start:end],
            path_or_hf_repo=model_id,
            language=language,
            initial_prompt=prompt,
            word_timestamps=True,
            hallucination_silence_threshold=HALLUCINATION_SILENCE_S,
            verbose=None,
        )
        windows.append(
            _sentences_from(
                cast("list[dict[str, Any]]", result.get("segments") or []), start / SAMPLE_RATE
            )
        )
        # Both lengths from the decoded samples (#173). The total used to be
        # left to the caller, which had only ffprobe's duration of the
        # container, so a padded or rounded container put the last window
        # short of 100% or past it.
        if on_progress is not None:
            on_progress(end / SAMPLE_RATE, total / SAMPLE_RATE)

    # A window with a next one always runs its full length, so the seconds two
    # neighbours share start at the later one's start and last the overlap.
    shared = (window - step) / SAMPLE_RATE
    cuts = [
        _handover(windows[i], windows[i + 1], starts[i + 1] / SAMPLE_RATE, shared)
        for i in range(len(starts) - 1)
    ]
    sentences: list[dict[str, Any]] = []
    written = 0.0
    for i, got in enumerate(windows):
        owned = _owned(
            got,
            cuts[i - 1] if i > 0 else 0.0,
            cuts[i] if i < len(cuts) else float("inf"),
            written,
        )
        sentences.extend(owned)
        written = max([written, *(float(s["end"]) for s in owned)])
    return sentences


def _handover(
    before: list[dict[str, Any]], after: list[dict[str, Any]], start: float, shared: float
) -> float:
    """The second at which one anchored window hands over to the next (#190).

    The two share `shared` seconds from `start`, and by default each writes its
    own half: the middle is as far from both windows' edges as it can be, and
    whisper is weakest at a window's edge. Except where one of them looped
    there and the other did not. On #148's fixture one window looped from
    343.3 s to its end at 348 s, 232 words, while the next read 12 words of
    speech from 342 to 345 s; split at the middle, the loop kept 345 s and the
    speech was lost. So where only one window loops in the shared seconds, the
    other writes all of them. Not just from where the loop starts: a loop
    whisper timed into a window's last second has a start that says nothing
    about where it began. Both looping, or neither, keeps the middle. A word
    across the edge of the shared seconds can then be cut by the window edge
    in the window that writes it, which is one word against a loop.

    is_loop is dsj.suno's, imported here because suno imports this module.
    """
    from dsj.suno import is_loop

    end = start + shared
    looped_before = [s for s in before if s["end"] > start and is_loop(str(s["text"]))]
    looped_after = [s for s in after if s["start"] < end and is_loop(str(s["text"]))]
    if looped_before and not looped_after:
        return start
    if looped_after and not looped_before:
        return end
    return start + shared / 2


def _owned(
    sentences: list[dict[str, Any]], lo: float, hi: float, written: float
) -> list[dict[str, Any]]:
    """The part of one anchored window's `sentences` that is this window's to write (#190).

    Two neighbouring windows both decode the seconds they share, and not the
    same way: on #148's fixture one wrote 114.0 to 119.1 s in Urdu script and
    the next 114.0 to 142.1 s in Roman, starting with the same words. Keeping
    whole segments by their midpoint kept both, so every anchored transcript
    measured had 4 to 13 pairs of sentences overlapping at its seams.

    So each second has one owner. A window writes from `lo` to `hi`, where it
    hands over to the windows either side (_handover: the middle of the
    seconds they share, unless one of them looped there), and a word is
    written by the window that owns its midpoint. The overlap still does its
    job: a word spoken across the middle lies at least half the overlap inside
    both windows, so it is whole in each and written by exactly one. What the
    window decoded past `hi` is the next window's to write, including a loop
    whisper timed into a window's last second (221 words in 0.16 s at 233.7 s
    on the fixture), which the next window reads over again.

    Two windows can still time one word a little differently, so a word that
    starts before `written`, the end of what earlier windows wrote, is taken as
    one of theirs and dropped: that is what keeps sentences from overlapping
    across a seam. A sentence that lost words, or whose bounds reach outside
    the window's share, is rebuilt from the words it keeps; one that keeps
    none is dropped. A sentence with no words at all goes by its midpoint.
    """
    floor = max(lo, written)
    out: list[dict[str, Any]] = []
    for s in sentences:
        tokens: list[dict[str, Any]] = s["tokens"]
        if not tokens:
            if floor <= (s["start"] + s["end"]) / 2 < hi:
                out.append(s | {"start": max(s["start"], floor), "end": min(s["end"], hi)})
            continue
        keep = [t for t in tokens if lo <= (t["t"] + t["e"]) / 2 < hi and t["t"] >= written]
        if not keep:
            continue
        if len(keep) == len(tokens) and floor <= s["start"] and s["end"] <= hi:
            out.append(s)
            continue
        out.append(
            s
            | {
                "start": min(float(t["t"]) for t in keep),
                "end": max(float(t["e"]) for t in keep),
                "text": "".join(str(t["w"]) for t in keep).strip(),
                "tokens": with_char_offsets(keep),
            }
        )
    return out


def speech_segments(
    spans: Sequence[tuple[float, float]],
    max_s: float,
    probs: Sequence[float] = (),
    frame_s: float = VAD_FRAME_S,
) -> list[tuple[float, float]]:
    """Cut and merge speech `spans` into clips of at most `max_s` seconds (#236).

    `spans` are the detector's (start, end) in seconds, padded, in order and not
    overlapping. A clip starts at a span's start and takes in each next span
    while it would still end within `max_s` of that start, so the pauses between
    the spans it took are decoded with them; WhisperX's cut-and-merge does the
    same. Whether a long pause inside a clip should end it instead is not
    settled (#236): this is what the podcast's gap count on #236 measures.

    A span longer than `max_s` is cut first, at its least speech-like frame in
    the back half of the reach (`probs[i]` scores the frame starting at
    `i * frame_s`), so a cut does not leave a sliver; with no scores in reach,
    evenly. Every second of every span lands in exactly one clip.
    """
    pieces: list[tuple[float, float]] = []
    for a, b in spans:
        while b - a > max_s:
            lo, hi = a + max_s / 2, a + max_s
            reach = [
                i
                for i in range(math.ceil(lo / frame_s), math.floor(hi / frame_s) + 1)
                if i < len(probs) and a < i * frame_s <= hi
            ]
            if reach:
                cut = min(reach, key=lambda i: probs[i]) * frame_s
            else:
                cut = a + (b - a) / math.ceil((b - a) / max_s)
            pieces.append((a, cut))
            a = cut
        pieces.append((a, b))

    segments: list[tuple[float, float]] = []
    for a, b in pieces:
        if segments and b - segments[-1][0] <= max_s:
            segments[-1] = (segments[-1][0], b)
        else:
            segments.append((a, b))
    return segments


def _speech(data: Any) -> tuple[list[tuple[float, float]], list[float]]:
    """Silero's padded speech spans over `data` (16 kHz samples), and its score per frame.

    ONNX when onnxruntime imports, which is what Silero recommends for CPU; the
    TorchScript model otherwise. Both ship inside silero-vad, so nothing is
    fetched. The scores are recorded off the model as get_speech_timestamps
    calls it, frame by frame, so one pass gives both.

    Raises:
        WhisperUnavailable: if silero-vad is not installed.
    """
    from importlib import import_module
    from importlib.util import find_spec

    # Neither ships type stubs; held as Any once here rather than suppressed
    # at every use.
    try:
        silero_vad: Any = import_module("silero_vad")
        torch: Any = import_module("torch")
    except ImportError as exc:  # pragma: no cover - exercised by the extra being absent
        raise WhisperUnavailable(
            "VAD_SEGMENTS needs silero-vad, the `vad` extra: add `--extra vad` to the "
            "`uv sync` line you already use"
        ) from exc

    model: Any = silero_vad.load_silero_vad(onnx=find_spec("onnxruntime") is not None)
    probs: list[float] = []

    class _Scored:
        """The model, with every frame's speech probability kept as it is returned."""

        def reset_states(self) -> None:
            model.reset_states()

        def __call__(self, chunk: Any, sr: int) -> Any:
            out: Any = model(chunk, sr)
            probs.append(float(out.item()))
            return out

    stamps: list[dict[str, int]] = silero_vad.get_speech_timestamps(
        torch.from_numpy(np.asarray(data, dtype=np.float32)),
        _Scored(),
        threshold=VAD_THRESHOLD,
        sampling_rate=SAMPLE_RATE,
        min_speech_duration_ms=VAD_MIN_SPEECH_MS,
        min_silence_duration_ms=VAD_MIN_SILENCE_MS,
        speech_pad_ms=VAD_PAD_MS,
    )
    return [(s["start"] / SAMPLE_RATE, s["end"] / SAMPLE_RATE) for s in stamps], probs


def _detect_language(model_id: str, clip: Any) -> str:
    """The language whisper would detect in `clip`, by mlx-whisper's own steps.

    transcribe.py's detection, lifted: the log-mel of the clip padded or trimmed
    to one 30 s window, then the model's language-token probabilities. The model
    comes from mlx-whisper's own cache, so the decodes after this reuse it.
    """
    from importlib import import_module

    mx: Any = import_module("mlx.core")
    audio: Any = import_module("mlx_whisper.audio")
    holder: Any = import_module("mlx_whisper.transcribe").ModelHolder

    model: Any = holder.get_model(model_id, mx.float16)
    mel: Any = audio.log_mel_spectrogram(
        mx.array(np.asarray(clip, dtype=np.float32)),
        n_mels=model.dims.n_mels,
        padding=audio.N_SAMPLES,
    )
    segment: Any = audio.pad_or_trim(mel, audio.N_FRAMES, axis=-2).astype(mx.float16)
    probs: dict[str, float]
    _, probs = model.detect_language(segment)
    return max(probs, key=lambda k: probs[k])


def _vad_decoded(
    transcribe: Callable[..., dict[str, Any]],
    audio: Path,
    *,
    model_id: str,
    language: str | None,
    prompt: str | None,
    on_progress: Callable[[float, float], None] | None,
) -> Transcription:
    """Decode only the speech in `audio`, clip by clip (#236, VAD_SEGMENTS).

    One path for every whisper mode. The audio is loaded once by the loader
    `_anchored` uses; Silero finds the speech (`_speech`); `speech_segments`
    cuts it into clips of at most VAD_MAX_S. Each clip is decoded alone, with
    `condition_on_previous_text=False` as WhisperX does, so no clip's text,
    invented or not, is fed to the next. `prompt` seeds every clip, which is
    the anchoring `--roman-urdu` asks for at a 30 s window, and `anchor_s` has
    nothing left to do.

    With no language asked, it is detected once, on up to the first 30 s of
    speech with the pauses left out, and every clip decodes in it: left to
    detect per clip, whisper wrote Urdu in English on short clips (#229).
    """
    from mlx_whisper.audio import (
        load_audio as _load_audio,  # pyright: ignore[reportUnknownVariableType]  # mlx has no stubs
    )

    data = cast("Any", _load_audio)(str(audio), sr=SAMPLE_RATE)
    total = len(data)
    spans, probs = _speech(data)
    segments = speech_segments(spans, VAD_MAX_S, probs, VAD_FRAME_S)

    if language is None and segments:
        speech: list[Any] = []
        need = int(VAD_MAX_S * SAMPLE_RATE)
        for a, b in spans:
            piece = np.asarray(data[int(a * SAMPLE_RATE) : int(b * SAMPLE_RATE)])[:need]
            speech.append(piece)
            need -= len(piece)
            if need <= 0:
                break
        language = _detect_language(model_id, np.concatenate(speech))

    sentences: list[dict[str, Any]] = []
    for a, b in segments:
        start, end = int(a * SAMPLE_RATE), min(int(b * SAMPLE_RATE), total)
        result = transcribe(
            data[start:end],
            path_or_hf_repo=model_id,
            language=language,
            initial_prompt=prompt,
            word_timestamps=True,
            condition_on_previous_text=False,
            hallucination_silence_threshold=HALLUCINATION_SILENCE_S,
            verbose=None,
        )
        sentences.extend(
            _sentences_from(
                cast("list[dict[str, Any]]", result.get("segments") or []), start / SAMPLE_RATE
            )
        )
        if on_progress is not None:
            on_progress(end / SAMPLE_RATE, total / SAMPLE_RATE)

    return Transcription(
        text=" ".join(str(s["text"]) for s in sentences).strip(),
        sentences=sentences,
        language=language,
    )


def transcribe_whisper(
    audio: Path,
    *,
    model_id: str = DEFAULT_WHISPER_MODEL,
    language: str | None = None,
    prompt: str | None = None,
    anchor_s: float | None = None,
    on_progress: Callable[[float, float], None] | None = None,
) -> Transcription:
    """Transcribe `audio` end to end with whisper.

    Unchunked by default: whisper does its own 30-second windows and threads
    each window's text into the next as a prompt. `anchor_s` overrides that for
    the case where the threading is the problem rather than the point -- see
    `_anchored`, which the Roman Urdu path sets because the bias does not
    otherwise survive an hour of audio.

    Args:
        audio: A file ffmpeg can open. 16 kHz mono costs least; anything else
            is resampled inside whisper.
        model_id: An mlx-community whisper repo.
        language: ISO code, or None to let whisper detect it. Naming it saves
            the detection pass and stops a code-switched clip being detected as
            English.
        prompt: Seeds the decoder. `ROMAN_URDU_PROMPT` is the measured one.
        anchor_s: Window length, in seconds, to re-seed `prompt` at. None
            leaves whisper's own window loop alone; ignored without a prompt,
            there being nothing to anchor.
        on_progress: Called after each anchored window with the seconds of
            audio finished and the seconds there are, both counted in the
            samples whisper decoded, so their ratio ends at exactly 1.0.
            Never called on the unchunked path, which has no hook to call it
            from.

    Returns:
        The full text and the payload's sentences, one per whisper segment,
        and the language it decoded in: `language`, or what whisper detected.

    Raises:
        WhisperUnavailable: if mlx-whisper is not installed.
    """
    try:
        import mlx_whisper
    except ImportError as exc:  # pragma: no cover - exercised by the extra being absent
        raise WhisperUnavailable(
            f"the whisper engine needs mlx-whisper, which is an optional extra. "
            f"Install it with {INSTALL_HINT}, or use the default "
            f"`--engine parakeet`."
        ) from exc

    # mlx-whisper annotates its parameters but returns
    # `dict[str, str | list[Unknown]]`, so every value read out of the result
    # is partially unknown at the read. Restating the call once here stops that
    # spreading through the loop below. The suppression is on the member access
    # itself, which has no expression to annotate.
    transcribe = cast(
        "Callable[..., dict[str, Any]]",
        mlx_whisper.transcribe,  # pyright: ignore[reportUnknownMemberType]
    )

    if VAD_SEGMENTS:
        return _vad_decoded(
            transcribe,
            audio,
            model_id=model_id,
            language=language,
            prompt=prompt,
            on_progress=on_progress,
        )

    if anchor_s is not None and prompt is not None:
        sentences = _anchored(
            transcribe,
            audio,
            model_id=model_id,
            language=language,
            prompt=prompt,
            anchor_s=anchor_s,
            overlap_s=ANCHOR_OVERLAP_S,
            on_progress=on_progress,
        )
        return Transcription(
            text=" ".join(str(s["text"]) for s in sentences).strip(),
            sentences=sentences,
            language=language,
        )

    result = transcribe(
        str(audio),
        path_or_hf_repo=model_id,
        language=language,
        initial_prompt=prompt,
        # The whole point of choosing whisper here. merge.py's speaker vote is
        # per token, and without this whisper returns segment bounds only.
        word_timestamps=True,
        hallucination_silence_threshold=HALLUCINATION_SILENCE_S,
        # None, and NOT False. mlx-whisper reads this backwards from the way it
        # looks: `disable=verbose is not False`, so verbose=False is the value
        # that SHOWS its tqdm bar, and only None silences it. Observed -- the
        # first run of this function printed an 11,580-frame bar over dsj's
        # own line. dsj owns this terminal row, and a detached run reads
        # --status rather than stderr.
        verbose=None,
    )

    segments = cast("list[dict[str, Any]]", result.get("segments") or [])
    # whisper names the language it decoded in, detected from the first 30 s
    # when none was asked for. The loop retry decodes in it (#229).
    detected = result.get("language")
    return Transcription(
        text=str(result.get("text", "")).strip(),
        sentences=_sentences_from(segments, 0.0),
        language=language or (str(detected) if detected else None),
    )


def redecoder(
    audio: Path, *, model_id: str, language: str | None, prompt: str | None
) -> Callable[[float, float, Mapping[str, Any]], list[dict[str, Any]]]:
    """A function that decodes `start_s` to `end_s` of `audio` again, for a loop span (#183).

    The audio is loaded once, here, by the loader `_anchored` uses, so a clip
    is the same samples the main pass decoded. Each call cuts one clip and
    decodes it alone with `condition_on_previous_text=False`: the text around a
    loop is what fed it, so nothing from outside the clip goes in. The call
    otherwise starts from the run's own settings, `language` and `prompt`, and
    `options` overrides them (dsj/suno.py: RETRY_PLAIN, RETRY_WARM).

    Returns payload sentences on the recording's clock, as `_sentences_from`
    builds them.

    Raises:
        WhisperUnavailable: if mlx-whisper is not installed.
    """
    try:
        import mlx_whisper
        from mlx_whisper.audio import (
            load_audio as _load_audio,  # pyright: ignore[reportUnknownVariableType]  # mlx has no stubs
        )
    except ImportError as exc:  # pragma: no cover - exercised by the extra being absent
        raise WhisperUnavailable(
            f"retrying a loop needs mlx-whisper. Install it with {INSTALL_HINT}."
        ) from exc

    transcribe = cast(
        "Callable[..., dict[str, Any]]",
        mlx_whisper.transcribe,  # pyright: ignore[reportUnknownMemberType]
    )
    data = cast("Any", _load_audio)(str(audio), sr=SAMPLE_RATE)

    def decode(start_s: float, end_s: float, options: Mapping[str, Any]) -> list[dict[str, Any]]:
        a = max(0, int(start_s * SAMPLE_RATE))
        b = min(len(data), int(end_s * SAMPLE_RATE))
        settings: dict[str, Any] = {
            "path_or_hf_repo": model_id,
            "language": language,
            "initial_prompt": prompt,
            "word_timestamps": True,
            "condition_on_previous_text": False,
            "hallucination_silence_threshold": HALLUCINATION_SILENCE_S,
            "verbose": None,
        } | dict(options)
        result = transcribe(data[a:b], **settings)
        return _sentences_from(
            cast("list[dict[str, Any]]", result.get("segments") or []), a / SAMPLE_RATE
        )

    return decode
