"""transcribe() wiring, exercised against a fake model.

The unit tests in test_chunk_callback.py prove the sample-to-second conversion
is correct. This module proves transcribe() actually hands the model's sample
rate to it, and that the chunk loop, the checkpoint and the heartbeat are wired
to each other -- the half a unit test cannot see.

Only the decode is faked. The chunk boundaries, the offsets and the merge are
the real ones from dsj/chunking.py.
"""

from __future__ import annotations

import json
import logging
import math
import os
import shutil
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING, Any

import numpy as np
import pytest
from conftest import FakeToken

from dsj.alignment import AlignedResult, AlignedSentence, AlignedToken
from dsj.checkpoint import checkpoint_path_for
from dsj.diarize import DiarizationUnavailable
from dsj.merge import Turn
from dsj.suno import CHUNK_S, OVERLAP_S, Progress, transcribe

if TYPE_CHECKING:
    from collections.abc import Callable

    from conftest import FakeModel

    from dsj.media import AudioStream

# transcribe() probes its input for real; these tests care about the chunk loop
# and not about ffmpeg, so they need the stub that used to be autouse.
pytestmark = pytest.mark.usefixtures("already_extracted_media", "no_real_diarizer")

RATE = 16_000


def _tokens() -> list[FakeToken]:
    """One sentence ending at 750.0s -- the trailing '.' is what closes it.

    The first token's confidence is not the default 1.0, so the pinned token
    shape below can tell the decoder's number from a constant.
    """
    return [
        FakeToken(0.0, 0.4, "see", confidence=0.5),
        FakeToken(0.5, 1.0, " this"),
        FakeToken(1.1, 1.6, " column"),
        FakeToken(1.7, 750.0, " here."),
    ]


def test_transcribe_reports_progress_in_seconds(
    fake_parakeet: Callable[..., FakeModel],
    fake_media: Path,
    tmp_path: Path,
) -> None:
    """The end-to-end version of the units regression.

    A 74-minute file at 16 kHz is 70,832,448 samples; reported as seconds that
    is 2.2 years of audio, and the shipped bug did exactly that.
    """
    fake_parakeet(sample_rate=RATE, tokens=[], audio_s=4427.028)
    seen: list[Progress] = []

    # def, not lambda: an annotated lambda parameter is not expressible.
    def capture(p: Progress, state: str) -> None:
        if state == "running":
            seen.append(p)

    transcribe(fake_media, tmp_path / "out.json", on_progress=capture)

    assert seen[0].audio_done_s == pytest.approx(CHUNK_S)
    assert seen[0].audio_total_s == pytest.approx(4427.028)
    assert seen[-1].audio_done_s == pytest.approx(4427.028)


def test_transcribe_uses_the_models_sample_rate(
    fake_parakeet: Callable[..., FakeModel],
    fake_media: Path,
    tmp_path: Path,
) -> None:
    """A model at 8kHz must halve the seconds, not reuse a hardcoded 16000."""
    fake_parakeet(sample_rate=8_000, tokens=[], audio_s=60.0)
    seen: list[Progress] = []

    # def, not lambda: an annotated lambda parameter is not expressible.
    def capture(p: Progress, state: str) -> None:
        if state == "running":
            seen.append(p)

    transcribe(fake_media, tmp_path / "out.json", on_progress=capture)

    assert seen[-1].audio_done_s == pytest.approx(60.0)
    assert seen[-1].audio_total_s == pytest.approx(60.0)


def test_transcribe_always_chunks(
    fake_parakeet: Callable[..., FakeModel],
    fake_media: Path,
    tmp_path: Path,
) -> None:
    """Feeding an hour of audio to Metal in one buffer asks ~14.5GB and dies.

    Asserted on the audio actually handed to the decoder, chunk by chunk: four
    chunks for 360s under the 120s/15s geometry, the first a full chunk long and
    the last the 45s remainder.
    """
    model = fake_parakeet(sample_rate=RATE, tokens=[], audio_s=360.0)

    transcribe(fake_media, tmp_path / "out.json")

    assert [len(m) for m in model.mels] == [
        int(CHUNK_S * RATE),
        int(CHUNK_S * RATE),
        int(CHUNK_S * RATE),
        360 * RATE - int(315.0 * RATE),
    ]
    # The stride is chunk minus overlap, so consecutive chunks start 105s apart.
    assert model.mels[1].start - model.mels[0].start == int((CHUNK_S - OVERLAP_S) * RATE)


def test_transcribe_writes_the_timestamped_index(
    fake_parakeet: Callable[..., FakeModel],
    fake_media: Path,
    tmp_path: Path,
) -> None:
    fake_parakeet(tokens=_tokens())
    out = tmp_path / "out.json"

    payload = transcribe(fake_media, out)

    on_disk = json.loads(out.read_text())
    assert on_disk == payload
    assert on_disk["sentences"][0]["start"] == 0.0
    assert on_disk["sentences"][0]["end"] == 750.0
    assert on_disk["sentences"][0]["text"] == "see this column here."
    assert on_disk["sentences"][0]["tokens"][0] == {
        "t": 0.0,
        "w": "see",
        "e": 0.4,
        "c": 0.5,
        "charOffset": 0,
    }
    assert on_disk["audio"] == str(fake_media)


def test_transcribe_on_an_empty_result_still_writes_a_file(
    fake_parakeet: Callable[..., FakeModel],
    fake_media: Path,
    tmp_path: Path,
) -> None:
    """No sentences must not mean no output -- the file is the deliverable."""
    fake_parakeet(tokens=[])
    out = tmp_path / "out.json"

    payload = transcribe(fake_media, out)

    assert out.exists()
    assert payload["sentences"] == []


def test_status_file_carries_seconds_and_a_state(
    fake_parakeet: Callable[..., FakeModel],
    fake_media: Path,
    tmp_path: Path,
) -> None:
    """A detached run is inspected through this file; it is the only window in."""
    fake_parakeet(sample_rate=RATE, tokens=[], audio_s=4427.028)
    status = tmp_path / "status.json"
    seen: list[dict[str, Any]] = []

    # Reading from inside on_progress pins the production fan-out order: emit
    # writes the status file first, then calls on_progress.
    def capture(_p: Progress, state: str) -> None:
        if state == "running":
            seen.append(json.loads(status.read_text()))

    transcribe(fake_media, tmp_path / "out.json", status_path=status, on_progress=capture)

    first = seen[0]
    assert first["state"] == "running"
    assert first["audio_done_s"] == pytest.approx(CHUNK_S)
    assert first["audio_total_s"] == pytest.approx(4427.028)
    assert first["fraction"] == pytest.approx(0.0271, abs=1e-4)


def test_status_file_ends_in_the_done_state(
    fake_parakeet: Callable[..., FakeModel],
    fake_media: Path,
    tmp_path: Path,
) -> None:
    """The done frame reports the length of the audio, as the running frames did (#52).

    The fake decodes 100 seconds and its one sentence claims to end at 750.0,
    which a real run cannot produce but which shows what the number is built
    from: this frame used to repeat the last sentence's end.
    """
    fake_parakeet(sample_rate=RATE, tokens=_tokens())
    status = tmp_path / "status.json"

    transcribe(fake_media, tmp_path / "out.json", status_path=status)

    final = json.loads(status.read_text())
    assert final["state"] == "done"
    assert final["audio_done_s"] == pytest.approx(100.0)
    assert final["audio_total_s"] == pytest.approx(100.0)
    assert final["fraction"] == 1.0


def test_a_recording_with_no_speech_ends_at_its_own_length(
    fake_parakeet: Callable[..., FakeModel],
    fake_media: Path,
    tmp_path: Path,
) -> None:
    """Four minutes with no sentences finish at 240 s and 100%, not at 0 s and 0% (#52).

    Measured on a real 240 s tone on 2026-09-05: the final frame read 0.0,
    0.0, fraction 0.0 and speed 0.0, because both totals came from the end of
    the last sentence and there was none. The case the bug hinges on, so the
    with-speech test above cannot stand in for it. Also held: the done frame's
    total is the one every running frame reported, so a bar does not jump on
    the last frame.
    """
    fake_parakeet(sample_rate=RATE, tokens=[], audio_s=240.0)
    status = tmp_path / "status.json"
    totals: list[tuple[str, float]] = []

    # def, not lambda: an annotated lambda parameter is not expressible.
    def capture(p: Progress, state: str) -> None:
        totals.append((state, p.audio_total_s))

    transcribe(fake_media, tmp_path / "out.json", status_path=status, on_progress=capture)

    final = json.loads(status.read_text())
    assert final["state"] == "done"
    assert final["audio_done_s"] == pytest.approx(240.0)
    assert final["audio_total_s"] == pytest.approx(240.0)
    assert final["fraction"] == 1.0
    assert final["speed"] > 0
    assert {total for state, total in totals if state in ("running", "done")} == {240.0}


def test_a_resumed_run_ends_at_a_positive_speed(
    fake_parakeet: Callable[..., FakeModel],
    fake_media: Path,
    tmp_path: Path,
) -> None:
    """Speed is audio done minus audio resumed from, so both must be the audio's (#52).

    With the done frame's total taken from the last sentence (none here) and
    `resumed_from_s` kept at the real 210 s, the subtraction went negative:
    reproduced at -3.71 on a real 240 s tone on 2026-09-05.
    """
    fake_parakeet(sample_rate=RATE, tokens=[], audio_s=360.0)
    out = tmp_path / "out.json"
    status = tmp_path / "status.json"

    class Interrupt(Exception):
        pass

    seen = 0

    def die_after_two(_p: Progress, state: str) -> None:
        nonlocal seen
        if state != "running":
            return
        seen += 1
        if seen == 2:
            raise Interrupt

    with pytest.raises(Interrupt):
        transcribe(fake_media, out, on_progress=die_after_two)

    transcribe(fake_media, out, status_path=status)

    final = json.loads(status.read_text())
    assert final["state"] == "done"
    assert final["resumed_from_s"] == pytest.approx(210.0)
    assert final["audio_total_s"] == pytest.approx(360.0)
    assert final["speed"] > 0


def test_a_run_resumed_from_a_finished_checkpoint_ends_at_zero_speed(
    fake_parakeet: Callable[..., FakeModel],
    fake_media: Path,
    tmp_path: Path,
    fake_turns: Callable[..., list[Path]],
) -> None:
    """Resumed past its last chunk, a run transcribed nothing, and says 0.0x, never less.

    Since #101 an interrupt during labelling leaves a checkpoint banked through
    the end of the audio, so `resumed_from_s` is the whole decoded length. The
    done frame's total is that same decoded length, not ffprobe's (4427.028 s
    under this module's stub), so the subtraction in `speed` is exactly zero.
    """
    fake_parakeet(tokens=_tokens())
    out = tmp_path / "out.json"
    status = tmp_path / "status.json"

    def interrupt(wav: Path) -> None:
        raise KeyboardInterrupt

    fake_turns(**_one_speaker(then=interrupt))
    with pytest.raises(KeyboardInterrupt):
        transcribe(fake_media, out)

    fake_turns(**_one_speaker())
    transcribe(fake_media, out, status_path=status)

    final = json.loads(status.read_text())
    assert final["state"] == "done"
    assert final["resumed_from_s"] == pytest.approx(100.0)
    assert final["audio_total_s"] == pytest.approx(100.0)
    assert final["fraction"] == 1.0
    assert final["speed"] == 0.0


def test_no_status_path_writes_nothing(
    fake_parakeet: Callable[..., FakeModel],
    fake_media: Path,
    tmp_path: Path,
) -> None:
    fake_parakeet(tokens=_tokens())

    transcribe(fake_media, tmp_path / "out.json")

    assert set(tmp_path.iterdir()) == {fake_media, tmp_path / "out.json"}


def test_a_completed_run_leaves_no_checkpoint(
    fake_parakeet: Callable[..., FakeModel],
    fake_media: Path,
    tmp_path: Path,
) -> None:
    """A completed run leaves no checkpoint behind.

    The checkpoint exists to be outlived. One left behind would be replayed by
    the next run over audio it no longer describes.
    """
    fake_parakeet(sample_rate=RATE, tokens=[], audio_s=360.0)
    out = tmp_path / "out.json"

    transcribe(fake_media, out)

    assert not checkpoint_path_for(out).exists()


def test_the_checkpoint_is_banked_once_per_chunk_before_progress_is_reported(
    fake_parakeet: Callable[..., FakeModel],
    fake_media: Path,
    tmp_path: Path,
) -> None:
    """An observer must never be able to outrun what a restart could recover.

    Reading the checkpoint from inside on_progress pins the order: if the
    report came first, a watcher at 40% could restart and find nothing banked.
    """
    fake_parakeet(sample_rate=RATE, tokens=[], audio_s=360.0)
    out = tmp_path / "out.json"
    ckpt = checkpoint_path_for(out)
    banked: list[int] = []

    def capture(_p: Progress, state: str) -> None:
        if state == "running":
            banked.append(json.loads(ckpt.read_text())["next_start"])

    transcribe(fake_media, out, on_progress=capture)

    # Four chunks starting at 0, 105s, 210s, 315s; each banks the FOLLOWING
    # boundary, and the last banks the end of the audio rather than a boundary
    # past it.
    assert banked == [
        int(105.0 * RATE),
        int(210.0 * RATE),
        int(315.0 * RATE),
        360 * RATE,
    ]


def test_an_interrupted_run_leaves_a_checkpoint_and_no_transcript(
    fake_parakeet: Callable[..., FakeModel],
    fake_media: Path,
    tmp_path: Path,
) -> None:
    fake_parakeet(sample_rate=RATE, tokens=[], audio_s=360.0)
    out = tmp_path / "out.json"

    class Interrupt(Exception):
        pass

    seen = 0

    def die_after_two(_p: Progress, state: str) -> None:
        nonlocal seen
        if state != "running":
            return
        seen += 1
        if seen == 2:
            raise Interrupt

    with pytest.raises(Interrupt):
        transcribe(fake_media, out, on_progress=die_after_two)

    assert not out.exists(), "a partial transcript was written as if complete"
    banked = json.loads(checkpoint_path_for(out).read_text())
    assert banked["next_start"] == int(210.0 * RATE)


def _interrupt_after_two_chunks(media: Path, out: Path) -> None:
    """Run on 360 s of fake audio and stop it with the checkpoint at 210 s."""

    class Interrupt(Exception):
        pass

    seen = 0

    def die_after_two(_p: Progress, state: str) -> None:
        nonlocal seen
        if state != "running":
            return
        seen += 1
        if seen == 2:
            raise Interrupt

    with pytest.raises(Interrupt):
        transcribe(media, out, on_progress=die_after_two)
    assert json.loads(checkpoint_path_for(out).read_text())["next_start"] == int(210.0 * RATE)


def _where_the_rerun_started(media: Path, out: Path) -> float:
    """Finish the run on `media`, and return the audio second it resumed from."""
    done: list[Progress] = []

    # def, not lambda: an annotated lambda parameter is not expressible.
    def capture(p: Progress, state: str) -> None:
        if state == "done":
            done.append(p)

    transcribe(media, out, on_progress=capture)
    return done[0].resumed_from_s


def _renamed(media: Path) -> Path:
    return media.rename(media.with_name("renamed.wav"))


def _moved(media: Path) -> Path:
    folder = media.parent / "elsewhere"
    folder.mkdir()
    return media.rename(folder / media.name)


def _copied(media: Path) -> Path:
    """A plain `cp`, which gives the copy a new mtime; utime makes that certain."""
    copy = media.with_name("copy.wav")
    shutil.copyfile(media, copy)
    os.utime(copy, ns=(1, 1))
    return copy


@pytest.mark.parametrize(
    "relocate", [_renamed, _moved, _copied], ids=["renamed", "moved", "copied"]
)
def test_a_recording_resumes_under_another_name_folder_or_mtime(
    fake_parakeet: Callable[..., FakeModel],
    fake_media: Path,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    relocate: Callable[[Path], Path],
) -> None:
    """Renaming, moving or copying a recording between two runs keeps its resume (#118).

    The fingerprint used to hold the path and the mtime, so each of these threw
    away an interrupted run and started it again from zero, with no message.
    """
    fake_parakeet(sample_rate=RATE, tokens=[], audio_s=360.0)
    out = tmp_path / "out.json"
    _interrupt_after_two_chunks(fake_media, out)

    caplog.set_level(logging.INFO, logger="dsj.suno")
    assert _where_the_rerun_started(relocate(fake_media), out) == 210.0
    assert "resuming from 3:30" in caplog.text
    assert "checkpoint ignored" not in caplog.text


def test_an_edited_recording_does_not_resume_and_says_why(
    fake_parakeet: Callable[..., FakeModel],
    fake_media: Path,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """New contents are a different recording, and the rerun names what failed (#118)."""
    fake_parakeet(sample_rate=RATE, tokens=[], audio_s=360.0)
    out = tmp_path / "out.json"
    _interrupt_after_two_chunks(fake_media, out)

    fake_media.write_bytes(b"RIFX")
    caplog.set_level(logging.INFO, logger="dsj.suno")
    assert _where_the_rerun_started(fake_media, out) == 0.0
    assert "resuming from" not in caplog.text
    assert (
        "checkpoint ignored, transcribing from the start: "
        "the recording's contents changed (content_id)"
    ) in caplog.text


def test_no_resume_removes_a_checkpoint_it_will_not_use(
    fake_parakeet: Callable[..., FakeModel],
    fake_media: Path,
    tmp_path: Path,
) -> None:
    fake_parakeet(sample_rate=RATE, tokens=_tokens())
    out = tmp_path / "out.json"
    ckpt = checkpoint_path_for(out)
    ckpt.write_text("{}")

    transcribe(fake_media, out, resume=False)

    assert not ckpt.exists()


def _spy_on_atomic_write(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Record every path routed through the atomic writer, and really write it.

    Patched in TWO places on purpose. transcribe.py binds the name at module
    import, so the patch has to land on `dsj.suno`; cli.py imports it
    inside the function body, so that call re-reads `dsj.atomic` and needs
    the source patched too. Patching one and not the other is how the failure
    path stopped being observed when the CLI moved.
    """
    import dsj.atomic as atomic_mod
    import dsj.suno as transcribe_mod

    seen: list[Path] = []
    real = transcribe_mod.atomic_write_text

    def spy(path: Path, text: str, **kwargs: Any) -> None:
        seen.append(path)
        real(path, text, **kwargs)

    monkeypatch.setattr(transcribe_mod, "atomic_write_text", spy)
    monkeypatch.setattr(atomic_mod, "atomic_write_text", spy)
    return seen


def test_the_heartbeat_is_written_through_the_atomic_writer(
    fake_parakeet: Callable[..., FakeModel],
    fake_media: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guards the call site, not the writer.

    tests/test_atomic.py proves atomic_write_text is atomic; it says nothing
    about whether transcribe() still calls it. A merge that resolves this line
    back to status_path.write_text reintroduces the torn read with the whole
    suite green, so the wiring needs its own assertion.
    """
    fake_parakeet(sample_rate=RATE, tokens=[], audio_s=360.0)
    status = tmp_path / "status.json"
    seen = _spy_on_atomic_write(monkeypatch)

    transcribe(fake_media, tmp_path / "out.json", status_path=status)

    assert seen.count(status) >= 2, "every heartbeat must go through the atomic writer"
    assert json.loads(status.read_text())["state"] == "done"


def test_the_transcript_is_written_through_the_atomic_writer(
    fake_parakeet: Callable[..., FakeModel],
    fake_media: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The transcript is written whole or not at all.

    `out` is what every downstream tool reads, and a truncated transcript does
    not announce itself -- it merely looks short.
    """
    fake_parakeet(sample_rate=RATE, tokens=_tokens())
    out = tmp_path / "out.json"
    seen = _spy_on_atomic_write(monkeypatch)

    transcribe(fake_media, out)

    assert out in seen


def test_the_failure_status_is_written_through_the_atomic_writer(
    fake_parakeet: Callable[..., FakeModel],
    fake_media: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """main()'s except-handler writes the one document a watcher polls hardest.

    A watcher distinguishing "died" from "not started yet" reads this file in a
    tight loop, so it is the reader most likely to land inside a torn write.
    """
    import dsj.suno as transcribe_mod

    status = tmp_path / "status.json"
    seen = _spy_on_atomic_write(monkeypatch)

    def boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("model exploded")

    monkeypatch.setattr(transcribe_mod, "transcribe", boom)

    with pytest.raises(RuntimeError):
        transcribe_mod.main(
            [str(fake_media), "-o", str(tmp_path / "out.json"), "--status", str(status)]
        )

    assert seen == [status]
    failed = json.loads(status.read_text())
    assert failed["state"] == "failed"
    assert "model exploded" in failed["error"]


# --- speaker labels ------------------------------------------------------


def _one_speaker(**kw: Any) -> dict[str, Any]:
    """The fake diarization every labelled test below uses unless it says more.

    One turn spanning the whole of _tokens()'s single 750s sentence, so the
    token vote has an unambiguous answer and the tests can be about the wiring.
    """
    return dict(turns=[Turn(0.0, 800.0, 0)], labels=["SPEAKER_01"], **kw)


def test_sentences_carry_a_speaker_index_into_the_speakers_list(
    fake_parakeet: Callable[..., FakeModel],
    fake_media: Path,
    tmp_path: Path,
    fake_turns: Callable[..., list[Path]],
) -> None:
    fake_parakeet(tokens=_tokens())
    fake_turns(**_one_speaker())
    out = tmp_path / "out.json"

    payload = transcribe(fake_media, out)

    on_disk = json.loads(out.read_text())
    assert on_disk == payload
    assert on_disk["speakers"] == ["SPEAKER_01"]
    assert on_disk["diarization"] == "senko 0.0.0-fake"
    for sentence in on_disk["sentences"]:
        assert 0 <= sentence["speaker"] < len(on_disk["speakers"])


def test_the_labelled_schema_only_adds_keys(
    fake_parakeet: Callable[..., FakeModel],
    fake_media: Path,
    tmp_path: Path,
    fake_turns: Callable[..., list[Path]],
) -> None:
    """Additive or nothing. Every downstream reader of the old shape still works.

    Pinned against the unlabelled run in the same test rather than against a
    literal key list, so this cannot drift out of agreement with the payload.
    """
    fake_parakeet(tokens=_tokens())
    fake_turns(**_one_speaker())

    plain = transcribe(fake_media, tmp_path / "plain.json", diarize=False)
    labelled = transcribe(fake_media, tmp_path / "labelled.json")

    assert set(labelled) - set(plain) == {"speakers", "diarization"}
    assert set(plain) - set(labelled) == set()
    for before, after in zip(plain["sentences"], labelled["sentences"], strict=True):
        assert set(after) - set(before) == {"speaker"}
        assert {k: after[k] for k in before} == before


def test_no_diarize_output_is_the_old_schema_exactly(
    fake_parakeet: Callable[..., FakeModel],
    fake_media: Path,
    tmp_path: Path,
    fake_turns: Callable[..., list[Path]],
) -> None:
    """The byte-identity guard. --no-diarize must produce today's file.

    `fake_turns` is installed and asserted never called: "the keys are absent"
    would also hold for a pass that ran and failed, and those are different
    bugs.
    """
    fake_parakeet(tokens=_tokens())
    calls = fake_turns(**_one_speaker())
    out = tmp_path / "out.json"

    payload = transcribe(fake_media, out, diarize=False)

    assert calls == []
    assert set(payload) == {"audio", "model", "text", "sentences"}
    assert set(payload["sentences"][0]) == {"start", "end", "text", "tokens"}


def test_diarization_failure_leaves_a_complete_unlabelled_transcript(
    fake_parakeet: Callable[..., FakeModel],
    fake_media: Path,
    tmp_path: Path,
    fake_turns: Callable[..., list[Path]],
) -> None:
    """An optional pass may not cost the hour of ASR that ran before it."""
    fake_parakeet(tokens=_tokens())
    fake_turns(raises=DiarizationUnavailable("senko is not installed"))
    out = tmp_path / "out.json"

    payload = transcribe(fake_media, out)

    on_disk = json.loads(out.read_text())
    assert on_disk == payload
    assert on_disk["sentences"][0]["text"] == "see this column here."
    assert "speaker" not in on_disk["sentences"][0]
    assert "speakers" not in on_disk
    # The absence of this key is how a reader tells "not run" from "ran and
    # found one speaker". A run that failed must not claim provenance.
    assert "diarization" not in on_disk


def test_require_diarize_makes_the_failure_fatal(
    fake_parakeet: Callable[..., FakeModel],
    fake_media: Path,
    tmp_path: Path,
    fake_turns: Callable[..., list[Path]],
) -> None:
    fake_parakeet(tokens=_tokens())
    fake_turns(raises=DiarizationUnavailable("senko is not installed"))
    out = tmp_path / "out.json"

    with pytest.raises(DiarizationUnavailable):
        transcribe(fake_media, out, require_diarize=True)

    # Still written: the caller asked for labels or nothing, but the ASR work
    # is banked on disk either way and re-running it would cost the hour.
    assert "speakers" not in json.loads(out.read_text())


def test_a_bug_in_diarization_is_not_swallowed(
    fake_parakeet: Callable[..., FakeModel],
    fake_media: Path,
    tmp_path: Path,
    fake_turns: Callable[..., list[Path]],
) -> None:
    """An unexpected exception from the diarizer propagates.

    Same narrowness as the boundary itself: only DiarizationUnavailable
    degrades. A TypeError here is a bug in dsj and must be loud.
    """
    fake_parakeet(tokens=_tokens())
    fake_turns(raises=TypeError("unsupported operand"))

    with pytest.raises(TypeError):
        transcribe(fake_media, tmp_path / "out.json")


def test_the_transcript_is_written_before_diarization_runs(
    fake_parakeet: Callable[..., FakeModel],
    fake_media: Path,
    tmp_path: Path,
    fake_turns: Callable[..., list[Path]],
) -> None:
    """§4's ordering, which is what makes optionality structural.

    The fake reads `out` from inside the diarization call. A refactor that
    holds the payload and writes once at the end breaks this and nothing else.
    """
    fake_parakeet(tokens=_tokens())
    out = tmp_path / "out.json"
    seen: list[dict[str, Any]] = []

    # def, not lambda: an annotated lambda parameter is not expressible.
    def record(wav: Path) -> None:
        seen.append(json.loads(out.read_text()))

    fake_turns(**_one_speaker(then=record))

    transcribe(fake_media, out)

    assert seen, "diarization never ran"
    assert seen[0]["sentences"][0]["text"] == "see this column here."
    assert "speaker" not in seen[0]["sentences"][0]


def test_the_checkpoint_outlives_the_labelling_pass(
    fake_parakeet: Callable[..., FakeModel],
    fake_media: Path,
    tmp_path: Path,
    fake_turns: Callable[..., list[Path]],
) -> None:
    """Present while labelling runs, gone once it is over (#101).

    The unlabelled transcript on disk carries no fingerprint, so a rerun cannot
    tell it is finished; the checkpoint can, and by now it banks every token
    through the end of the audio. Deleted before this pass, as it used to be,
    an interrupt here cost the whole transcription.
    """
    fake_parakeet(sample_rate=RATE, tokens=[], audio_s=360.0)
    out = tmp_path / "out.json"
    ckpt = checkpoint_path_for(out)
    seen: list[int] = []

    # def, not lambda: an annotated lambda parameter is not expressible.
    def record(wav: Path) -> None:
        seen.append(json.loads(ckpt.read_text())["next_start"])

    fake_turns(**_one_speaker(then=record))

    transcribe(fake_media, out)

    assert seen == [360 * RATE], "labelling ran without a complete checkpoint beside it"
    assert not ckpt.exists()


def test_an_interrupt_while_labelling_does_not_transcribe_again(
    fake_parakeet: Callable[..., FakeModel],
    fake_media: Path,
    tmp_path: Path,
    fake_turns: Callable[..., list[Path]],
) -> None:
    """Stopped during speaker labelling, the rerun goes straight back to labelling (#101).

    Reproduced on 2026-09-22 with both `kill` and `kill -9`: the rerun redid
    the whole transcription from 0:00, although the complete unlabelled
    transcript was on disk. On an hour of audio that is most of an hour.
    KeyboardInterrupt stands in for the signal; it is what Ctrl-C raises, and
    like a kill it lets none of transcribe()'s own clean-up run.

    The fake model counts its decodes, so "the ASR pass did not re-execute" is
    asserted directly: one decode across both runs.
    """
    model = fake_parakeet(tokens=_tokens())
    out = tmp_path / "out.json"

    def interrupt(wav: Path) -> None:
        raise KeyboardInterrupt

    fake_turns(**_one_speaker(then=interrupt))
    with pytest.raises(KeyboardInterrupt):
        transcribe(fake_media, out)
    unlabelled = json.loads(out.read_text())
    assert "speakers" not in unlabelled
    assert len(model.mels) == 1

    fake_turns(**_one_speaker())
    states: list[str] = []

    # def, not lambda: an annotated lambda parameter is not expressible.
    def capture(p: Progress, state: str) -> None:
        states.append(state)

    payload = transcribe(fake_media, out, on_progress=capture)

    assert len(model.mels) == 1, "the rerun transcribed the audio again"
    assert "running" not in states, "the rerun reported transcription progress again"
    assert payload["speakers"] == ["SPEAKER_01"]
    assert [s["speaker"] for s in payload["sentences"]] == [0]
    assert [s["tokens"] for s in payload["sentences"]] == [
        s["tokens"] for s in unlabelled["sentences"]
    ]
    assert not checkpoint_path_for(out).exists()


def test_the_diarizing_state_is_reported_between_running_and_done(
    fake_parakeet: Callable[..., FakeModel],
    fake_media: Path,
    tmp_path: Path,
    fake_turns: Callable[..., list[Path]],
) -> None:
    fake_parakeet(sample_rate=RATE, tokens=_tokens(), audio_s=360.0)
    fake_turns(**_one_speaker())
    states: list[str] = []

    # def, not lambda: an annotated lambda parameter is not expressible.
    def capture(p: Progress, state: str) -> None:
        states.append(state)

    transcribe(fake_media, tmp_path / "out.json", on_progress=capture)

    assert "diarizing" in states
    assert states.index("running") < states.index("diarizing")
    assert states.index("diarizing") < states.index("done")
    # Two frames, not a bar: senko emits nothing from inside, so the honest
    # report is a start and an end rather than invented intermediate progress.
    assert states.count("diarizing") == 2


def test_the_diarizing_heartbeat_reaches_the_status_file(
    fake_parakeet: Callable[..., FakeModel],
    fake_media: Path,
    tmp_path: Path,
    fake_turns: Callable[..., list[Path]],
) -> None:
    """The status file reports the diarizing phase while it runs.

    A detached run is inspected through this file, and this is the phase a
    watcher would otherwise see as a stall between "running" and "done".
    """
    fake_parakeet(sample_rate=RATE, tokens=_tokens(), audio_s=360.0)
    status = tmp_path / "status.json"
    seen: list[dict[str, Any]] = []

    # def, not lambda: an annotated lambda parameter is not expressible.
    def record(wav: Path) -> None:
        seen.append(json.loads(status.read_text()))

    fake_turns(**_one_speaker(then=record))

    transcribe(fake_media, tmp_path / "out.json", status_path=status)

    assert seen[0]["state"] == "diarizing"


def test_the_labelled_transcript_is_written_through_the_atomic_writer(
    fake_parakeet: Callable[..., FakeModel],
    fake_media: Path,
    tmp_path: Path,
    fake_turns: Callable[..., list[Path]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both writes of the transcript go through the atomic writer.

    Two atomic writes to the same path, so there is no instant in which the
    transcript is absent or partial. A merge that resolves either back to
    write_text reintroduces the torn read with the whole suite green.
    """
    fake_parakeet(tokens=_tokens())
    out = tmp_path / "out.json"
    fake_turns(**_one_speaker())
    seen = _spy_on_atomic_write(monkeypatch)

    transcribe(fake_media, out)

    assert seen.count(out) == 2


def test_the_diarizer_is_handed_the_extracted_wav_not_the_source(
    fake_parakeet: Callable[..., FakeModel],
    fake_media: Path,
    tmp_path: Path,
    fake_turns: Callable[..., list[Path]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The diarizer is handed the extracted wav, never the source media.

    senko wants a wav and the source is normally a .mov.

    media.py already produces the 16 kHz mono pcm_s16le the ASR pass consumes,
    and it lives only until the temp directory is torn down -- so the pass has
    to run inside that window, against that file.
    """
    from dsj import media

    fake_parakeet(tokens=_tokens())
    extracted: list[Path] = []
    # def, not lambda: an annotated lambda parameter is not expressible.
    def always_convert(stream: AudioStream, rate: int) -> bool:
        return True

    monkeypatch.setattr(media, "needs_conversion", always_convert)

    def fake_extract(
        _source: Path,
        dest: Path,
        rate: int,
        on_progress: Callable[[float], None] | None = None,
    ) -> Path:
        dest.write_bytes(b"RIFF")
        extracted.append(dest)
        return dest

    monkeypatch.setattr(media, "extract_audio", fake_extract)
    calls = fake_turns(**_one_speaker())

    transcribe(fake_media, tmp_path / "out.json")

    assert calls == extracted
    assert calls[0] != fake_media


# --- time order ----------------------------------------------------------


def _seam_token(start: float, text: str) -> AlignedToken:
    return AlignedToken(id=1, text=text, start=start, duration=0.08)


def _seam_result() -> AlignedResult:
    """What the overlap merge returns at a chunk seam, in the shape it returns it.

    Copied from the real one rather than invented. At the 2535s seam of a
    105-minute recording the merge emitted a full stop the earlier chunk had
    timed at 2534.84 AFTER the words the later chunk timed at 2540, so the
    sentence that full stop closes reports a start 5.72s before the two
    sentences printed ahead of it. Captured by scratch/seam_probe.py against
    scratch/meeting.wav, where the same fault produces 31 backwards steps in
    14,394 merged tokens.

    AlignedSentence sorts a sentence's own tokens, which is why the stray token
    lands at the front and sets `start`, and why the tokens WITHIN a sentence
    are in order here even though the sentences are not.
    """
    said = AlignedSentence(
        text=" Structured SAP.",
        tokens=[_seam_token(2538.4, " Structured"), _seam_token(2540.4, " SAP.")],
    )
    agreed = AlignedSentence(text=" Yeah.", tokens=[_seam_token(2540.56, " Yeah.")])
    mistimed = AlignedSentence(
        text=" First name.",
        tokens=[_seam_token(2540.88, " First name"), _seam_token(2534.84, ".")],
    )
    sentences = [said, agreed, mistimed]
    return AlignedResult(
        text="".join(s.text for s in sentences), sentences=sentences
    )


def _merge_that_went_backwards(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stand in for the chunk loop, returning a seam it stitched wrong.

    The loop itself is proved against the real model in tests/test_chunking.py.
    What is on trial here is what transcribe() does with a result whose
    sentences do not run forwards, and driving that from real audio would need
    105 minutes of it plus the weights.
    """

    # def, not lambda: an annotated lambda parameter is not expressible.
    def fake(engine: Any, audio_data: Any, **kwargs: Any) -> AlignedResult:
        return _seam_result()

    monkeypatch.setattr("dsj.chunking.transcribe_chunked", fake)


def test_sentences_are_written_earliest_first(
    fake_parakeet: Callable[..., FakeModel],
    fake_media: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The promise the whole index rests on: walk it down and time goes up.

    A reader that stops at the first `start` past its window -- which is the
    obvious way to answer "what was said between 40:00 and 41:00" -- silently
    loses every sentence after the first backwards step.
    """
    fake_parakeet(tokens=[])
    _merge_that_went_backwards(monkeypatch)
    out = tmp_path / "out.json"

    payload = transcribe(fake_media, out, diarize=False)

    on_disk = json.loads(out.read_text())
    assert on_disk == payload
    starts = [s["start"] for s in on_disk["sentences"]]
    assert starts == sorted(starts)
    assert starts == [2534.84, 2538.4, 2540.56]
    # The order promise reaches the tokens too, and for a different reason:
    # merge.py bisects a sentence's token list to vote on who spoke it.
    for sentence in on_disk["sentences"]:
        times = [t["t"] for t in sentence["tokens"]]
        assert times == sorted(times)


def test_the_text_reads_in_the_order_the_sentences_are_written_in(
    fake_parakeet: Callable[..., FakeModel],
    fake_media: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reordering one and not the other leaves the file disagreeing with itself.

    `text` is the sentence texts glued together, and parakeet's carry their own
    leading space, so the glue is the empty string.
    """
    fake_parakeet(tokens=[])
    _merge_that_went_backwards(monkeypatch)

    payload = transcribe(fake_media, tmp_path / "out.json", diarize=False)

    assert payload["text"] == "".join(s["text"] for s in payload["sentences"]).strip()
    # The mistimed full stop reads where its time puts it, ahead of the words it
    # closed: a sentence's text is its tokens joined (#106), and at this seam
    # the time is wrong by 5.72s. The text shows what the timing says.
    assert payload["text"] == ". First name Structured SAP. Yeah."


def _merge_that_reordered_a_sentence(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stand in for the chunk loop, returning one sentence whose words it re-sorted.

    The overlap merge left a full stop timed before the word it follows, and
    AlignedSentence sorted the tokens by time after its `text` had been glued
    in arrival order (dsj/alignment.py:76). One sentence, so the sentence order
    is already right and _in_time_order has nothing to do: the case that made
    up most of the 16 of 480, 23 of 664 and 32 of 1038 measured on #106.
    """
    tokens = [
        AlignedToken(id=1, text=" hello", start=10.0, duration=0.4),
        AlignedToken(id=2, text=".", start=9.0, duration=0.1),
    ]
    sentence = AlignedSentence(text="".join(t.text for t in tokens), tokens=tokens)
    assert sentence.text == " hello."  # precondition: the two copies disagree
    assert "".join(t.text for t in sentence.tokens) == ". hello"

    def fake(engine: Any, audio_data: Any, **kwargs: Any) -> AlignedResult:
        return AlignedResult(text=sentence.text, sentences=[sentence])

    monkeypatch.setattr("dsj.chunking.transcribe_chunked", fake)


def test_a_sentences_text_is_its_tokens_joined(
    fake_parakeet: Callable[..., FakeModel],
    fake_media: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The two copies of a sentence are one: `text` is `w` joined, in time order.

    Left as the merge built it, a reader sees " hello." and a click on the
    first word plays the full stop. The tokens win because they carry the
    times, and times are what the order of everything in the file promises.
    """
    fake_parakeet(tokens=[])
    _merge_that_reordered_a_sentence(monkeypatch)

    payload = transcribe(fake_media, tmp_path / "out.json", diarize=False)

    sentence = payload["sentences"][0]
    assert [t["w"] for t in sentence["tokens"]] == [".", " hello"]
    assert sentence["text"] == ". hello"
    assert payload["text"] == ". hello"


def test_speaker_turns_run_forwards_too(
    fake_parakeet: Callable[..., FakeModel],
    fake_media: Path,
    tmp_path: Path,
    fake_turns: Callable[..., list[Path]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Labels are applied to the written order, so ordering sentences orders turns.

    Two speakers, split so that the out-of-order sentence belongs to the first
    of them: left unordered the labels read 1, 1, 0 down the file, which is a
    speaker taking the floor back before he gave it up.
    """
    fake_parakeet(tokens=[])
    _merge_that_went_backwards(monkeypatch)
    fake_turns(
        turns=[Turn(2534.0, 2536.0, 0), Turn(2536.0, 2541.0, 1)],
        labels=["SPEAKER_01", "SPEAKER_02"],
    )

    payload = transcribe(fake_media, tmp_path / "out.json")

    assert [s["speaker"] for s in payload["sentences"]] == [0, 1, 1]
    turns = [(s["speaker"], s["start"]) for s in payload["sentences"]]
    firsts = [start for i, (spk, start) in enumerate(turns) if i == 0 or turns[i - 1][0] != spk]
    assert firsts == sorted(firsts)


# --- what a token carries ------------------------------------------------


def test_parakeet_tokens_carry_the_decoders_end_and_confidence(
    fake_parakeet: Callable[..., FakeModel],
    fake_media: Path,
    tmp_path: Path,
) -> None:
    """`e` is the token's own end, not the next token's start, and `c` is the decoder's.

    The gap after "see" is the case that matters. A bleep cut to the next start
    would run 0.1s into the pause here, and seconds across a real one. Dropping
    either key again, or writing a constant in place of the decoder's number,
    fails this.
    """
    fake_parakeet(
        tokens=[
            FakeToken(0.0, 0.4, "see", confidence=0.5),
            FakeToken(0.5, 1.0, " this", confidence=0.12345678),
            FakeToken(3.0, 3.5, " here."),
        ]
    )

    payload = transcribe(fake_media, tmp_path / "out.json", diarize=False)

    tokens = payload["sentences"][0]["tokens"]
    # Rounded to 3 places on the way out: the second confidence is written as
    # 0.123. The third is AlignedToken's default and parakeet does report it.
    assert [(t["t"], t["e"], t["c"]) for t in tokens] == [
        (0.0, 0.4, 0.5),
        (0.5, 1.0, 0.123),
        (3.0, 3.5, 1.0),
    ]


def test_no_written_token_ends_before_it_starts(
    fake_parakeet: Callable[..., FakeModel],
    fake_media: Path,
    tmp_path: Path,
) -> None:
    """`t` is rounded to the millisecond like `e`, so a zero-length token cannot go negative (#174).

    parakeet emits zero-length tokens for some subword continuations, 8 of 806
    on a 3-minute clip. `e` was rounded to 3 places and `t` was not, so a start
    carrying float noise wrote `"t": 107.60000000000001, "e": 107.6`, and a
    bleep span computed as `e - t` came out negative. 0.1 + 0.2 is the same
    noise in a smaller number. Read back from the file, the way a consumer
    reads it.
    """
    noisy = 0.1 + 0.2
    fake_parakeet(
        tokens=[
            FakeToken(0.0, noisy, " see"),
            FakeToken(noisy, noisy, "s"),
            FakeToken(0.5, 1.0, " here."),
        ]
    )
    out = tmp_path / "out.json"

    transcribe(fake_media, out, diarize=False)

    tokens = [t for s in json.loads(out.read_text())["sentences"] for t in s["tokens"]]
    assert [(t["t"], t["e"]) for t in tokens] == [(0.0, 0.3), (0.3, 0.3), (0.5, 1.0)]
    assert all(t["e"] >= t["t"] for t in tokens)
    assert [t["w"] for t in tokens] == [" see", "s", " here."]
    assert [t["charOffset"] for t in tokens] == [0, 4, 5]


def test_an_end_the_decoder_put_before_the_start_is_written_at_the_start() -> None:
    """`e >= t` holds for any token, not only for the float noise #174 found.

    A negative duration has not been seen from either chunk engine; the guard
    costs a max() and makes the promise payload.md states true by construction.
    """
    from dsj.suno import _token  # pyright: ignore[reportPrivateUsage]

    backwards = AlignedToken(id=1, text=" x", start=2.0, duration=-0.25, confidence=1.0)
    assert _token(backwards, measured=True) == {"t": 2.0, "w": " x", "e": 2.0, "c": 1.0}


class _SherpaStream:
    """What sherpa-onnx hands back for one stream: the four per-token lists dsj reads.

    The real result carries more (`text`, `words`, `lang` and others); these
    are the ones dsj/sherpa.py decodes, one entry per token in each.
    """

    def __init__(
        self,
        tokens: list[str],
        timestamps: list[float],
        durations: list[float],
        ys_log_probs: list[float],
    ) -> None:
        self.result = SimpleNamespace(
            tokens=tokens, timestamps=timestamps, durations=durations, ys_log_probs=ys_log_probs
        )

    def accept_waveform(self, sample_rate: int, samples: Any) -> None:
        """Take the audio and ignore it; the result is fixed."""


class _SherpaRecognizer:
    """Stands in for sherpa_onnx.OfflineRecognizer, which dsj.sherpa.wrap accepts."""

    def __init__(
        self,
        tokens: list[str],
        timestamps: list[float],
        durations: list[float],
        ys_log_probs: list[float],
    ) -> None:
        self.lists = (tokens, timestamps, durations, ys_log_probs)

    def create_stream(self) -> _SherpaStream:
        return _SherpaStream(*self.lists)

    def decode_stream(self, stream: _SherpaStream) -> None:
        """Nothing to decode: the stream already holds its result."""


def test_sherpa_tokens_carry_the_decoders_end_and_confidence(
    fake_media: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`e` is the start plus sherpa's own duration, `c` the probability it gave the token.

    The three-second pause after " see" is the case that matters. Before #77
    this engine took a token's end from the next token's start, which runs
    " see" to 3.0 and puts the whole pause inside the word, so a bleep cut on
    it would cover the silence and a subtitle would hold the word on screen.

    The duration arrives as a float32, the way the native library returns it
    (0.24 reads 0.23999999463558197), and is written rounded like parakeet's.
    `c` is exp of the log-probability, so log(0.5) must come back as 0.5.

    The real sherpa decode runs here; only the recognizer under it is faked.
    """
    import dsj.sherpa as sherpa_mod

    loaded = sherpa_mod.wrap(
        _SherpaRecognizer(
            [" see", " this."],
            [0.0, 3.0],
            durations=[float(np.float32(0.24)), float(np.float32(0.32))],
            ys_log_probs=[math.log(0.5), math.log(0.9)],
        )
    )

    def load_audio(path: Path) -> Any:
        return np.zeros(10 * RATE, dtype=np.float32)

    def load(model_id: str) -> Any:
        return loaded

    def fingerprint_fields() -> dict[str, str]:
        return {"sherpa_onnx_version": "0.0.0-fake"}

    # A stand-in module, so available() says yes without loading the native
    # library, which is absent wherever the sherpa extra is.
    monkeypatch.setitem(sys.modules, "sherpa_onnx", ModuleType("sherpa_onnx"))
    monkeypatch.setattr(loaded, "load_audio", load_audio)
    monkeypatch.setattr(sherpa_mod, "load", load)
    monkeypatch.setattr(sherpa_mod, "fingerprint_fields", fingerprint_fields)

    payload = transcribe(fake_media, tmp_path / "out.json", engine="sherpa", diarize=False)

    tokens = [t for s in payload["sentences"] for t in s["tokens"]]
    assert [(t["t"], t["w"], t["e"], t["c"]) for t in tokens] == [
        (0.0, " see", 0.24, 0.5),
        (3.0, " this.", 3.32, 0.9),
    ]


@pytest.mark.parametrize(
    ("durations", "ys_log_probs", "missing"),
    [([], [-0.1], "0 durations"), ([0.08], [], "0 log-probabilities")],
)
def test_sherpa_refuses_to_guess_an_end_or_a_confidence(
    durations: list[float], ys_log_probs: list[float], missing: str
) -> None:
    """A model whose result lacks either list fails loudly instead of writing a guess.

    Only a TDT model has a duration head (a plain transducer leaves
    `durations` empty), and dsj writes `e` and `c` as the decoder's own. So a
    token without its duration or log-probability is an error, the same way a
    token without its timestamp already is, never a quiet return to inferring.
    """
    import dsj.sherpa as sherpa_mod

    loaded = sherpa_mod.wrap(_SherpaRecognizer([" see"], [0.0], durations, ys_log_probs))

    with pytest.raises(RuntimeError, match=f"1 tokens and {missing}"):
        loaded.decode(np.zeros(RATE, dtype=np.float32))


def test_parakeet_token_charoffset_indexes_the_sentence_text(
    fake_parakeet: Callable[..., FakeModel],
    fake_media: Path,
    tmp_path: Path,
) -> None:
    """A click on rendered prose maps back to a word through `charOffset` (#126).

    Each token's offset is where its `w` starts in the sentence's `text`, so a
    reader rendering `text` can turn a character position into a token index
    without re-deriving the join, which is where the #106 mismatch came from.
    """
    fake_parakeet(tokens=_tokens())

    payload = transcribe(fake_media, tmp_path / "out.json", diarize=False)

    sentence = payload["sentences"][0]
    text = sentence["text"]
    assert [t["charOffset"] for t in sentence["tokens"]] == [0, 3, 8, 15]
    for token in sentence["tokens"]:
        start = token["charOffset"]
        assert text[start : start + len(token["w"])] == token["w"]


def test_charoffset_indexes_the_text_a_seam_rebuilt(
    fake_parakeet: Callable[..., FakeModel],
    fake_media: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """At a seam the offsets point into the text as it is written, not as the merge glued it.

    The merge glued " hello." and the tokens run ". hello". Offsets taken from
    the glued string would put the full stop at 6; in the written text it is at 0.
    """
    fake_parakeet(tokens=[])
    _merge_that_reordered_a_sentence(monkeypatch)

    payload = transcribe(fake_media, tmp_path / "out.json", diarize=False)

    sentence = payload["sentences"][0]
    assert [(t["w"], t["charOffset"]) for t in sentence["tokens"]] == [(".", 0), (" hello", 1)]
    for token in sentence["tokens"]:
        start = token["charOffset"]
        assert sentence["text"][start : start + len(token["w"])] == token["w"]
