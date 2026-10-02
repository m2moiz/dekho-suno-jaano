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


def stub_run(work: Path, *extra: str, hold: bool = True) -> subprocess.Popen[bytes]:
    """The stub `dsj suno` over `work/rec.wav`, writing `out.json` and `run.json`.

    It touches `work/loaded` if it gets as far as loading the model.
    """
    work.mkdir(exist_ok=True)
    media = work / "rec.wav"
    media.touch()
    argv = [
        sys.executable, str(STUB), str(media),
        "-o", str(work / "out.json"), "--status", str(work / "run.json"),
        "--no-diarize", *extra,
    ]
    env = {"STUB_HOLD": "1" if hold else "0", "STUB_LOADED": str(work / "loaded")}
    return launch(argv, work / "stderr.log", env)


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
        "pid": run.pid,
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


# --------------------------------------------------------------------------
# #138: the writer's pid, so dead and slow stop looking alike
# --------------------------------------------------------------------------


def alive(pid: int) -> bool:
    """`kill -0`: does a process with this pid exist?"""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_a_killed_run_is_told_apart_from_a_slow_one(tmp_path: Path) -> None:
    """SIGKILL cannot be caught, so the frame stays `running`; its pid gives it away."""
    status = tmp_path / "run.json"
    run = stub_run(tmp_path)
    frame = wait_for_state(status, "running", run)
    assert frame["pid"] == run.pid
    assert alive(frame["pid"]), "a live run's pid must answer kill -0"

    os.kill(run.pid, signal.SIGKILL)
    assert run.wait(timeout=60) == -signal.SIGKILL

    assert read_status(status) == frame, "nothing can write after SIGKILL; the last frame stays"
    assert not alive(frame["pid"]), "and the pid it names is gone, at once"


def test_every_document_names_its_writer(tmp_path: Path) -> None:
    """A done frame and a failure document carry the pid too, not only running frames."""
    finished = stub_run(tmp_path, hold=False)
    assert finished.wait(timeout=60) == 0
    done = read_status(tmp_path / "run.json")
    assert done is not None
    assert (done["state"], done["pid"]) == ("done", finished.pid)

    (tmp_path / "rec.wav").unlink()
    broken = launch(
        [sys.executable, str(STUB), str(tmp_path / "rec.wav"), "-o", str(tmp_path / "out.json"),
         "--status", str(tmp_path / "run.json"), "--no-diarize"],
        tmp_path / "stderr.log",
    )
    assert broken.wait(timeout=60) == 1
    failed = read_status(tmp_path / "run.json")
    assert failed is not None
    assert (failed["state"], failed["pid"]) == ("failed", broken.pid)
    assert failed["error"].startswith("FileNotFoundError")


# --------------------------------------------------------------------------
# #136: one run at a time
# --------------------------------------------------------------------------


def test_a_second_run_is_refused_while_the_first_runs(tmp_path: Path) -> None:
    """Different media, different outputs: the case that froze the machine on 2026-09-19."""
    first = stub_run(tmp_path / "first")
    frame = wait_for_state(tmp_path / "first" / "run.json", "running", first)

    second = stub_run(tmp_path / "second", hold=False)
    assert second.wait(timeout=60) == 75

    said = (tmp_path / "second" / "stderr.log").read_text()
    assert "already running" in said
    assert f"pid {first.pid}" in said
    assert str(tmp_path / "first" / "out.json") in said
    # Refused before the model loaded and before --status was touched.
    assert not (tmp_path / "second" / "loaded").exists()
    assert not (tmp_path / "second" / "run.json").exists()
    # And the run it refused for carries on, undisturbed.
    assert first.poll() is None
    assert read_status(tmp_path / "first" / "run.json") == frame

    assert stop(first, signal.SIGTERM) == 143


def test_a_run_killed_with_sigkill_does_not_block_the_next(tmp_path: Path) -> None:
    first = stub_run(tmp_path / "first")
    wait_for_state(tmp_path / "first" / "run.json", "running", first)
    os.kill(first.pid, signal.SIGKILL)
    assert first.wait(timeout=60) == -signal.SIGKILL
    # The file outlives the run, still naming it. Its contents are not the lock.
    lock = Path(os.environ["DSJ_SUNO_LOCK"])
    assert json.loads(lock.read_text())["pid"] == first.pid

    second = stub_run(tmp_path / "second", hold=False)
    assert second.wait(timeout=60) == 0, (tmp_path / "second" / "stderr.log").read_text()
    done = read_status(tmp_path / "second" / "run.json")
    assert done is not None
    assert (done["state"], done["pid"]) == ("done", second.pid)
    assert json.loads(lock.read_text())["pid"] == second.pid


# --------------------------------------------------------------------------
# #164: an extraction that stops moving says so
# --------------------------------------------------------------------------

# Stands in for ffmpeg on PATH, so the real extract_audio reads a real progress
# stream from a real process. Its position advances to 1 s, stands still there
# for about a second while it keeps reporting, which is what ffmpeg did for 15
# minutes on 2026-09-22, then advances again and ends.
FAKE_FFMPEG = """\
#!{python}
import sys, time
open(sys.argv[-1], "wb").write(b"RIFF")
def report(us):
    print(f"out_time_us={{us}}", flush=True)
    print("progress=continue", flush=True)
report(500000)
report(1000000)
for _ in range(20):
    time.sleep(0.05)
    report(1000000)
report(2000000)
print("progress=end", flush=True)
"""


@pytest.mark.usefixtures("already_extracted_media", "no_real_diarizer")
def test_a_stalled_extraction_says_so_until_it_moves_again(
    fake_parakeet: Any,
    fake_media: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import dsj.suno as suno_mod
    from dsj import media

    fake_parakeet()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ffmpeg = bin_dir / "ffmpeg"
    ffmpeg.write_text(FAKE_FFMPEG.format(python=sys.executable))
    ffmpeg.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

    def always_convert(stream: media.AudioStream, rate: int) -> bool:
        return True

    monkeypatch.setattr(media, "needs_conversion", always_convert)
    # A third of a second for the minute: the rule under test is the same, and
    # the fake stands still for about three times the bound.
    monkeypatch.setattr(suno_mod, "STALL_S", 0.3)

    status = tmp_path / "run.json"
    frames: list[dict[str, Any]] = []
    real = suno_mod.atomic_write_text

    def record(path: Path, text: str, **kwargs: Any) -> None:
        if path == status:
            frames.append(json.loads(text))
        real(path, text, **kwargs)

    monkeypatch.setattr(suno_mod, "atomic_write_text", record)

    suno_mod.transcribe(fake_media, tmp_path / "out.json", status_path=status, diarize=False)

    extracting = [f for f in frames if f["state"] == "extracting"]
    marked = [i for i, f in enumerate(extracting) if "stalled_s" in f]
    assert marked, f"no frame said the extraction had stalled: {extracting}"
    # Only frames standing at 1 s, only once the bound has passed, and growing.
    assert all(extracting[i]["audio_done_s"] == 1.0 for i in marked)
    assert extracting[marked[0]]["stalled_s"] >= 0.3
    stalls = [extracting[i]["stalled_s"] for i in marked]
    assert stalls == sorted(stalls)
    assert "stalled_s" not in extracting[0]
    # Cleared as soon as the position moves again, and never on another phase.
    moved = [f for f in extracting if f["audio_done_s"] == 2.0]
    assert moved, extracting
    assert all("stalled_s" not in f for f in moved)
    assert all("stalled_s" not in f for f in frames if f["state"] != "extracting")


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
