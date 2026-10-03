"""Adding a recording to the library from the app, and re-pointing a moved one (#110).

The Mac's file dialog is the one thing these tests stand in for: `pick.choose_file`
answers with the file a test names, as osascript would with the file a person
picked. Everything after it is real: the route, the store, ffprobe on files
ffmpeg made in a temporary directory. Each test's library is its own (conftest).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from dsj import media as media_mod
from dsj.ui import pick
from dsj.ui import store as store_mod
from dsj.ui.routes import media as media_route
from dsj.ui.server import create_app
from dsj.ui.store import Library, library_path

SIZE = 356 * 1024 * 1024


def page() -> TestClient:
    """A fresh `dsj ui` launch, asked the way its page asks."""
    app, token = create_app(port=8721)
    return TestClient(
        app, base_url="http://127.0.0.1:8721", headers={"Authorization": f"Bearer {token}"}
    )


@pytest.fixture
def picks(monkeypatch: pytest.MonkeyPatch) -> list[Path | None]:
    """What the file dialog answers, one entry a click, in order; None is a cancel."""
    answers: list[Path | None] = []

    def choose(prompt: str) -> Path | None:
        assert prompt
        return answers.pop(0)

    monkeypatch.setattr(pick, "choose_file", choose)
    return answers


def ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def tone(path: Path, hz: int = 440, seconds: int = 3) -> Path:
    ffmpeg("-f", "lavfi", "-i", f"sine=frequency={hz}:duration={seconds}", str(path))
    return path


def screen(path: Path, *video: str) -> Path:
    """Four seconds of a moving picture with a tone, in `path`'s container."""
    ffmpeg(
        "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=10:duration=4",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
        *video, "-shortest", str(path),
    )
    return path


def disk_bytes(folder: Path) -> int:
    """Bytes `folder` takes on disk, everything under it: what a copy would add to."""
    return sum(
        (Path(root) / name).stat().st_blocks * 512
        for root, _, names in os.walk(folder)
        for name in names
    )


def test_picking_a_file_adds_it_with_its_length_and_size(
    tmp_path: Path, picks: list[Path | None]
) -> None:
    picks.append(tone(tmp_path / "standup.wav", seconds=3))
    reply = page().post("/api/recordings/import")
    assert reply.status_code == 200, reply.text
    row = reply.json()
    assert Path(row["path"]) == (tmp_path / "standup.wav").resolve()
    assert row["duration_s"] == pytest.approx(3.0, abs=0.05)
    assert row["size_bytes"] == (tmp_path / "standup.wav").stat().st_size
    assert (row["unreadable"], row["missing"], row["transcripts"]) == (None, False, [])
    # And the library page lists it before anything has transcribed it.
    assert [r["id"] for r in page().get("/api/recordings").json()] == [row["id"]]


def test_a_cancelled_dialog_adds_nothing(picks: list[Path | None]) -> None:
    picks.append(None)
    reply = page().post("/api/recordings/import")
    assert reply.status_code == 200, reply.text
    assert reply.json() is None
    assert page().get("/api/recordings").json() == []


def test_importing_a_356_mb_recording_copies_zero_bytes(
    tmp_path: Path, picks: list[Path | None]
) -> None:
    """The library folder takes the same space before and after: the file is read where it is."""
    big = tmp_path / "screen.mov"
    with big.open("wb") as f:
        f.truncate(SIZE)  # sparse: reads as 356 MB, costs nothing on disk
    folder = library_path().parent
    with Library.open():
        pass
    before = disk_bytes(folder)
    picks.append(big)
    row = page().post("/api/recordings/import").json()
    assert row["size_bytes"] == SIZE
    # A page of SQLite is the most one more row can cost; a copy would be 356 MB.
    assert disk_bytes(folder) - before < 64 * 1024


def test_a_truncated_recording_imports_saying_what_ffprobe_said(
    tmp_path: Path, picks: list[Path | None]
) -> None:
    """A recording cut off before its index was written: the interrupted-recording case.

    QuickTime-style files write the index (the `moov` atom) last, so a
    recording stopped by a crash or a full disk has none, and ffprobe cannot
    open it at all. This is the failure #55 sets out to repair, reproduced.
    """
    whole = screen(tmp_path / "whole.mov", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac")
    cut = tmp_path / "interrupted.mov"
    cut.write_bytes(whole.read_bytes()[: whole.stat().st_size * 6 // 10])
    with pytest.raises(media_mod.MediaError, match="moov atom not found"):
        media_mod.probe(cut)

    picks.append(cut)
    reply = page().post("/api/recordings/import")
    assert reply.status_code == 200, reply.text
    row = reply.json()
    assert "moov atom not found" in row["unreadable"]
    assert (row["duration_s"], row["audio_codec"], row["missing"]) == (None, None, False)
    listed = page().get("/api/recordings").json()
    assert [r["unreadable"] for r in listed] == [row["unreadable"]]


def test_a_file_with_no_sound_is_readable_not_unreadable(
    tmp_path: Path, picks: list[Path | None]
) -> None:
    silent = tmp_path / "silent.mp4"
    ffmpeg("-f", "lavfi", "-i", "testsrc2=size=160x120:rate=10:duration=2",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", str(silent))
    picks.append(silent)
    row = page().post("/api/recordings/import").json()
    assert (row["unreadable"], row["audio_codec"], row["video_codec"]) == (None, None, "h264")


def test_the_same_contents_imported_twice_are_one_row_and_a_namesake_is_two(
    tmp_path: Path, picks: list[Path | None]
) -> None:
    first = tone(tmp_path / "call.wav", 440)
    (tmp_path / "copy").mkdir()
    copy = Path(shutil.copy2(first, tmp_path / "copy" / "renamed.wav"))
    (tmp_path / "other").mkdir()
    namesake = tone(tmp_path / "other" / "call.wav", 660)
    picks.extend([first, first, copy, namesake])
    ids = [page().post("/api/recordings/import").json()["id"] for _ in range(4)]
    assert ids[0] == ids[1] == ids[2] != ids[3]
    rows = page().get("/api/recordings").json()
    assert len(rows) == 2
    # The copy found while the original is in place leaves the row on the original.
    assert {Path(r["path"]) for r in rows} == {first.resolve(), namesake.resolve()}


def _transcript_of(media: Path, json_path: Path) -> int:
    json_path.write_text(json.dumps({
        "audio": str(media), "model": "mlx-community/parakeet-tdt-0.6b-v3", "text": " Hi.",
        "sentences": [{"start": 0.0, "end": 1.0, "text": " Hi.", "tokens": []}],
    }))
    with Library.open() as library:
        return library.record_run(json_path, engine="parakeet").recording_id


def test_a_renamed_recording_is_re_pointed_from_its_row_and_keeps_its_transcripts(
    tmp_path: Path, picks: list[Path | None]
) -> None:
    media = tone(tmp_path / "standup.wav")
    rid = _transcript_of(media, tmp_path / "standup.json")
    moved = media.rename(tmp_path / "standup-2026-10-02.wav")
    before = page().get("/api/recordings").json()
    assert [(r["id"], r["missing"]) for r in before] == [(rid, True)]

    picks.append(moved)
    reply = page().post(f"/api/recordings/{rid}/relink")
    assert reply.status_code == 200, reply.text
    row = reply.json()
    assert (row["id"], Path(row["path"]), row["missing"]) == (rid, moved.resolve(), False)
    assert [t["id"] for t in row["transcripts"]] == [t["id"] for t in before[0]["transcripts"]]
    # And it plays again.
    assert page().get(f"/api/recording/{rid}/media").status_code == 200


def test_re_pointing_at_another_recording_is_refused_and_changes_nothing(
    tmp_path: Path, picks: list[Path | None]
) -> None:
    media = tone(tmp_path / "standup.wav", 440)
    rid = _transcript_of(media, tmp_path / "standup.json")
    media.unlink()
    picks.append(tone(tmp_path / "another.wav", 660))
    reply = page().post(f"/api/recordings/{rid}/relink")
    assert reply.status_code == 422, reply.text
    assert reply.json()["error"] == "NotTheSameRecording"
    row = page().get("/api/recordings").json()[0]
    assert (Path(row["path"]), row["missing"]) == (media.resolve(), True)


@pytest.mark.parametrize("rid", ["%2E%2E", "1%2F..%2F1", "-1", "99"])
def test_re_pointing_a_recording_the_library_does_not_have_is_refused(
    rid: str, picks: list[Path | None]
) -> None:
    reply = page().post(f"/api/recordings/{rid}/relink")
    # A slash inside the id matches no route at all, and the page's own files
    # answer a POST with 405; either way nothing was looked up.
    assert reply.status_code in (404, 405), reply.text
    assert picks == []  # and no dialog was opened for it


def test_a_prores_recording_imports_and_its_sound_copy_is_served(
    tmp_path: Path, picks: list[Path | None], monkeypatch: pytest.MonkeyPatch
) -> None:
    """ProRes: Chromium plays its sound over a blank box (#59), and it still transcribes.

    The copy is AAC in MP4, which every browser the page runs in plays, made
    once and served by the same media route.
    """
    prores = screen(tmp_path / "export.mov", "-c:v", "prores_ks", "-c:a", "pcm_s16le")
    picks.append(prores)
    row = page().post("/api/recordings/import").json()
    assert (row["video_codec"], row["audio_codec"], row["unreadable"]) == (
        "prores", "pcm_s16le", None,
    )
    before = prores.read_bytes()

    made: list[Path] = []
    real = media_mod.sound_copy

    def counted(media: Path, dest: Path) -> Path:
        made.append(media)
        return real(media, dest)

    monkeypatch.setattr(media_mod, "sound_copy", counted)
    client = page()
    reply = client.get(f"/api/recording/{row['id']}/media", params={"sound": "true"})
    assert reply.status_code == 200, reply.text[:200]
    assert reply.headers["content-type"] == "audio/mp4"
    served = tmp_path / "served.m4a"
    served.write_bytes(reply.content)
    assert media_mod.video_codec(served) is None
    assert media_mod.probe(served).codec_name == "aac"
    assert media_mod.probe(served).duration_s == pytest.approx(4.0, abs=0.1)
    # Ranges, as for the file itself, and no second ffmpeg for them.
    ranged = client.get(
        f"/api/recording/{row['id']}/media", params={"sound": "true"},
        headers={"Range": "bytes=0-15"},
    )
    assert ranged.status_code == 206
    assert made == [prores.resolve()]
    assert media_route.sound_cache(row["content_id"]).is_file()
    # The recording is never touched, and without `sound` it is what is served.
    assert prores.read_bytes() == before
    assert client.get(f"/api/recording/{row['id']}/media").content == before


def test_a_file_with_no_sound_has_no_sound_copy(tmp_path: Path) -> None:
    silent = tmp_path / "silent.mp4"
    ffmpeg("-f", "lavfi", "-i", "testsrc2=size=160x120:rate=10:duration=2",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", str(silent))
    with Library.open() as library:
        rid = library.add_recording(silent).id
    reply = page().get(f"/api/recording/{rid}/media", params={"sound": "true"})
    assert reply.status_code == 422, reply.text
    assert reply.json()["error"] == "NoAudioStream"
    assert not list((library_path().parent / "sound").glob("*.tmp"))


# -- the dialog itself, with osascript stood in for -------------------------


def _which(found: str | None) -> Callable[[str], str | None]:
    """shutil.which, answering `found` for every name."""

    def which(_name: str) -> str | None:
        return found

    return which


def _osascript(
    monkeypatch: pytest.MonkeyPatch, returncode: int, stdout: str = "", stderr: str = ""
) -> list[list[str]]:
    calls: list[list[str]] = []

    def run(argv: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, returncode, stdout, stderr)

    monkeypatch.setattr(pick.shutil, "which", _which("/usr/bin/osascript"))
    monkeypatch.setattr(pick.subprocess, "run", run)
    return calls


def test_the_dialog_answers_the_posix_path_of_the_file_picked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _osascript(monkeypatch, 0, stdout="/Users/me/Movies/screen recording.mov\n")
    assert pick.choose_file("Add a recording") == Path("/Users/me/Movies/screen recording.mov")
    script = " ".join(calls[0])
    assert "choose file" in script
    assert "POSIX path" in script


def test_cancel_is_none_and_any_other_failure_says_what_osascript_said(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _osascript(monkeypatch, 1, stderr="execution error: User canceled. (-128)\n")
    assert pick.choose_file("Add a recording") is None
    _osascript(monkeypatch, 1, stderr="execution error: No user interaction allowed. (-1713)")
    with pytest.raises(pick.NoFilePicker, match=r"No user interaction allowed. \(-1713\)"):
        pick.choose_file("Add a recording")


def test_a_machine_with_no_osascript_is_told_what_to_do_instead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pick.shutil, "which", _which(None))
    reply = page().post("/api/recordings/import")
    assert reply.status_code == 503, reply.text
    assert reply.json()["error"] == "NoFilePicker"
    assert "dsj suno" in reply.json()["message"]


def test_a_second_dialog_is_refused_while_the_first_is_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _osascript(monkeypatch, 0, stdout="/x.mov\n")
    assert pick._open.acquire(blocking=False)  # pyright: ignore[reportPrivateUsage]
    try:
        reply = page().post("/api/recordings/import")
    finally:
        pick._open.release()  # pyright: ignore[reportPrivateUsage]
    assert reply.status_code == 409, reply.text
    assert reply.json()["error"] == "PickerBusy"
    assert calls == []


# -- the library file this needs -------------------------------------------


def test_a_version_1_library_gains_the_unreadable_column_and_keeps_its_rows(
    tmp_path: Path,
) -> None:
    media = tone(tmp_path / "old.wav")
    with Library.open() as library:
        rid = library.add_recording(media).id
    db = library_path()
    import sqlite3

    with sqlite3.connect(db) as con:
        # A version 1 library, which had neither column version 2 and 3 added.
        con.execute("ALTER TABLE recordings DROP COLUMN unreadable")
        con.execute("ALTER TABLE transcripts DROP COLUMN last_edited_at")
        con.execute("PRAGMA user_version = 1")
    with Library.open() as library:
        found = library.recording(rid)
    assert found is not None
    assert (found.path, found.unreadable) == (media.resolve(), None)
    with sqlite3.connect(db) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == store_mod.SCHEMA_VERSION == 3


def test_a_reader_waiting_on_a_migration_finds_it_done(tmp_path: Path) -> None:
    """Two opens of one old library: the second must not add the column twice."""
    with Library.open():
        pass
    db = library_path()
    import sqlite3

    with sqlite3.connect(db) as con:
        con.execute("ALTER TABLE recordings DROP COLUMN unreadable")
        con.execute("PRAGMA user_version = 1")
    first = sqlite3.connect(db)
    second = sqlite3.connect(db)
    try:
        migrate: Callable[[sqlite3.Connection, int], int] = store_mod._migrate  # pyright: ignore[reportPrivateUsage]
        assert migrate(first, 1) == 2
        assert migrate(second, 1) == 2
    finally:
        first.close()
        second.close()
