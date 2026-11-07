"""A transcript riding inside a copy of its recording, invisibly (#122).

#117 measured one in-file route that survives a QuickTime re-save: a hidden
`mov_text` subtitle track holding the transcript gzip-compressed and
base64-encoded. This is that route as code. The source recording is never
written; the copy carries the track; a player does not show it; and a
re-save with `avconvert --preset PresetPassthrough` still yields the
transcript back out unchanged.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from dsj import embed
from dsj.cli import main


def _video(path: Path, seconds: int = 2) -> Path:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=duration={seconds}:size=320x240:rate=10",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={seconds}",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        check=True,
    )
    return path


def _transcript(path: Path, sentences: int = 1) -> dict[str, object]:
    payload: dict[str, object] = {
        "audio": "/somewhere/talk.mov",
        "model": "mlx-community/parakeet-tdt-0.6b-v3",
        "text": " Hello there." * sentences,
        "sentences": [
            {
                "start": i * 1.0,
                "end": i * 1.0 + 0.9,
                "text": " Hello there.",
                "tokens": [
                    {"t": i * 1.0, "w": " Hello", "e": i + 0.5},
                    {"t": i + 0.5, "w": " there.", "e": i + 0.9},
                ],
            }
            for i in range(sentences)
        ],
        "speakers": ["SPEAKER_00"],
    }
    path.write_text(json.dumps(payload))
    return payload


def test_the_copy_carries_the_transcript_and_the_source_is_untouched(tmp_path: Path) -> None:
    media = _video(tmp_path / "talk.mov")
    before = hashlib.sha256(media.read_bytes()).hexdigest()
    payload = _transcript(tmp_path / "talk.json")
    out = embed.embed_transcript(media, tmp_path / "talk.json", tmp_path / "with.mov")
    assert out == tmp_path / "with.mov"
    assert hashlib.sha256(media.read_bytes()).hexdigest() == before
    assert embed.extract_transcript(out) == payload
    # The track is there, named for finding and in no language a player picks.
    # (ffmpeg's mov muxer marks the only subtitle track enabled whatever its
    # disposition, so "not shown by default" is a player check, not this one.)
    track = embed.find_track(out)
    assert track is not None
    assert track["codec_name"] == "mov_text"
    assert track.get("tags", {}).get("language", "und") == "und"
    assert embed.TRACK_TITLE in str(track.get("tags", {}))


def test_a_long_transcript_spans_many_cues_and_comes_back_whole(tmp_path: Path) -> None:
    media = _video(tmp_path / "talk.mov")
    payload = _transcript(tmp_path / "talk.json", sentences=4000)
    out = embed.embed_transcript(media, tmp_path / "talk.json", tmp_path / "with.mov")
    assert embed.extract_transcript(out) == payload
    assert embed.cue_count(out) > 1


def test_a_recording_with_no_transcript_inside_says_so(tmp_path: Path) -> None:
    media = _video(tmp_path / "talk.mov")
    with pytest.raises(embed.NoTranscriptInside, match="carries no dsj transcript"):
        embed.extract_transcript(media)


def test_the_copy_is_never_the_source(tmp_path: Path) -> None:
    media = _video(tmp_path / "talk.mov")
    _transcript(tmp_path / "talk.json")
    with pytest.raises(embed.EmbedRefused, match="never the source"):
        embed.embed_transcript(media, tmp_path / "talk.json", media)


def test_the_track_survives_a_quicktime_resave(tmp_path: Path) -> None:
    """#117's measured claim, kept true here: a passthrough re-save keeps the track."""
    assert shutil.which("avconvert") or Path("/usr/bin/avconvert").exists(), (
        "avconvert is on every Mac"
    )
    media = _video(tmp_path / "talk.mov")
    payload = _transcript(tmp_path / "talk.json", sentences=50)
    out = embed.embed_transcript(media, tmp_path / "talk.json", tmp_path / "with.mov")
    resaved = tmp_path / "qt.mov"
    subprocess.run(
        [
            "/usr/bin/avconvert",
            "--source",
            str(out),
            "--output",
            str(resaved),
            "--preset",
            "PresetPassthrough",
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )
    assert embed.extract_transcript(resaved) == payload


def test_the_cli_puts_it_in_and_takes_it_out(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    media = _video(tmp_path / "talk.mov")
    payload = _transcript(tmp_path / "talk.json")
    assert (
        main(
            [
                "daalo",
                str(media),
                "-t",
                str(tmp_path / "talk.json"),
                "-o",
                str(tmp_path / "with.mov"),
            ]
        )
        == 0
    )
    assert capsys.readouterr().out.strip() == str(tmp_path / "with.mov")
    assert main(["nikalo", str(tmp_path / "with.mov"), "-o", str(tmp_path / "back.json")]) == 0
    assert json.loads((tmp_path / "back.json").read_text()) == payload
    # Without --out the transcript goes to stdout.
    assert main(["nikalo", str(tmp_path / "with.mov")]) == 0
    assert json.loads(capsys.readouterr().out) == payload
    assert main(["nikalo", str(media)]) == 1
    assert "carries no dsj transcript" in capsys.readouterr().err
