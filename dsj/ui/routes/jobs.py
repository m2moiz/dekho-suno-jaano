"""Starting a transcription from the page, and watching it run (#113).

The work is in dsj/ui/jobs.py; this file only turns requests into its calls.
The registry is `app.state.jobs`, made by create_app(), so each server has its
own and a test's app never sees another's jobs.
"""

from __future__ import annotations

__all__ = ["router"]

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request

from dsj.ui.jobs import Jobs, engine_choices
from dsj.ui.schemas import Engine, Job, TranscribeRequest

router = APIRouter(prefix="/api")


def _jobs(request: Request) -> Jobs:
    jobs: Jobs = request.app.state.jobs
    return jobs


@router.get("/engines")
def engines() -> list[Engine]:
    """Every engine, each with the reason it cannot run here, or none.

    Asked again on every call rather than once at startup: installing an extra
    and reopening the picker should show it, with no restart.
    """
    return [Engine.model_validate(asdict(choice)) for choice in engine_choices()]


@router.get("/jobs")
def jobs(request: Request) -> list[Job]:
    """Every transcription this server has started, the first first."""
    return [Job.model_validate(job.view()) for job in _jobs(request).all()]


@router.post("/recordings/{recording_id}/transcribe", status_code=202)
def transcribe(recording_id: str, settings: TranscribeRequest, request: Request) -> Job:
    """Start transcribing one recording of the library; answered once the run is queued.

    The id is checked as text, as the transcript route checks it, so anything
    but a plain number is the same 404 as an id the library never had.
    """
    started = None
    if recording_id.isascii() and recording_id.isdigit():
        started = _jobs(request).start(int(recording_id), settings)
    if started is None:
        raise HTTPException(404, f"There is no recording {recording_id!r} in the library.")
    return Job.model_validate(started.view())
