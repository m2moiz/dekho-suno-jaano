"""The library store (#105), against real files, real ffprobe and a real SQLite file.

Nothing is stubbed. The store's promises are about files on disk: a transcript
it adopts keeps every byte, a recording renamed and re-pointed keeps its
transcripts, and deleting the database loses nothing but the index. A stub of
the disk would assert none of that.

Every recording here is a few seconds of synthesized sine or test pattern, made
by ffmpeg at test time; no binary and no real recording is committed.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from dsj.cli import main
from dsj.identity import content_id
from dsj.ui import store
from dsj.ui.store import Library, LibraryError, NotTheSameRecording

# When the "older" transcripts were written: well before any library existed.
LONG_AGO = datetime(2026, 9, 1, 8, 30, tzinfo=UTC)


@pytest.fixture(autouse=True)
def private_library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point every test at its own library, so none can touch the owner's."""
    path = tmp_path / "library" / "library.db"
    monkeypatch.setenv(store.LIBRARY_ENV, str(path))
    return path


@pytest.fixture
def library() -> Iterator[Library]:
    with Library.open() as opened:
        yield opened


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def _wav(path: Path, hz: int = 440) -> Path:
    """Two seconds of tone; a different `hz` is a different recording."""
    _ffmpeg("-f", "lavfi", "-i", f"sine=frequency={hz}:duration=2", str(path))
    return path


def _screen_recording(path: Path) -> Path:
    """Two seconds of moving test pattern with sound: H.264 and AAC."""
    _ffmpeg(
        "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=10:duration=2",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path),
    )
    return path


def _transcript(path: Path, audio: Path | str, **extra: Any) -> Path:
    """A transcript as `dsj suno` writes one, dated LONG_AGO."""
    payload: dict[str, Any] = {
        "audio": str(audio),
        "model": "mlx-community/parakeet-tdt-0.6b-v3",
        "text": " Hello.",
        "unclear": [],
        "sentences": [{"start": 0.0, "end": 1.0, "text": " Hello.", "tokens": []}],
    }
    path.write_text(json.dumps(payload | extra))
    os.utime(path, (LONG_AGO.timestamp(), LONG_AGO.timestamp()))
    return path


def _rows(db: Path) -> dict[str, list[tuple[Any, ...]]]:
    """Every row of both tables, as SQLite holds them."""
    with sqlite3.connect(db) as con:
        return {
            table: con.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
            for table in ("recordings", "transcripts")
        }


def test_first_open_creates_one_file_where_dsj_library_points(private_library: Path) -> None:
    assert not private_library.parent.exists()
    with Library.open() as opened:
        assert opened.path == private_library
    assert sorted(p.name for p in private_library.parent.iterdir()) == ["library.db"]
    assert _rows(private_library) == {"recordings": [], "transcripts": []}


def test_the_mac_library_lives_in_application_support(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(store.LIBRARY_ENV)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(store.sys, "platform", "darwin")
    expected = tmp_path / "Library" / "Application Support" / "dsj" / "library.db"
    assert store.library_path() == expected


def test_an_older_transcript_is_adopted_with_zero_bytes_changed(
    tmp_path: Path, library: Library
) -> None:
    media = _wav(tmp_path / "call.wav")
    path = _transcript(tmp_path / "call.json", media)
    before = (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)

    adoption = library.adopt([path])

    assert (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns) == before
    assert adoption.refused == []
    [transcript_id] = adoption.transcripts
    transcript = library.transcript(transcript_id)
    assert transcript is not None
    assert transcript.json_path == path
    assert transcript.finished_at == "2026-09-01T08:30:00+00:00"
    assert transcript.model == "mlx-community/parakeet-tdt-0.6b-v3"
    # Never guessed from the model id (#46): an adopted transcript's engine is unknown.
    assert transcript.engine is None
    assert transcript.language is None
    recording = library.recording(transcript.recording_id)
    assert recording is not None
    assert recording.path == media
    assert recording.size_bytes == media.stat().st_size
    assert recording.content_id == content_id(media)
    assert recording.duration_s == pytest.approx(2.0, abs=0.05)
    assert recording.audio_codec == "pcm_s16le"
    assert recording.video_codec is None
    assert recording.first_seen
    assert not recording.missing


def test_a_screen_recording_keeps_its_video_codec(tmp_path: Path, library: Library) -> None:
    media = _screen_recording(tmp_path / "screen.mp4")
    recording = library.add_recording(media)
    assert (recording.audio_codec, recording.video_codec) == ("aac", "h264")


@pytest.mark.parametrize(
    ("extra", "diarized", "speaker_count"),
    [
        ({}, False, None),
        ({"speakers": ["SPEAKER_00"], "diarization": "senko 0.1.0"}, True, 1),
        ({"speakers": ["SPEAKER_00", "SPEAKER_01"], "diarization": "senko 0.1.0"}, True, 2),
        ({"speakers": ["SPEAKER_00"]}, None, 1),
    ],
    ids=["labelling never ran", "one speaker", "two speakers", "legend without provenance"],
)
def test_speakers_not_labelled_is_not_one_speaker(
    tmp_path: Path,
    library: Library,
    extra: dict[str, Any],
    diarized: bool | None,
    speaker_count: int | None,
) -> None:
    path = _transcript(tmp_path / "t.json", _wav(tmp_path / "a.wav"), **extra)
    [transcript_id] = library.adopt([path]).transcripts
    transcript = library.transcript(transcript_id)
    assert transcript is not None
    assert (transcript.diarized, transcript.speaker_count) == (diarized, speaker_count)


@pytest.mark.parametrize(
    ("extra", "mark_count"),
    [({}, None), ({"marks": [], "marks_meta": {}}, 0), ({"marks": [{"t": 1.0}] * 3}, 3)],
    ids=["dekho never ran", "dekho found nothing", "three marks"],
)
def test_mark_count_counts_dekho_marks_and_only_when_dekho_ran(
    tmp_path: Path, library: Library, extra: dict[str, Any], mark_count: int | None
) -> None:
    path = _transcript(tmp_path / "t.json", _wav(tmp_path / "a.wav"), **extra)
    [transcript_id] = library.adopt([path]).transcripts
    transcript = library.transcript(transcript_id)
    assert transcript is not None
    assert transcript.mark_count == mark_count


def test_a_transcript_whose_recording_is_gone_still_gets_both_rows(
    tmp_path: Path, library: Library
) -> None:
    gone = tmp_path / "deleted.mov"
    [transcript_id] = library.adopt([_transcript(tmp_path / "t.json", gone)]).transcripts
    transcript = library.transcript(transcript_id)
    assert transcript is not None
    recording = library.recording(transcript.recording_id)
    assert recording is not None
    assert recording.missing
    assert recording.path == gone
    assert (recording.content_id, recording.size_bytes) == (None, None)


def test_renaming_then_relinking_keeps_transcripts_and_marks(
    tmp_path: Path, library: Library
) -> None:
    media = _wav(tmp_path / "standup.wav")
    first = _transcript(tmp_path / "standup.json", media)
    marked = _transcript(
        tmp_path / "standup.marked.json",
        media,
        speakers=["SPEAKER_00", "SPEAKER_01"],
        diarization="senko 0.1.0",
        marks=[{"t": 0.5, "score": 9, "look": 1.0}],
    )
    ids = library.adopt([first, marked]).transcripts
    before = [library.transcript(i) for i in ids]
    [recording] = library.recordings()

    renamed = media.rename(tmp_path / "standup, renamed.wav")
    assert library.refresh_missing() == [recording.id]
    assert library.recordings()[0].missing

    relinked = library.relink(recording.id, renamed)

    assert relinked.id == recording.id
    assert relinked.path == renamed
    assert not relinked.missing
    assert relinked.content_id == recording.content_id
    assert [library.transcript(i) for i in ids] == before
    assert {t.id for t in library.transcripts(recording.id)} == set(ids)
    assert library.refresh_missing() == []


def test_relinking_to_another_recording_is_refused_and_changes_nothing(
    tmp_path: Path, library: Library, private_library: Path
) -> None:
    media = _wav(tmp_path / "one.wav", hz=440)
    library.adopt([_transcript(tmp_path / "one.json", media)])
    [recording] = library.recordings()
    media.unlink()
    library.refresh_missing()
    before = _rows(private_library)

    with pytest.raises(NotTheSameRecording, match="its contents differ"):
        library.relink(recording.id, _wav(tmp_path / "other.wav", hz=880))

    assert _rows(private_library) == before


def test_relinking_an_unknown_recording_says_so(tmp_path: Path, library: Library) -> None:
    with pytest.raises(LibraryError, match="no recording with id 99"):
        library.relink(99, _wav(tmp_path / "a.wav"))


def test_a_recording_first_seen_missing_becomes_the_one_it_turns_out_to_be(
    tmp_path: Path, library: Library
) -> None:
    media = _wav(tmp_path / "talk.wav")
    [known] = library.adopt([_transcript(tmp_path / "known.json", media)]).transcripts
    [stray] = library.adopt(
        [_transcript(tmp_path / "stray.json", tmp_path / "talk, old name.wav")]
    ).transcripts
    stray_transcript = library.transcript(stray)
    assert stray_transcript is not None
    placeholder = stray_transcript.recording_id

    merged = library.relink(placeholder, media)

    known_transcript = library.transcript(known)
    assert known_transcript is not None
    assert merged.id == known_transcript.recording_id != placeholder
    assert library.recording(placeholder) is None
    assert {t.id for t in library.transcripts(merged.id)} == {known, stray}
    assert len(library.recordings()) == 1


def test_deleting_the_library_loses_the_index_only(
    tmp_path: Path, private_library: Path
) -> None:
    video = _screen_recording(tmp_path / "screen.mp4")
    audio = _wav(tmp_path / "voice.wav")
    paths = [
        _transcript(tmp_path / "screen.json", video, marks=[{"t": 1.0}]),
        _transcript(tmp_path / "voice.json", audio),
        _transcript(tmp_path / "lost.json", tmp_path / "lost.wav"),
    ]
    with Library.open() as first:
        first.adopt(paths)
    built = _rows(private_library)

    private_library.unlink()
    with Library.open() as second:
        second.adopt(paths)
    rebuilt = _rows(private_library)

    # first_seen is when this library first saw the recording, so it is the one
    # column a rebuild cannot reproduce. Column 7 of recordings.
    def without_first_seen(rows: dict[str, list[tuple[Any, ...]]]) -> Any:
        return [r[:7] + r[8:] for r in rows["recordings"]], rows["transcripts"]

    assert without_first_seen(rebuilt) == without_first_seen(built)
    # And the transcript is still a transcript, to the tool that reads it next.
    assert main(["dekho", str(video), "-t", str(paths[0]), "-o", str(tmp_path / "m.json")]) == 0


def test_a_run_started_from_the_app_fills_every_column(tmp_path: Path, library: Library) -> None:
    media = _screen_recording(tmp_path / "screen.mp4")
    path = _transcript(
        tmp_path / "screen.json",
        media,
        speakers=["SPEAKER_00"],
        diarization="senko 0.1.0",
        marks=[{"t": 1.0}],
        model="mlx-community/whisper-large-v3-turbo",
    )

    transcript = library.record_run(path, engine="whisper", language="ur")

    assert transcript.engine == "whisper"
    assert transcript.language == "ur"
    assert transcript.finished_at > LONG_AGO.isoformat()
    recording = library.recording(transcript.recording_id)
    assert recording is not None
    # `last_edited_at` is None until a person edits it in the app (#83).
    assert transcript.last_edited_at is None
    assert None not in (vars(transcript) | {"last_edited_at": "never"}).values()
    # `unreadable` is the one column whose None is the good answer: ffprobe read it.
    assert recording.unreadable is None
    # `title` is None until a person types one in the app (#245).
    assert recording.title is None
    assert None not in (vars(recording) | {"unreadable": "read", "title": "set"}).values()


def test_adopting_again_keeps_what_the_run_recorded_and_reads_new_marks(
    tmp_path: Path, library: Library
) -> None:
    media = _wav(tmp_path / "a.wav")
    path = _transcript(tmp_path / "a.json", media)
    ran = library.record_run(path, engine="sherpa")
    _transcript(path, media, marks=[{"t": 1.0}, {"t": 1.5}])

    [again] = library.adopt([path]).transcripts

    adopted = library.transcript(again)
    assert adopted is not None
    assert adopted.id == ran.id
    assert (adopted.engine, adopted.finished_at) == ("sherpa", ran.finished_at)
    assert adopted.mark_count == 2


@pytest.mark.parametrize(
    ("named", "stored"),
    [({"engine": "sherpa"}, "sherpa"), ({}, None), ({"engine": "mlx-community/x"}, None)],
)
def test_adopting_reads_the_engine_the_transcript_names(
    tmp_path: Path, library: Library, named: dict[str, str], stored: str | None
) -> None:
    """Since #172 a transcript names its engine; one before it, or a stray value, leaves NULL."""
    path = _transcript(tmp_path / "a.json", _wav(tmp_path / "a.wav"), **named)
    [adopted] = library.adopt([path]).transcripts
    found = library.transcript(adopted)
    assert found is not None
    assert found.engine == stored


def test_an_engine_a_run_recorded_wins_over_the_file_on_adopting_again(
    tmp_path: Path, library: Library
) -> None:
    media = _wav(tmp_path / "a.wav")
    path = _transcript(tmp_path / "a.json", media)
    ran = library.record_run(path, engine="whisper")
    _transcript(path, media, engine="parakeet")
    [again] = library.adopt([path]).transcripts
    assert again == ran.id
    found = library.transcript(again)
    assert found is not None
    assert found.engine == "whisper"


def test_record_run_refuses_an_engine_dsj_does_not_have(
    tmp_path: Path, library: Library
) -> None:
    path = _transcript(tmp_path / "a.json", _wav(tmp_path / "a.wav"))
    with pytest.raises(ValueError, match="parakeet, whisper, sherpa"):
        library.record_run(path, engine="mlx-community/parakeet-tdt-0.6b-v3")


def test_recordings_are_listed_newest_transcript_first(tmp_path: Path, library: Library) -> None:
    older = _transcript(tmp_path / "older.json", _wav(tmp_path / "older.wav", hz=300))
    newer = _transcript(tmp_path / "newer.json", _wav(tmp_path / "newer.wav", hz=600))
    os.utime(newer, (LONG_AGO.timestamp() + 3600, LONG_AGO.timestamp() + 3600))
    library.adopt([older, newer])
    assert [r.path.name for r in library.recordings()] == ["newer.wav", "older.wav"]


def test_the_same_recording_under_two_names_is_one_row(tmp_path: Path, library: Library) -> None:
    media = _wav(tmp_path / "a.wav")
    copy = tmp_path / "copy of a.wav"
    copy.write_bytes(media.read_bytes())
    library.adopt(
        [_transcript(tmp_path / "a.json", media), _transcript(tmp_path / "b.json", copy)]
    )
    [recording] = library.recordings()
    assert recording.path == media
    assert library.add_recording(copy).id == recording.id


def test_a_file_that_is_not_a_transcript_is_refused_and_the_rest_adopted(
    tmp_path: Path, library: Library
) -> None:
    status = tmp_path / "run.status.json"
    status.write_text(json.dumps({"state": "running", "pid": 1}))
    good = _transcript(tmp_path / "a.json", _wav(tmp_path / "a.wav"))

    adoption = library.adopt([status, good])

    assert len(adoption.transcripts) == 1
    [(refused, reason)] = adoption.refused
    assert refused == status
    assert "has no str `audio`" in reason


def test_a_relative_audio_path_is_found_beside_the_transcript(
    tmp_path: Path, library: Library
) -> None:
    media = _wav(tmp_path / "a.wav")
    [transcript_id] = library.adopt([_transcript(tmp_path / "a.json", "a.wav")]).transcripts
    transcript = library.transcript(transcript_id)
    assert transcript is not None
    recording = library.recording(transcript.recording_id)
    assert recording is not None
    assert (recording.path, recording.missing) == (media, False)


def test_a_library_written_by_a_newer_dsj_is_refused(private_library: Path) -> None:
    private_library.parent.mkdir(parents=True)
    with sqlite3.connect(private_library) as con:
        con.execute(f"PRAGMA user_version = {store.SCHEMA_VERSION + 1}")
    with pytest.raises(LibraryError, match="Upgrade dsj"):
        Library.open()


def test_a_version_3_library_gains_titles_and_script_shares_and_keeps_its_rows(
    tmp_path: Path,
) -> None:
    """Schema 4 adds recordings.title, 5 transcripts.urdu_share (#245)."""
    media = _wav(tmp_path / "old.wav")
    with Library.open() as library:
        rid = library.add_recording(media).id
    with sqlite3.connect(store.library_path()) as con:
        con.execute("ALTER TABLE recordings DROP COLUMN title")
        con.execute("ALTER TABLE transcripts DROP COLUMN urdu_share")
        con.execute("PRAGMA user_version = 3")
    with Library.open() as library:
        found = library.recording(rid)
        assert found is not None and found.title is None
        assert library.set_title(rid, "Kept").title == "Kept"
    with sqlite3.connect(store.library_path()) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == store.SCHEMA_VERSION == 5


def test_a_version_3_library_is_copied_aside_once_before_it_is_upgraded(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Final review I3: dsj 0.4.2 reads only version 3, and refuses the library once it is 5.

    So the file as 0.4.2 left it is kept beside it, once, and the upgrade says so.
    """
    media = _wav(tmp_path / "old.wav")
    with Library.open() as library:
        rid = library.add_recording(media).id
    path = store.library_path()
    with sqlite3.connect(path) as con:
        con.execute("ALTER TABLE recordings DROP COLUMN title")
        con.execute("ALTER TABLE transcripts DROP COLUMN urdu_share")
        con.execute("PRAGMA user_version = 3")
    capsys.readouterr()
    with Library.open() as library:
        assert library.recording(rid) is not None
    backup = path.with_name(f"{path.name}.v3.bak")
    with sqlite3.connect(backup) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == 3
        assert con.execute("SELECT id FROM recordings").fetchall() == [(rid,)]
    said = capsys.readouterr().err.splitlines()
    assert len(said) == 1, said
    assert str(backup) in said[0] and "0.4" in said[0]
    # Opened again it is version 5: nothing is copied, nothing said.
    with Library.open():
        pass
    assert capsys.readouterr().err == ""
    assert sorted(p.name for p in path.parent.iterdir() if p.name.startswith(path.name)) == [
        path.name, backup.name,
    ]


def _downgrade_to_version_3(path: Path) -> Path:
    with sqlite3.connect(path) as con:
        con.execute("ALTER TABLE recordings DROP COLUMN title")
        con.execute("ALTER TABLE transcripts DROP COLUMN urdu_share")
        con.execute("PRAGMA user_version = 3")
    return path.with_name(f"{path.name}.v3.bak")


def test_a_half_written_backup_from_a_killed_upgrade_does_not_stop_the_next_one(
    tmp_path: Path,
) -> None:
    """#284: SQLite refuses to copy into the leftover temp file, and every start failed on it."""
    with Library.open() as library:
        rid = library.add_recording(_wav(tmp_path / "old.wav")).id
    path = store.library_path()
    backup = _downgrade_to_version_3(path)
    partial = backup.with_name(f".{backup.name}.tmp")
    partial.write_bytes(path.read_bytes()[:100])
    with Library.open() as library:
        assert library.recording(rid) is not None
    with sqlite3.connect(backup) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == 3
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert con.execute("SELECT id FROM recordings").fetchall() == [(rid,)]
    assert not partial.exists()


def test_a_backup_copy_that_raises_leaves_no_temp_file_behind(tmp_path: Path) -> None:
    with Library.open() as library:
        library.add_recording(_wav(tmp_path / "old.wav"))
    path = store.library_path()
    backup = _downgrade_to_version_3(path)

    class Boom(Exception):
        pass

    class Dying(sqlite3.Connection):
        def backup(self, target: sqlite3.Connection, **kwargs: Any) -> None:
            # Some bytes reach the temp file before the process dies.
            target.execute("CREATE TABLE half (x)")
            raise Boom

    db = sqlite3.connect(path, factory=Dying)
    try:
        with pytest.raises(Boom):
            store._keep_before_upgrade(db, path, 3)  # pyright: ignore[reportPrivateUsage]
    finally:
        db.close()
    assert not backup.exists()
    assert not backup.with_name(f".{backup.name}.tmp").exists()


def test_a_library_backup_already_there_is_never_written_over(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with Library.open() as library:
        library.add_recording(_wav(tmp_path / "old.wav"))
    path = store.library_path()
    with sqlite3.connect(path) as con:
        con.execute("ALTER TABLE recordings DROP COLUMN title")
        con.execute("ALTER TABLE transcripts DROP COLUMN urdu_share")
        con.execute("PRAGMA user_version = 3")
    backup = path.with_name(f"{path.name}.v3.bak")
    backup.write_bytes(b"the first backup")
    with Library.open():
        pass
    assert backup.read_bytes() == b"the first backup"
    assert str(backup) in capsys.readouterr().err


def test_a_version_4_library_gains_script_shares_and_keeps_every_row_and_title(
    tmp_path: Path,
) -> None:
    """A library the first step of this change wrote: it has titles, not script shares (#245)."""
    audio = _wav(tmp_path / "old.wav")
    arabic = _transcript(
        tmp_path / "old.json", audio,
        sentences=[{"start": 0.0, "end": 1.0, "tokens": [], "text": " آج صبح ہم نے دیکھا"}],
    )
    with Library.open() as library:
        assert not library.adopt([arabic]).refused
        rid = library.recordings()[0].id
        library.set_title(rid, "Kept")
    before = _rows(store.library_path())
    with sqlite3.connect(store.library_path()) as con:
        con.execute("ALTER TABLE transcripts DROP COLUMN urdu_share")
        con.execute("PRAGMA user_version = 4")
    with Library.open() as library:
        found = library.recording(rid)
        assert found is not None and found.title == "Kept"
        (row,) = library.transcripts(rid)
        assert row.urdu_share is None
        assert library.backfill_urdu_share() == 1
        assert library.backfill_urdu_share() == 0
        (row,) = library.transcripts(rid)
        assert row.urdu_share == 1.0
    after = _rows(store.library_path())
    # Every row survives, and the one new column is the only difference.
    assert after["recordings"] == before["recordings"]
    assert [r[:-1] for r in after["transcripts"]] == [r[:-1] for r in before["transcripts"]]
    with sqlite3.connect(store.library_path()) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == store.SCHEMA_VERSION == 5


def test_a_new_transcript_row_carries_its_script_share(tmp_path: Path) -> None:
    audio = _wav(tmp_path / "mix.wav")
    mixed = _transcript(
        tmp_path / "mix.json", audio,
        sentences=[{"start": 0.0, "end": 1.0, "tokens": [], "text": " آج ab"}],
    )
    with Library.open() as library:
        assert not library.adopt([mixed]).refused
        rid = library.recordings()[0].id
        (row,) = library.transcripts(rid)
    assert row.urdu_share == 0.5


def test_a_title_for_a_recording_the_library_lacks_is_refused(library: Library) -> None:
    with pytest.raises(LibraryError, match="no recording with id 7"):
        library.set_title(7, "x")
