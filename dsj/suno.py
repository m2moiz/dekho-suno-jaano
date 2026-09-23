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
    "OVERLAP_S",
    "Progress",
    "clock",
    "main",
    "render_bar",
    "transcribe",
]

import json
import logging
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

# Imported as media_mod because the parameter it serves is named `media` and
# would shadow the module inside the function body.
from dsj import media as media_mod
from dsj.asr import ENGINES, Transcription, get_engine, with_char_offsets
from dsj.atomic import atomic_write_text

# Names only -- both engine modules keep their backends lazy, so pulling
# these in costs nothing to a run that never asks for the engine, and it
# keeps `--help` able to print the defaults.
from dsj.parakeet import DEFAULT_MODEL
from dsj.whisper import DEFAULT_WHISPER_MODEL
from dsj.whisper import SAMPLE_RATE as WHISPER_SAMPLE_RATE

if TYPE_CHECKING:
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
    before you choose it: it owns its own window loop, so there is no
    checkpoint and no resume, and it reports no progress between start and
    finish. `language` and `prompt` are whisper's; parakeet takes neither.
    `model_id` defaults to whichever engine's model, so it is usually left
    alone.
    """
    if engine not in ENGINES:
        raise ValueError(f"unknown engine {engine!r}, expected one of {', '.join(ENGINES)}")
    if engine == "parakeet" and (language is not None or prompt is not None):
        raise ValueError(
            "--language and --prompt are whisper's; parakeet takes neither. "
            "Add --engine whisper, or drop them."
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
        write_checkpoint,
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

    def write_status(p: Progress, state: str) -> None:
        if status_path is None:
            return
        payload = asdict(p) | {
            "state": state,
            "fraction": round(p.fraction, 4),
            "speed": round(p.speed, 2),
            "eta_s": p.eta_s,
        }
        # Not fsynced: a reader is protected by the rename alone, and a
        # heartbeat lost to a power cut costs nothing to regenerate.
        atomic_write_text(status_path, json.dumps(payload))

    def report(p: Progress, state: str) -> None:
        write_status(p, state)
        if on_progress:
            on_progress(p, state)

    stream = media_mod.probe(media)

    with tempfile.TemporaryDirectory(prefix="dsj-") as tmp:
        if media_mod.needs_conversion(stream, rate):
            # Per-phase clock. Extraction runs three orders of magnitude faster
            # than realtime and the transcription that follows around 20x;
            # sharing one elapsed would make both speeds meaningless.
            extract_started = time.monotonic()

            def on_extract(done_s: float) -> None:
                report(
                    Progress(done_s, stream.duration_s, time.monotonic() - extract_started),
                    "extracting",
                )

            audio = media_mod.extract_audio(
                media, Path(tmp) / "audio.wav", rate, on_progress=on_extract
            )
        else:
            audio = media

        ckpt_path: Path | None = None
        resumed_from_s = 0.0
        # The recording's length as this run's transcription frames report it,
        # kept so the done frame can report the same number (#52). whisper's
        # frames take ffprobe's duration; the chunk branch below replaces it
        # with the decoded length, which is what its running frames divide by.
        audio_total_s = stream.duration_s
        if spec.kind == "file":
            from dsj.whisper import transcribe_whisper

            # No checkpoint, and so no resume: whisper owns its window loop and
            # exposes no per-window hook to bank one from. Said out loud rather
            # than left as a silently absent feature, because a resumable engine
            # and a non-resumable one look identical until the run is killed.
            if resume:
                logger.info("whisper writes no checkpoint; an interrupted run starts over")
            report(Progress(0.0, stream.duration_s, 0.0), "running")
            whisper_started = time.monotonic()

            # The anchored path cuts the audio itself, so it can say where it
            # has got to. Unanchored there is still one report at 0% and
            # nothing until the end: mlx-whisper takes no progress callback,
            # and a bar that moved without evidence would be a bar that lies.
            whisper_progress: Callable[[float], None] | None = None
            if anchor_s is not None and prompt is not None:

                def _whisper_progress(done_s: float) -> None:
                    report(
                        Progress(done_s, stream.duration_s, time.monotonic() - whisper_started),
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
        else:
            audio_data = loaded.load_audio(audio)
            audio_total_s = len(audio_data) / rate

            ckpt_path = checkpoint_path_for(out)
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
        transcription = _in_time_order(_in_whole_milliseconds(_text_from_tokens(transcription)))

        payload: Payload = {
            # The source the user handed us, never the temp wav -- this JSON is
            # an index into that file and has to keep pointing at it.
            "audio": str(media),
            # No separate engine field: the model id already names it, and
            # tests/test_suno.py pins this key set precisely so a downstream
            # reader can rely on it.
            "model": model_id,
            "text": transcription.text,
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

        # Removed once labelling is over, not as soon as `out` is written
        # (#101). The unlabelled transcript carries no fingerprint, so the next
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
        if ckpt_path is not None:
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
