"""The heartbeat's whole value is that an outside observer can trust it.

A reader that catches Path.write_text between truncate and write gets an empty
or half-written file, which is worse than no file at all -- it looks like data.

The raw-write_text version of the concurrent-reader test below was run before
this module existed and produced 80 JSONDecodeErrors over 200 writes, so the
race is measured rather than assumed.
"""

from __future__ import annotations

import json
import os
import stat
import threading
from pathlib import Path

import pytest

from dsj.atomic import atomic_write_text, atomic_write_texts

# Big enough that the write cannot complete in one syscall-sized gulp, which is
# what makes the torn-read window wide enough to hit reliably. With a 200-byte
# payload the race exists but takes thousands of iterations to observe.
PAYLOAD_KEYS = 20_000
WRITES = 200


def _payload(i: int) -> str:
    return json.dumps({"n": i, "pad": {str(k): k for k in range(PAYLOAD_KEYS)}})


def test_concurrent_reader_never_sees_a_partial_document(tmp_path: Path) -> None:
    target = tmp_path / "status.json"
    atomic_write_text(target, _payload(0))

    torn: list[str] = []
    stop = threading.Event()

    def reader() -> None:
        while not stop.is_set():
            try:
                json.loads(target.read_text())
            except json.JSONDecodeError as exc:
                torn.append(str(exc))
            except FileNotFoundError:
                torn.append("file did not exist")

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    try:
        for i in range(1, WRITES + 1):
            atomic_write_text(target, _payload(i))
    finally:
        stop.set()
        t.join(timeout=5)

    assert torn == []
    assert json.loads(target.read_text())["n"] == WRITES


def test_temp_file_is_a_sibling_so_the_rename_stays_on_one_filesystem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # rename(2) requires both paths on the same file system. A /tmp temp file
    # with a target on the data volume is EXDEV on this machine.
    import os

    from dsj import atomic

    target = tmp_path / "status.json"
    seen: list[Path] = []
    real_replace = os.replace

    # Path, not the wider StrOrBytesPath os.replace accepts: the only caller
    # this stands in front of is atomic_write_text, which passes two Paths.
    def spy(src: Path, dst: Path) -> None:
        seen.append(Path(src))
        return real_replace(src, dst)

    monkeypatch.setattr(atomic.os, "replace", spy)
    atomic_write_text(target, "{}")

    assert seen, "os.replace was never called -- this is not an atomic write"
    assert seen[0].parent == target.parent


class Boom(Exception):
    pass


def _explode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail at the rename, the last possible moment -- so a temp file exists."""
    from dsj import atomic

    def boom(src: Path, dst: Path) -> None:
        raise Boom

    monkeypatch.setattr(atomic.os, "replace", boom)


def test_a_failed_write_leaves_no_temp_file_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "status.json"
    _explode(monkeypatch)

    with pytest.raises(Boom):
        atomic_write_text(target, "{}")

    assert list(tmp_path.iterdir()) == []


def test_the_previous_document_survives_a_failed_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "status.json"
    atomic_write_text(target, '{"n": 1}')
    _explode(monkeypatch)

    with pytest.raises(Boom):
        atomic_write_text(target, '{"n": 2}')

    assert json.loads(target.read_text()) == {"n": 1}
    assert [p.name for p in tmp_path.iterdir()] == ["status.json"]


def test_fsync_is_off_by_default_and_reaches_the_file_when_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The asymmetry is deliberate, so it is asserted rather than assumed.

    The heartbeat is only protected against a concurrent reader and a dying
    process, both of which the rename alone covers; paying an fsync per ~3s
    heartbeat buys only power-loss protection for a file that costs nothing to
    regenerate. The checkpoint that jaano-fdy adds inverts that trade, so the
    same primitive has to be able to do both.
    """
    from dsj import atomic

    synced: list[int] = []
    # def, not lambda: strict flags every unannotated lambda parameter, and a
    # lambda has nowhere to put the annotation.
    def record_fsync(fd: int) -> None:
        synced.append(fd)

    monkeypatch.setattr(atomic.os, "fsync", record_fsync)

    atomic_write_text(tmp_path / "a.json", "{}")
    assert synced == []

    atomic_write_text(tmp_path / "b.json", "{}", fsync=True)
    # The file's bytes, then the folder that holds its new name (#285).
    assert len(synced) == 2


def _spy_fsync(monkeypatch: pytest.MonkeyPatch, watch: Path) -> list[tuple[str, str]]:
    """Record each os.fsync as (kind of fd, what `watch` held at that moment).

    The fd is inspected inside the call, while it is still open, so the test
    sees whether it was a folder and whether the rename had happened yet.
    """
    from dsj import atomic

    calls: list[tuple[str, str]] = []

    def record_fsync(fd: int) -> None:
        kind = "folder" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file"
        calls.append((kind, watch.read_text(encoding="utf-8") if watch.exists() else "absent"))

    monkeypatch.setattr(atomic.os, "fsync", record_fsync)
    return calls


def test_a_single_file_write_syncs_its_folder_after_the_rename_only_when_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#285: a rename is a change to the folder, so the folder is what must reach the disk."""
    target = tmp_path / "key.json"
    target.write_text("old", encoding="utf-8")
    calls = _spy_fsync(monkeypatch, target)

    atomic_write_text(target, "new", fsync=False)
    assert calls == []

    target.write_text("old", encoding="utf-8")
    atomic_write_text(target, "new", fsync=True)
    # The file is synced while the old name still holds the old text; the
    # folder is synced once the new text is in place.
    assert calls == [("file", "old"), ("folder", "new")]


def test_a_pair_write_syncs_the_folder_once_after_the_last_rename_only_when_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = tmp_path / "key.json", tmp_path / "key.txt"
    first.write_text("old", encoding="utf-8")
    second.write_text("old", encoding="utf-8")
    calls = _spy_fsync(monkeypatch, second)

    atomic_write_texts([(first, "new"), (second, "new")], fsync=False)
    assert calls == []

    first.write_text("old", encoding="utf-8")
    second.write_text("old", encoding="utf-8")
    atomic_write_texts([(first, "new"), (second, "new")], fsync=True)
    assert calls == [("file", "old"), ("file", "old"), ("folder", "new")]


def test_a_pair_in_two_folders_syncs_each_folder_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    calls = _spy_fsync(monkeypatch, tmp_path / "a" / "key.json")
    atomic_write_texts(
        [(tmp_path / "a" / "key.json", "x"), (tmp_path / "b" / "key.txt", "x")], fsync=True
    )
    assert [kind for kind, _ in calls] == ["file", "file", "folder", "folder"]


def test_the_file_is_written_as_utf8_whatever_the_locale_is(tmp_path: Path) -> None:
    """encoding="utf-8" explicitly, not the platform default.

    Two mutants survived -- `encoding=None` and the argument dropped -- because
    on this machine the locale default IS utf-8, so a round-trip through
    read_text() cannot tell the difference. Asserting on the raw BYTES can.

    A transcript carries whatever the speaker said; a checkpoint carries the
    tokens. Both are non-ASCII the moment a name or an accent appears, and a
    file written in a different codec is one another machine cannot read back.
    """
    p = tmp_path / "out.json"
    atomic_write_text(p, "café — ünïcode ✓")

    assert p.read_bytes() == "café — ünïcode ✓".encode()


def test_a_pair_that_fails_part_way_leaves_both_files_as_they_were(tmp_path: Path) -> None:
    """The second temp cannot be written: the first file is not replaced either."""
    first = tmp_path / "key.json"
    first.write_text("old json", encoding="utf-8")
    second = tmp_path / "gone" / "key.txt"
    with pytest.raises(FileNotFoundError):
        atomic_write_texts([(first, "new json"), (second, "new text")], fsync=True)
    assert first.read_text(encoding="utf-8") == "old json"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["key.json"]


def test_a_pair_is_written_whole(tmp_path: Path) -> None:
    pair = [(tmp_path / "key.json", "{}"), (tmp_path / "key.txt", "text\n")]
    atomic_write_texts(pair)
    assert [p.read_text(encoding="utf-8") for p, _ in pair] == ["{}", "text\n"]


def test_two_threads_writing_one_file_never_take_each_others_temp(tmp_path: Path) -> None:
    """One server, two requests at once: the pid alone named the temp, and one renamed it away."""
    single = tmp_path / "key.json"
    pair = [tmp_path / "key.json", tmp_path / "key.txt"]
    failures: list[BaseException] = []

    def writer(mark: str) -> None:
        try:
            for _ in range(200):
                atomic_write_text(single, mark)
                atomic_write_texts([(p, mark) for p in pair])
        except BaseException as exc:  # collected, then asserted empty
            failures.append(exc)

    threads = [threading.Thread(target=writer, args=(m,)) for m in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert failures == []
    assert sorted(p.name for p in tmp_path.iterdir()) == ["key.json", "key.txt"]
