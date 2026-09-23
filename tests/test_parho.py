"""`dsj parho`: a transcript someone else made, read in instead of running ASR (#78).

The shape it has to accept is the one `dsj likho` writes (#54), so the central
tests here export with likho and read the result back. Each format gives back
exactly what it can hold, and says through `model` where its times came from.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from dsj.cli import main
from dsj.likho import to_srt, to_vtt
from dsj.parho import ParhoError, detect, parse


def _tok(t: float, w: str, e: float) -> dict[str, Any]:
    return {"t": t, "w": w, "e": e, "c": 0.9}


def _native() -> dict[str, Any]:
    """A labelled transcript whose cues neither overlap nor share a start.

    Every token starts on its own millisecond, so a VTT holds each one's start.
    """
    return {
        "audio": "/recordings/meeting.mov",
        "model": "mlx-community/parakeet-tdt-0.6b-v3",
        "speakers": ["SPEAKER_00", "SPEAKER_01"],
        "diarization": "senko 0.1.0",
        "text": "See this. Yes & no. Hm.",
        "sentences": [
            {"start": 1.0, "end": 2.5, "speaker": 0, "text": " See this.",
             "tokens": [_tok(1.0, " See", 1.3), _tok(1.5, " this", 2.2), _tok(2.25, ".", 2.5)]},
            {"start": 3.0, "end": 4.75, "speaker": 1, "text": " Yes & no.",
             "tokens": [_tok(3.0, " Yes", 3.4), _tok(3.6, " &", 3.8),
                        _tok(4.0, " no", 4.5), _tok(4.5, ".", 4.75)]},
            {"start": 7.0, "end": 8.0, "speaker": None, "text": " Hm.",
             "tokens": [_tok(7.0, " Hm", 7.9), _tok(7.95, ".", 8.0)]},
        ],
    }


def _said(payload: dict[str, Any]) -> list[tuple[float, float, str | None, str]]:
    """Each sentence as (start, end, speaker label, text)."""
    labels = payload.get("speakers", [])
    return [
        (s["start"], s["end"], None if s.get("speaker") is None else labels[s["speaker"]],
         s["text"])
        for s in payload["sentences"]
    ]


# --------------------------------------------------------------------------
# Exported by likho, read back by parho
# --------------------------------------------------------------------------


def test_vtt_gives_back_the_sentences_the_voices_and_every_word_start() -> None:
    original = _native()
    back = parse(to_vtt(original), "/recordings/meeting.mov")

    assert back["audio"] == "/recordings/meeting.mov"
    assert back["model"] == "import:vtt"
    assert back["speakers"] == ["SPEAKER_00", "SPEAKER_01"]
    assert back["diarization"] == "import:vtt"
    assert back["text"] == original["text"]
    assert _said(back) == _said(original)
    for got, want in zip(back["sentences"], original["sentences"], strict=True):
        assert [(t["t"], t["w"]) for t in got["tokens"]] == [
            (t["t"], t["w"]) for t in want["tokens"]
        ]
        # What a VTT has no room for is not invented: no end, no confidence.
        assert all("e" not in t and "c" not in t for t in got["tokens"])
        assert [t["charOffset"] for t in got["tokens"]] == [
            len("".join(t["w"] for t in want["tokens"][:i]))
            for i in range(len(want["tokens"]))
        ]


def test_srt_gives_back_the_sentences_and_labels_as_one_token_per_cue() -> None:
    """SRT holds a cue's span and its words, and nothing finer.

    So each sentence is one token from the cue's start to its end, the only
    times the file states, and `model` says so.
    """
    original = _native()
    back = parse(to_srt(original), "/recordings/meeting.mov")

    assert back["model"] == "import:srt"
    assert back["speakers"] == ["SPEAKER_00", "SPEAKER_01"]
    assert back["text"] == original["text"]
    assert _said(back) == _said(original)
    assert back["sentences"][0]["tokens"] == [
        {"t": 1.0, "w": " See this.", "e": 2.5, "charOffset": 0}
    ]


def test_a_token_that_is_only_a_space_keeps_its_own_time() -> None:
    """A bare space ahead of a number is a token of its own under parakeet, and timed.

    Found on the round trip of scratch/real_0806.json: 5 of its 480 cues came
    back with the space folded into the digit after it, and the space's time
    gone, while the text read the same.
    """
    original = _native()
    del original["speakers"], original["diarization"]
    original["sentences"] = [
        {"start": 1.0, "end": 2.0, "text": " page 20",
         "tokens": [_tok(1.0, " page", 1.4), _tok(1.5, " ", 1.6), _tok(1.7, "2", 1.8),
                    _tok(1.85, "0", 2.0)]},
    ]
    back = parse(to_vtt(original), "r.mov")
    assert [(t["t"], t["w"]) for t in back["sentences"][0]["tokens"]] == [
        (1.0, " page"), (1.5, " "), (1.7, "2"), (1.85, "0")
    ]


def test_an_unlabelled_export_imports_unlabelled() -> None:
    original = _native()
    del original["speakers"], original["diarization"]
    for sentence in original["sentences"]:
        del sentence["speaker"]
    for exported in (to_srt(original), to_vtt(original)):
        back = parse(exported, "r.mov")
        assert "speakers" not in back
        assert "diarization" not in back
        assert all("speaker" not in s for s in back["sentences"])


def test_json_is_a_dsj_transcript_passed_through_and_pointed_at_the_recording() -> None:
    original = _native()
    back = parse(json.dumps(original), "/elsewhere/meeting.mov")
    assert back == original | {"audio": "/elsewhere/meeting.mov"}
    assert next(iter(back)) == "audio"


def test_keys_come_in_the_order_suno_writes_them() -> None:
    back = parse(to_vtt(_native()), "r.mov")
    assert list(back) == ["audio", "model", "speakers", "diarization", "text", "sentences"]
    assert list(back["sentences"][0]) == ["start", "end", "speaker", "text", "tokens"]


# --------------------------------------------------------------------------
# Detected from the content
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("WEBVTT\n\n00:01.000 --> 00:02.000\nhi\n", "vtt"),
        ("﻿WEBVTT - a title\n", "vtt"),
        ("1\r\n00:00:01,000 --> 00:00:02,000\r\nhi\r\n", "srt"),
        ('  {"sentences": []}', "json"),
    ],
    ids=["vtt", "vtt with a bom and a title", "srt with crlf", "json"],
)
def test_the_format_is_read_off_the_content(text: str, kind: str) -> None:
    assert detect(text) == kind


def test_a_file_that_is_none_of_them_is_refused() -> None:
    with pytest.raises(ParhoError, match="not SRT, WebVTT or a dsj transcript"):
        detect("Speaker 1: hello\n")


def test_json_that_is_not_a_transcript_is_refused() -> None:
    with pytest.raises(ParhoError, match="not a dsj transcript"):
        parse('{"segments": []}', "r.mov")


# --------------------------------------------------------------------------
# Files dsj did not write
# --------------------------------------------------------------------------


def test_a_vtt_from_elsewhere_reads() -> None:
    """Identifiers, a NOTE, cue settings, hourless times, `<c>` spans, entities, two lines.

    The shape of a YouTube caption file: a word's tag before its span, its
    space inside the span.
    """
    text = (
        "WEBVTT\nKind: captions\n\n"
        "NOTE made by hand\n\n"
        "intro\n"
        "00:01.000 --> 00:03.500 align:start position:0%\n"
        "fish<00:01.800><c> &amp;</c><00:02.400><c> chips</c>\n"
        "tonight\n\n"
        "00:04.000 --> 00:05.000\n"
        "<v.loud Esme>Done.</v>\n"
    )
    back = parse(text, "r.mov")
    first, second = back["sentences"]
    assert (first["start"], first["end"], first["text"]) == (1.0, 3.5, " fish & chips tonight")
    assert [(t["t"], t["w"]) for t in first["tokens"]] == [
        (1.0, " fish"), (1.8, " &"), (2.4, " chips tonight")
    ]
    # The file names a voice somewhere, so every sentence says who, or null.
    assert first["speaker"] is None
    assert back["speakers"] == ["Esme"]
    assert second["speaker"] == 0
    assert second["tokens"] == [{"t": 4.0, "w": " Done.", "e": 5.0, "charOffset": 0}]


def test_an_srt_from_elsewhere_reads_in_time_order() -> None:
    """Crlf, markup, two lines to a cue, and cues out of order: sentences run earliest first."""
    text = (
        "2\r\n00:00:05,000 --> 00:00:06,000\r\n<i>Later</i> on.\r\n\r\n"
        "1\r\n00:00:01,000 --> 00:00:02,500\r\nFirst line\r\nand second.\r\n"
    )
    back = parse(text, "r.mov")
    assert [(s["start"], s["text"]) for s in back["sentences"]] == [
        (1.0, " First line and second."),
        (5.0, " Later on."),
    ]
    assert "speakers" not in back


def test_a_cue_with_nothing_to_say_is_not_a_sentence() -> None:
    back = parse("WEBVTT\n\n00:01.000 --> 00:02.000\n<c></c>\n", "r.mov")
    assert back["sentences"] == []
    assert back["text"] == ""


# --------------------------------------------------------------------------
# The verb, and what an imported transcript is good for
# --------------------------------------------------------------------------


@pytest.fixture
def recording(tmp_path: Path) -> Path:
    """Three flat colours, six seconds each: two cuts, further apart than dekho's 5 s gap."""
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not on PATH")
    out = tmp_path / "cuts.mp4"
    subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", "color=c=black:s=160x100:d=6",
         "-f", "lavfi", "-i", "color=c=white:s=160x100:d=6",
         "-f", "lavfi", "-i", "color=c=red:s=160x100:d=6",
         "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
         "-map", "[v]", "-r", "10", "-pix_fmt", "yuv420p", str(out)],
        check=True,
    )
    return out


def test_parho_writes_a_transcript_dekho_can_mark(recording: Path, tmp_path: Path) -> None:
    """An imported transcript works where a native one does: dekho merges marks into it."""
    captions = tmp_path / "captions.srt"
    captions.write_text(to_vtt(_native()))  # a VTT under an SRT name: content decides
    out = tmp_path / "t.json"

    assert main(["parho", str(recording), str(captions), "-o", str(out)]) == 0
    imported = json.loads(out.read_text())
    assert imported["audio"] == str(recording)
    assert imported["model"] == "import:vtt"

    assert main(["dekho", str(recording), "-t", str(out)]) == 0
    marked = json.loads(out.read_text())
    assert len(marked["marks"]) == 2
    assert marked["sentences"] == imported["sentences"]


def test_parho_refuses_a_recording_that_is_not_there(tmp_path: Path) -> None:
    """The transcript is an index into the recording; one pointing nowhere is no index."""
    captions = tmp_path / "c.vtt"
    captions.write_text(to_vtt(_native()))
    with pytest.raises(FileNotFoundError):
        main(["parho", str(tmp_path / "nope.mov"), str(captions), "-o", str(tmp_path / "t.json")])


def test_parho_then_likho_gives_back_the_same_vtt(tmp_path: Path) -> None:
    recording = tmp_path / "r.mov"
    recording.write_bytes(b"")
    captions = tmp_path / "c.vtt"
    captions.write_text(to_vtt(_native()))
    out = tmp_path / "t.json"
    again = tmp_path / "again.vtt"

    assert main(["parho", str(recording), str(captions), "-o", str(out)]) == 0
    assert main(["likho", str(out), "-o", str(again)]) == 0
    assert again.read_text() == captions.read_text()
