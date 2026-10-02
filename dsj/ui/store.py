"""The library: every recording dsj knows about, and every transcript of each (#105).

A transcription writes one JSON file wherever `-o` pointed and keeps no list, so
without this nothing can say what you have transcribed, when, or with which
engine. This is that list: one SQLite file, an index over the transcript JSON
files and nothing more. The files stay the truth for sentences and marks, and
nothing here ever writes to one. Delete the database and every transcript still
opens; adopting the same files again rebuilds the same rows.

A recording is known by its contents, through #120's content id, never by its
path. A path is only where the file was last seen: rename the file and the row
is marked missing, point it at the new name and every transcript under it comes
back, because the transcripts hang off the recording's row and not off a path.

Plain Python and the standard library's sqlite3, so it runs without the `ui`
extra and before any server exists: the routes that serve these rows are #156.

"Mark" means one thing here: one of `dsj dekho`'s screen-change marks, the
`marks` key it writes into a transcript. Transcript annotations, which #67 plans
for v0.5.0, are called annotations, so `mark_count` never has to change meaning.
"""

from __future__ import annotations

__all__ = [
    "LIBRARY_ENV",
    "SCHEMA_VERSION",
    "Adoption",
    "Library",
    "LibraryError",
    "NotATranscript",
    "NotTheSameRecording",
    "Recording",
    "Transcript",
    "library_path",
]

import json
import os
import sqlite3
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self, cast

from dsj import media as media_mod
from dsj.asr import ENGINES
from dsj.identity import content_id

# The database file's path, when set. Tests point it into a temporary directory
# so the suite never reads or writes the owner's library.
LIBRARY_ENV = "DSJ_LIBRARY"

# Kept in SQLite's own `user_version`. Bumped by whoever changes the tables, so
# an older dsj refuses a library a newer one wrote instead of misreading it.
# Version 2 added `recordings.unreadable` (#110); _MIGRATIONS brings a version 1
# library up to it in place.
SCHEMA_VERSION = 2

# Two things differ from #105's first comment, both on purpose:
#
#   * `content_id`, not `fingerprint`: the value is #120's content_id(), and
#     dsj/checkpoint.py already has a fingerprint() that means something else.
#   * `content_id` and `size_bytes` may be NULL, and so may `mark_count`. A
#     transcript whose recording is already gone still gets both rows (#105),
#     and a file that is not there cannot be read for an id. A transcript `dsj
#     dekho` never scanned has no `marks` key, which is not the same document as
#     one it scanned and found nothing in: the reason `diarized` has three
#     values, applied to marks.
#
# IF NOT EXISTS, inside one IMMEDIATE transaction with the version stamp, so two
# processes opening a new library at the same moment both end up with it whole.
_SCHEMA = f"""
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS recordings (
  id            INTEGER PRIMARY KEY,
  path          TEXT NOT NULL,
  size_bytes    INTEGER,
  duration_s    REAL,
  content_id    TEXT UNIQUE,
  audio_codec   TEXT,
  video_codec   TEXT,
  first_seen    TEXT NOT NULL,
  missing       INTEGER NOT NULL DEFAULT 0,
  unreadable    TEXT,
  CHECK ((content_id IS NULL) = (size_bytes IS NULL))
);
CREATE TABLE IF NOT EXISTS transcripts (
  id            INTEGER PRIMARY KEY,
  recording_id  INTEGER NOT NULL REFERENCES recordings(id),
  json_path     TEXT NOT NULL UNIQUE,
  finished_at   TEXT NOT NULL,
  engine        TEXT,
  model         TEXT NOT NULL,
  diarized      INTEGER,
  speaker_count INTEGER,
  mark_count    INTEGER,
  language      TEXT
);
CREATE INDEX IF NOT EXISTS transcripts_by_recording ON transcripts(recording_id);
PRAGMA user_version = {SCHEMA_VERSION};
COMMIT;
"""

# What each older version needs to become the next, keyed by the older one
# (_migrate runs one, with its version stamp, in one transaction).
_MIGRATIONS = {
    # What ffprobe said about a file it could not read, so the library page can
    # show it (#110). NULL for every row written before, which is what a fresh
    # read of those files would mostly say too: version 1 stored no reason.
    1: "ALTER TABLE recordings ADD COLUMN unreadable TEXT",
}

_RECORDING_COLUMNS = (
    "r.id, r.path, r.size_bytes, r.duration_s, r.content_id, r.audio_codec, r.video_codec, "
    "r.first_seen, r.missing, r.unreadable"
)
_TRANSCRIPT_COLUMNS = (
    "id, recording_id, json_path, finished_at, engine, model, diarized, speaker_count, "
    "mark_count, language"
)


class LibraryError(RuntimeError):
    """The library cannot do what was asked. Nothing in it has changed."""


class NotATranscript(LibraryError):
    """A file handed to the library is not a transcript dsj wrote or imported."""


class NotTheSameRecording(LibraryError):
    """The file picked to re-point a recording holds different contents."""


@dataclass(frozen=True)
class Recording:
    """One row of `recordings`: a recording, wherever it was last seen."""

    id: int
    path: Path
    size_bytes: int | None
    duration_s: float | None
    content_id: str | None
    audio_codec: str | None
    video_codec: str | None
    first_seen: str
    missing: bool
    # ffprobe's own words when it could not read the file, else None (#110). A
    # file with no sound at all is readable, and is not this.
    unreadable: str | None = None


@dataclass(frozen=True)
class Transcript:
    """One row of `transcripts`: a JSON file, and what it says about itself."""

    id: int
    recording_id: int
    json_path: Path
    finished_at: str
    engine: str | None
    model: str
    # True when speaker labelling ran, False when it did not, None when the
    # file carries one of `speakers` and `diarization` without the other.
    diarized: bool | None
    speaker_count: int | None
    mark_count: int | None
    language: str | None


@dataclass(frozen=True)
class Adoption:
    """What one adoption scan did: the rows it now covers, and what it refused."""

    transcripts: list[int] = field(default_factory=list[int])
    refused: list[tuple[Path, str]] = field(default_factory=list[tuple[Path, str]])


def library_path() -> Path:
    """Where the library lives: `$DSJ_LIBRARY`, else this platform's data folder.

    On a Mac that is `~/Library/Application Support/dsj/library.db`. Elsewhere
    (the phone, under Termux) it is `$XDG_DATA_HOME/dsj/library.db`, which is
    `~/.local/share/dsj/library.db` when that variable is unset.
    """
    configured = os.environ.get(LIBRARY_ENV)
    if configured:
        return Path(configured)
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "dsj" / "library.db"
    data = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(data) / "dsj" / "library.db"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _read_payload(path: Path) -> dict[str, Any]:
    """The transcript at `path`, checked for the three keys the library reads."""
    try:
        loaded: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NotATranscript(f"{path} could not be read as JSON: {exc}") from exc
    if not isinstance(loaded, dict):
        raise NotATranscript(f"{path} holds JSON, but not an object, so it is not a transcript.")
    payload = cast("dict[str, Any]", loaded)
    for key, kind in (("audio", str), ("model", str), ("sentences", list)):
        if not isinstance(payload.get(key), kind):
            raise NotATranscript(
                f"{path} has no {kind.__name__} `{key}`, which every transcript `dsj suno` "
                f"writes and `dsj parho` imports carries. Hand the library the transcript "
                f"JSON itself, not a status, checkpoint or export file."
            )
    return payload


def _media_of(transcript: Path, audio: str) -> Path:
    """Where the recording a transcript names is, as an absolute path.

    Before #201 `dsj suno` wrote `audio` exactly as it was typed, so a relative
    one is relative to wherever that run was started, which the file does not
    record. Those transcripts are left as they are, and this guess stays for them.
    Counted on 2026-10-02 over the 97 transcripts under this repo's scratch/: 23
    were relative, all 23 found from the folder the runs were started in and
    none from the folder the JSON sits in. So beside the transcript is tried
    first and the current folder second, and the first that exists wins; when
    neither does, the recording is stored missing at the path beside the
    transcript, ready to be re-pointed.
    """
    named = Path(audio).expanduser()
    if named.is_absolute():
        return named.resolve()
    beside = (transcript.parent / named).resolve()
    if beside.exists():
        return beside
    here = (Path.cwd() / named).resolve()
    return here if here.exists() else beside


@dataclass(frozen=True)
class _Described:
    """What reading a recording's file says about it."""

    duration_s: float | None
    audio_codec: str | None
    video_codec: str | None
    unreadable: str | None


def _describe(media: Path) -> _Described:
    """Duration and codecs, each None where ffprobe would not say, and why it would not.

    FFmpegNotFound is not caught: without ffprobe every recording would be
    stored with nothing known about it, and its error already says how to
    install ffmpeg. A file ffprobe cannot read, a damaged one, is a fact about
    that one file, so it is stored with what is known and ffprobe's own words
    (#110). A file with no sound is readable, and is stored as having none.
    """
    unreadable = None
    try:
        stream = media_mod.probe(media)
        duration, audio = stream.duration_s or None, stream.codec_name
    except media_mod.FFmpegNotFound:
        raise
    except media_mod.NoAudioStream:
        duration, audio = None, None
    except media_mod.MediaError as exc:
        duration, audio, unreadable = None, None, str(exc)
    try:
        video = media_mod.video_codec(media)
    except media_mod.FFmpegNotFound:
        raise
    except media_mod.MediaError:
        video = None
    return _Described(duration, audio, video, unreadable)


def _engine_of(payload: dict[str, Any]) -> str | None:
    """The engine the transcript names (#172), or None.

    None for a transcript written before #172 and for one `dsj parho`
    imported, which no engine wrote; also for any value that is not one of
    dsj's engines, which the library would otherwise list as though it were.
    """
    engine = payload.get("engine")
    return engine if isinstance(engine, str) and engine in ENGINES else None


def _counts(payload: dict[str, Any]) -> tuple[int | None, int | None, int | None]:
    """`diarized`, `speaker_count` and `mark_count`, each read as present or absent.

    `speakers` and `diarization` are written together, and only when labelling
    ran (`_with_speakers()` in dsj/suno.py), so both absent means it did not
    run, and one without the other is a file the library cannot vouch for.
    """
    speakers = payload.get("speakers")
    has_speakers = isinstance(speakers, list)
    has_provenance = "diarization" in payload
    diarized = None if has_speakers != has_provenance else int(has_speakers)
    speaker_count = len(cast("list[Any]", speakers)) if has_speakers else None
    marks = payload.get("marks")
    mark_count = len(cast("list[Any]", marks)) if isinstance(marks, list) else None
    return diarized, speaker_count, mark_count


def _migrate(db: sqlite3.Connection, version: int) -> int:
    """Bring a version `version` library up one version, and return the version it is at.

    The version is read again under the write lock, so of two processes opening
    the same old library at once, the second finds the first's work done.
    """
    db.execute("BEGIN IMMEDIATE")
    try:
        now = int(db.execute("PRAGMA user_version").fetchone()[0])
        if now == version:
            db.execute(_MIGRATIONS[version])
            db.execute(f"PRAGMA user_version = {version + 1}")
            now = version + 1
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return now


def _recording(row: tuple[Any, ...]) -> Recording:
    return Recording(
        id=row[0],
        path=Path(row[1]),
        size_bytes=row[2],
        duration_s=row[3],
        content_id=row[4],
        audio_codec=row[5],
        video_codec=row[6],
        first_seen=row[7],
        missing=bool(row[8]),
        unreadable=row[9],
    )


def _transcript(row: tuple[Any, ...]) -> Transcript:
    return Transcript(
        id=row[0],
        recording_id=row[1],
        json_path=Path(row[2]),
        finished_at=row[3],
        engine=row[4],
        model=row[5],
        diarized=None if row[6] is None else bool(row[6]),
        speaker_count=row[7],
        mark_count=row[8],
        language=row[9],
    )


class Library:
    """One open library database. Use it as a context manager, or call close()."""

    def __init__(self, db: sqlite3.Connection, path: Path) -> None:
        """Wrap an open connection; open() is how one is made."""
        self._db = db
        self.path = path

    @classmethod
    def open(cls, path: Path | None = None) -> Self:
        """Open the library at `path` (library_path() if None), creating it on first use.

        Raises:
            LibraryError: if a newer dsj wrote the file, whose tables this one
                would misread.
        """
        path = path or library_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(path)
        try:
            db.execute("PRAGMA foreign_keys = ON")
            version = int(db.execute("PRAGMA user_version").fetchone()[0])
            if version == 0:
                db.executescript(_SCHEMA)
                version = SCHEMA_VERSION
            while version in _MIGRATIONS:
                version = _migrate(db, version)
            if version != SCHEMA_VERSION:
                raise LibraryError(
                    f"{path} is a version {version} library and this dsj reads version "
                    f"{SCHEMA_VERSION}. Upgrade dsj, or point {LIBRARY_ENV} at another file."
                )
        except BaseException:
            db.close()
            raise
        return cls(db, path)

    def close(self) -> None:
        """Close the database. Every write has already been committed."""
        self._db.close()

    def __enter__(self) -> Self:
        """Hand back this library for a `with` block."""
        return self

    def __exit__(self, *_: object) -> None:
        """Close on the way out, however the block ended."""
        self.close()

    # -- reading ------------------------------------------------------------

    def recordings(self) -> list[Recording]:
        """Every recording, the one with the newest transcript first.

        A recording with no transcript yet sorts by when it was first seen.
        """
        rows = self._db.execute(
            f"SELECT {_RECORDING_COLUMNS} FROM recordings r "
            "LEFT JOIN transcripts t ON t.recording_id = r.id "
            "GROUP BY r.id ORDER BY COALESCE(MAX(t.finished_at), r.first_seen) DESC, r.id DESC"
        ).fetchall()
        return [_recording(row) for row in rows]

    def recording(self, recording_id: int) -> Recording | None:
        """The recording with this id, or None if there is none."""
        row = self._db.execute(
            f"SELECT {_RECORDING_COLUMNS} FROM recordings r WHERE r.id = ?", (recording_id,)
        ).fetchone()
        return None if row is None else _recording(row)

    def transcripts(self, recording_id: int) -> list[Transcript]:
        """Every transcript of one recording, newest first."""
        rows = self._db.execute(
            f"SELECT {_TRANSCRIPT_COLUMNS} FROM transcripts WHERE recording_id = ? "
            "ORDER BY finished_at DESC, id DESC",
            (recording_id,),
        ).fetchall()
        return [_transcript(row) for row in rows]

    def transcript(self, transcript_id: int) -> Transcript | None:
        """The transcript with this id, or None if there is none."""
        row = self._db.execute(
            f"SELECT {_TRANSCRIPT_COLUMNS} FROM transcripts WHERE id = ?", (transcript_id,)
        ).fetchone()
        return None if row is None else _transcript(row)

    # -- writing ------------------------------------------------------------

    def add_recording(self, media: Path) -> Recording:
        """The library's row for the recording at `media`, added if it has none.

        Matched on contents: the same file under another name or in another
        folder is the same row, and so is a copy of it.
        """
        with self._db:
            recording_id = self._recording_for(media.expanduser().resolve())
        return self._must_recording(recording_id)

    def adopt(self, paths: Iterable[Path]) -> Adoption:
        """Index transcript JSON files that already exist, changing nothing in them.

        Who hands over the paths (files given to `dsj ui`, a folder, every `dsj
        suno` run) is the owner's call, open in #105; this takes a list so that
        any of them can. A file that is not a transcript is refused and named,
        and the rest are still adopted.

        A transcript already in the library keeps its recording, its finish
        time, and the engine and language a run recorded; only what the file
        says (model, speakers, marks, and its engine where none was recorded)
        is read again, since `dsj dekho` may have added marks since.
        """
        adoption = Adoption()
        for path in paths:
            try:
                adoption.transcripts.append(self._adopt_one(path.expanduser().resolve()))
            except NotATranscript as exc:
                adoption.refused.append((path, str(exc)))
        return adoption

    def record_run(
        self, transcript: Path, *, engine: str, language: str | None = None
    ) -> Transcript:
        """Index the transcript a run just wrote, with what only the run knows.

        The language is not in the JSON, and a transcript written before #172
        carries no `engine`, while the model id cannot stand in for one (#46
        hands sherpa parakeet's id). So the run that knows them says so here;
        an adopted transcript has the engine its file names, or NULL.

        A run writing over a transcript the library already has replaces that
        row's recording, finish time, engine and language: it is a new run.
        """
        if engine not in ENGINES:
            raise ValueError(f"engine must be one of {', '.join(ENGINES)}, not {engine!r}")
        path = transcript.expanduser().resolve()
        payload = _read_payload(path)
        with self._db:
            recording_id = self._recording_for(_media_of(path, payload["audio"]))
            transcript_id = self._existing_transcript(path)
            if transcript_id is None:
                transcript_id = self._insert_transcript(path, payload, recording_id, _now())
            else:
                self._refresh_transcript(transcript_id, payload)
            self._db.execute(
                "UPDATE transcripts SET recording_id = ?, finished_at = ?, engine = ?, "
                "language = ? WHERE id = ?",
                (recording_id, _now(), engine, language, transcript_id),
            )
        found = self.transcript(transcript_id)
        assert found is not None
        return found

    def relink(self, recording_id: int, media: Path) -> Recording:
        """Point a recording at `media`, if `media` holds the same recording.

        Every transcript keeps its row and its recording id, so its speakers and
        marks come back with it. A recording first seen already missing has no
        content id to check against; the file picked is then taken at its word,
        and if the library already knows those contents under another row, the
        two rows become one.

        Nothing is written to any transcript, so this lives in the library only:
        delete the database and adopt the files again, and the recording reads
        missing at the path the JSON names until it is re-pointed again.

        Raises:
            LibraryError: if there is no recording with this id.
            NotTheSameRecording: if `media`'s contents are not this recording's.
                Nothing is changed.
        """
        media = media.expanduser().resolve()
        found = self.recording(recording_id)
        if found is None:
            raise LibraryError(f"the library has no recording with id {recording_id}.")
        picked = content_id(media)
        if found.content_id is not None and found.content_id != picked:
            raise NotTheSameRecording(
                f"{media} is not the recording last seen at {found.path}: its contents "
                f"differ. Pick the file that was moved or renamed, not another take of it."
            )
        with self._db:
            known = self._db.execute(
                "SELECT id FROM recordings WHERE content_id = ? AND id != ?",
                (picked, recording_id),
            ).fetchone()
            if known is not None:
                self._db.execute(
                    "UPDATE transcripts SET recording_id = ? WHERE recording_id = ?",
                    (known[0], recording_id),
                )
                self._db.execute("DELETE FROM recordings WHERE id = ?", (recording_id,))
                recording_id = int(known[0])
            self._fill(recording_id, media, picked)
        return self._must_recording(recording_id)

    def refresh_missing(self) -> list[int]:
        """Mark each recording missing or found by looking at its path. Returns the missing.

        A look, not a read: a recording whose file is there at the size it had
        counts as found, so this costs one stat per recording and never pulls a
        cloud-synced file down to read it.
        """
        missing: list[int] = []
        with self._db:
            rows = self._db.execute("SELECT id, path, size_bytes FROM recordings").fetchall()
            for recording_id, path, size in rows:
                where = Path(path)
                gone = size is None or not where.is_file() or where.stat().st_size != size
                self._db.execute(
                    "UPDATE recordings SET missing = ? WHERE id = ?", (int(gone), recording_id)
                )
                if gone:
                    missing.append(int(recording_id))
        return missing

    # -- the pieces, each run inside a caller's transaction ------------------

    def _must_recording(self, recording_id: int) -> Recording:
        found = self.recording(recording_id)
        assert found is not None
        return found

    def _adopt_one(self, path: Path) -> int:
        payload = _read_payload(path)
        with self._db:
            transcript_id = self._existing_transcript(path)
            if transcript_id is not None:
                self._refresh_transcript(transcript_id, payload)
                return transcript_id
            recording_id = self._recording_for(_media_of(path, payload["audio"]))
            finished_at = datetime.fromtimestamp(path.stat().st_mtime, UTC)
            return self._insert_transcript(
                path, payload, recording_id, finished_at.isoformat(timespec="seconds")
            )

    def _existing_transcript(self, path: Path) -> int | None:
        row = self._db.execute(
            "SELECT id FROM transcripts WHERE json_path = ?", (str(path),)
        ).fetchone()
        return None if row is None else int(row[0])

    def _insert_transcript(
        self, path: Path, payload: dict[str, Any], recording_id: int, finished_at: str
    ) -> int:
        diarized, speaker_count, mark_count = _counts(payload)
        cursor = self._db.execute(
            "INSERT INTO transcripts (recording_id, json_path, finished_at, engine, model, "
            "diarized, speaker_count, mark_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (recording_id, str(path), finished_at, _engine_of(payload), payload["model"],
             diarized, speaker_count, mark_count),
        )
        return int(cast("int", cursor.lastrowid))

    def _refresh_transcript(self, transcript_id: int, payload: dict[str, Any]) -> None:
        diarized, speaker_count, mark_count = _counts(payload)
        # COALESCE: an engine a run recorded stays; the file only fills one in.
        self._db.execute(
            "UPDATE transcripts SET engine = COALESCE(engine, ?), model = ?, diarized = ?, "
            "speaker_count = ?, mark_count = ? WHERE id = ?",
            (_engine_of(payload), payload["model"], diarized, speaker_count, mark_count,
             transcript_id),
        )

    def _recording_for(self, media: Path) -> int:
        """The id of the recording at `media`, adding a row if the library has none."""
        if not media.is_file():
            # Nothing to read, so nothing to match on but the path the
            # transcript names. The newest row last seen there is the best
            # guess, and relink() is how a wrong one gets put right.
            row = self._db.execute(
                "SELECT id FROM recordings WHERE path = ? ORDER BY id DESC", (str(media),)
            ).fetchone()
            if row is not None:
                self._db.execute("UPDATE recordings SET missing = 1 WHERE id = ?", (row[0],))
                return int(row[0])
            cursor = self._db.execute(
                "INSERT INTO recordings (path, first_seen, missing) VALUES (?, ?, 1)",
                (str(media), _now()),
            )
            return int(cast("int", cursor.lastrowid))

        cid = content_id(media)
        # A recording last seen at this path is not here any more when the file
        # there now holds different contents.
        self._db.execute(
            "UPDATE recordings SET missing = 1 "
            "WHERE path = ? AND content_id IS NOT NULL AND content_id != ?",
            (str(media), cid),
        )
        row = self._db.execute(
            "SELECT id, path FROM recordings WHERE content_id = ?", (cid,)
        ).fetchone()
        if row is not None:
            # A copy found while the original is still in place leaves the row
            # pointing at the original.
            if row[1] == str(media) or not Path(row[1]).is_file():
                self._db.execute(
                    "UPDATE recordings SET path = ?, missing = 0 WHERE id = ?",
                    (str(media), row[0]),
                )
            return int(row[0])
        placeholder = self._db.execute(
            "SELECT id FROM recordings WHERE path = ? AND content_id IS NULL ORDER BY id DESC",
            (str(media),),
        ).fetchone()
        if placeholder is not None:
            self._fill(int(placeholder[0]), media, cid)
            return int(placeholder[0])
        cursor = self._db.execute(
            "INSERT INTO recordings (path, first_seen) VALUES (?, ?)", (str(media), _now())
        )
        recording_id = int(cast("int", cursor.lastrowid))
        self._fill(recording_id, media, cid)
        return recording_id

    def _fill(self, recording_id: int, media: Path, cid: str) -> None:
        """Write what reading `media` says into the row, and mark it found."""
        found = _describe(media)
        self._db.execute(
            "UPDATE recordings SET path = ?, size_bytes = ?, duration_s = ?, content_id = ?, "
            "audio_codec = ?, video_codec = ?, unreadable = ?, missing = 0 WHERE id = ?",
            (str(media), media.stat().st_size, found.duration_s, cid, found.audio_codec,
             found.video_codec, found.unreadable, recording_id),
        )
