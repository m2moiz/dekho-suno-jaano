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
import wave
from itertools import pairwise
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
import pytest

from dsj import whisper as whisper_mod
from dsj.suno import Progress, transcribe
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
        "words": [{"word": text, "start": start, "end": end, "probability": 0.9}],
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
                    {"word": " Mujhe", "start": 0.0, "end": 0.5, "probability": 0.25},
                    {"word": " maloom", "start": 0.5, "end": 1.0, "probability": 0.9},
                    {"word": " nahin.", "start": 1.0, "end": 1.5, "probability": 0.75},
                ],
            },
            {
                "start": 1.5,
                "end": 2.5,
                "text": " Aap kaise hain?",
                "words": [{"word": " Aap", "start": 1.5, "end": 2.5, "probability": 0.5}],
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
        {"t": 0.0, "w": " Mujhe", "e": 0.5, "c": 0.25, "charOffset": 0},
        {"t": 0.5, "w": " maloom", "e": 1.0, "c": 0.9, "charOffset": 6},
        {"t": 1.0, "w": " nahin.", "e": 1.5, "c": 0.75, "charOffset": 13},
    ]


def test_words_carry_whispers_end_and_probability_shifted_with_the_window() -> None:
    """`e` is the word's own end and `c` its probability, the keys parakeet writes (#77).

    Anchored windows hand `_sentences_from` a non-zero offset, so the end has to
    move with the start: an `e` left window-relative would sit 114 seconds
    before its own `t`. Both are rounded to 3 places, as parakeet's are, which
    also drops the float noise the addition leaves (114.0 + 0.57 is
    114.57000000000001) and the tail of a float32 mean.
    """
    segment = {
        "start": 0.12,
        "end": 0.57,
        "text": " hi",
        "words": [{"word": " hi", "start": 0.12, "end": 0.57, "probability": 0.87654321}],
    }

    [sentence] = whisper_mod._sentences_from([segment], 114.0)  # pyright: ignore[reportPrivateUsage]

    [token] = sentence["tokens"]
    assert token["e"] == 114.57
    assert token["c"] == 0.877
    assert token["e"] > token["t"]


@pytest.mark.usefixtures("already_extracted_media")
def test_no_written_whisper_word_ends_before_it_starts(
    monkeypatch: pytest.MonkeyPatch, fake_media: Path, tmp_path: Path
) -> None:
    """The whisper half of #174: `t` rounded like `e`, so `e >= t` on every word.

    whisper gives zero-length words often, 159 of 686 on a 3-minute clip. One
    whose start carries float noise wrote an `e` below its own `t` once `e` was
    rounded and `t` was not.
    """
    noisy = 0.1 + 0.2
    _stub_mlx_whisper(
        monkeypatch,
        _result(
            segments=[
                {
                    "start": 0.0,
                    "end": 1.0,
                    "text": " a b c",
                    "words": [
                        {"word": " a", "start": 0.0, "end": noisy, "probability": 0.9},
                        {"word": " b", "start": noisy, "end": noisy, "probability": 0.9},
                        {"word": " c", "start": 0.5, "end": 1.0, "probability": 0.9},
                    ],
                }
            ]
        ),
    )
    out = tmp_path / "out.json"

    transcribe(fake_media, out, engine="whisper", diarize=False)

    [sentence] = json.loads(out.read_text())["sentences"]
    tokens = sentence["tokens"]
    assert [(t["t"], t["e"]) for t in tokens] == [(0.0, 0.3), (0.3, 0.3), (0.5, 1.0)]
    assert all(t["e"] >= t["t"] for t in tokens)
    assert [t["w"] for t in tokens] == [" a", " b", " c"]


def test_a_whisper_word_ending_before_it_starts_is_written_at_its_start() -> None:
    """`e >= t` by construction, whatever the alignment hands back (#174)."""
    segment = {
        "start": 1.0,
        "end": 1.5,
        "text": " x",
        "words": [{"word": " x", "start": 1.0, "end": 0.75, "probability": 1.0}],
    }
    [sentence] = whisper_mod._sentences_from([segment], 0.0)  # pyright: ignore[reportPrivateUsage]
    [token] = sentence["tokens"]
    assert (token["t"], token["e"]) == (1.0, 1.0)


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
                "words": [
                    {
                        "word": " hello",
                        "start": np.float64(0.0),
                        "end": np.float64(1.0),
                        "probability": np.float64(0.5),
                    }
                ],
            }
        ]
    )
    _stub_mlx_whisper(monkeypatch, result)
    got = transcribe_whisper(Path("a.wav"))

    token = got.sentences[0]["tokens"][0]
    assert [type(token[k]) for k in ("t", "e", "c")] == [float, float, float]
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


def test_both_transcribe_calls_pass_the_anomaly_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    """The unanchored call and every anchored window get HALLUCINATION_SILENCE_S (#99).

    Read when the call is made, not when the module is imported, because that
    is how scratch/whisper_sweep.py measures a setting: it assigns the module
    attribute and then runs dsj's own CLI. So the constant is set to a value
    that is not mlx-whisper's default, and a call that dropped the keyword or
    froze it at import would fail. Two paths, because `--roman-urdu` goes
    through `_anchored` and `--engine whisper` alone does not: a value wired
    into one of the two calls would pass every test that exercises the other.
    `word_timestamps=True` is asserted beside it because the switch only runs
    with word timestamps on.
    """
    monkeypatch.setattr(whisper_mod, "HALLUCINATION_SILENCE_S", 3.5)
    seen: dict[str, Any] = {}
    _stub_mlx_whisper(monkeypatch, _result(), seen)
    transcribe_whisper(Path("a.wav"), language="en")

    assert seen["hallucination_silence_threshold"] == 3.5
    assert seen["word_timestamps"] is True

    calls = _stub_anchored(
        monkeypatch,
        samples=16 * whisper_mod.SAMPLE_RATE,
        results=[_result(segments=[]) for _ in range(3)],
    )
    transcribe_whisper(Path("a.wav"), prompt="seed", anchor_s=10.0)

    assert len(calls) == 3
    for call in calls:
        assert call["hallucination_silence_threshold"] == 3.5
        assert call["word_timestamps"] is True


def test_the_anomaly_threshold_is_off() -> None:
    """Off is the measured choice: on, it removed real speech with the loops (#99).

    None is mlx-whisper's own default and means the switch never runs. A
    change here re-opens #99 and needs its measurement repeated first.
    """
    assert whisper_mod.HALLUCINATION_SILENCE_S is None


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

    assert set(payload) == {"audio", "model", "text", "unclear", "sentences"}
    assert payload["model"] == whisper_mod.DEFAULT_WHISPER_MODEL
    assert json.loads(out.read_text())["sentences"][0]["tokens"][0] == {
        "t": 0.0,
        "w": " Mujhe",
        "e": 0.5,
        "c": 0.25,
        "charOffset": 0,
    }
    assert list(tmp_path.glob("*.checkpoint*")) == []


@pytest.mark.usefixtures("already_extracted_media")
def test_a_whisper_run_ends_at_the_length_its_running_frame_reported(
    monkeypatch: pytest.MonkeyPatch, fake_media: Path, tmp_path: Path
) -> None:
    """The whisper half of #52: the done frame's total is the recording's, not a sentence's.

    whisper's frames take their total from the probe, 4427.028 s under the stub,
    and its last sentence here ends at 2.5 s. The done frame used to say 2.5.
    """
    _stub_mlx_whisper(monkeypatch, _result())
    frames: list[tuple[str, float, float]] = []

    # def, not lambda: an annotated lambda parameter is not expressible.
    def capture(p: Progress, state: str) -> None:
        frames.append((state, p.audio_done_s, p.audio_total_s))

    transcribe(
        fake_media, tmp_path / "out.json", engine="whisper", diarize=False, on_progress=capture
    )

    assert frames[0] == ("running", 0.0, 4427.028)
    assert frames[-1] == ("done", 4427.028, 4427.028)


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

    def fake(_media: Path, _out: Path, model: str = "", **kw: object) -> dict[str, object]:
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
                        {"word": " Aap", "start": 2.5, "end": 2.8, "probability": 0.9},
                        {"word": " kaise", "start": 2.8, "end": 3.2, "probability": 0.9},
                        {"word": " hain?", "start": 3.2, "end": 3.5, "probability": 0.9},
                    ],
                },
                {
                    "start": 1.5,
                    "end": 2.0,
                    "text": " Mujhe maloom nahin.",
                    "words": [
                        {"word": " Mujhe", "start": 1.5, "end": 1.7, "probability": 0.9},
                        {"word": " maloom", "start": 1.7, "end": 1.9, "probability": 0.9},
                        {"word": " nahin.", "start": 1.9, "end": 2.0, "probability": 0.9},
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


@pytest.mark.usefixtures("already_extracted_media")
def test_whisper_token_charoffset_indexes_the_sentence_text(
    monkeypatch: pytest.MonkeyPatch, fake_media: Path, tmp_path: Path
) -> None:
    """The whisper half of #126: same key, same meaning, as parakeet's.

    whisper builds its own sentence dicts and never reaches the chunk path's
    serializer, so a field added only there would pass every parakeet test and
    be missing here. Asserted against the written `text`, whose leading space
    whisper's own segment text did not have: an offset off by that one
    character would fail on every token.
    """
    _stub_mlx_whisper(monkeypatch, _result())

    payload = transcribe(fake_media, tmp_path / "out.json", engine="whisper", diarize=False)

    sentence = payload["sentences"][0]
    assert [t["charOffset"] for t in sentence["tokens"]] == [0, 6, 13]
    for token in sentence["tokens"]:
        start = token["charOffset"]
        assert sentence["text"][start : start + len(token["w"])] == token["w"]


@pytest.mark.usefixtures("already_extracted_media")
def test_a_whisper_sentences_words_are_written_earliest_first(
    monkeypatch: pytest.MonkeyPatch, fake_media: Path, tmp_path: Path
) -> None:
    """The time order the README promises, held by a sort rather than by whisper's habit (#167).

    whisper decodes left to right, so its word times normally rise, and no
    transcript has been seen breaking that. But nothing enforced it, and since
    #106 a sentence's `text` is its words joined, so one word out of order
    would scramble the prose as well as the times. The segment below hands
    `_sentences_from` its last two words swapped; what is written must run
    earliest first, read in that order, and keep every `charOffset` pointing
    at its own word.
    """
    _stub_mlx_whisper(
        monkeypatch,
        _result(
            segments=[
                {
                    "start": 0.0,
                    "end": 1.5,
                    "text": " Mujhe maloom nahin.",
                    "words": [
                        {"word": " Mujhe", "start": 0.0, "end": 0.5, "probability": 0.9},
                        {"word": " nahin.", "start": 1.0, "end": 1.5, "probability": 0.9},
                        {"word": " maloom", "start": 0.5, "end": 1.0, "probability": 0.9},
                    ],
                }
            ]
        ),
    )

    payload = transcribe(fake_media, tmp_path / "out.json", engine="whisper", diarize=False)

    [sentence] = payload["sentences"]
    assert [(t["t"], t["w"]) for t in sentence["tokens"]] == [
        (0.0, " Mujhe"),
        (0.5, " maloom"),
        (1.0, " nahin."),
    ]
    assert sentence["text"] == " Mujhe maloom nahin."
    for token in sentence["tokens"]:
        start = token["charOffset"]
        assert sentence["text"][start : start + len(token["w"])] == token["w"]


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
    """A segment decoded by two windows is written once, by the window that owns its seconds.

    Same 16s/10s/6s geometry: windows at offset 0, 4, 8, handing over at the
    middles of their overlaps, 7 s and 11 s (#190). Window 0's segment near its
    right edge (8.5-9.3) reappears in window 1 at the same time; it lies past
    7 s, so window 1's copy is the one written. Window 1's segment at 10.5-12.0
    has its midpoint past 11 s, so window 2's decode of the same speech
    (11.0-12.0) is written instead of it. 4 of the 6 segments survive.
    """
    calls = _stub_anchored(
        monkeypatch,
        samples=16 * whisper_mod.SAMPLE_RATE,
        results=[
            _result(segments=[_seg(1.0, 2.0, " one"), _seg(8.5, 9.3, " edge")]),
            # Offset +4s: local 4.5-5.3 is global 8.5-9.3, the duplicate above.
            _result(segments=[_seg(4.5, 5.3, " edge"), _seg(6.5, 8.0, " new")]),
            # Offset +8s: local 3.0-4.0 is global 11.0-12.0, the speech window
            # 1 decoded as 10.5-12.0.
            _result(segments=[_seg(3.0, 4.0, " newagain"), _seg(6.0, 7.5, " tail")]),
        ],
    )

    got = transcribe_whisper(Path("a.wav"), prompt="seed", anchor_s=10.0)

    assert len(calls) == 3
    assert [(s["start"], s["end"], s["text"]) for s in got.sentences] == [
        (1.0, 2.0, "one"),
        (8.5, 9.3, "edge"),
        (11.0, 12.0, "newagain"),
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
    for the whole file. Neither is what should happen when ANCHOR_CHUNK_S,
    set from #100's window measurements, gets retuned.
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


@pytest.mark.usefixtures("already_extracted_media")
def test_a_whisper_sentence_is_timed_in_whole_milliseconds_and_spans_its_words(
    monkeypatch: pytest.MonkeyPatch, fake_media: Path, tmp_path: Path
) -> None:
    """The whisper half of #175: sentence times are whole milliseconds and cover the words.

    A segment's own bounds carry float noise, and nothing but this keeps the
    written sentence from starting after its first word or ending before its
    last one.
    """
    noisy = 0.1 + 0.2
    _stub_mlx_whisper(
        monkeypatch,
        _result(
            segments=[
                {
                    "start": noisy,
                    "end": 1.0 + noisy,
                    "text": " a b",
                    "words": [
                        {"word": " a", "start": 0.2, "end": 0.5, "probability": 0.9},
                        {"word": " b", "start": 0.6, "end": 1.4, "probability": 0.9},
                    ],
                }
            ]
        ),
    )
    out = tmp_path / "out.json"

    transcribe(fake_media, out, engine="whisper", diarize=False)

    [sentence] = json.loads(out.read_text())["sentences"]
    assert (sentence["start"], sentence["end"]) == (0.2, 1.4)


# --- decoding a loop span again (#183) --------------------------------------


def _words_seg(words: list[tuple[float, float, str]]) -> dict[str, Any]:
    """One whisper segment of several timed words."""
    return {
        "start": words[0][0],
        "end": words[-1][1],
        "text": "".join(w for _, _, w in words),
        "words": [{"word": w, "start": a, "end": b, "probability": 0.9} for a, b, w in words],
    }


# A loop from 10.0 to 18.5 s between two real sentences; the second starts
# inside the loop's span, as a neighbour after a loop can.
_LOOP = _words_seg([(10.0 + i, 10.5 + i, " na") for i in range(9)])
_BEFORE = _words_seg([(0.0, 0.5, " We"), (0.5, 1.0, " began.")])
_AFTER = _words_seg([(18.0, 18.2, " Then"), (18.2, 18.4, " stop.")])
_MAIN = {"text": "", "segments": [_BEFORE, _LOOP, _AFTER]}

# The neighbour after the loop starts at 18.0 s, inside the loop's span, so the
# retry reads 10.0 to 18.0 s, decoded as 8.0 to 20.0 s: its clip clock is 8 s
# behind the recording's. A word in the pad on each side (9.0 and 19.0 s) is a
# neighbour's, decoded again, and so is the word at 18.3 s, which falls inside
# the neighbour. Six distinct words are left.
_READ = {
    "segments": [
        _words_seg(
            [(1.0, 1.4, " began.")]
            + [(2.5 + i, 3.0 + i, f" w{i}") for i in range(6)]
        ),
        _words_seg([(10.3, 11.0, " last"), (11.0, 11.5, " stop.")]),
    ]
}
_LOOPED = {"segments": [_words_seg([(2.0 + i * 0.5, 2.4 + i * 0.5, " na") for i in range(9)])]}
_SHORT = {"segments": [_words_seg([(3.0, 3.5, " one"), (3.5, 4.0, " two")])]}


@pytest.mark.usefixtures("already_extracted_media")
def test_a_loop_span_is_replaced_by_the_retrys_words_on_the_recordings_clock(
    monkeypatch: pytest.MonkeyPatch, fake_media: Path, tmp_path: Path
) -> None:
    """The first retry reads, so it replaces the loop and the second is never tried."""
    calls = _stub_anchored(monkeypatch, 30 * 16000, [_MAIN, _READ])
    states: list[str] = []

    def capture(p: Progress, state: str) -> None:
        states.append(state)

    payload = transcribe(
        fake_media, tmp_path / "out.json", engine="whisper", language="ur",
        prompt=ROMAN_URDU_PROMPT, diarize=False, on_progress=capture,
    )

    assert len(calls) == 2
    retry = calls[1]
    assert retry["n_samples"] == int(20.0 * 16000) - int(8.0 * 16000)
    assert retry["initial_prompt"] is None
    assert retry["temperature"] == 0.0
    assert retry["language"] == "ur"
    assert retry["condition_on_previous_text"] is False
    assert retry["word_timestamps"] is True
    assert payload["unclear"] == []
    tokens = [(t["t"], t["e"], t["w"]) for s in payload["sentences"] for t in s["tokens"]]
    assert tokens == [
        (0.0, 0.5, " We"),
        (0.5, 1.0, " began."),
        *[(10.5 + i, 11.0 + i, f" w{i}") for i in range(6)],
        (18.0, 18.2, " Then"),
        (18.2, 18.4, " stop."),
    ]
    _assert_no_overlap(payload["sentences"])
    assert payload["text"] == "We began. w0 w1 w2 w3 w4 w5 Then stop."
    assert states.count("retrying") == 2
    assert states.index("running") < states.index("retrying") < states.index("done")


@pytest.mark.usefixtures("already_extracted_media")
@pytest.mark.parametrize("first", [_LOOPED, _SHORT], ids=["loops", "five-words-or-fewer"])
def test_the_warm_retry_runs_only_when_the_plain_one_fails(
    monkeypatch: pytest.MonkeyPatch, fake_media: Path, tmp_path: Path, first: dict[str, Any]
) -> None:
    calls = _stub_anchored(monkeypatch, 30 * 16000, [_MAIN, first, _READ])

    payload = transcribe(
        fake_media, tmp_path / "out.json", engine="whisper", language="ur",
        prompt=ROMAN_URDU_PROMPT, diarize=False,
    )

    assert len(calls) == 3
    assert calls[2]["temperature"] == 0.4
    assert calls[2]["initial_prompt"] == ROMAN_URDU_PROMPT
    assert payload["unclear"] == []
    assert " w0" in payload["text"]


@pytest.mark.usefixtures("already_extracted_media")
def test_a_span_both_retries_fail_on_stays_unclear(
    monkeypatch: pytest.MonkeyPatch, fake_media: Path, tmp_path: Path
) -> None:
    calls = _stub_anchored(monkeypatch, 30 * 16000, [_MAIN, _LOOPED, _SHORT])

    payload = transcribe(fake_media, tmp_path / "out.json", engine="whisper", diarize=False)

    assert len(calls) == 3
    assert payload["unclear"] == [
        {"start": 10.0, "end": 18.5, "reason": "repetition loop", "words": 9}
    ]
    assert payload["text"] == "We began. Then stop."


@pytest.mark.usefixtures("already_extracted_media")
def test_the_retry_can_be_switched_off(
    monkeypatch: pytest.MonkeyPatch, fake_media: Path, tmp_path: Path
) -> None:
    monkeypatch.setattr("dsj.suno.RETRY_LOOPS", False)
    calls = _stub_anchored(monkeypatch, 30 * 16000, [_MAIN])

    payload = transcribe(fake_media, tmp_path / "out.json", engine="whisper", diarize=False)

    assert len(calls) == 1
    assert [u["reason"] for u in payload["unclear"]] == ["repetition loop"]


def _assert_no_overlap(sentences: list[dict[str, Any]]) -> None:
    """Every sentence ends by the next one's start, and holds its own tokens."""
    for a, b in pairwise(sentences):
        assert a["end"] <= b["start"], (a["start"], a["end"], b["start"])
    for s in sentences:
        assert all(s["start"] <= t["t"] <= t["e"] <= s["end"] for t in s["tokens"])


# An anchored seam: the sentence before the loop runs into its span, to 12.0 s,
# and the one after starts inside it, at 16.0 s, so only 12.0 to 16.0 s is
# unread. The retry decodes 10.0 to 18.0 s and returns, on its clip clock, a
# word inside each neighbour (11.0 and 16.5 s) and eight between them.
_PREV = _words_seg([(7.0, 9.0, " Before"), (9.0, 12.0, " seam.")])
_NEXT = _words_seg([(16.0, 18.0, " After"), (18.0, 20.0, " seam.")])
_SEAM_READ = {
    "segments": [
        _words_seg(
            [(1.0, 2.0, " seam.")]
            + [(2.0 + i * 0.5, 2.5 + i * 0.5, f" v{i}") for i in range(8)]
            + [(6.5, 7.0, " After")]
        )
    ]
}


@pytest.mark.usefixtures("already_extracted_media")
def test_retried_words_never_land_inside_a_neighbour(
    monkeypatch: pytest.MonkeyPatch, fake_media: Path, tmp_path: Path
) -> None:
    """Only the stretch no other sentence covers is read again, so nothing is written twice."""
    calls = _stub_anchored(
        monkeypatch, 30 * 16000, [{"segments": [_PREV, _LOOP, _NEXT]}, _SEAM_READ]
    )

    payload = transcribe(fake_media, tmp_path / "out.json", engine="whisper", diarize=False)

    assert len(calls) == 2
    assert calls[1]["n_samples"] == int(18.0 * 16000) - int(10.0 * 16000)
    assert payload["unclear"] == []
    _assert_no_overlap(payload["sentences"])
    tokens = [(t["t"], t["w"]) for s in payload["sentences"] for t in s["tokens"]]
    assert tokens == [
        (7.0, " Before"),
        (9.0, " seam."),
        *[(12.0 + i * 0.5, f" v{i}") for i in range(8)],
        (16.0, " After"),
        (18.0, " seam."),
    ]


@pytest.mark.usefixtures("already_extracted_media")
def test_a_loop_a_neighbour_already_covers_is_not_decoded_again(
    monkeypatch: pytest.MonkeyPatch, fake_media: Path, tmp_path: Path
) -> None:
    """A window-tail loop whose seconds the next window already read has nothing left to read.

    The case of #148's fixture at 803.94 s: 221 words timed into 0.04 s at the
    end of one window, inside the next window's first sentence (798.0 to
    825.3 s). It stays a loop, as before the retry existed.
    """
    cover = _words_seg([(8.0, 14.0, " Long"), (14.0, 20.0, " sentence.")])
    calls = _stub_anchored(monkeypatch, 30 * 16000, [{"segments": [cover, _LOOP]}])

    payload = transcribe(fake_media, tmp_path / "out.json", engine="whisper", diarize=False)

    assert len(calls) == 1
    assert [u["reason"] for u in payload["unclear"]] == ["repetition loop"]


def test_a_loop_over_silence_is_never_decoded_again(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Silence is no speech, not a failed read, so there is nothing to retry (#181).

    One loop lies inside 20 s of -60 dB noise and leaves as no speech. The other
    has words on both sides of the silence and none inside it, so the silence
    rule keeps it, and its span still crosses the silence: decoding it again
    could write words over the silence, so it stays a loop.
    """
    from dsj import media as media_mod
    from dsj.suno import NO_SPEECH_REASON

    rate = 16000
    rng = np.random.default_rng(183)
    tone = np.sin(2 * np.pi * 220 * np.arange(5 * rate) / rate) * 0.1
    noise = rng.standard_normal(20 * rate) * 10 ** (-60 / 20)
    samples = np.concatenate([tone, noise, tone])
    wav = tmp_path / "in.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.round(samples * 32767).astype("<i2").tobytes())
    assert media_mod.loudness(wav, 0.1).size == 300

    over_silence = _words_seg([(10.0 + i, 10.5 + i, " na") for i in range(9)])
    across = _words_seg(
        [(1.0 + i * 0.5, 1.4 + i * 0.5, " ha") for i in range(4)]
        + [(26.0 + i * 0.5, 26.4 + i * 0.5, " ha") for i in range(4)]
    )
    calls = _stub_anchored(monkeypatch, 30 * rate, [{"segments": [across, over_silence]}])

    payload = transcribe(wav, tmp_path / "out.json", engine="whisper", diarize=False)

    assert len(calls) == 1
    assert [(u["reason"], u["words"]) for u in payload["unclear"]] == [
        ("repetition loop", 8),
        (NO_SPEECH_REASON, 9),
    ]


# --- the seconds two anchored windows share (#190) --------------------------


def test_the_seconds_two_windows_share_are_written_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both windows decode the overlap, differently, and only one copy is written.

    A 14 s clip at anchor_s=10 is two windows, [0, 10) and [4, 14), sharing 4
    to 10 s. As on #148's fixture at 114 s, each window returns its own segment
    for those seconds, starting at a different time and spelled differently,
    and the second one runs on past the first window's end. Keeping a segment
    by its midpoint keeps both (#190: 9 overlapping pairs on the fixture).

    Each second has one owner instead: the first window up to the middle of
    the overlap, 7 s, the second from there on. A word goes to the window that
    owns its midpoint, so " here", which the first window times at 7.0 to
    8.0 s, is the second window's; and the second window's " Shared" and
    " Words" lie before 7 s, so they are the first window's to write.
    """
    _stub_anchored(
        monkeypatch,
        samples=14 * whisper_mod.SAMPLE_RATE,
        results=[
            {"segments": [
                _words_seg([(1.0, 2.0, " one"), (2.0, 3.0, " two")]),
                _words_seg([(5.0, 6.0, " shared"), (6.0, 7.0, " words"), (7.0, 8.0, " here")]),
            ]},
            # Offset +4 s: local 0.6 is global 4.6.
            {"segments": [
                _words_seg([
                    (0.6, 1.8, " Shared"), (1.8, 3.1, " Words"), (3.1, 4.1, " here"),
                    (4.1, 6.0, " then"), (6.0, 9.0, " more."),
                ]),
            ]},
        ],
    )

    got = transcribe_whisper(Path("a.wav"), prompt="seed", anchor_s=10.0)

    _assert_no_overlap(got.sentences)
    assert [(t["t"], t["w"]) for s in got.sentences for t in s["tokens"]] == [
        (1.0, " one"), (2.0, " two"), (5.0, " shared"), (6.0, " words"),
        (7.1, " here"), (8.1, " then"), (10.0, " more."),
    ]


def test_a_loop_timed_into_a_windows_last_second_is_not_written(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A window-tail loop belongs to seconds the next window owns, and reads them itself.

    On #148's fixture whisper ended a window with 221 words timed into 233.7 to
    233.86 s, the last 0.3 s of the window. Kept by its midpoint, it became a
    sub-second `unclear` span that says nothing about where the failure was,
    and the next window's sentence from 228 s was written over it.
    """
    loop = _words_seg([(9.8, 9.95, " na")] * 30)
    _stub_anchored(
        monkeypatch,
        samples=14 * whisper_mod.SAMPLE_RATE,
        results=[
            {"segments": [_words_seg([(1.0, 2.0, " one"), (2.0, 3.0, " two.")]), loop]},
            {"segments": [
                _words_seg([(4.0, 5.0, " The"), (5.0, 6.0, " next"), (6.0, 9.0, " window.")]),
            ]},
        ],
    )

    got = transcribe_whisper(Path("a.wav"), prompt="seed", anchor_s=10.0)

    _assert_no_overlap(got.sentences)
    assert [(t["t"], t["w"]) for s in got.sentences for t in s["tokens"]] == [
        (1.0, " one"), (2.0, " two."), (8.0, " The"), (9.0, " next"), (10.0, " window."),
    ]


@pytest.mark.parametrize("looped", ["before", "after"])
def test_where_one_window_loops_over_the_shared_seconds_the_other_writes_them(
    monkeypatch: pytest.MonkeyPatch, looped: str
) -> None:
    """The window that read the shared seconds writes all of them, not the one that looped.

    On #148's fixture one window looped from 343.3 s to its end while the next
    read speech from 342 s; split at the middle, the loop kept 345 s onwards of
    the first and the speech before 345 s of the second was lost. Here the two
    windows share 4 to 10 s; one loops across all of it and the other reads
    words at 4.5 and 8.5 s, either side of the middle.
    """
    loop = _words_seg([(4.2 + i * 0.6, 4.5 + i * 0.6, " na") for i in range(9)])
    first: list[dict[str, Any]] = [_words_seg([(1.0, 2.0, " one")])]
    second: list[dict[str, Any]] = [_words_seg([(9.0, 9.5, " last.")])]
    # On the second window's clock, 4 s behind the recording's.
    read = _words_seg([(0.5, 1.0, " early"), (4.5, 5.0, " late")])
    if looped == "before":
        first.append(loop)
        second.insert(0, read)
    else:
        first.append(_words_seg([(4.5, 5.0, " early"), (8.5, 9.0, " late")]))
        second.insert(0, _words_seg([(t - 4.0, e - 4.0, " na") for t, e in [
            (4.2 + i * 0.6, 4.5 + i * 0.6) for i in range(9)
        ]]))
    _stub_anchored(
        monkeypatch,
        samples=14 * whisper_mod.SAMPLE_RATE,
        results=[{"segments": first}, {"segments": second}],
    )

    got = transcribe_whisper(Path("a.wav"), prompt="seed", anchor_s=10.0)

    _assert_no_overlap(got.sentences)
    assert [(t["t"], t["w"]) for s in got.sentences for t in s["tokens"]] == [
        (1.0, " one"), (4.5, " early"), (8.5, " late"), (13.0, " last."),
    ]
