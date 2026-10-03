"""Transcriptions (#113) and bleep renders (#215) from the page, run in this process, one at a time.

The server imports dsj and calls `dsj.suno.transcribe()` itself (#57 section 16):
no subprocess, so a run's failure is an exception this process sees, and its
progress is the status file the run writes, read back by the page's next poll.

One run at a time, by the same lock `dsj suno` takes (#136): a job from the page
refuses to start beside a terminal run, and a terminal run refuses to start
beside a job, each naming the other's pid. Every job also runs on one worker
thread that lives as long as the server, so a model mlx loaded for one job is
only ever used on the thread that loaded it.

A render is the terminal's: `dsj.hatao.render`, the function `dsj hatao`
calls, on the edit list the page sends, writing beside the recording as `dsj
hatao -o` would, with the same `.bleeps.json` log and `.source.txt` sidecar
(#121). It takes the same run lock, so a render and a transcription never
share the machine.

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
    "Render",
    "engine_choices",
    "render_path",
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

from dsj import hatao, runlock, suno
from dsj.asr import ENGINES, EngineUnavailable, get_engine
from dsj.atomic import atomic_write_text
from dsj.filetag import source_sidecar_for
from dsj.parakeet import DEFAULT_MODEL as PARAKEET_MODEL
from dsj.sherpa import DEFAULT_MODEL as SHERPA_MODEL
from dsj.ui import edits
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


def render_path(media: Path) -> Path:
    """Where a render from the page goes: beside its recording, never over anything.

    `<stem>.bleeped<suffix>`, or `.bleeped-2`, `-3` and on, the first whose
    file, `.bleeps.json` log and `.source.txt` sidecar are all free: a second
    render after more review keeps the first, as a terminal run without
    `--overwrite` does.
    """
    n = 1
    while True:
        tag = "bleeped" if n == 1 else f"bleeped-{n}"
        out = media.with_name(f"{media.stem}.{tag}{media.suffix}")
        if not any(p.exists() for p in (out, _log_for(out), source_sidecar_for(out))):
            return out
        n += 1


def _log_for(out: Path) -> Path:
    """The bleep log beside a render: `dsj hatao`'s `<stem>.bleeps.json`."""
    return out.with_name(f"{out.stem}.bleeps.json")


@dataclass
class Render:
    """A bleep render started from the page (#215), and what has become of it."""

    id: int
    transcript_id: int
    recording_id: int
    started_at: str
    out: Path
    # How many stretches it silences, known before it starts.
    spans: int
    # Written by the worker as ffmpeg goes: seconds written, and of how many.
    done_s: float = 0.0
    total_s: float = 0.0
    # Set by the worker when the render is over, and only then.
    outcome: str | None = None
    error: str | None = None
    # What it could not do, though it finished: the tag (#121), words capped (#212).
    notes: list[str] = field(default_factory=list[str])

    def view(self) -> dict[str, Any]:
        """This render as the page reads it."""
        state = self.outcome or ("rendering" if self.total_s > 0 else "starting")
        return {
            "id": self.id,
            "transcript_id": self.transcript_id,
            "recording_id": self.recording_id,
            "started_at": self.started_at,
            "state": state,
            "fraction": min(self.done_s / self.total_s, 1.0) if self.total_s > 0 else 0.0,
            "output": str(self.out),
            "spans": self.spans,
            "error": self.error,
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
        self._renders: dict[int, Render] = {}
        # Each task runs one job, transcription or render, on the one worker thread.
        self._queue: queue.SimpleQueue[Callable[[], None]] = queue.SimpleQueue()
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
            run_arguments = arguments | {"out": out, "status_path": status_path}
            self._put(lambda: self._run(job, run_arguments, held))
        return job

    def _put(self, task: Callable[[], None]) -> None:
        """Queue `task` for the worker, starting the worker the first time. Under _start_lock."""
        self._queue.put(task)
        if self._worker is None:
            self._worker = threading.Thread(target=self._work, name="dsj-ui-jobs", daemon=True)
            self._worker.start()

    def renders(self) -> list[Render]:
        """Every render, the first started first."""
        return [self._renders[k] for k in sorted(self._renders)]

    def render(self, render_id: int) -> Render | None:
        """The render with this id, or None."""
        return self._renders.get(render_id)

    def start_render(self, transcript_id: int, content: tuple[hatao.Entry, ...]) -> Render:
        """Render the page's edit list of a transcript beside its recording, or refuse first.

        The list is the page's own, as it is on screen: a review, or one match
        alone (#84), is a list with just those words muted.

        Raises:
            dsj.ui.edits.NoSuchTranscript: no such transcript.
            dsj.hatao.InvalidDocument: the list is broken, named.
            dsj.hatao.RenderRefused: the list holds a cut or a move, which a render does not make.
            NotStarted: the recording is gone, or nothing in the list is muted.
            dsj.runlock.AlreadyRunning: a transcription or a render holds the machine.
        """
        opened = edits.open_edits(transcript_id)
        doc = hatao.validate(hatao.Document(opened.doc.sources, content))
        media = Path(doc.sources[edits.SOURCE])
        if not media.is_file():
            raise NotStarted(
                f"{media} is not there any more, so it cannot be rendered. Put the file back "
                f"where it was, then render again."
            )
        duration = opened.duration_s if opened.duration_s is not None else float("inf")
        spans = hatao.spans_to_mute(doc, duration_s=duration)
        if not spans:
            # dsj hatao's exit 3: a render that mutes nothing must not pass for a bleeped file.
            raise NotStarted(
                "Nothing in this list is muted, so a render would only copy the recording."
            )
        with Library.open() as library:
            found = library.transcript(transcript_id)
        assert found is not None  # open_edits found it a moment ago
        out = render_path(media)
        with self._start_lock:
            held = runlock.acquire({"pid": os.getpid(), "out": str(out), "media": str(media)})
            render = Render(
                id=len(self._renders) + 1,
                transcript_id=transcript_id,
                recording_id=found.recording_id,
                started_at=datetime.now(UTC).isoformat(timespec="seconds"),
                out=out,
                spans=len(spans),
            )
            self._renders[render.id] = render
            self._put(lambda: self._render(render, doc, media, held, found.json_path))
        return render

    def _render(
        self, render: Render, doc: hatao.Document, media: Path, held: int, transcript: Path
    ) -> None:
        def progress(done: float, total: float) -> None:
            render.total_s = total
            render.done_s = done

        error: str | None = None
        try:
            with self._hold():
                rendered = hatao.render(doc, media, render.out, on_progress=progress)
                capped = rendered.capped
                self._log(render, doc, media, transcript, rendered.spans, capped)
            if rendered.untagged:
                render.notes.append(
                    f"The source tag was not written onto {render.out.name}, so only "
                    f"{source_sidecar_for(render.out).name} names its recording: "
                    f"{rendered.untagged}"
                )
            if capped:
                render.notes.append(
                    f"Capped {len(capped)} muted words whose transcript end ran past "
                    f"{hatao.MAX_WORD_S:g} s or into the next word; `capped` in "
                    f"{_log_for(render.out).name} lists them."
                )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            traceback.print_exception(exc, file=sys.stderr)
        finally:
            os.close(held)
        render.error = error
        render.outcome = "done" if error is None else "failed"

    @staticmethod
    def _log(
        render: Render,
        doc: hatao.Document,
        media: Path,
        transcript: Path,
        spans: list[tuple[float, float]],
        capped: tuple[Any, ...],
    ) -> None:
        """`dsj hatao`'s bleep log beside the render: every muted word, its times, the spans."""
        muted = [
            {"word": e.text.strip(), "start": round(e.source_start, 3),
             "end": round(e.source_end, 3)}
            for e in doc.content
            if isinstance(e, hatao.Item) and e.muted and e.text.strip()
        ]
        log: dict[str, Any] = {
            "media": str(media.resolve()),
            "transcript": str(transcript),
            "output": str(render.out.resolve()),
            "from": "dsj ui",
            "pad_s": hatao.PAD_S,
            "muted": muted,
            "spans": [[a, b] for a, b in spans],
        }
        if capped:
            log["capped"] = [
                {"start": round(c.source_start, 3), "end": round(c.source_end, 3),
                 "muted_to": c.muted_end}
                for c in capped
            ]
        atomic_write_text(_log_for(render.out), json.dumps(log, ensure_ascii=False, indent=1))

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
            self._queue.get()()

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
