"""Silero's speech detector in front of whisper (#236), off by default.

`speech_segments` is the cut-and-merge that turns the detector's speech spans
into the clips whisper decodes. It is pure, so most of these tests are about it
alone. The rest stub mlx-whisper and the detector the way tests/test_whisper.py
does, and pin what the VAD path sends whisper for each clip.
"""

from __future__ import annotations

import importlib.metadata
import random
import sys
from itertools import pairwise
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
import pytest

from dsj import whisper as whisper_mod
from dsj.whisper import ROMAN_URDU_PROMPT, fingerprint_fields, speech_segments, transcribe_whisper

SR = whisper_mod.SAMPLE_RATE


def _covered(spans: list[tuple[float, float]], segments: list[tuple[float, float]]) -> bool:
    """Every second of every span lies inside some segment."""
    return all(
        any(a <= s0 + 1e-9 and s1 <= b + 1e-9 for a, b in segments)
        or _split_cover(s0, s1, segments)
        for s0, s1 in spans
    )


def _split_cover(s0: float, s1: float, segments: list[tuple[float, float]]) -> bool:
    """A span cut into several segments is covered when they tile it with no hole."""
    at = s0
    for a, b in sorted(segments):
        if a <= at + 1e-9 < b:
            at = b
        if at >= s1 - 1e-9:
            return True
    return False


def test_no_speech_makes_no_segments() -> None:
    assert speech_segments([], 30.0) == []


def test_spans_merge_while_the_segment_stays_within_the_cap() -> None:
    """Measured from the segment's start to the added span's end, gaps included."""
    spans = [(0.0, 10.0), (12.0, 25.0), (26.0, 31.0), (40.0, 41.0)]

    assert speech_segments(spans, 30.0) == [(0.0, 25.0), (26.0, 41.0)]


def test_a_span_longer_than_the_cap_is_cut_at_its_quietest_frame() -> None:
    """70 s of speech, frames of 1 s: the least likely frame in reach is where it is cut.

    The first cut is looked for in the back half of the cap, 15 to 30 s, so a
    quiet frame at 5 s does not leave a 5 s segment; 22 s is the quietest there.
    The second is looked for in 37 to 52 s, where 40 s is.
    """
    probs = [0.9] * 70
    probs[5] = 0.0
    probs[22] = 0.1
    probs[40] = 0.2

    got = speech_segments([(0.0, 70.0)], 30.0, probs=probs, frame_s=1.0)

    assert got == [(0.0, 22.0), (22.0, 40.0), (40.0, 70.0)]


def test_without_frame_scores_a_long_span_is_cut_evenly() -> None:
    assert speech_segments([(10.0, 85.0)], 30.0) == [(10.0, 35.0), (35.0, 60.0), (60.0, 85.0)]


def test_the_rest_of_a_cut_span_merges_with_the_speech_after_it() -> None:
    got = speech_segments([(0.0, 40.0), (41.0, 45.0)], 30.0)

    assert got == [(0.0, 20.0), (20.0, 45.0)]


@pytest.mark.parametrize("seed", range(20))
def test_segments_keep_order_respect_the_cap_and_lose_no_speech(seed: int) -> None:
    rng = random.Random(seed)
    spans: list[tuple[float, float]] = []
    at = rng.uniform(0, 3)
    for _ in range(rng.randint(1, 40)):
        length = rng.choice([rng.uniform(0.3, 8), rng.uniform(8, 95)])
        spans.append((round(at, 3), round(at + length, 3)))
        at += length + rng.choice([0.0, rng.uniform(0.1, 2), rng.uniform(2, 40)])
    frames = int(at / 0.032) + 1
    probs = [rng.random() for _ in range(frames)] if seed % 2 else []

    got = speech_segments(spans, 30.0, probs=probs, frame_s=0.032)

    assert all(b - a <= 30.0 + 1e-9 for a, b in got)
    assert all(a < b for a, b in got)
    assert all(b0 <= a1 for (_, b0), (a1, _) in pairwise(got))
    assert _covered(spans, got)
    assert got[0][0] == spans[0][0]
    assert got[-1][1] == spans[-1][1]


def _stub_vad_run(
    monkeypatch: pytest.MonkeyPatch,
    seconds: float,
    spans: list[tuple[float, float]],
    results: list[dict[str, Any]],
    detected: str = "hi",
) -> tuple[list[dict[str, Any]], list[float]]:
    """mlx-whisper, its loader and the detector stubbed; the VAD switch on.

    Returns the calls whisper got (samples handed it plus every keyword) and
    the lengths of every clip language detection was asked about.
    """
    monkeypatch.setattr(whisper_mod, "VAD_SEGMENTS", True)
    calls: list[dict[str, Any]] = []

    def fake_transcribe(audio: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append({"n_samples": len(audio), **kwargs})
        return results[len(calls) - 1]

    module = ModuleType("mlx_whisper")
    module.transcribe = fake_transcribe  # pyright: ignore[reportAttributeAccessIssue]
    monkeypatch.setitem(sys.modules, "mlx_whisper", module)
    audio_module = ModuleType("mlx_whisper.audio")
    def fake_load_audio(file: str, sr: int = SR) -> np.ndarray:
        return np.zeros(int(seconds * SR), dtype=np.float32)

    audio_module.load_audio = fake_load_audio  # pyright: ignore[reportAttributeAccessIssue]
    monkeypatch.setitem(sys.modules, "mlx_whisper.audio", audio_module)

    def fake_speech(data: Any) -> tuple[list[tuple[float, float]], list[float]]:
        return spans, []

    monkeypatch.setattr(whisper_mod, "_speech", fake_speech)
    asked: list[float] = []

    def fake_detect(model_id: str, clip: Any) -> str:
        asked.append(len(clip) / SR)
        return detected

    monkeypatch.setattr(whisper_mod, "_detect_language", fake_detect)
    return calls, asked


def _seg(start: float, end: float, text: str) -> dict[str, Any]:
    return {
        "start": start,
        "end": end,
        "text": text,
        "words": [{"word": f" {text}", "start": start, "end": end, "probability": 0.9}],
    }


def test_each_segment_is_decoded_alone_and_timed_on_the_files_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, asked = _stub_vad_run(
        monkeypatch,
        seconds=100.0,
        spans=[(2.0, 12.0), (60.0, 70.0)],
        results=[
            {"segments": [_seg(0.5, 1.5, "ek")]},
            {"segments": [_seg(1.0, 2.0, "do")]},
        ],
    )

    got = transcribe_whisper(Path("a.wav"), model_id="m", language="ur")

    assert [c["n_samples"] for c in calls] == [10 * SR, 10 * SR]
    assert all(c["condition_on_previous_text"] is False for c in calls)
    assert all(c["word_timestamps"] is True for c in calls)
    assert all(c["language"] == "ur" for c in calls)
    assert all(c["initial_prompt"] is None for c in calls)
    assert [(s["start"], s["end"]) for s in got.sentences] == [(2.5, 3.5), (61.0, 62.0)]
    assert [t["t"] for s in got.sentences for t in s["tokens"]] == [2.5, 61.0]
    assert got.language == "ur"
    assert asked == []


def test_roman_urdu_seeds_every_segment_and_no_anchor_windows_are_cut(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, _ = _stub_vad_run(
        monkeypatch,
        seconds=300.0,
        spans=[(0.0, 20.0), (100.0, 110.0), (200.0, 229.0)],
        results=[{"segments": []} for _ in range(3)],
    )

    transcribe_whisper(
        Path("a.wav"), language="ur", prompt=ROMAN_URDU_PROMPT, anchor_s=whisper_mod.ANCHOR_CHUNK_S
    )

    assert [c["n_samples"] for c in calls] == [20 * SR, 10 * SR, 29 * SR]
    assert all(c["initial_prompt"] == ROMAN_URDU_PROMPT for c in calls)


def test_a_language_left_to_whisper_is_detected_once_on_the_first_speech(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Up to 30 s of speech, gaps left out, and every segment decodes in what it found."""
    calls, asked = _stub_vad_run(
        monkeypatch,
        seconds=200.0,
        spans=[(0.0, 20.0), (100.0, 120.0), (150.0, 160.0)],
        results=[{"segments": []} for _ in range(3)],
        detected="ur",
    )

    got = transcribe_whisper(Path("a.wav"))

    assert asked == [30.0]
    assert all(c["language"] == "ur" for c in calls)
    assert got.language == "ur"


def test_progress_is_reported_at_each_segments_end(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_vad_run(
        monkeypatch,
        seconds=50.0,
        spans=[(1.0, 5.0), (40.0, 45.0)],
        results=[{"segments": []} for _ in range(2)],
    )
    seen: list[tuple[float, float]] = []

    transcribe_whisper(
        Path("a.wav"), language="en", on_progress=lambda d, t: seen.append((d, t))
    )

    assert seen == [(5.0, 50.0), (45.0, 50.0)]


def test_a_file_with_no_speech_decodes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    calls, asked = _stub_vad_run(monkeypatch, seconds=20.0, spans=[], results=[])

    got = transcribe_whisper(Path("a.wav"))

    assert calls == []
    assert asked == []
    assert got.sentences == []
    assert got.language is None


def test_the_fingerprint_is_unchanged_with_the_detector_off_and_differs_with_it_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Off, a checkpoint banked before #236 still resumes; on, it never does.

    silero-vad's version is stubbed: the `vad` extra is not in CI's sync line.
    """
    off = fingerprint_fields("ur", ROMAN_URDU_PROMPT, 120.0)
    assert not any(k.startswith(("vad", "silero")) for k in off)

    real = importlib.metadata.version

    def version(name: str) -> str:
        return "6.2.1" if name == "silero-vad" else real(name)

    monkeypatch.setattr(importlib.metadata, "version", version)
    monkeypatch.setattr(whisper_mod, "VAD_SEGMENTS", True)
    on = fingerprint_fields("ur", ROMAN_URDU_PROMPT, 120.0)

    assert on != off
    assert on["vad_max_s"] == str(whisper_mod.VAD_MAX_S)
    assert on["vad_pad_ms"] == str(whisper_mod.VAD_PAD_MS)
    # The anchor is not used under the detector, so it is not part of the key.
    assert on["anchor_s"] == "None"


def test_the_detector_is_off_by_default() -> None:
    assert whisper_mod.VAD_SEGMENTS is False
