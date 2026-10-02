"""What a `dsj suno` process leaves behind when it is stopped, and who it lets run.

Every test here drives a real process and sends it real signals, because the
failures they guard against were facts about processes: on 2026-09-22 a `kill`
and a Ctrl-C both left a status file reading `running` about a job that no
longer existed (#143). A mock of the CLI cannot be killed.

The fast tests run tests/stub_suno.py, the shipped CLI over a stub engine, so they
cost a second each and run in CI. The slow test runs parakeet on a real clip.

SIGINT is reset to its default in every child. A process started from a shell
without job control inherits SIGINT ignored, and Python then never raises
KeyboardInterrupt for it, so a test run from an agent's background shell would
fail for a reason that has nothing to do with dsj. That is how #178 was filed
against working code.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parent.parent
STUB = REPO / "tests" / "stub_suno.py"


def _sigint_default() -> None:
    signal.signal(signal.SIGINT, signal.SIG_DFL)


def launch(
    argv: list[str], log: Path, env: dict[str, str] | None = None
) -> subprocess.Popen[bytes]:
    """Start `argv` in its own session, with SIGINT at its default and stderr to `log`.

    Its own session so that a signal sent to its process group, which is what a
    terminal's Ctrl-C does, reaches it and never this test.
    """
    with log.open("wb") as err:
        return subprocess.Popen(
            argv,
            stdout=subprocess.DEVNULL,
            stderr=err,
            env=os.environ | (env or {}),
            start_new_session=True,
            preexec_fn=_sigint_default,
        )


def stub_run(tmp_path: Path, *extra: str, hold: bool = True) -> subprocess.Popen[bytes]:
    """The stub `dsj suno` over `tmp_path/rec.wav`, writing `out.json` and `run.json`."""
    media = tmp_path / "rec.wav"
    media.touch()
    argv = [
        sys.executable, str(STUB), str(media),
        "-o", str(tmp_path / "out.json"), "--status", str(tmp_path / "run.json"),
        "--no-diarize", *extra,
    ]
    return launch(argv, tmp_path / "stderr.log", {"STUB_HOLD": "1" if hold else "0"})


def read_status(path: Path) -> dict[str, Any] | None:
    """The heartbeat, or None while there is none. Never torn: it is replaced atomically."""
    if not path.exists():
        return None
    return json.loads(path.read_text())


def wait_for_state(
    path: Path, state: str, proc: subprocess.Popen[bytes], timeout_s: float = 60.0
) -> dict[str, Any]:
    """Block until the heartbeat at `path` says `state`. An observable, never a sleep."""
    deadline = time.monotonic() + timeout_s
    while True:
        doc = read_status(path)
        if doc is not None and doc.get("state") == state:
            return doc
        assert proc.poll() is None, f"the run exited {proc.returncode} before {state!r}: {doc}"
        assert time.monotonic() < deadline, f"no {state!r} frame within {timeout_s:g}s: {doc}"
        time.sleep(0.02)


def stop(proc: subprocess.Popen[bytes], sig: signal.Signals) -> int:
    """Send `sig` the way a person would, and return the exit code.

    SIGINT goes to the process group, as a terminal's Ctrl-C does; SIGTERM to the
    pid alone, as `kill <pid>` does.
    """
    if sig == signal.SIGINT:
        os.killpg(proc.pid, sig)
    else:
        proc.send_signal(sig)
    return proc.wait(timeout=60)


# --------------------------------------------------------------------------
# #143: Ctrl-C and kill write "interrupted"
# --------------------------------------------------------------------------


@pytest.mark.parametrize(("sig", "code"), [(signal.SIGINT, 130), (signal.SIGTERM, 143)])
def test_a_stopped_run_says_interrupted(sig: signal.Signals, code: int, tmp_path: Path) -> None:
    status = tmp_path / "run.json"
    run = stub_run(tmp_path)
    wait_for_state(status, "running", run)

    assert stop(run, sig) == code

    doc = read_status(status)
    assert doc == {
        "state": "interrupted",
        "signal": sig.name,
        "during": "running",
        "audio_done_s": 105.0,
        "audio_total_s": 300.0,
    }
    # Stopping is not failing: the chunk banked before the signal is still there
    # for the rerun to resume from.
    assert (tmp_path / "out.json.ckpt").exists()
    assert not (tmp_path / "out.json").exists()


def test_a_finished_run_puts_the_default_sigterm_back(tmp_path: Path) -> None:
    """The handler belongs to the run, not to whoever called suno() in-process."""
    from typer.testing import CliRunner

    import dsj.cli

    before = signal.getsignal(signal.SIGTERM)
    # --language on parakeet is refused inside transcribe(), after the handler is
    # in and before any model loads.
    result = CliRunner().invoke(
        dsj.cli.app,
        ["suno", str(tmp_path / "rec.wav"), "-o", str(tmp_path / "o.json"), "--language", "ur"],
    )
    assert isinstance(result.exception, ValueError), result.output
    assert signal.getsignal(signal.SIGTERM) == before


@pytest.mark.slow
@pytest.mark.parametrize(("sig", "code"), [(signal.SIGINT, 130), (signal.SIGTERM, 143)])
def test_parakeet_stopped_mid_run_says_interrupted(
    sig: signal.Signals, code: int, chunked_audio_path: Path, tmp_path: Path
) -> None:
    """The same, on the real engine and a real 360 s clip, signalled after its first chunk."""
    status = tmp_path / "run.json"
    run = launch(
        [sys.executable, "-m", "dsj.suno", str(chunked_audio_path), "-o", str(tmp_path / "o.json"),
         "--status", str(status), "--no-diarize", "--no-resume"],
        tmp_path / "stderr.log",
    )
    running = wait_for_state(status, "running", run, timeout_s=600)

    assert stop(run, sig) == code, (tmp_path / "stderr.log").read_text()

    doc = read_status(status)
    assert doc is not None
    assert doc["state"] == "interrupted", doc
    assert doc["signal"] == sig.name
    assert doc["during"] == "running"
    assert doc["audio_done_s"] >= running["audio_done_s"]
    assert doc["audio_total_s"] == pytest.approx(360.0, abs=1.0)
