"""The Mac stays awake for the length of a run, and not a second longer (#89)."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from conftest import FakeToken

from dsj import awake
from dsj.suno import main

if TYPE_CHECKING:
    from collections.abc import Callable

    from conftest import FakeModel

pytestmark = pytest.mark.usefixtures("already_extracted_media", "no_real_diarizer")


def _present(_path: Path) -> bool:
    """Stands in for Path.exists, so the tests do not depend on caffeinate being installed."""
    return True


class _FakeProcess:
    """What `held` does to the process it starts: terminate once, after the last release."""

    def __init__(self, argv: list[str]) -> None:
        self.argv = argv
        self.terminated = 0
        self.alive = True

    def poll(self) -> int | None:
        return None if self.alive else 0

    def terminate(self) -> None:
        self.terminated += 1
        self.alive = False

    def wait(self, timeout: float | None = None) -> int:
        return 0


def _spy_popen(monkeypatch: pytest.MonkeyPatch) -> list[_FakeProcess]:
    """Stand in for caffeinate only.

    `awake.subprocess` is the one subprocess module, so anything else a run
    starts (ffmpeg, say) still gets the real Popen.
    """
    started: list[_FakeProcess] = []
    real = subprocess.Popen

    def popen(argv: list[str], **kwargs: Any) -> Any:
        if argv[:1] != [awake.CAFFEINATE]:
            return real(argv, **kwargs)
        process = _FakeProcess(argv)
        started.append(process)
        return process

    monkeypatch.setattr(awake.subprocess, "Popen", popen)
    monkeypatch.setattr(awake.Path, "exists", _present)
    return started


def test_a_hold_is_caffeinate_tied_to_this_process(monkeypatch: pytest.MonkeyPatch) -> None:
    started = _spy_popen(monkeypatch)
    with awake.held("transcription"):
        assert awake.holders() == ("transcription",)
        [process] = started
        assert process.argv == [awake.CAFFEINATE, "-i", "-w", str(os.getpid())]
        assert process.terminated == 0
    assert awake.holders() == ()
    assert process.terminated == 1


def test_overlapping_holds_share_one_assertion_and_the_first_out_keeps_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = _spy_popen(monkeypatch)
    with awake.held("transcription"):
        with awake.held("render"):
            assert len(started) == 1
        # The render ended; the transcription still holds the machine.
        assert started[0].terminated == 0
        assert awake.holders() == ("transcription",)
    assert started[0].terminated == 1


def test_a_hold_that_cannot_be_taken_is_said_and_never_raised(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise PermissionError("no")

    monkeypatch.setattr(awake.subprocess, "Popen", refuse)
    monkeypatch.setattr(awake.Path, "exists", _present)
    with awake.held("transcription"):
        pass
    err = capsys.readouterr().err
    assert "could not keep the machine awake (PermissionError: no)" in err


def test_the_hold_is_released_when_the_block_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    started = _spy_popen(monkeypatch)
    with pytest.raises(RuntimeError), awake.held("transcription"):
        raise RuntimeError("the run died")
    assert started[0].terminated == 1
    assert awake.holders() == ()


@pytest.mark.skipif(not shutil.which("pmset"), reason="pmset is macOS; the hold is caffeinate's")
def test_the_assertion_is_real_and_ends_with_the_hold() -> None:
    """`pmset -g assertions` shows caffeinate during the hold and not after (#89's Verify)."""

    def mentions_us() -> bool:
        pmset = subprocess.run(["pmset", "-g", "assertions"], capture_output=True, text=True)
        listed = pmset.stdout
        # pmset names the holder as "caffeinate asserting on behalf of Process ID N".
        return f"on behalf of Process ID {os.getpid()}" in listed

    assert not mentions_us()
    with awake.held("test"):
        deadline = time.monotonic() + 5
        while not mentions_us() and time.monotonic() < deadline:
            time.sleep(0.1)
        assert mentions_us()
    deadline = time.monotonic() + 5
    while mentions_us() and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not mentions_us()


def test_a_terminal_run_holds_the_machine_awake(
    fake_parakeet: Callable[..., FakeModel],
    fake_media: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The hold wraps the whole run: taken before the model loads, released after the write."""
    started = _spy_popen(monkeypatch)
    fake_parakeet(tokens=[FakeToken(0.0, 0.5, " hello")])
    out = tmp_path / "out.json"

    assert main([str(fake_media), "-o", str(out), "--no-diarize"]) == 0

    [process] = started
    assert process.argv[:2] == [awake.CAFFEINATE, "-i"]
    assert process.terminated == 1
    assert out.exists()
