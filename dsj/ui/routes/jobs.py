"""Starting a transcription (#113) or a bleep render (#215) from the page, and watching it run.

The work is in dsj/ui/jobs.py; this file only turns requests into its calls.
The registry is `app.state.jobs`, made by create_app(), so each server has its
own and a test's app never sees another's jobs.
"""

from __future__ import annotations

__all__ = ["router"]

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from dsj.ui.jobs import Jobs, engine_choices
from dsj.ui.routes.marks import entries
from dsj.ui.schemas import EditsUpdate, Engine, Job, RenderJob, TranscribeRequest

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


@router.post("/transcripts/{transcript_id}/render", status_code=202)
def render(transcript_id: str, update: EditsUpdate, request: Request) -> RenderJob:
    """Render the page's edit list beside the recording with dsj.hatao.render, once queued.

    Refused before anything is written when the list mutes nothing, cannot be
    rendered, or the machine is busy with another run.
    """
    if not (transcript_id.isascii() and transcript_id.isdigit()):
        raise HTTPException(404, f"There is no transcript {transcript_id!r} in the library.")
    started = _jobs(request).start_render(int(transcript_id), entries(update))
    return RenderJob.model_validate(started.view())


@router.get("/renders")
def renders(request: Request) -> list[RenderJob]:
    """Every render this server has started, the first first."""
    return [RenderJob.model_validate(r.view()) for r in _jobs(request).renders()]


@router.get(
    "/renders/{render_id}/media",
    response_class=FileResponse,
    responses={200: {"content": {"audio/*": {}, "video/*": {}}}, 206: {"description": "a range"}},
)
def render_media(render_id: str, request: Request) -> FileResponse:
    """A finished render's file, so the page can play it beside the original (#215).

    By the render's id, never a path (#112 rule 5), and only once it is done.
    """
    found = None
    if render_id.isascii() and render_id.isdigit():
        found = _jobs(request).render(int(render_id))
    if found is None or found.outcome != "done" or not found.out.is_file():
        raise HTTPException(404, f"There is no finished render {render_id!r}.")
    return FileResponse(found.out)
