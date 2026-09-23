"""The whisper engine: the mapping, the call it makes, and one real run.

mlx-whisper is stubbed in every fast test here -- not to avoid asserting on a
stub, but because what these tests are about IS the boundary: which keyword
arguments dsj sends, and what it does with the dict that comes back. The one
test that runs the real thing is slow-marked and runs whisper-tiny against
speech `say` synthesizes, so nothing binary is committed.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
import pytest

from dsj import whisper as whisper_mod
from dsj.suno import transcribe
from dsj.whisper import ROMAN_URDU_PROMPT, WhisperUnavailable, transcribe_whisper


def _stub_mlx_whisper(
    monkeypatch: pytest.MonkeyPatch, result: dict[str, Any], seen: dict[str, Any] | None = None
) -> None:
    """Put a fake `mlx_whisper` in sys.modules for the duration of one test.

    transcribe_whisper imports it inside the function body, so the import runs
    on every call and reads sys.modules fresh -- there is no
    dsj.whisper.mlx_whisper attribute to patch.
    """
    module = ModuleType("mlx_whisper")

    def fake_transcribe(audio: str, **kwargs: Any) -> dict[str, Any]:
        if seen is not None:
            seen.update({"audio": audio, **kwargs})
        return result

    module.transcribe = fake_transcribe  # pyright: ignore[reportAttributeAccessIssue]
    monkeypatch.setitem(sys.modules, "mlx_whisper", module)


def _stub_anchored(
    monkeypatch: pytest.MonkeyPatch, samples: int, results: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Stub mlx_whisper for the anchored path: a fixed-length clip, one result per window.

    `_anchored` loads audio through `mlx_whisper.audio.load_audio`, a separate
    submodule `_stub_mlx_whisper` does not reach, and calls `mlx_whisper.transcribe`
    once per window rather than once per file. `results[i]` is returned for the
    `i`th call; asking for more windows than `results` holds is a test bug, not
    something to paper over, so it is left to raise IndexError rather than looping.

    Returns the list calls are recorded into: one dict per call, `n_samples` (the
    window's length -- by the time whisper sees it the audio is an opaque array,
    not a path, so this is how a test checks what it was handed) plus every
    keyword whisper was called with.
    """
    calls: list[dict[str, Any]] = []

    def fake_transcribe(audio: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append({"n_samples": len(audio), **kwargs})
        return results[len(calls) - 1]

    transcribe_module = ModuleType("mlx_whisper")
    transcribe_module.transcribe = fake_transcribe  # pyright: ignore[reportAttributeAccessIssue]
    monkeypatch.setitem(sys.modules, "mlx_whisper", transcribe_module)

    def fake_load_audio(file: str, sr: int = 16000, from_stdin: bool = False) -> np.ndarray:
        return np.zeros(samples, dtype=np.float32)

    audio_module = ModuleType("mlx_whisper.audio")
    audio_module.load_audio = fake_load_audio  # pyright: ignore[reportAttributeAccessIssue]
    monkeypatch.setitem(sys.modules, "mlx_whisper.audio", audio_module)

    return calls


def _seg(start: float, end: float, text: str) -> dict[str, Any]:
    """One whisper segment, word timestamps included, for anchored-path tests."""
    return {
        "start": start,
        "end": end,
        "text": text,
        "words": [{"word": text, "start": start, "end": end}],
    }


def _result(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "text": "  Mujhe maloom nahin. Aap kaise hain?  ",
        "segments": [
            {
                "start": 0.0,
                "end": 1.5,
                "text": " Mujhe maloom nahin.",
                "words": [
                    {"word": " Mujhe", "start": 0.0, "end": 0.5},
                    {"word": " maloom", "start": 0.5, "end": 1.0},
                    {"word": " nahin.", "start": 1.0, "end": 1.5},
                ],
            },
            {
                "start": 1.5,
                "end": 2.5,
                "text": " Aap kaise hain?",
                "words": [{"word": " Aap", "start": 1.5, "end": 2.5}],
            },
        ],
    }
    return base | over


def test_segments_become_the_payloads_sentences(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_mlx_whisper(monkeypatch, _result())
    got = transcribe_whisper(Path("a.wav"))

    assert got.text == "Mujhe maloom nahin. Aap kaise hain?"
    assert [s["start"] for s in got.sentences] == [0.0, 1.5]
    assert got.sentences[0]["text"] == "Mujhe maloom nahin."
    # The token list is what merge.py votes over, and `t` is the only field it
    # reads. The word text keeps its leading space, as parakeet's tokens do.
    assert got.sentences[0]["tokens"] == [
        {"t": 0.0, "w": " Mujhe"},
        {"t": 0.5, "w": " maloom"},
        {"t": 1.0, "w": " nahin."},
    ]


def test_numpy_times_are_narrowed_to_floats(monkeypatch: pytest.MonkeyPatch) -> None:
    """Word times arrive as np.float64, which json.dumps refuses.

    Not a hypothetical: a real whisper-tiny run returns
    `{'word': ' The', 'start': np.float64(0.0), ...}`. Without the float()
    at the boundary the transcript raises at the write, an hour of ASR after
    the last point where anything could be salvaged.
    """
    result = _result(
        segments=[
            {
                "start": np.float64(0.0),
                "end": np.float64(1.0),
                "text": " hello",
                "words": [{"word": " hello", "start": np.float64(0.0), "end": np.float64(1.0)}],
            }
        ]
    )
    _stub_mlx_whisper(monkeypatch, result)
    got = transcribe_whisper(Path("a.wav"))

    assert type(got.sentences[0]["tokens"][0]["t"]) is float
    json.dumps(got.sentences)  # the assertion that matters: it serialises


def test_the_call_asks_for_words_and_silences_the_bar(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two arguments dsj cannot get wrong, pinned against upstream drift.

    `word_timestamps=True` is the reason to choose whisper here at all -- the
    speaker vote is per token. `verbose=None` reads backwards: mlx-whisper
    disables its tqdm on `verbose is not False`, so False is the value that
    PRINTS an 11,580-frame bar over dsj's own progress line.
    """
    seen: dict[str, Any] = {}
    _stub_mlx_whisper(monkeypatch, _result(), seen)
    transcribe_whisper(Path("a.wav"), model_id="m", language="ur", prompt=ROMAN_URDU_PROMPT)

    assert seen["word_timestamps"] is True
    assert seen["verbose"] is None
    assert seen["path_or_hf_repo"] == "m"
    assert seen["language"] == "ur"
    assert seen["initial_prompt"] == ROMAN_URDU_PROMPT


def test_the_missing_extra_names_both_install_forms(monkeypatch: pytest.MonkeyPatch) -> None:
    """A None in sys.modules is what an absent module raises through."""
    monkeypatch.setitem(sys.modules, "mlx_whisper", None)
    with pytest.raises(WhisperUnavailable) as exc:
        transcribe_whisper(Path("a.wav"))

    # Both forms, because `uv sync` is a no-op for someone who installed the
    # tool rather than the project, and the reverse.
    assert "uv tool install" in str(exc.value)
    assert "uv sync --extra whisper" in str(exc.value)


@pytest.mark.usefixtures("already_extracted_media")
def test_the_whisper_engine_writes_the_schema_and_leaves_no_checkpoint(
    monkeypatch: pytest.MonkeyPatch, fake_media: Path, tmp_path: Path
) -> None:
    """The transcript a whisper run leaves behind is the same document.

    Downstream -- dekho, and any agent reading the index -- must not be able to
    tell which engine wrote it apart from the model id. The checkpoint check is
    the other half: whisper has no chunk loop of dsj's to bank, so a file
    beside the output would be a stale one nothing could ever resume from.
    """
    _stub_mlx_whisper(monkeypatch, _result())
    out = tmp_path / "out.json"

    payload = transcribe(fake_media, out, engine="whisper", diarize=False)

    assert set(payload) == {"audio", "model", "text", "sentences"}
    assert payload["model"] == whisper_mod.DEFAULT_WHISPER_MODEL
    assert json.loads(out.read_text())["sentences"][0]["tokens"][0] == {"t": 0.0, "w": " Mujhe"}
    assert list(tmp_path.glob("*.checkpoint*")) == []


def test_an_unknown_engine_is_refused_by_name(fake_media: Path, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown engine 'wshiper'"):
        transcribe(fake_media, tmp_path / "o.json", engine="wshiper")


def test_parakeet_refuses_the_flags_that_are_not_its(fake_media: Path, tmp_path: Path) -> None:
    """Silently ignoring --prompt would be the worst of the three options.

    A prompt is the whole mechanism behind Roman Urdu output. Accepting one and
    dropping it means a run that looks configured and is not.
    """
    with pytest.raises(ValueError, match="whisper's; parakeet takes neither"):
        transcribe(fake_media, tmp_path / "o.json", language="ur")


def test_roman_urdu_sets_the_engine_the_language_and_the_prompt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """One flag, because the three that make it work are not guessable."""
    import dsj.suno as suno_mod

    seen: dict[str, object] = {}

    def fake(media: Path, out: Path, model: str = "", **kw: object) -> dict[str, object]:
        seen.update({"model": model, **kw})
        return {"sentences": []}

    monkeypatch.setattr(suno_mod, "transcribe", fake)
    out = tmp_path / "o.json"
    assert suno_mod.main(["v.mov", "-o", str(out), "--roman-urdu"]) == 0

    assert seen["engine"] == "whisper"
    assert seen["language"] == "ur"
    assert seen["prompt"] == ROMAN_URDU_PROMPT
    # The model default follows the engine, so --roman-urdu alone must not send
    # parakeet's repo id to whisper.
    assert seen["model"] == whisper_mod.DEFAULT_WHISPER_MODEL


@pytest.mark.slow
@pytest.mark.skipif(
    importlib.util.find_spec("mlx_whisper") is None or shutil.which("say") is None,
    reason="needs the whisper extra and macOS `say`",
)
def test_a_real_whisper_run_returns_words_with_times(tmp_path: Path) -> None:
    """The stubs above assert the wiring; this asserts the wiring was right.

    whisper-tiny rather than the default turbo, and three seconds of `say`
    rather than a committed clip: the point is that a real model returns the
    shape dsj maps, not that a small model is accurate.
    """
    wav = tmp_path / "said.wav"
    subprocess.run(
        ["say", "-o", str(wav), "--data-format=LEI16@16000", "The quick brown fox."],
        check=True,
    )

    got = transcribe_whisper(wav, model_id="mlx-community/whisper-tiny", language="en")

    # Two words, not the sentence: tiny heard "the quick brown socks." on the
    # first run of this test. Its accuracy is not what is on trial -- that
    # something real came back, in the shape dsj maps, is.
    assert "quick brown" in got.text.lower()
    tokens = [t for s in got.sentences for t in s["tokens"]]
    assert len(tokens) >= 4
    assert all(isinstance(t["t"], float) for t in tokens)
    # Monotonic, because a token list out of order silently mislabels speakers:
    # merge.py bisects it.
    assert [t["t"] for t in tokens] == sorted(t["t"] for t in tokens)


@pytest.mark.usefixtures("already_extracted_media")
def test_segments_are_written_earliest_first(
    monkeypatch: pytest.MonkeyPatch, fake_media: Path, tmp_path: Path
) -> None:
    """The whisper path can hand back backwards segments too, for its own reason.

    No `anchor_s` is passed here, so this is the plain unchunked path, not
    `_anchored` -- and that is the point: whisper's own segments can arrive out
    of `start` order from a single decode with no chunking involved at all, so
    `_in_time_order` has to hold for whisper even before `_anchored` exists.
    Ordering lives in dsj/suno.py:_in_time_order, which both engines pass
    through, so this is the whisper half of the same promise tests/test_suno.py
    makes for parakeet. `_anchored`'s own overlap/midpoint dedup is a different
    mechanism and is pinned separately, by the `test_anchored_*` tests below.

    `text` is asserted too, because it is rebuilt from the reordered sentences.
    Each one's text is its words joined, leading space kept, so the glue is the
    empty string, as it is for parakeet.
    """
    _stub_mlx_whisper(
        monkeypatch,
        _result(
            text="Aap kaise hain? Mujhe maloom nahin.",
            segments=[
                {
                    "start": 2.5,
                    "end": 3.5,
                    "text": " Aap kaise hain?",
                    "words": [
                        {"word": " Aap", "start": 2.5, "end": 2.8},
                        {"word": " kaise", "start": 2.8, "end": 3.2},
                        {"word": " hain?", "start": 3.2, "end": 3.5},
                    ],
                },
                {
                    "start": 1.5,
                    "end": 2.0,
                    "text": " Mujhe maloom nahin.",
                    "words": [
                        {"word": " Mujhe", "start": 1.5, "end": 1.7},
                        {"word": " maloom", "start": 1.7, "end": 1.9},
                        {"word": " nahin.", "start": 1.9, "end": 2.0},
                    ],
                },
            ],
        ),
    )
    out = tmp_path / "out.json"

    payload = transcribe(fake_media, out, engine="whisper", diarize=False)

    on_disk = json.loads(out.read_text())
    assert on_disk == payload
    assert [s["start"] for s in on_disk["sentences"]] == [1.5, 2.5]
    assert on_disk["text"] == "".join(s["text"] for s in on_disk["sentences"]).strip()
    assert on_disk["text"] == "Mujhe maloom nahin. Aap kaise hain?"


@pytest.mark.usefixtures("already_extracted_media")
def test_a_whisper_sentences_text_is_its_words_joined(
    monkeypatch: pytest.MonkeyPatch, fake_media: Path, tmp_path: Path
) -> None:
    """The leading space included, which whisper's own segment text had stripped.

    Each word keeps its leading space, as parakeet's tokens do, so a stripped
    `text` was one character short of the words joined in every sentence. A
    reader mapping a click on the prose back to a word would be off by one.
    """
    _stub_mlx_whisper(monkeypatch, _result())

    payload = transcribe(fake_media, tmp_path / "out.json", engine="whisper", diarize=False)

    first = payload["sentences"][0]
    assert first["text"] == " Mujhe maloom nahin."
    for sentence in payload["sentences"]:
        assert sentence["text"] == "".join(t["w"] for t in sentence["tokens"])
    assert payload["text"] == "".join(s["text"] for s in payload["sentences"]).strip()


def test_anchored_windows_step_by_anchor_minus_overlap(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 16s clip at anchor_s=10 (overlap fixed at ANCHOR_OVERLAP_S=6) makes three calls.

    step = anchor_s - overlap_s = 4s, so windows are [0,10), [4,14), [8,16) --
    the third clipped to the real length by `end = min(start + window, total)`,
    which is also where the loop has to stop rather than asking for a fourth,
    empty window past the end of the file.
    """
    calls = _stub_anchored(
        monkeypatch,
        samples=16 * whisper_mod.SAMPLE_RATE,
        results=[_result(segments=[]) for _ in range(3)],
    )

    transcribe_whisper(Path("a.wav"), prompt="seed", anchor_s=10.0)

    assert [c["n_samples"] for c in calls] == [
        10 * whisper_mod.SAMPLE_RATE,
        10 * whisper_mod.SAMPLE_RATE,
        8 * whisper_mod.SAMPLE_RATE,
    ]
    # The whole point of the feature: every window gets the seed, not just the
    # first one whisper's own condition-on-previous-text would carry it into.
    assert all(c["initial_prompt"] == "seed" for c in calls)


def test_anchored_reports_progress_at_each_windows_real_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`on_progress` fires once per window, with the window's end in seconds.

    Same 16s/10s/6s geometry as the step test above: windows end at 10s, 14s
    and 16s (the last clipped to the real length, not the nominal 18s a fourth
    window would reach).
    """
    _stub_anchored(
        monkeypatch,
        samples=16 * whisper_mod.SAMPLE_RATE,
        results=[_result(segments=[]) for _ in range(3)],
    )
    seen: list[float] = []

    def on_progress(done_s: float) -> None:
        seen.append(done_s)

    transcribe_whisper(Path("a.wav"), prompt="seed", anchor_s=10.0, on_progress=on_progress)

    assert seen == [10.0, 14.0, 16.0]


def test_anchored_drops_the_overlap_duplicate_and_keeps_new_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A segment re-decoded inside the overlap is kept once; new content past it survives.

    Same 16s/10s/6s geometry: windows at offset 0, 4, 8. Window 0's segment near
    its right edge (8.5-9.3) sits inside window 1's overlap and reappears there
    at the same absolute time -- that copy must be dropped, not duplicated.
    Window 1's own new segment (10.5-12.0) is past window 0's watermark and must
    survive; window 2 re-decodes part of it (11.0-12.0) and must not duplicate
    it either. 4 of the 6 segments across the three windows should survive.
    """
    calls = _stub_anchored(
        monkeypatch,
        samples=16 * whisper_mod.SAMPLE_RATE,
        results=[
            _result(segments=[_seg(1.0, 2.0, " one"), _seg(8.5, 9.3, " edge")]),
            # Offset +4s: local 4.5-5.3 is global 8.5-9.3, the duplicate above.
            _result(segments=[_seg(4.5, 5.3, " edge"), _seg(6.5, 8.0, " new")]),
            # Offset +8s: local 3.0-4.0 is global 11.0-12.0, inside the segment
            # window 1 already kept (10.5-12.0).
            _result(segments=[_seg(3.0, 4.0, " newagain"), _seg(6.0, 7.5, " tail")]),
        ],
    )

    got = transcribe_whisper(Path("a.wav"), prompt="seed", anchor_s=10.0)

    assert len(calls) == 3
    assert [(s["start"], s["end"], s["text"]) for s in got.sentences] == [
        (1.0, 2.0, "one"),
        (8.5, 9.3, "edge"),
        (10.5, 12.0, "new"),
        (14.0, 15.5, "tail"),
    ]


def test_anchored_handles_audio_shorter_than_one_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """Audio under `anchor_s` is one window, not zero windows and not a crash.

    `end = min(start + window, total)` caps the first window at the real
    length, and `end >= total` breaks right after -- so a 5s clip with a 10s
    anchor_s makes exactly one call, not an attempt at a second, empty one.
    """
    calls = _stub_anchored(
        monkeypatch, samples=5 * whisper_mod.SAMPLE_RATE, results=[_result(segments=[])]
    )

    transcribe_whisper(Path("a.wav"), prompt="seed", anchor_s=10.0)

    assert len(calls) == 1
    assert calls[0]["n_samples"] == 5 * whisper_mod.SAMPLE_RATE


def test_anchor_s_must_exceed_overlap_s(monkeypatch: pytest.MonkeyPatch) -> None:
    """A future re-tuning of ANCHOR_CHUNK_S below ANCHOR_OVERLAP_S must fail loudly.

    Left unguarded, `step = anchor_s - overlap_s` goes to zero or negative:
    `range(0, total, 0)` raises a confusing `range() arg 3 must not be zero`,
    and a negative step iterates zero times, silently returning no transcript
    for the whole file. Neither is what should happen when the ratio the
    116s measurement (#100, unverified) justifies gets retuned.
    """
    _stub_mlx_whisper(monkeypatch, _result())

    with pytest.raises(ValueError, match=r"anchor_s .* must be greater than overlap_s"):
        transcribe_whisper(Path("a.wav"), prompt="seed", anchor_s=whisper_mod.ANCHOR_OVERLAP_S)


def test_overlap_s_must_be_at_least_one_second(monkeypatch: pytest.MonkeyPatch) -> None:
    """A too-short overlap can drop real audio at the very end of a file, silently.

    The short-fragment break at the tail of `_anchored`'s loop assumes a
    dropped under-a-second tail was already covered by the previous window's
    overlap. Shrink the overlap below that and the assumption breaks.
    """
    monkeypatch.setattr(whisper_mod, "ANCHOR_OVERLAP_S", 0.5)
    _stub_mlx_whisper(monkeypatch, _result())

    with pytest.raises(ValueError, match=r"overlap_s .* must be at least 1.0s"):
        transcribe_whisper(Path("a.wav"), prompt="seed", anchor_s=10.0)
