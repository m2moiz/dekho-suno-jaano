"""The library page's two routes: every recording, and one transcript by id (#156).

The store (#105) is read, never written, except that listing re-checks which
recordings' files are still where they were, so a file moved since the last
look reads as missing rather than as fine.

One SQLite connection per request, opened inside the handler: FastAPI runs a
sync handler on a worker thread, and a sqlite3 connection may only be used on
the thread that opened it. A dependency with `yield` can enter and exit on
different threads, so the library is opened here, not injected.
"""

from __future__ import annotations

__all__ = ["router"]

from fastapi import APIRouter, HTTPException, Response

from dsj.ui.schemas import RecordingRow, TranscriptRow
from dsj.ui.store import Library

router = APIRouter(prefix="/api")


@router.get("/recordings")
def recordings() -> list[RecordingRow]:
    """Every recording, the one with the newest transcript first, each with its transcripts."""
    with Library.open() as library:
        library.refresh_missing()
        return [
            RecordingRow(
                id=rec.id,
                path=str(rec.path),
                missing=rec.missing,
                duration_s=rec.duration_s,
                video_codec=rec.video_codec,
                first_seen=rec.first_seen,
                transcripts=[
                    TranscriptRow(
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
            for rec in library.recordings()
        ]


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
