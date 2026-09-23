"""whisper, for the audio parakeet cannot read.

`parakeet-tdt-0.6b-v3` is the default engine and stays the default: it runs at
~13x realtime and does not invent words over silence. What it does not have is
Urdu -- its 25 languages are European, and `ur` is not among the model card's
tags. A voice note that mixes Urdu and English comes back as nothing usable.

whisper-large-v3-turbo does read it, at a cost: measured on 116s of Urdu speech
it took 84.7s (~1.4x realtime) against parakeet's ~13x. That is fine for a voice
note and would not be for an hour of lecture, which is why this is a flag and
not a replacement.

ROMAN URDU IS A PROMPT, NOT A SETTING. whisper transcribes Urdu in Urdu script
by default. Seeding the decoder with a Roman Urdu `initial_prompt` makes it emit
Roman instead, and it carries across windows through whisper's own
condition-on-previous-text. UNVERIFIED -- no reproducing script in this repo,
see #100: over the same 116s, 275 of 277 words were claimed to come back in
Latin, the two exceptions single words inside otherwise-Roman sentences.

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

That trick is model-specific, and the difference is not subtle. The full
whisper-large-v3 ignores the prompt completely -- 280 of 280 words in Urdu
script, in 218s rather than 85s. Hence the default here is turbo, and changing
it means re-measuring rather than assuming.
"""

from __future__ import annotations

__all__ = [
    "ANCHOR_CHUNK_S",
    "ANCHOR_OVERLAP_S",
    "DEFAULT_WHISPER_MODEL",
    "INSTALL_HINT",
    "ROMAN_URDU_PROMPT",
    "SAMPLE_RATE",
    "WhisperUnavailable",
    "available",
    "transcribe_whisper",
]

from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from dsj.asr import Transcription

DEFAULT_WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"

# whisper's own front end resamples to 16 kHz mono whatever it is handed, so
# this is not a preference: handing it anything else means paying for a second
# resample of an hour of audio inside a library that will not report progress.
SAMPLE_RATE = 16000

# The window the Roman Urdu prompt is re-seeded at, and how much of it is
# decoded twice. 120s because the bias was measured to survive 116s unaided --
# UNVERIFIED, no reproducing script in this repo, see #100 -- and shortening it
# buys anchoring at the price of the continuity whisper is good at. The overlap
# is there so a word spoken across a boundary is whole in at least one window;
# `_anchored` keeps each segment in exactly one of them. `_anchored` also
# requires `ANCHOR_CHUNK_S > ANCHOR_OVERLAP_S >= 1.0`; see its own validation.
ANCHOR_CHUNK_S = 120.0
ANCHOR_OVERLAP_S = 6.0

INSTALL_HINT = (
    'uv tool install "dsj[whisper] @ git+https://github.com/m2moiz/dekho-suno-jaano"'
    " (or `uv sync --extra whisper` from a clone)"
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
        return f"mlx-whisper is not installed. Install it with `{INSTALL_HINT}`."
    return None


class WhisperUnavailable(RuntimeError):
    """The whisper engine was asked for and mlx-whisper is not installed."""

def _sentences_from(segments: list[dict[str, Any]], offset: float) -> list[dict[str, Any]]:
    """Turn whisper's segments into payload sentences, shifted by `offset` seconds.

    The word text is kept exactly as whisper emits it, leading space and all,
    which is how parakeet's tokens arrive too. A reader joining tokens gets the
    sentence back either way.
    """
    out: list[dict[str, Any]] = []
    for segment in segments:
        words = cast("list[dict[str, Any]]", segment.get("words") or [])
        out.append(
            {
                "start": float(segment["start"]) + offset,
                "end": float(segment["end"]) + offset,
                "text": str(segment["text"]).strip(),
                "tokens": [
                    {"t": float(w["start"]) + offset, "w": str(w["word"])} for w in words
                ],
            }
        )
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
    on_progress: Callable[[float], None] | None,
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
    which a hallucination loop over silence produces on its own, becomes the
    prompt for the next, and the run never comes back. Measured over four
    recordings on 20 Sep 2026, the share of each transcript returned in Urdu
    script despite `--roman-urdu` was 41%, 80%, 97% and 99%, worst on the
    longest file (scratch/urdu_script_share.py reproduces three of the four;
    the fourth transcript was deleted, #137).

    Cutting the audio up and prompting each piece bounds that: drift can spread
    within one window and no further. What it costs is the cross-window
    continuity whisper would otherwise carry, which is why the windows overlap
    and are not shorter than the 116s the Roman bias was measured to survive
    (also UNVERIFIED, see #100).

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

    sentences: list[dict[str, Any]] = []
    covered = 0.0
    for start in range(0, total, step):
        end = min(start + window, total)
        # Under a second of audio is a feature window whisper cannot fill, and
        # is in any case the tail of the previous window's overlap.
        if end - start < SAMPLE_RATE:
            break

        result = transcribe(
            data[start:end],
            path_or_hf_repo=model_id,
            language=language,
            initial_prompt=prompt,
            word_timestamps=True,
            verbose=None,
        )
        offset = start / SAMPLE_RATE
        for sentence in _sentences_from(
            cast("list[dict[str, Any]]", result.get("segments") or []), offset
        ):
            # The overlap is decoded twice on purpose, so that a word across a
            # boundary is whole in at least one window. A segment is kept by
            # its midpoint, which puts it in exactly one of the two. Known
            # limitation, not fixed here: this trusts whichever window decoded
            # the overlap first. A hallucinated segment there (whisper is known
            # to hallucinate over silence -- see this function's own docstring)
            # can push `covered` past real content, and the next window's
            # re-decode of that same span -- possibly the correct one -- is
            # the copy that gets dropped. Needs a real failing recording to
            # measure against (#100); none exists in this repo yet.
            if (sentence["start"] + sentence["end"]) / 2 < covered:
                continue
            sentences.append(sentence)
            covered = max(covered, float(sentence["end"]))

        if on_progress is not None:
            on_progress(end / SAMPLE_RATE)
        if end >= total:
            break

    return sentences


def transcribe_whisper(
    audio: Path,
    *,
    model_id: str = DEFAULT_WHISPER_MODEL,
    language: str | None = None,
    prompt: str | None = None,
    anchor_s: float | None = None,
    on_progress: Callable[[float], None] | None = None,
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
        on_progress: Called with seconds of audio finished, after each anchored
            window. Never called on the unchunked path, which has no hook to
            call it from.

    Returns:
        The full text and the payload's sentences, one per whisper segment.

    Raises:
        WhisperUnavailable: if mlx-whisper is not installed.
    """
    try:
        import mlx_whisper
    except ImportError as exc:  # pragma: no cover - exercised by the extra being absent
        raise WhisperUnavailable(
            f"the whisper engine needs mlx-whisper, which is an optional extra. "
            f"Install it with `{INSTALL_HINT}`, or use the default "
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
            text=" ".join(str(s["text"]) for s in sentences).strip(), sentences=sentences
        )

    result = transcribe(
        str(audio),
        path_or_hf_repo=model_id,
        language=language,
        initial_prompt=prompt,
        # The whole point of choosing whisper here. merge.py's speaker vote is
        # per token, and without this whisper returns segment bounds only.
        word_timestamps=True,
        # None, and NOT False. mlx-whisper reads this backwards from the way it
        # looks: `disable=verbose is not False`, so verbose=False is the value
        # that SHOWS its tqdm bar, and only None silences it. Observed -- the
        # first run of this function printed an 11,580-frame bar over dsj's
        # own line. dsj owns this terminal row, and a detached run reads
        # --status rather than stderr.
        verbose=None,
    )

    segments = cast("list[dict[str, Any]]", result.get("segments") or [])
    return Transcription(
        text=str(result.get("text", "")).strip(), sentences=_sentences_from(segments, 0.0)
    )
