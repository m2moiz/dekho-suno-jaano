"""The library page's routes: every recording, one transcript by id, and adding a recording.

Listing and reading are #156; adding a recording and re-pointing a moved one
are #110. The store (#105) is read, and written only by those two, and by the
listing re-checking which recordings' files are still where they were, so a
file moved since the last look reads as missing rather than as fine.

No route takes a path (#112 rule 5). A recording comes in through the Mac's
own file dialog, which the server opens itself (dsj/ui/pick.py): a page is
never told where a file is, and a path from a page is the hole rule 5 closes.

One SQLite connection per request, opened inside the handler: FastAPI runs a
sync handler on a worker thread, and a sqlite3 connection may only be used on
the thread that opened it. A dependency with `yield` can enter and exit on
different threads, so the library is opened here, not injected.
"""

from __future__ import annotations

__all__ = ["router"]

from fastapi import APIRouter, HTTPException, Response

from dsj.ui import pick
from dsj.ui import store as store_mod
from dsj.ui.schemas import Recording, Transcript
from dsj.ui.store import Library

router = APIRouter(prefix="/api")


def _row(library: Library, rec: store_mod.Recording) -> Recording:
    """One recording as the page reads it, with every transcript of it."""
    return Recording(
        id=rec.id,
        path=str(rec.path),
        size_bytes=rec.size_bytes,
        duration_s=rec.duration_s,
        content_id=rec.content_id,
        audio_codec=rec.audio_codec,
        video_codec=rec.video_codec,
        first_seen=rec.first_seen,
        missing=rec.missing,
        unreadable=rec.unreadable,
        transcripts=[
            Transcript(
                id=t.id,
                finished_at=t.finished_at,
                engine=t.engine,
                model=t.model,
                diarized=t.diarized,
                speaker_count=t.speaker_count,
                mark_count=t.mark_count,
                language=t.language,
            )
            for t in library.transcripts(rec.id)
        ],
    )


@router.get("/recordings")
def recordings() -> list[Recording]:
    """Every recording, the one with the newest transcript first, each with its transcripts."""
    with Library.open() as library:
        library.refresh_missing()
        return [_row(library, rec) for rec in library.recordings()]


@router.post("/recordings/import")
def import_recording() -> Recording | None:
    """Ask for a recording in the Mac's file dialog and add it to the library, copying nothing.

    The library keeps where the file is and reads it there (#110). The same
    contents picked again, from anywhere, are the row the library already
    has. A file ffprobe cannot read is added all the same, with what ffprobe
    said, so the page can show it. None when the dialog was cancelled.
    """
    picked = pick.choose_file("Add a recording to dsj")
    if picked is None:
        return None
    with Library.open() as library:
        return _row(library, library.add_recording(picked))


@router.post("/recordings/{recording_id}/relink")
def relink(recording_id: str) -> Recording | None:
    """Ask where a moved recording is now, and point its row there if the contents match.

    Every transcript stays on the row, so it opens and plays again (#105's
    relink). A file with other contents is refused and nothing changes. None
    when the dialog was cancelled.
    """
    if not (recording_id.isascii() and recording_id.isdigit()):
        raise HTTPException(404, f"There is no recording {recording_id!r} in the library.")
    with Library.open() as library:
        found = library.recording(int(recording_id))
    if found is None:
        raise HTTPException(404, f"There is no recording {recording_id} in the library.")
    picked = pick.choose_file(f"Where is {found.path.name} now?")
    if picked is None:
        return None
    with Library.open() as library:
        return _row(library, library.relink(found.id, picked))


@router.get(
    "/transcripts/{transcript_id}",
    response_class=Response,
    responses={200: {"content": {"application/json": {}}}},
)
def transcript(transcript_id: str) -> Response:
    """One transcript's JSON, byte for byte as the file holds it.

    The id is taken as text and checked here rather than typed `int`, so that
    anything but a plain number (`..`, `-1`, `1.0`) is the same 404 as an id the
    library has never had, and never a 422 that echoes the input back.
    """
    if not (transcript_id.isascii() and transcript_id.isdigit()):
        raise HTTPException(404, f"There is no transcript {transcript_id!r} in the library.")
    with Library.open() as library:
        found = library.transcript(int(transcript_id))
    if found is None:
        raise HTTPException(404, f"There is no transcript {transcript_id} in the library.")
    try:
        content = found.json_path.read_bytes()
    except FileNotFoundError:
        raise HTTPException(
            404,
            f"Transcript {transcript_id} was last seen at {found.json_path}, and that file "
            f"is gone. The library is only an index; the JSON file is the transcript.",
        ) from None
    return Response(content=content, media_type="application/json")
