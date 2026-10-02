"""`dsj hatao` from a terminal (#153), on recordings ffmpeg makes at test time.

The word list is the per-test user file conftest points $DSJ_WORDS at, holding an
ordinary word, so the tests mute something without shipping a test-only swear word.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from dsj import hatao
from dsj.cli import EXIT_NOTHING_MUTED, main

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not on PATH",
)


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def _transcript(path: Path, words: list[tuple[float, float, str]], engine: str = "whisper") -> Path:
    tokens = [{"t": t, "w": w, "e": e, "c": 1.0} for t, e, w in words]
    path.write_text(json.dumps({
        "audio": "/r.wav", "engine": engine, "model": "m", "text": "", "unclear": [],
        "sentences": [{"start": tokens[0]["t"], "end": tokens[-1]["e"],
                       "text": "".join(w for _, _, w in words), "tokens": tokens}],
    }))
    return path


@pytest.fixture
def recording(tmp_path: Path) -> Path:
    path = tmp_path / "rec.wav"
    _ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:duration=4:sample_rate=16000",
            "-c:a", "pcm_s16le", str(path))
    return path


@pytest.fixture
def transcript(tmp_path: Path) -> Path:
    return _transcript(tmp_path / "t.json", [
        (0.5, 0.9, " the"), (1.0, 1.4, " weather"), (1.5, 1.9, " is"), (2.6, 3.0, " Weather."),
    ])


@pytest.fixture
def word_list() -> Path:
    path = hatao.user_words_path()
    path.write_text('[[entry]]\nname = "weather"\nroman = ["weather"]\n')
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _peak(path: Path, start: float, end: float) -> int:
    """The loudest 16-bit sample between two times of a 16 kHz mono wav."""
    import wave

    with wave.open(str(path)) as w:
        w.setpos(int(start * 16000))
        frames = w.readframes(int((end - start) * 16000))
    return max(abs(int.from_bytes(frames[i : i + 2], "little", signed=True))
               for i in range(0, len(frames), 2))


def test_hatao_mutes_the_listed_words_and_logs_each_one(
    recording: Path, transcript: Path, word_list: Path, tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    before = _sha(recording)
    out = tmp_path / "clean.wav"
    assert main(["hatao", str(recording), "-t", str(transcript), "-o", str(out)]) == 0
    assert _sha(recording) == before
    assert _peak(out, 1.0, 1.4) == 0 and _peak(out, 2.6, 3.0) == 0
    assert _peak(out, 1.6, 2.4) == _peak(recording, 1.6, 2.4) > 0  # between them, untouched
    log = json.loads((tmp_path / "clean.bleeps.json").read_text())
    assert log["muted"] == [
        {"word": "weather", "entry": "user:weather", "start": 1.0, "end": 1.4},
        {"word": "Weather.", "entry": "user:weather", "start": 2.6, "end": 3.0},
    ]
    assert log["spans"] == [[0.9, 1.5], [2.5, 3.1]]
    assert log["lists"][-1] == str(word_list)
    assert (log["media"], log["output"]) == (str(recording.resolve()), str(out.resolve()))
    err = capsys.readouterr().err
    assert "muted 2 words in 2 spans" in err


def test_nothing_to_mute_warns_writes_nothing_and_exits_3(
    recording: Path, transcript: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "clean.wav"
    code = main(["hatao", str(recording), "-t", str(transcript), "-o", str(out)])
    assert code == EXIT_NOTHING_MUTED == 3
    err = capsys.readouterr().err
    assert "warning: nothing to mute" in err
    assert str(transcript) in err
    assert all(f"/{name}.toml" in err for name in hatao.SHIPPED_LISTS)
    assert not out.exists()
    assert not (tmp_path / "clean.bleeps.json").exists()


def test_the_recall_line_says_unmeasured_until_it_is_measured(
    recording: Path, transcript: Path, word_list: Path, tmp_path: Path,
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    main(["hatao", str(recording), "-t", str(transcript), "-o", str(tmp_path / "a.wav")])
    assert "recall: how often whisper leaves a swear word out" in capsys.readouterr().err
    assert "is unmeasured (#152)" in hatao.recall_line("whisper")
    monkeypatch.setitem(hatao.RECALL, "whisper", "missed 2 of 30 known words (docs/x.md)")
    main(["hatao", str(recording), "-t", str(transcript), "-o", str(tmp_path / "b.wav")])
    err = capsys.readouterr().err
    assert "recall: whisper missed 2 of 30 known words" in err
    assert "unmeasured" not in err


def test_an_existing_output_is_refused_without_overwrite(
    recording: Path, transcript: Path, word_list: Path, tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = tmp_path / "clean.wav"
    out.write_bytes(b"keep me")
    args = ["hatao", str(recording), "-t", str(transcript), "-o", str(out)]
    assert main(args) == 1
    assert "refusing to replace" in capsys.readouterr().err
    assert out.read_bytes() == b"keep me"
    assert not (tmp_path / "clean.bleeps.json").exists()
    assert main([*args, "--overwrite"]) == 0
    assert out.read_bytes() != b"keep me"


def test_an_output_in_another_container_is_a_usage_error(
    recording: Path, transcript: Path, word_list: Path, tmp_path: Path
) -> None:
    out = tmp_path / "clean.mp3"
    assert main(["hatao", str(recording), "-t", str(transcript), "-o", str(out)]) == 2
    assert not out.exists()


def test_a_transcript_with_no_word_ends_is_one_line_not_a_guess(
    recording: Path, word_list: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    old = tmp_path / "old.json"
    old.write_text(json.dumps({"sentences": [{"start": 1.0, "end": 2.0, "text": " weather",
                                              "tokens": [{"t": 1.0, "w": " weather"}]}]}))
    out = tmp_path / "clean.wav"
    assert main(["hatao", str(recording), "-t", str(old), "-o", str(out)]) == 1
    assert capsys.readouterr().err.startswith("dsj: sentence 0, token 0 (at 1.0 s) has no end")
    assert not out.exists()


def test_hatao_imports_nothing_from_the_app(
    recording: Path, transcript: Path, word_list: Path, tmp_path: Path
) -> None:
    """No server and no window: the command must run without dsj.ui loaded at all."""
    out = tmp_path / "clean.wav"
    args = ["hatao", str(recording), "-t", str(transcript), "-o", str(out)]
    program = (
        "import sys; from dsj.cli import main\n"
        f"code = main({args!r})\n"
        "loaded = sorted(m for m in sys.modules if m == 'dsj.ui' or m.startswith('dsj.ui.'))\n"
        "print(loaded); sys.exit(code)\n"
    )
    done = subprocess.run([sys.executable, "-c", program], capture_output=True, text=True,
                          timeout=120)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "[]"
    assert out.exists()


def test_kill_stops_a_render_and_leaves_no_file(
    tmp_path: Path, word_list: Path
) -> None:
    """SIGTERM, as an agent stops a job it started; Ctrl-C takes the same path."""
    long = tmp_path / "long.m4a"
    _ffmpeg("-f", "lavfi", "-i", "anoisesrc=color=pink:sample_rate=48000:duration=300",
            "-ac", "2", "-c:a", "aac", "-b:a", "128k", str(long))
    words: list[tuple[float, float, str]] = [(1.0, 1.5, " weather"), (250.0, 250.5, " weather")]
    transcript = _transcript(tmp_path / "t.json", words)
    out = tmp_path / "clean.m4a"
    script = Path(sys.executable).parent / "dsj"
    proc = subprocess.Popen(
        [str(script), "hatao", str(long), "-t", str(transcript), "-o", str(out)],
        stderr=subprocess.PIPE, text=True,
    )
    assert proc.stderr is not None
    deadline = time.monotonic() + 60
    while "rendering" not in proc.stderr.readline():
        assert time.monotonic() < deadline and proc.poll() is None, "no progress line"
    proc.send_signal(signal.SIGTERM)
    assert proc.wait(timeout=60) == 143
    # ffmpeg was stopped with it, not left writing a file nobody will rename.
    assert subprocess.run(["pgrep", "-f", str(tmp_path)], capture_output=True).returncode == 1
    left: list[Any] = sorted(p.name for p in tmp_path.iterdir())
    assert left == ["long.m4a", "t.json"], left


# --------------------------------------------------------------------------
# Which recording a rendered file came from (#121)
# --------------------------------------------------------------------------


def test_a_rendered_file_names_its_source_in_a_sidecar_and_a_tag(
    recording: Path, transcript: Path, word_list: Path, tmp_path: Path
) -> None:
    from dsj.filetag import SOURCE_TAG, read_tag
    from dsj.identity import content_id

    out = tmp_path / "clean.wav"
    assert main(["hatao", str(recording), "-t", str(transcript), "-o", str(out)]) == 0
    expected = content_id(recording)
    assert (tmp_path / "clean.source.txt").read_text() == expected + "\n"
    assert read_tag(out, SOURCE_TAG) == expected.encode()


def test_a_render_into_a_cloud_synced_folder_writes_the_sidecar_only(
    recording: Path, transcript: Path, word_list: Path, tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """A fake Google Drive folder under a temporary home, as #202's tests do."""
    from dsj.filetag import SOURCE_TAG, read_tag
    from dsj.identity import content_id

    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    drive = home / "Library" / "CloudStorage" / "GoogleDrive-someone" / "My Drive"
    drive.mkdir(parents=True)
    out = drive / "clean.wav"
    assert main(["hatao", str(recording), "-t", str(transcript), "-o", str(out)]) == 0
    assert (drive / "clean.source.txt").read_text() == content_id(recording) + "\n"
    assert read_tag(out, SOURCE_TAG) is None
    err = capsys.readouterr().err
    assert f"source not tagged onto {out}, so only {drive / 'clean.source.txt'} names it" in err
    assert "cloud-synced folder" in err


def test_a_leftover_source_sidecar_is_not_replaced_without_overwrite(
    recording: Path, transcript: Path, word_list: Path, tmp_path: Path
) -> None:
    sidecar = tmp_path / "clean.source.txt"
    sidecar.write_text("an older render's\n")
    args = ["hatao", str(recording), "-t", str(transcript), "-o", str(tmp_path / "clean.wav")]
    assert main(args) == 1
    assert sidecar.read_text() == "an older render's\n"
    assert not (tmp_path / "clean.wav").exists()
    assert main([*args, "--overwrite"]) == 0
    assert sidecar.read_text() != "an older render's\n"
