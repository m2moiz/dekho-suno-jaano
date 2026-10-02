"""What the `dsj ui` server sends and accepts: the one written description of it (#155).

`just api` turns these models, through FastAPI's OpenAPI description, into
`ui/src/api/schema.d.ts`, and the page's client is typed from that file. So a
field renamed here and not in the page is a `tsc` error, not a blank column at
runtime, and `just check` fails while the generated file is out of date.

Plain pydantic, no fastapi: the store and anything else under `dsj.ui` must
import without the `ui` extra.

The two models mirror the store's rows (`dsj/ui/store.py`, `Recording` and
`Transcript`) minus the file paths of transcripts: the page asks for a
transcript by id and never handles a path to one (#156, #112). The rest
describe starting a transcription from the page and watching it (#113).
"""

from __future__ import annotations

__all__ = [
    "Engine",
    "EngineName",
    "Job",
    "JobState",
    "Recording",
    "TranscribeRequest",
    "Transcript",
]

from typing import Literal

from pydantic import BaseModel

# dsj.asr.ENGINES, spelled out because a type cannot be built from a tuple;
# tests/test_jobs.py holds the two equal.
type EngineName = Literal["parakeet", "whisper", "sherpa"]

# What a run's status file says (dsj/suno.py, `report(` and the two documents
# transcribe() ends on), plus the page's own `starting` and `saving`
# (dsj/ui/jobs.py, Job.view).
type JobState = Literal[
    "starting", "extracting", "running", "retrying", "diarizing", "saving", "done", "failed"
]


class Transcript(BaseModel):
    """One transcript of a recording, as the library page lists it."""

    id: int
    finished_at: str
    # None for a transcript adopted from before the library: the model id does
    # not say which engine ran it (#156).
    engine: str | None
    model: str
    # True when speaker labelling ran, False when it did not, None when unknown.
    diarized: bool | None
    speaker_count: int | None
    mark_count: int | None
    language: str | None


class Recording(BaseModel):
    """One recording, wherever it was last seen, with every transcript of it."""

    id: int
    path: str
    size_bytes: int | None
    duration_s: float | None
    content_id: str | None
    audio_codec: str | None
    video_codec: str | None
    first_seen: str
    missing: bool
    transcripts: list[Transcript]


class Engine(BaseModel):
    """One engine the picker offers, and whether it can run on this machine."""

    name: EngineName
    # The sentence the engine's own available() wrote when it cannot run, else None.
    reason: str | None
    default_model: str


class TranscribeRequest(BaseModel):
    """What the page sends to start a transcription: the flags of `dsj suno`, as values."""

    engine: EngineName = "parakeet"
    # Empty or absent means the engine's own default.
    model: str | None = None
    # whisper's three; parakeet refuses language and prompt, as `dsj suno` does.
    language: str | None = None
    prompt: str | None = None
    roman_urdu: bool = False
    # "Label speakers", on unless switched off: `--no-diarize` inverted.
    diarize: bool = True
    require_diarize: bool = False
    # "Start over": `--no-resume`.
    start_over: bool = False


class Job(BaseModel):
    """A transcription started from the page, as its last status frame and its outcome say."""

    id: int
    recording_id: int
    engine: EngineName
    model: str
    language: str | None
    # False for whisper unanchored: one frame at 0%, then nothing until done.
    reports_progress: bool
    started_at: str
    state: JobState
    fraction: float
    audio_done_s: float
    audio_total_s: float
    elapsed_s: float
    speed: float
    eta_s: float | None
    # Seconds ffmpeg's position has stood still, while it has (dsj/suno.py STALL_S).
    stalled_s: float | None
    error: str | None
    # The library's row for the finished transcript.
    transcript_id: int | None
    # Warnings the run logged: what it could not do, though it finished.
    notes: list[str]
