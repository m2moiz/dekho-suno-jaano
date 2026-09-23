"""`dsj likho`: a transcript written out as SRT, WebVTT or plain text (#54).

Until this existed the transcript was JSON only, and on 2026-09-22 an agent asked
to make one readable hand-wrote a 60-line converter with its own guesses at a
speaker label and a timestamp format. These tests pin the one format dsj decides
on, and hold the subtitle timeline to what a muxer will keep.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from dsj.cli import main
from dsj.likho import LikhoError, to_srt, to_txt, to_vtt


def _tok(t: float, w: str, e: float) -> dict[str, Any]:
    return {"t": t, "w": w, "e": e, "c": 1.0}


def _diarized() -> dict[str, Any]:
    """Two speakers, a sentence nobody was heard in, and an overlap.

    The second sentence ends at 5.25 s, after the third begins at 5.0 s: the
    shape a chunk seam leaves, and the one ffmpeg rewrote in 22 of 480 cues
    before the exporter existed (#54).
    """
    return {
        "audio": "/recordings/meeting.mov",
        "model": "mlx-community/parakeet-tdt-0.6b-v3",
        "speakers": ["SPEAKER_00", "SPEAKER_01"],
        "diarization": "senko 0.1.0",
        "text": "See this. Yes & no. Right. Hm.",
        "sentences": [
            {"start": 1.0, "end": 2.5, "speaker": 0, "text": " See this.",
             "tokens": [_tok(1.0, " See", 1.3), _tok(1.5, " this", 2.2), _tok(2.2, ".", 2.5)]},
            {"start": 3.0, "end": 5.25, "speaker": 1, "text": " Yes & no.",
             "tokens": [_tok(3.0, " Yes", 3.4), _tok(3.6, " &", 3.8),
                        _tok(4.0, " no", 4.9), _tok(4.9, ".", 5.25)]},
            {"start": 5.0, "end": 6.0, "speaker": 1, "text": " Right.",
             "tokens": [_tok(5.0, " Right", 5.8), _tok(5.8, ".", 6.0)]},
            {"start": 7.0, "end": 8.0, "speaker": None, "text": " Hm.",
             "tokens": [_tok(7.0, " Hm", 7.9), _tok(7.9, ".", 8.0)]},
        ],
    }


def _old() -> dict[str, Any]:
    """A transcript from before speakers, token ends and the sort: two sentences backwards."""
    return {
        "audio": "/recordings/old.mov",
        "model": "mlx-community/parakeet-tdt-0.6b-v3",
        "text": "Second. First.",
        "sentences": [
            {"start": 62.0, "end": 63.0, "text": " Second.",
             "tokens": [{"t": 62.0, "w": " Second"}, {"t": 62.8, "w": "."}]},
            {"start": 61.0, "end": 61.5, "text": " First.",
             "tokens": [{"t": 61.0, "w": " First"}, {"t": 61.4, "w": "."}]},
        ],
    }


def test_srt_has_speaker_labels_and_no_overlapping_cues() -> None:
    assert to_srt(_diarized()) == (
        "1\n00:00:01,000 --> 00:00:02,500\nSPEAKER_00: See this.\n\n"
        "2\n00:00:03,000 --> 00:00:05,000\nSPEAKER_01: Yes & no.\n\n"
        "3\n00:00:05,000 --> 00:00:06,000\nSPEAKER_01: Right.\n\n"
        "4\n00:00:07,000 --> 00:00:08,000\nHm.\n"
    )


def test_vtt_times_every_word_and_names_the_voice() -> None:
    """Inline timestamps are the word-level timing WebVTT allows inside a cue.

    A word that starts where the cue does, or at the same millisecond as the word
    before it, needs no tag: it is already timed. The `&` is escaped, as the
    format requires.
    """
    assert to_vtt(_diarized()) == (
        "WEBVTT\n\n"
        "00:00:01.000 --> 00:00:02.500\n"
        "<v SPEAKER_00>See<00:00:01.500> this<00:00:02.200>.\n\n"
        "00:00:03.000 --> 00:00:05.000\n"
        "<v SPEAKER_01>Yes<00:00:03.600> &amp;<00:00:04.000> no<00:00:04.900>.\n\n"
        "00:00:05.000 --> 00:00:06.000\n"
        "<v SPEAKER_01>Right<00:00:05.800>.\n\n"
        "00:00:07.000 --> 00:00:08.000\n"
        "Hm<00:00:07.900>.\n"
    )


def test_a_word_past_a_clamped_cue_end_gets_no_tag() -> None:
    """A tag must fall inside its cue, so a word the clamp cut off keeps the last time."""
    payload = _diarized()
    payload["sentences"][1]["tokens"][-1]["t"] = 5.1
    vtt = to_vtt(payload)
    assert "<00:00:05.100>" not in vtt
    assert "<00:00:04.000> no.\n" in vtt


def test_txt_is_one_block_per_speaker_turn() -> None:
    assert to_txt(_diarized()) == (
        "[0:01] SPEAKER_00\nSee this.\n\n"
        "[0:03] SPEAKER_01\nYes & no. Right.\n\n"
        "[0:07]\nHm.\n"
    )


def test_an_undiarized_transcript_is_one_timestamped_line_per_sentence() -> None:
    assert to_txt(_old()) == "[1:01] First.\n[1:02] Second.\n"


def test_an_old_transcript_exports_in_time_order_without_word_tags() -> None:
    """No speakers, no token ends, sentences backwards: it still exports.

    Its tokens have starts, so VTT still times the words.
    """
    assert to_srt(_old()) == (
        "1\n00:01:01,000 --> 00:01:01,500\nFirst.\n\n"
        "2\n00:01:02,000 --> 00:01:03,000\nSecond.\n"
    )
    assert "First<00:01:01.400>." in to_vtt(_old())


def test_text_its_tokens_do_not_spell_is_written_untimed() -> None:
    """Before #106 a sentence's text and its tokens could disagree. The text wins, untagged."""
    payload = _old()
    payload["sentences"][0]["tokens"].reverse()
    assert "\nSecond.\n" in to_vtt(payload)


def test_a_sentence_with_no_words_is_not_a_cue() -> None:
    payload = _old()
    payload["sentences"].append({"start": 70.0, "end": 71.0, "text": "", "tokens": []})
    assert to_srt(payload).count("-->") == 2


def test_two_sentences_starting_on_the_same_millisecond_share_a_cue() -> None:
    """Clamped to the next start, the first would last no time at all; its words go on.

    The shared cue ends where the later of the two ends, not where the second
    listed does: here the second listed ends first.
    """
    payload = _old()
    payload["sentences"][1]["start"] = 62.0
    payload["sentences"][1]["end"] = 62.5
    assert to_srt(payload) == "1\n00:01:02,000 --> 00:01:03,000\nSecond. First.\n"


def test_a_json_array_is_refused_rather_than_read_as_a_transcript() -> None:
    not_a_transcript: Any = []
    with pytest.raises(LikhoError, match="not a transcript"):
        to_srt(not_a_transcript)


# --------------------------------------------------------------------------
# What a consumer does with it
# --------------------------------------------------------------------------


def _srt_times(srt: str) -> list[str]:
    return [line for line in srt.splitlines() if "-->" in line]


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH")
def test_srt_survives_being_muxed_into_a_video_unchanged(tmp_path: Path) -> None:
    """The round trip that failed before this existed: 22 of 480 cues came back moved.

    MP4 timed text holds one cue at a time, so ffmpeg rewrites any cue that
    overlaps the next. The fixture has one such overlap in the transcript; the
    export must not carry it into the file, or it comes back with another end.
    """
    video = tmp_path / "v.mp4"
    srt = tmp_path / "t.srt"
    muxed = tmp_path / "muxed.mp4"
    back = tmp_path / "back.srt"
    srt.write_text(to_srt(_diarized()))

    def ffmpeg(*args: str) -> None:
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", *args], check=True)

    ffmpeg("-f", "lavfi", "-i", "color=c=black:s=64x64:d=10:r=10", "-pix_fmt", "yuv420p",
           str(video))
    ffmpeg("-i", str(video), "-i", str(srt), "-map", "0", "-map", "1", "-c", "copy",
           "-c:s", "mov_text", str(muxed))
    ffmpeg("-i", str(muxed), "-map", "0:s:0", str(back))

    assert _srt_times(back.read_text()) == _srt_times(srt.read_text())


# --------------------------------------------------------------------------
# The verb
# --------------------------------------------------------------------------


@pytest.fixture
def transcript(tmp_path: Path) -> Path:
    path = tmp_path / "t.json"
    path.write_text(json.dumps(_diarized()))
    return path


@pytest.mark.parametrize("suffix", ["srt", "vtt", "txt"])
def test_likho_picks_the_format_from_the_out_suffix(
    transcript: Path, tmp_path: Path, suffix: str
) -> None:
    out = tmp_path / f"t.{suffix}"
    assert main(["likho", str(transcript), "-o", str(out)]) == 0
    exporter = {"srt": to_srt, "vtt": to_vtt, "txt": to_txt}[suffix]
    assert out.read_text() == exporter(_diarized())


def test_likho_format_beats_the_suffix(transcript: Path, tmp_path: Path) -> None:
    out = tmp_path / "captions.txt"
    assert main(["likho", str(transcript), "-o", str(out), "--format", "vtt"]) == 0
    assert out.read_text().startswith("WEBVTT\n")


def test_likho_refuses_a_format_it_cannot_name(
    transcript: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A usage error, exit 2, and nothing written: a guess would be a wrong file."""
    out = tmp_path / "t.docx"
    assert main(["likho", str(transcript), "-o", str(out)]) == 2
    assert "srt, vtt or txt" in capsys.readouterr().err
    assert not out.exists()


def test_likho_writes_nothing_to_stdout(
    transcript: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["likho", str(transcript), "-o", str(tmp_path / "t.srt")]) == 0
    assert capsys.readouterr().out == ""
