"""A terminal `dsj suno` run adds itself to the library, so `dsj ui` lists it.

The owner's answer, on 2 Oct 2026, to #127's open question about adoption: a
transcript made in the terminal shows up in the app (#57, #156). The CLI records
the run, not transcribe(): the app's own jobs call transcribe() and record their
run themselves (dsj/ui/jobs.py), so recording it in transcribe() would record
every app job twice.

Every test here has its own library: conftest points DSJ_LIBRARY into a
temporary directory for each test.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from conftest import FakeToken

from dsj.suno import main, transcribe
from dsj.ui.store import LIBRARY_ENV, Library, library_path

if TYPE_CHECKING:
    from collections.abc import Callable

    from conftest import FakeModel

pytestmark = pytest.mark.usefixtures("already_extracted_media", "no_real_diarizer")

REPO = Path(__file__).resolve().parent.parent
STUB = REPO / "tests" / "stub_suno.py"


def _tokens() -> list[FakeToken]:
    return [FakeToken(0.0, 0.4, "see"), FakeToken(0.5, 12.0, " this.")]


def test_a_finished_run_is_in_the_library(
    fake_parakeet: Callable[..., FakeModel], fake_media: Path, tmp_path: Path
) -> None:
    fake_parakeet(tokens=_tokens())
    out = tmp_path / "out.json"

    assert main([str(fake_media), "-o", str(out), "--no-diarize"]) == 0

    with Library.open() as library:
        [recording] = library.recordings()
        [transcript] = library.transcripts(recording.id)
    assert recording.path == fake_media.resolve()
    assert not recording.missing
    assert transcript.json_path == out.resolve()
    assert transcript.engine == "parakeet"
    assert transcript.language is None


def test_the_library_is_the_one_dsj_library_names(
    fake_parakeet: Callable[..., FakeModel],
    fake_media: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mine = tmp_path / "elsewhere" / "mine.db"
    monkeypatch.setenv(LIBRARY_ENV, str(mine))
    fake_parakeet(tokens=_tokens())

    main([str(fake_media), "-o", str(tmp_path / "out.json"), "--no-diarize"])

    with Library.open(mine) as library:
        assert len(library.recordings()) == 1


def test_running_again_into_the_same_file_keeps_one_row(
    fake_parakeet: Callable[..., FakeModel], fake_media: Path, tmp_path: Path
) -> None:
    """A second run writing the same `-o` is a new run of the same transcript."""
    fake_parakeet(tokens=_tokens())
    out = tmp_path / "out.json"

    main([str(fake_media), "-o", str(out), "--no-diarize"])
    main([str(fake_media), "-o", str(out), "--no-diarize", "--no-resume"])

    with Library.open() as library:
        [recording] = library.recordings()
        assert len(library.transcripts(recording.id)) == 1


def _a_file_where_the_folder_should_be(tmp_path: Path) -> Path:
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("")
    return blocker / "library.db"


def _a_library_from_a_newer_dsj(tmp_path: Path) -> Path:
    path = tmp_path / "newer.db"
    db = sqlite3.connect(path)
    db.execute("PRAGMA user_version = 99")
    db.close()
    return path


@pytest.mark.parametrize(
    ("make", "named"),
    [(_a_file_where_the_folder_should_be, "FileExistsError"),
     (_a_library_from_a_newer_dsj, "LibraryError")],
)
def test_a_library_that_cannot_record_never_fails_the_run(
    fake_parakeet: Callable[..., FakeModel],
    fake_media: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    make: Callable[[Path], Path],
    named: str,
) -> None:
    """The transcript is written and is the truth; the library is only its index."""
    broken = make(tmp_path)
    monkeypatch.setenv(LIBRARY_ENV, str(broken))
    fake_parakeet(tokens=_tokens())
    out = tmp_path / "out.json"

    code = main([str(fake_media), "-o", str(out), "--no-diarize"])

    assert code == 0
    assert out.exists()
    err = capsys.readouterr().err
    warning = next(line for line in err.splitlines() if str(broken) in line)
    assert "not added to the library" in warning
    assert named in warning
    assert "dsj ui" in warning
    # The summary still closes the run, after the warning.
    assert err.rstrip().splitlines()[-1].startswith("done: ")


def test_a_failed_run_adds_nothing(
    fake_parakeet: Callable[..., FakeModel], tmp_path: Path
) -> None:
    fake_parakeet(tokens=_tokens())

    code = main([str(tmp_path / "absent.wav"), "-o", str(tmp_path / "out.json")])

    assert code == 1
    assert not library_path().exists()


def test_transcribe_itself_records_nothing(
    fake_parakeet: Callable[..., FakeModel], fake_media: Path, tmp_path: Path
) -> None:
    """The app's jobs call transcribe() and record their run once, themselves."""
    fake_parakeet(tokens=_tokens())

    transcribe(fake_media, tmp_path / "out.json", diarize=False)

    assert not library_path().exists()


def test_a_run_records_itself_without_the_ui_extra(tmp_path: Path) -> None:
    """The shipped CLI, in its own process, with fastapi, uvicorn and starlette hidden.

    A bare `dsj` install carries no web server (#111), and `dsj suno` there must
    still record its run: the store is plain sqlite3.
    """
    media = tmp_path / "rec.wav"
    media.touch()
    out = tmp_path / "out.json"
    probe = (
        "import runpy, sys\n"
        "for name in ('fastapi', 'uvicorn', 'starlette'):\n"
        "    sys.modules[name] = None\n"
        f"sys.argv = [{str(STUB)!r}, {str(media)!r}, '-o', {str(out)!r}, '--no-diarize']\n"
        f"runpy.run_path({str(STUB)!r}, run_name='__main__')\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True, text=True, check=False, timeout=120,
        env=os.environ | {"STUB_HOLD": "0"},
    )

    assert done.returncode == 0, done.stderr
    assert "not added to the library" not in done.stderr, done.stderr
    with Library.open() as library:
        [recording] = library.recordings()
        [transcript] = library.transcripts(recording.id)
    assert recording.path == media.resolve()
    assert transcript.json_path == out.resolve()
