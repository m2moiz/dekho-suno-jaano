"""Marks on a recording (#67): make one, list them, change one, take one away, export them.

A mark is a stretch of the recording in seconds with a kind and a note, kept
in the library on the recording (dsj/ui/store.py Highlight), so every
transcript of the recording shows the same marks and a re-run with the same
words keeps them. The export is one Markdown list with timestamps, the format
the README names.
"""

from __future__ import annotations

__all__ = ["router"]

from fastapi import APIRouter, HTTPException, Response

from dsj.ui import store as store_mod
from dsj.ui.schemas import Highlight, HighlightNew, HighlightUpdate
from dsj.ui.store import Library

router = APIRouter(prefix="/api")


def _wire(found: store_mod.Highlight) -> Highlight:
    return Highlight.model_validate(vars(found))


def _number(given: str, what: str) -> int:
    if not (given.isascii() and given.isdigit()):
        raise HTTPException(404, f"There is no {what} {given!r} in the library.")
    return int(given)


def _clock(seconds: float) -> str:
    whole = int(seconds)
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


@router.get("/recordings/{recording_id}/highlights")
def list_highlights(recording_id: str) -> list[Highlight]:
    """Every mark on the recording, in the order of the recording."""
    rid = _number(recording_id, "recording")
    with Library.open() as library:
        if library.recording(rid) is None:
            raise HTTPException(404, f"There is no recording {rid} in the library.")
        return [_wire(h) for h in library.highlights(rid)]


@router.post("/recordings/{recording_id}/highlights", status_code=201)
def make_highlight(recording_id: str, mark: HighlightNew) -> Highlight:
    """Make a mark on the recording."""
    rid = _number(recording_id, "recording")
    with Library.open() as library:
        if library.recording(rid) is None:
            raise HTTPException(404, f"There is no recording {rid} in the library.")
        return _wire(
            library.add_highlight(rid, mark.start_s, mark.end_s, mark.kind, mark.note, mark.text)
        )


@router.patch("/highlights/{highlight_id}")
def change_highlight(highlight_id: str, update: HighlightUpdate) -> Highlight:
    """Change a mark's kind or note."""
    hid = _number(highlight_id, "mark")
    with Library.open() as library:
        changed = library.set_highlight(hid, kind=update.kind, note=update.note)
    if changed is None:
        raise HTTPException(404, f"There is no mark {hid}.")
    return _wire(changed)


@router.delete("/highlights/{highlight_id}", status_code=204, response_class=Response)
def remove_highlight(highlight_id: str) -> Response:
    """Take a mark away."""
    hid = _number(highlight_id, "mark")
    with Library.open() as library:
        gone = library.remove_highlight(hid)
    if not gone:
        raise HTTPException(404, f"There is no mark {hid}.")
    return Response(status_code=204)


@router.get(
    "/recordings/{recording_id}/highlights.md",
    response_class=Response,
    responses={200: {"content": {"text/markdown": {}}}},
)
def export_highlights(recording_id: str) -> Response:
    """The marks as one Markdown list with timestamps: the one export format (README, Likho)."""
    rid = _number(recording_id, "recording")
    with Library.open() as library:
        recording = library.recording(rid)
        if recording is None:
            raise HTTPException(404, f"There is no recording {rid} in the library.")
        marks = library.highlights(rid)
    title = recording.title or recording.path.stem
    lines = [f"# Marks: {title}", ""]
    for mark in marks:
        words = f": {mark.text}" if mark.text else ""
        lines.append(f"- **{_clock(mark.start_s)}** {mark.kind}{words}")
        if mark.note:
            lines.append(f"  {mark.note}")
    text = "\n".join(lines) + "\n"
    return Response(
        content=text,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="marks-{rid}.md"'},
    )
