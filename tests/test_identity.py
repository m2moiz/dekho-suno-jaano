"""One id for a recording, whatever it is called and wherever it sits (#120).

The checkpoint, the library (#105) and the sidecar (#119) all have to decide
whether two files are the same recording. These tests pin the answer they share:
the same bytes give the same id, a byte changed in either end gives a different
one, and neither the name, the folder nor the modification time takes part.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from dsj.identity import EDGE_BYTES, content_id

# Three edges long, so the head, the middle and the tail are disjoint and a byte
# in one of them can be told from a byte in another.
SIZE = 3 * EDGE_BYTES


def _recording(path: Path, size: int = SIZE) -> Path:
    """`size` bytes that differ position to position, so no edit is a no-op."""
    path.write_bytes(bytes(i % 251 for i in range(size)))
    return path


def _flip(path: Path, offset: int) -> None:
    """Change the one byte at `offset` in place, leaving the size alone."""
    data = bytearray(path.read_bytes())
    data[offset] ^= 0xFF
    path.write_bytes(bytes(data))


def test_content_id_is_the_same_on_two_calls(tmp_path: Path) -> None:
    source = _recording(tmp_path / "recording.mov")
    assert content_id(source) == content_id(source)


@pytest.mark.parametrize(
    "offset",
    [0, EDGE_BYTES - 1, SIZE - EDGE_BYTES, SIZE - 1],
    ids=["first byte", "last byte of the head", "first byte of the tail", "last byte"],
)
def test_content_id_changes_when_one_byte_in_either_end_changes(
    tmp_path: Path, offset: int
) -> None:
    source = _recording(tmp_path / "recording.mov")
    before = content_id(source)
    _flip(source, offset)
    assert content_id(source) != before


def test_content_id_does_not_read_the_middle(tmp_path: Path) -> None:
    """The price of the bounded read, pinned so it cannot quietly grow.

    A byte outside both edges is never read, so changing it leaves the id alone.
    If this starts failing, the function has started reading the middle of the
    file, and on a 1.25 GB recording that is the difference between milliseconds
    and seconds.
    """
    source = _recording(tmp_path / "recording.mov")
    before = content_id(source)
    _flip(source, SIZE // 2)
    assert content_id(source) == before


def test_content_id_covers_every_byte_of_a_file_under_two_edges(tmp_path: Path) -> None:
    """Between one and two edges long, the head and the tail meet and nothing is skipped."""
    size = EDGE_BYTES + EDGE_BYTES // 2
    source = _recording(tmp_path / "short.wav", size)
    before = content_id(source)
    _flip(source, EDGE_BYTES + 1)
    assert content_id(source) != before


def test_content_id_changes_with_the_size(tmp_path: Path) -> None:
    """A trimmed or extended copy is a different recording, even with equal edges."""
    short = _recording(tmp_path / "a.wav", 10)
    longer = tmp_path / "b.wav"
    longer.write_bytes(short.read_bytes() + b"\x00")
    assert content_id(short) != content_id(longer)


def test_content_id_ignores_the_name_the_folder_and_the_mtime(tmp_path: Path) -> None:
    """What the id exists for: a renamed, moved or copied recording is the same one.

    `shutil.copyfile` gives the copy a new modification time, as a plain `cp` does;
    the utime below makes that certain rather than a matter of clock resolution.
    """
    source = _recording(tmp_path / "recording.mov")
    elsewhere = tmp_path / "moved" / "renamed.mov"
    elsewhere.parent.mkdir()
    shutil.copyfile(source, elsewhere)
    os.utime(elsewhere, ns=(1, 1))
    assert source.stat().st_mtime_ns != elsewhere.stat().st_mtime_ns
    assert content_id(elsewhere) == content_id(source)


def test_content_id_leads_with_the_size(tmp_path: Path) -> None:
    """Size first, then the hex digest, so two ids can be told apart at a glance."""
    source = _recording(tmp_path / "recording.mov", 10)
    size, digest = content_id(source).split("-")
    assert size == "10"
    assert len(digest) == 64
    int(digest, 16)
