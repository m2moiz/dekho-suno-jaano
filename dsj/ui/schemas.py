"""What the `dsj ui` server sends and accepts: the one written description of it (#155).

`just api` turns these models, through FastAPI's OpenAPI description, into
`ui/src/api/schema.d.ts`, and the page's client is typed from that file. So a
field renamed here and not in the page is a `tsc` error, not a blank column at
runtime, and `just check` fails while the generated file is out of date.

Plain pydantic, no fastapi: the store and anything else under `dsj.ui` must
import without the `ui` extra.

The two models mirror the store's rows (`dsj/ui/store.py`, `Recording` and
`Transcript`) minus the file paths of transcripts: the page asks for a
transcript by id and never handles a path to one (#156, #112).
"""

from __future__ import annotations

__all__ = ["Recording", "Transcript"]

from pydantic import BaseModel


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
