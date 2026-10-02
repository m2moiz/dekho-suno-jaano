"""Transcriptions started from the page (#113), run in this process, one at a time.

The server imports dsj and calls `dsj.suno.transcribe()` itself (#57 section 16):
no subprocess, so a run's failure is an exception this process sees, and its
progress is the status file the run writes, read back by the page's next poll.

One run at a time, by the same lock `dsj suno` takes (#136): a job from the page
refuses to start beside a terminal run, and a terminal run refuses to start
beside a job, each naming the other's pid. Every job also runs on one worker
thread that lives as long as the server, so a model mlx loaded for one job is
only ever used on the thread that loaded it.

Plain Python, no fastapi: dsj/ui/errors.py maps NotStarted to a status, and
everything under dsj.ui but the server must import without the `ui` extra.
"""

from __future__ import annotations

__all__ = [
    "DEFAULT_MODELS",
    "EngineChoice",
    "Job",
    "Jobs",
    "NotStarted",
    "engine_choices",
    "transcript_path",
]

import contextlib
import json
import logging
import os
import queue
import re
import sys
import tempfile
import threading
import traceback
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from dsj import runlock, suno
from dsj.asr import ENGINES, EngineUnavailable, get_engine
from dsj.parakeet import DEFAULT_MODEL as PARAKEET_MODEL
from dsj.sherpa import DEFAULT_MODEL as SHERPA_MODEL
from dsj.ui.schemas import TranscribeRequest
from dsj.ui.store import Library, library_path
from dsj.whisper import DEFAULT_WHISPER_MODEL

# Each engine's own default, which the page's model box starts on. Not what
# `dsj suno` fills in: it hands sherpa parakeet's id, which sherpa cannot load
# (#46). The page offers what each engine module itself names.
DEFAULT_MODELS = {
    "parakeet": PARAKEET_MODEL,
    "whisper": DEFAULT_WHISPER_MODEL,
    "sherpa": SHERPA_MODEL,
}

class NotStarted(RuntimeError):
    """The page asked for a transcription that was refused. Nothing ran and nothing was written."""


@dataclass(frozen=True)
class EngineChoice:
    """One engine as the page's picker offers it."""

    name: str
    # Why it cannot run here, in the sentence its own available() wrote, or None.
    reason: str | None
    default_model: str


def engine_choices() -> list[EngineChoice]:
    """Every engine dsj has, in ENGINES' order, each asked whether it can run here.

    A runtime question, never a guess from the platform (dsj/asr.py says why),
    and an engine that cannot run is listed with its reason rather than hidden:
    a missing engine with no word about it reads as one dsj does not have.
    """
    choices: list[EngineChoice] = []
    for name in ENGINES:
        try:
            get_engine(name)
            reason = None
        except EngineUnavailable as exc:
            reason = str(exc)
        choices.append(EngineChoice(name, reason, DEFAULT_MODELS[name]))
    return choices


def transcript_path(recording_id: int, engine: str, model: str, language: str | None) -> Path:
    """Where a run from the page writes its transcript: one file per recording and settings.

    Beside the library, not beside the recording: the page never writes into
    the owner's folders. Named by what decides the transcript's contents, so a
    second run with other settings keeps the first one's file, and a run
    repeated with the same settings writes the same path, where its checkpoint
    lets it resume (dsj/checkpoint.py keys that file to `out`).
    """
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(model).name or model).strip("._") or "model"
    stem = f"{recording_id}-{engine}-{name}" + (f"-{language}" if language else "")
    return library_path().parent / "transcripts" / f"{stem}.json"


@dataclass
class Job:
    """One transcription started from the page, and what has become of it."""

    id: int
    recording_id: int
    engine: str
    model: str
    language: str | None
    reports_progress: bool
    started_at: str
    out: Path
    status_path: Path
    # Set by the worker when the run is over, and only then.
    outcome: str | None = None
    error: str | None = None
    transcript_id: int | None = None
    # The warnings the run logged: labelling that degraded, a checkpoint not
    # used. The run still finished; these say what it could not do.
    notes: list[str] = field(default_factory=list[str])

    def view(self) -> dict[str, Any]:
        """This job as the page reads it: the run's own last frame, and the outcome.

        Two states are the page's own, around the ones the run writes:
        `starting` before the first frame, while the model loads, and `saving`
        between the run's last frame (`done`, `failed` or `interrupted`) and the
        job's own outcome. A job is finished only by its outcome, which is set
        after the run lock is let go: a page that starts the next job the moment
        this one reads finished must not be refused by it.
        """
        frame: dict[str, Any] = {}
        # Absent until the run's first frame. Written by rename, never torn.
        with contextlib.suppress(FileNotFoundError):
            frame = json.loads(self.status_path.read_text())
        state = self.outcome or frame.get("state", "starting")
        if self.outcome is None and state in ("done", "failed", "interrupted"):
            state = "saving"
        return {
            "id": self.id,
            "recording_id": self.recording_id,
            "engine": self.engine,
            "model": self.model,
            "language": self.language,
            "reports_progress": self.reports_progress,
            "started_at": self.started_at,
            "state": state,
            "fraction": frame.get("fraction", 0.0),
            "audio_done_s": frame.get("audio_done_s", 0.0),
            "audio_total_s": frame.get("audio_total_s", 0.0),
            "elapsed_s": frame.get("elapsed_s", 0.0),
            "speed": frame.get("speed", 0.0),
            "eta_s": frame.get("eta_s"),
            "stalled_s": frame.get("stalled_s"),
            "error": self.error or frame.get("error"),
            "transcript_id": self.transcript_id,
            "notes": list(self.notes),
        }


class _Notes(logging.StreamHandler[TextIO]):
    """dsj.suno's log on stderr, as `dsj suno` shows it, and its warnings on the job.

    On stderr too because a handler here means Python's last-resort printer no
    longer runs, and a warning nobody sees on the terminal is one lost. Only
    records from the worker thread become notes.
    """

    def __init__(self, job: Job) -> None:
        super().__init__(sys.stderr)
        self.setFormatter(logging.Formatter("%(message)s"))
        self.job = job
        self.thread = threading.get_ident()

    def emit(self, record: logging.LogRecord) -> None:
        super().emit(record)
        if record.levelno >= logging.WARNING and record.thread == self.thread:
            self.job.notes.append(record.getMessage())


class Jobs:
    """Every job this server has started, and the one thread that runs them."""

    def __init__(self, hold: Callable[[], AbstractContextManager[None]]) -> None:
        """`hold` keeps the server up while a run is going (Heartbeat.hold)."""
        self._hold = hold
        self._jobs: dict[int, Job] = {}
        self._queue: queue.SimpleQueue[tuple[Job, dict[str, Any], int]] = queue.SimpleQueue()
        self._worker: threading.Thread | None = None
        self._start_lock = threading.Lock()
        # Status files only this server reads; nothing in them outlives a run.
        self._status_dir = Path(tempfile.mkdtemp(prefix="dsj-ui-jobs-"))

    def all(self) -> list[Job]:
        """Every job, the first started first."""
        return [self._jobs[k] for k in sorted(self._jobs)]

    def start(self, recording_id: int, request: TranscribeRequest) -> Job | None:
        """Start transcribing a library recording, or refuse before anything runs.

        Returns None when the library has no recording with this id.

        Raises:
            NotStarted: the recording's file is gone.
            EngineUnavailable: the engine cannot run on this machine.
            dsj.runlock.AlreadyRunning: another transcription holds the machine.
        """
        with Library.open() as library:
            recording = library.recording(recording_id)
        if recording is None:
            return None
        media = recording.path
        if not media.is_file():
            raise NotStarted(
                f"{media} is not there any more, so it cannot be transcribed. Put the file "
                f"back where it was, then start again."
            )
        # A file in a cloud-synced folder is transcribed like any other: the run
        # leaves it untagged (dsj/filetag.py, #202) and writes nothing beside it.
        arguments = self._arguments(media, request)
        engine: str = arguments["engine"]
        get_engine(engine)  # EngineUnavailable with its remedy, before any lock is taken
        model: str = arguments["model_id"]
        language: str | None = arguments["language"]
        out = transcript_path(recording_id, engine, model, language)
        out.parent.mkdir(parents=True, exist_ok=True)
        with self._start_lock:
            job_id = len(self._jobs) + 1
            status_path = self._status_dir / f"{job_id}.status.json"
            # Taken here, so a refusal is this request's answer; released by the
            # worker when the run is over.
            held = runlock.acquire(
                {
                    "pid": os.getpid(),
                    "out": str(out),
                    "status": str(status_path),
                    "media": str(media),
                }
            )
            job = Job(
                id=job_id,
                recording_id=recording_id,
                engine=engine,
                model=model,
                language=language,
                reports_progress=suno.reports_progress(
                    engine, arguments["prompt"], arguments["anchor_s"]
                ),
                started_at=datetime.now(UTC).isoformat(timespec="seconds"),
                out=out,
                status_path=status_path,
            )
            self._jobs[job_id] = job
            self._queue.put((job, arguments | {"out": out, "status_path": status_path}, held))
            if self._worker is None:
                self._worker = threading.Thread(target=self._work, name="dsj-ui-jobs", daemon=True)
                self._worker.start()
        return job

    @staticmethod
    def _arguments(media: Path, request: TranscribeRequest) -> dict[str, Any]:
        """transcribe()'s arguments for this request, as `dsj suno` would build them."""
        engine: str = request.engine
        language = request.language or None
        prompt = request.prompt or None
        anchor_s: float | None = None
        if request.roman_urdu:
            engine, language, prompt, anchor_s = suno.roman_urdu(engine, language, prompt)
        return {
            "media": media,
            "model_id": request.model or DEFAULT_MODELS[engine],
            "resume": not request.start_over,
            "diarize": request.diarize,
            "require_diarize": request.require_diarize,
            "engine": engine,
            "language": language,
            "prompt": prompt,
            "anchor_s": anchor_s,
        }

    def _work(self) -> None:
        """Run each queued job in turn, for as long as the server lives."""
        while True:
            job, arguments, held = self._queue.get()
            self._run(job, arguments, held)

    def _run(self, job: Job, arguments: dict[str, Any], held: int) -> None:
        notes = _Notes(job)
        log = logging.getLogger("dsj.suno")
        log.addHandler(notes)
        log.setLevel(logging.INFO)
        transcript_id: int | None = None
        error: str | None = None
        try:
            with self._hold():
                # Looked up at call time, so a test can stand in for it.
                suno.transcribe(**arguments)
                with Library.open() as library:
                    row = library.record_run(job.out, engine=job.engine, language=job.language)
            transcript_id = row.id
        except Exception as exc:
            # The run has already written `failed` to its status file (#103);
            # this also covers a failure after it, writing the library row.
            error = f"{type(exc).__name__}: {exc}"
            # On the terminal, as an exception in a route reaches it (#82).
            traceback.print_exception(exc, file=sys.stderr)
        finally:
            log.removeHandler(notes)
            os.close(held)
        # Published only after the lock is let go: a page that sees this job
        # finished and starts the next one at once must not be refused by it.
        job.transcript_id = transcript_id
        job.error = error
        job.outcome = "done" if error is None else "failed"
