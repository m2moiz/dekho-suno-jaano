"""The public Urdu-English fixture (#148): how it is laid out, and what was built.

Two halves. The fast tests drive `scratch/build_urdu_fixture.py`'s pure parts
on made-up clips, so a change to where the gaps go or how jumps are recorded
fails in the inner loop. The slow tests read the built fixture itself.

The slow tests FAIL when the fixture is missing; they never skip. The older
slow tests that keep audio in scratch/ skip when it is absent
(tests/test_suno_e2e.py), which on a fresh clone reports green having run
nothing. `just verify` builds the fixture first, so the only way to a green
result here is to have actually read the audio.
"""

from __future__ import annotations

import importlib.util
import json
import wave
from collections.abc import Callable
from itertools import pairwise
from pathlib import Path
from typing import Any, Protocol, cast

import numpy as np
import numpy.typing as npt
import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scratch" / "build_urdu_fixture.py"


class FixtureBuilder(Protocol):
    """What these tests use from scratch/build_urdu_fixture.py."""

    OUT: Path
    SAMPLE_RATE: int
    GAPS: tuple[tuple[int, float], ...]
    NOISE_DBFS: float
    CLIPS: int
    PODCAST_SHA256: str
    clip_number: Callable[[str], int]
    noise: Callable[[int, str, int], npt.NDArray[np.int16]]
    layout: Callable[
        [list[tuple[str, int, str]], tuple[tuple[int, float], ...], str],
        tuple[list[dict[str, Any]], list[dict[str, Any]]],
    ]
    sha256: Callable[[Path], str]


@pytest.fixture(scope="module")
def builder() -> FixtureBuilder:
    """The build script, imported by path: scratch/ is not a package.

    Loud if it cannot load. The fixture may be missing on a fresh clone; the
    script that builds it may not.
    """
    spec = importlib.util.spec_from_file_location("build_urdu_fixture", SCRIPT)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast("FixtureBuilder", module)


def db(samples: npt.NDArray[np.int16]) -> float:
    """RMS level in dB relative to 16-bit full scale."""
    rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
    return 20 * float(np.log10(max(rms, 1e-9) / 32768.0))


# --- fast: the layout, on made-up clips ------------------------------------


def test_clip_numbers_come_from_the_end_of_the_name(builder: FixtureBuilder) -> None:
    assert builder.clip_number("SPEAKER_000_PODCAST_0010.WAV") == 10
    assert builder.clip_number("SPEAKER_000_PODCAST_0074") == 74
    with pytest.raises(ValueError, match="no clip number"):
        builder.clip_number("podcast.wav")


def test_gaps_sit_at_clip_joins_and_jumps_are_recorded(builder: FixtureBuilder) -> None:
    """Two gaps and two numbering holes over six clips, every boundary checked.

    The timeline must have no holes and no overlaps, each gap must follow the
    clip it was asked to follow, and a jump is recorded exactly where the
    numbering skips (4 to 6, 7 to 10), at the start of the clip after it.
    """
    rate = builder.SAMPLE_RATE
    numbers = [2, 3, 4, 6, 7, 10]
    clips = [(f"SPEAKER_000_PODCAST_{n:04d}", (n + 1) * rate, f"text {n}") for n in numbers]

    segments, jumps = builder.layout(clips, ((2, 1.0), (4, 0.5)), "noise")

    assert [s.get("clip", s["kind"]) for s in segments] == [
        "SPEAKER_000_PODCAST_0002", "SPEAKER_000_PODCAST_0003", "gap",
        "SPEAKER_000_PODCAST_0004", "SPEAKER_000_PODCAST_0006", "gap",
        "SPEAKER_000_PODCAST_0007", "SPEAKER_000_PODCAST_0010",
    ]
    assert segments[0]["start"] == 0.0
    for before, after in pairwise(segments):
        assert after["start"] == before["end"]
    gaps = [s for s in segments if s["kind"] == "gap"]
    assert [s["end"] - s["start"] for s in gaps] == [1.0, 0.5]
    assert {s["noise"] for s in gaps} == {"noise"}
    assert [s["ground_truth"] for s in segments if s["kind"] == "clip"] == [
        f"text {n}" for n in numbers
    ]

    by_clip = {s.get("clip"): s["start"] for s in segments}
    assert jumps == [
        {"from_clip": 4, "to_clip": 6, "at": by_clip["SPEAKER_000_PODCAST_0006"]},
        {"from_clip": 7, "to_clip": 10, "at": by_clip["SPEAKER_000_PODCAST_0010"]},
    ]


def test_noise_gaps_are_quiet_room_sound_and_reproducible(builder: FixtureBuilder) -> None:
    """-60 dBFS white noise: audible to a meter, silent to a listener, same every build."""
    ten_s = 10 * builder.SAMPLE_RATE
    first = builder.noise(ten_s, "noise", 148)

    assert first.dtype == np.int16
    assert len(first) == ten_s
    assert abs(db(first) - builder.NOISE_DBFS) < 0.5
    assert np.count_nonzero(first) > 0.9 * ten_s
    assert np.array_equal(first, builder.noise(ten_s, "noise", 148))
    assert not np.array_equal(first, builder.noise(ten_s, "noise", 149))


def test_zero_gaps_are_digital_silence(builder: FixtureBuilder) -> None:
    zero = builder.noise(16000, "zero", 148)
    assert zero.dtype == np.int16
    assert not zero.any()


# --- slow: the built fixture -----------------------------------------------


def built(builder: FixtureBuilder) -> tuple[Path, dict[str, Any]]:
    """The fixture's audio path and ground truth, or a failure naming the fix."""
    wav = builder.OUT / "podcast.wav"
    truth = builder.OUT / "ground_truth.json"
    if not (wav.exists() and truth.exists()):
        pytest.fail(
            f"{wav.relative_to(builder.OUT.parent.parent)} or ground_truth.json is missing: "
            "run `just urdu-fixture` (#148). This test fails rather than skips, so a "
            "green run means the audio was actually read."
        )
    return wav, json.loads(truth.read_text())


def samples_of(wav: Path) -> tuple[int, npt.NDArray[np.int16]]:
    with wave.open(str(wav), "rb") as fh:
        assert (fh.getnchannels(), fh.getsampwidth()) == (1, 2)
        return fh.getframerate(), np.frombuffer(fh.readframes(fh.getnframes()), dtype="<i2")


@pytest.mark.slow
def test_the_fixture_is_the_pinned_build(builder: FixtureBuilder) -> None:
    """The bytes every number measured on this fixture was measured on."""
    wav, truth = built(builder)
    assert builder.sha256(wav) == builder.PODCAST_SHA256
    assert truth["sha256"] == builder.PODCAST_SHA256
    assert truth["source"]["licence"] == "CC-BY-4.0"


@pytest.mark.slow
def test_the_ground_truth_covers_the_audio_end_to_end(builder: FixtureBuilder) -> None:
    """30 clips and three gaps, back to back, from 0 to the file's last sample."""
    wav, truth = built(builder)
    rate, audio = samples_of(wav)
    segments: list[dict[str, Any]] = truth["segments"]

    assert rate == builder.SAMPLE_RATE == truth["sample_rate"]
    assert truth["duration_s"] == round(len(audio) / rate, 3)
    assert segments[0]["start"] == 0.0
    assert segments[-1]["end"] == truth["duration_s"]
    for before, after in pairwise(segments):
        assert after["start"] == before["end"]
    clips = [s for s in segments if s["kind"] == "clip"]
    gaps = [s for s in segments if s["kind"] == "gap"]
    assert len(clips) == builder.CLIPS
    assert all(s["ground_truth"].strip() for s in clips)
    assert [round(s["end"] - s["start"], 3) for s in gaps] == [g for _, g in builder.GAPS]


@pytest.mark.slow
def test_the_gaps_are_quiet_and_every_clip_is_speech(builder: FixtureBuilder) -> None:
    """Gaps below the -45 dB line scratch/real_bench.py calls quiet; no clip is."""
    wav, truth = built(builder)
    rate, audio = samples_of(wav)
    for segment in truth["segments"]:
        part = audio[round(segment["start"] * rate) : round(segment["end"] * rate)]
        if segment["kind"] == "gap":
            assert abs(db(part) - builder.NOISE_DBFS) < 0.5, segment
        else:
            assert db(part) > -45.0, segment["clip"]
