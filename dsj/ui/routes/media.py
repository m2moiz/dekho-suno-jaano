"""A recording's file and the shape of its sound, both by the library's id for it.

The file is served so the player can seek (#59); the shape, so the page can
draw the sound without decoding it (#61).

No range code lives here. Starlette's FileResponse answers `Range` with 206 and
a correct `Content-Range` itself, single and multipart (#57 first comment,
section 9, run against a 355,955,725-byte recording). Seeking to 1:45:00 is a
request for the bytes there, not for the whole file before them.

The browser names a recording by its library id and never by a path (#112 rule
5). A path from the page would let any tab that guessed the port and the token
read any file on this machine; an id can only reach a file the library already
holds. The routes sit under /api, so the server's Host and token checks run
before they do.
"""

from __future__ import annotations

__all__ = ["MEDIA_TYPES", "router", "waveform_cache"]

import mimetypes
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response

from dsj import media as media_mod
from dsj.ui.store import Library, Recording, library_path

router = APIRouter(prefix="/api")

# Where Python's guess, read from this Mac's own mime.types, is the wrong
# type. `.m4a` guesses `audio/mp4a-latm`, the type of a bare LATM stream, not of
# an MP4 file; the container's registered type is `audio/mp4` (RFC 4337).
# Chromium and Playwright's WebKit played a 10 s AAC .m4a under either type
# (2026-10-02), so this is correctness, not a fix for an observed failure; real
# Safari was not checked.
MEDIA_TYPES = {".m4a": "audio/mp4"}


def _media_type(path: Path) -> str | None:
    return MEDIA_TYPES.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0]


def _found(recording_id: str) -> Recording:
    """The recording, with its file where the library last saw it, or a 404 saying why.

    The id is taken as text and checked here, as the transcript route does, so
    `..`, `-1` or anything but a plain number is the same 404 as an id the
    library never had, and never a 422 echoing the input.
    """
    if not (recording_id.isascii() and recording_id.isdigit()):
        raise HTTPException(404, f"There is no recording {recording_id!r} in the library.")
    with Library.open() as library:
        found = library.recording(int(recording_id))
    if found is None:
        raise HTTPException(404, f"There is no recording {recording_id} in the library.")
    path = found.path
    # The same look the library list takes (Library.refresh_missing): the file
    # is there at the size the library knows. A different file now sitting at
    # that path is not this recording, and playing it under these words would
    # put every click on the wrong sound.
    if found.size_bytes is None or not path.is_file() or path.stat().st_size != found.size_bytes:
        raise HTTPException(
            404,
            f"Recording {recording_id} was last seen at {path}, and it is not there "
            f"now. Its transcripts still open; the sound needs the file back where it was.",
        )
    return found


@router.get(
    "/recording/{recording_id}/media",
    response_class=FileResponse,
    responses={200: {"content": {"audio/*": {}, "video/*": {}}}, 206: {"description": "a range"}},
)
def media(recording_id: str) -> FileResponse:
    """The recording's file, whole or by the byte range the request asks for."""
    path = _found(recording_id).path
    return FileResponse(path, media_type=_media_type(path))


# HEAD too, which is how a player learns the size and that ranges are accepted
# before it asks for any. Kept out of the API description: the same operation
# under two methods is one entry in the page's types, not two.
router.add_api_route(
    "/recording/{recording_id}/media", media, methods=["HEAD"], include_in_schema=False
)


def waveform_cache(content_id: str) -> Path:
    """Where a recording's envelope is kept: beside the library, by content id (#120).

    Keyed by contents, so a recording moved or renamed, or a copy of it, finds
    the same file, and a different recording at the same path never does. The
    rate is in the name, so changing ENVELOPE_RATE can never read an old file
    at the wrong scale.
    """
    return library_path().parent / "waveforms" / f"{content_id}.{media_mod.ENVELOPE_RATE}hz.i8"


@router.get(
    "/recording/{recording_id}/waveform",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}}},
)
def waveform(recording_id: str) -> Response:
    """The shape of the recording's sound, for the page to draw without decoding it (#61).

    Pairs of signed bytes, min then max, ENVELOPE_RATE buckets a second
    (dsj.media.envelope). Computed once per recording and kept on disk; every
    later request reads the file.
    """
    found = _found(recording_id)
    # _found refuses a recording with no size, and the library stores a size
    # exactly when it stores a content id (its CHECK on the recordings table).
    assert found.content_id is not None
    cache = waveform_cache(found.content_id)
    try:
        data = cache.read_bytes()
    except FileNotFoundError:
        data = media_mod.envelope(found.path)
        cache.parent.mkdir(parents=True, exist_ok=True)
        # Written beside the target and renamed into place, so a reader never
        # sees half an envelope; the pid keeps two writers' temp files apart.
        tmp = cache.with_name(f".{cache.name}.{os.getpid()}.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, cache)  # noqa: PTH105
    return Response(content=data, media_type="application/octet-stream")
