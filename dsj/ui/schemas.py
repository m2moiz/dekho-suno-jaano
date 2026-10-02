"""The wire format between `dsj ui` and its page: the only place it is written down (#57 section 6).

#155 generates the page's TypeScript types from these models, so a field
renamed here and not there is a type error, not a 404. Plain pydantic, which
dsj already depends on, so this imports without the `ui` extra.

Three things the library page must keep apart (#156), and so these models do:

  * `diarized` has three values. False is "labelling never ran", which is not
    "one speaker": `speakers` is written only when labelling ran. None is a file
    that carries one of `speakers` and `diarization` without the other.
  * `engine` is None for a transcript the library adopted rather than saw being
    made. The model id does not say which engine ran it while #46 hands sherpa
    parakeet's id, so None is shown as "unknown", never guessed.
  * `missing` keeps a recording whose file is gone in the list, with the path
    it was last seen at.
"""

from __future__ import annotations

__all__ = ["RecordingRow", "TranscriptRow"]

from pydantic import BaseModel


class TranscriptRow(BaseModel):
    """One transcript of a recording: what the library knows without opening the file."""

    id: int
    # When it finished, UTC ISO 8601. An adopted file's is its modification time.
    finished_at: str
    # parakeet, whisper or sherpa; None when the library adopted the file.
    engine: str | None
    model: str
    # True: labelling ran. False: it did not. None: the file cannot say.
    diarized: bool | None
    speaker_count: int | None
    # `dsj dekho`'s screen-change marks. None: dekho never scanned this one.
    mark_count: int | None
    language: str | None


class RecordingRow(BaseModel):
    """One recording, wherever it was last seen, with every transcript of it, newest first."""

    id: int
    # Where the file was last seen. Shown, never accepted back: no route takes a path (#112).
    path: str
    missing: bool
    duration_s: float | None
    # None when there is no picture, or when the file could not be read for one.
    video_codec: str | None
    first_seen: str
    transcripts: list[TranscriptRow]
