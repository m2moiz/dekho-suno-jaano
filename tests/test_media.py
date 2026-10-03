"""media.py against real ffmpeg, on fixtures ffmpeg synthesizes at test time.

Nothing here is stubbed: probe really shells out to ffprobe and extract_audio
really runs ffmpeg. That is the point -- this module exists to own the
subprocess boundary and its error surfaces, and a stubbed test of a subprocess
wrapper asserts only that the stub was called.

The fixtures are seconds long and a few kilobytes; no binary is committed.
"""

from __future__ import annotations

import gc
import re
import shutil
import subprocess
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from dsj import media

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not on PATH",
)


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def _which_finds_nothing(_name: str) -> str | None:
    """Stand-in for shutil.which for the not-on-PATH tests.

    def, not lambda: an annotated lambda is not expressible, and under strict
    every unannotated lambda parameter is an error apiece.
    """
    return None


@pytest.fixture(scope="session")
def video_with_audio(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A 2s stand-in for a screen recording: H.264 video, 48kHz stereo AAC.

    Tiny on purpose -- the properties under test are container and stream
    metadata, and none of them care how many pixels or seconds there are.
    """
    out = tmp_path_factory.mktemp("fixtures") / "clip.mov"
    _ffmpeg(
        "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=10:duration=2",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2:sample_rate=48000",
        "-ac", "2", "-c:a", "aac", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(out),
    )
    return out


@pytest.fixture(scope="session")
def video_without_audio(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("fixtures") / "silent.mov"
    _ffmpeg(
        "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=10:duration=2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out),
    )
    return out


@pytest.fixture(scope="session")
def ready_wav(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Already exactly what the model wants: 16kHz mono s16le."""
    out = tmp_path_factory.mktemp("fixtures") / "ready.wav"
    _ffmpeg(
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2:sample_rate=16000",
        "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(out),
    )
    return out


@pytest.fixture(scope="session")
def video_outlasting_its_audio(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """4s of video over 2s of audio -- the mic stopped, the recorder did not.

    Deliberately built without `-shortest`, which is what a screen recorder
    does when it keeps capturing after the microphone drops out.
    """
    out = tmp_path_factory.mktemp("fixtures") / "video_outlasts_audio.mov"
    _ffmpeg(
        "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=10:duration=4",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2:sample_rate=48000",
        "-ac", "2", "-c:a", "aac", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(out),
    )
    return out


def test_probe_reads_stream_metadata(video_with_audio: Path) -> None:
    s = media.probe(video_with_audio)
    assert s.codec_name == "aac"
    assert s.sample_rate == 48000
    assert s.channels == 2
    assert s.duration_s == pytest.approx(2.0, abs=0.2)


def test_probe_reads_a_plain_wav(ready_wav: Path) -> None:
    s = media.probe(ready_wav)
    assert s.codec_name == "pcm_s16le"
    assert s.sample_rate == 16000
    assert s.channels == 1


def test_probe_prefers_the_streams_duration_over_the_containers(
    video_outlasting_its_audio: Path,
) -> None:
    """The regression this file exists for.

    The container's duration is the max across its streams, so denominating
    the extraction bar in it leaves the bar stalled short of 100% for the whole
    stretch where video rolls on without audio -- observed at 88% on a real
    recording. probe() must report the audio stream's own duration.
    """
    probed = media.probe(video_outlasting_its_audio)
    container = float(
        subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(video_outlasting_its_audio)],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    )

    # The fixture is only meaningful if the two actually disagree.
    assert container == pytest.approx(4.0, abs=0.3)
    assert probed.duration_s == pytest.approx(2.0, abs=0.2)


def test_probe_rejects_a_file_with_no_audio(video_without_audio: Path) -> None:
    # ffprobe exits 0 here and returns an empty stream list, so this is a
    # content check, not an exit-code check.
    with pytest.raises(media.NoAudioStream) as exc:
        media.probe(video_without_audio)
    assert "silent.mov" in str(exc.value)
    assert "nothing to transcribe" in str(exc.value)


def test_probe_reports_a_corrupt_container(tmp_path: Path) -> None:
    bad = tmp_path / "corrupt.mov"
    bad.write_bytes(b"\x00" * 200_000)
    with pytest.raises(media.MediaError) as exc:
        media.probe(bad)
    assert "corrupt.mov" in str(exc.value)
    assert "ffprobe could not read" in str(exc.value)


def test_probe_raises_before_shelling_out_for_a_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "nope.mov"
    with pytest.raises(FileNotFoundError) as exc:
        media.probe(missing)
    assert "nope.mov" in str(exc.value)


def test_missing_ffprobe_names_the_binary(
    monkeypatch: pytest.MonkeyPatch, video_with_audio: Path
) -> None:
    monkeypatch.setattr(media.shutil, "which", _which_finds_nothing)
    with pytest.raises(media.FFmpegNotFound) as exc:
        media.probe(video_with_audio)
    assert "ffprobe is not on PATH" in str(exc.value)
    assert "brew install ffmpeg" in str(exc.value)


def test_conversion_needed_for_a_screen_recording(video_with_audio: Path) -> None:
    assert media.needs_conversion(media.probe(video_with_audio), 16000) is True


def test_conversion_skipped_for_an_already_ready_wav(ready_wav: Path) -> None:
    assert media.needs_conversion(media.probe(ready_wav), 16000) is False


def test_conversion_needed_for_model_shaped_sound_in_a_mov(tmp_path: Path) -> None:
    # The sound needs nothing, but the speaker labelling reads the file as a
    # WAV, and a .mov is not one (#205).
    mov = tmp_path / "edit.mov"
    _ffmpeg(
        "-f", "lavfi", "-i", "testsrc2=size=64x48:rate=5:duration=1",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=1:sample_rate=16000",
        "-ac", "1", "-c:a", "pcm_s16le", "-c:v", "mpeg4", str(mov),
    )
    s = media.probe(mov)
    assert (s.codec_name, s.sample_rate, s.channels) == ("pcm_s16le", 16000, 1)
    assert s.container != "wav"
    assert media.needs_conversion(s, 16000) is True


def test_a_wav_reports_its_container(ready_wav: Path) -> None:
    assert media.probe(ready_wav).container == "wav"


def test_conversion_needed_when_the_rate_does_not_match_the_model(ready_wav: Path) -> None:
    # A 16kHz mono wav is still wrong if the model asks for something else --
    # which is why the rate is a parameter and not a constant.
    assert media.needs_conversion(media.probe(ready_wav), 22050) is True


def test_extract_produces_model_shaped_audio(video_with_audio: Path, tmp_path: Path) -> None:
    dest = media.extract_audio(video_with_audio, tmp_path / "a.wav", 16000)
    assert dest.exists()
    s = media.probe(dest)
    assert (s.codec_name, s.sample_rate, s.channels) == ("pcm_s16le", 16000, 1)
    assert s.duration_s == pytest.approx(2.0, abs=0.2)


def test_extract_reports_progress_in_audio_seconds(
    video_with_audio: Path, tmp_path: Path
) -> None:
    # A 2s fixture finishes well inside one -stats_period, so the assertion
    # below rides on ffmpeg's terminal `progress=end` block, which always
    # carries a final out_time_us. Do not lengthen the fixture to make progress
    # appear -- that would hide a regression in the parsing.
    seen: list[float] = []
    media.extract_audio(
        video_with_audio, tmp_path / "a.wav", 16000,
        on_progress=seen.append,
    )
    assert seen, "no progress was reported"
    assert seen == sorted(seen)
    assert seen[-1] == pytest.approx(2.0, abs=0.2)


def test_extract_names_the_file_when_there_is_no_audio(
    video_without_audio: Path, tmp_path: Path
) -> None:
    with pytest.raises(media.MediaError) as exc:
        media.extract_audio(video_without_audio, tmp_path / "a.wav", 16000)
    assert "silent.mov" in str(exc.value)
    assert "no audio track" in str(exc.value)


def test_missing_ffmpeg_names_the_binary(
    monkeypatch: pytest.MonkeyPatch, video_with_audio: Path, tmp_path: Path
) -> None:
    monkeypatch.setattr(media.shutil, "which", _which_finds_nothing)
    with pytest.raises(media.FFmpegNotFound) as exc:
        media.extract_audio(video_with_audio, tmp_path / "a.wav", 16000)
    assert "ffmpeg is not on PATH" in str(exc.value)
    assert "brew install ffmpeg" in str(exc.value)


def test_extraction_closes_the_ffmpeg_pipe(tmp_path: Path, video_with_audio: Path) -> None:
    """The ffmpeg stdout pipe is closed explicitly, not left to the collector.

    Popen with stdout=PIPE hands back a TextIOWrapper that stays open until
    something closes it, and `proc.wait()` does not. CPython's refcounting then
    reclaims it when `proc` falls out of scope -- so a descriptor COUNT cannot
    see the bug, which is why this test asserts on the ResourceWarning instead.

    That warning is the real signal, and it is invisible in a normal run
    because Python ignores ResourceWarning by default. It fired throughout this
    project's history until it was found by running the suite once with
    `-W default` and reading the output rather than the pass count.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ResourceWarning)
        media.extract_audio(video_with_audio, tmp_path / "a.wav", 16000)
        gc.collect()

    leaked = [w for w in caught if issubclass(w.category, ResourceWarning)]
    assert not leaked, f"extract_audio leaked: {[str(w.message) for w in leaked]}"


def test_loudness_is_the_rms_of_each_whole_frame_in_dbfs(ready_wav: Path) -> None:
    """The sine ffmpeg makes is amplitude 1/8, so RMS 1/(8 * sqrt 2): -21.07 dBFS (#181).

    2 s in 0.3 s frames is six whole frames; the part frame left over is dropped.
    """
    expected = 20 * np.log10(1 / (8 * np.sqrt(2)))

    frames = media.loudness(ready_wav, 0.1)
    assert frames.shape == (20,)
    assert np.allclose(frames, expected, atol=0.05)
    assert media.loudness(ready_wav, 0.3).shape == (6,)


def test_loudness_reports_a_file_ffmpeg_cannot_read(tmp_path: Path) -> None:
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"RIFF")

    with pytest.raises(media.MediaError, match="failed to read the audio"):
        media.loudness(bad, 0.1)


def test_envelope_is_each_buckets_min_and_max_as_signed_bytes(ready_wav: Path) -> None:
    """The 2 s sine is amplitude 1/8: every 20 ms bucket spans -16 to 16 of 127 (#61)."""
    pairs = np.frombuffer(media.envelope(ready_wav), dtype=np.int8).reshape(-1, 2)
    assert pairs.shape == (2 * media.ENVELOPE_RATE, 2)
    assert (pairs[:, 0] == -16).all()
    assert (pairs[:, 1] == 16).all()


def test_envelope_shows_a_silence_as_flat_and_keeps_the_last_part_bucket(
    tmp_path: Path,
) -> None:
    """1 s of silence then 0.51 s of tone: 50 flat buckets, then 26, the last a part one."""
    out = tmp_path / "gap.wav"
    _ffmpeg(
        "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono:d=1",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=0.51:sample_rate=16000",
        "-filter_complex", "[0][1]concat=n=2:v=0:a=1", "-ar", "16000", str(out),
    )
    pairs = np.frombuffer(media.envelope(out), dtype=np.int8).reshape(-1, 2)
    assert pairs.shape == (76, 2)
    assert (pairs[:50] == 0).all()
    assert (pairs[51:, 1] > 10).all()
    assert (pairs[51:, 0] < -10).all()


def test_envelope_reports_a_file_ffmpeg_cannot_read(tmp_path: Path) -> None:
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"RIFF")

    with pytest.raises(media.MediaError, match="failed to read the audio"):
        media.envelope(bad)


# --------------------------------------------------------------------------
# mute: the bleep render (#65)
# --------------------------------------------------------------------------


def _samples(path: Path) -> np.ndarray[Any, np.dtype[np.float32]]:
    """The sound, decoded to mono float at 16 kHz, from its first sample."""
    raw = subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(path), "-vn", "-ac", "1",
         "-ar", "16000", "-f", "f32le", "-"],
        capture_output=True, check=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.float32)


def _mean_volume(path: Path, start: float, length: float) -> float:
    """`ffmpeg -ss <start> -t <len> -i <file> -af volumedetect`, as #128 measures a span."""
    log = subprocess.run(
        ["ffmpeg", "-nostdin", "-hide_banner", "-ss", str(start), "-t", str(length),
         "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    ).stderr
    line = next(x for x in log.splitlines() if "mean_volume" in x)
    return float(line.split("mean_volume:")[1].split("dB")[0])


def _video(path: Path) -> tuple[str, str]:
    """The first picture stream's codec, size and frame count, and its packets' md5."""
    shape = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
         "-show_entries", "stream=codec_name,width,height,nb_read_frames",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    digest = subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(path), "-map", "0:v",
         "-c", "copy", "-f", "md5", "-"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return shape, digest


def _duration(path: Path) -> float:
    return float(
        subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
             str(path)],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    )


def test_mute_silences_exactly_the_spans_of_a_wav_and_nothing_else(
    ready_wav: Path, tmp_path: Path
) -> None:
    before = ready_wav.read_bytes()
    out = media.mute(ready_wav, [(0.5, 0.75), (1.2, 1.3)], tmp_path / "clean.wav")
    assert ready_wav.read_bytes() == before
    original, muted = _samples(ready_wav), _samples(out)
    assert len(muted) == len(original)
    silent = np.flatnonzero(muted != original)
    # Every sample of each span is silent, and only the fades either side change.
    for a, b in ((0.5, 0.75), (1.2, 1.3)):
        assert not muted[int(a * 16000) : int(b * 16000)].any()
    fade = int(media.MUTE_FADE_S * 16000)
    inside = ((silent >= 0.5 * 16000 - fade) & (silent < 0.75 * 16000 + fade)) | (
        (silent >= 1.2 * 16000 - fade) & (silent < 1.3 * 16000 + fade)
    )
    assert inside.all(), "a sample outside every span changed"


def test_mute_fades_into_and_out_of_the_silence_rather_than_cutting(
    ready_wav: Path, tmp_path: Path
) -> None:
    """A sound dropped to 0 in one sample is a click at the mute's edge (#216).

    The sine's own steepest step between two samples is the most any sample of
    the render may move by. A cut at a 440 Hz sine's crest steps by its whole
    height, about five times that.
    """
    original = _samples(ready_wav)
    out = media.mute(ready_wav, [(0.5, 0.75), (1.2, 1.3)], tmp_path / "clean.wav")
    muted = _samples(out)
    own = float(np.abs(np.diff(original)).max())
    assert float(np.abs(np.diff(muted)).max()) <= 1.25 * own


def test_the_apps_preview_fades_as_long_as_a_render() -> None:
    """The app's live preview of a bleep fades with the render's own length (#225)."""
    preview = Path(__file__).parents[1] / "ui/src/features/bleep/liveMute.ts"
    found = re.search(r"^export const MUTE_FADE_S = ([0-9.]+);$", preview.read_text(), re.MULTILINE)
    assert found, f"{preview} no longer declares MUTE_FADE_S"
    assert float(found[1]) == media.MUTE_FADE_S


def test_mute_keeps_the_picture_and_the_length_of_a_movie(
    video_with_audio: Path, tmp_path: Path
) -> None:
    before = video_with_audio.read_bytes()
    out = media.mute(video_with_audio, [(0.5, 1.0)], tmp_path / "clean.mov")
    assert video_with_audio.read_bytes() == before
    assert _video(out) == _video(video_with_audio)  # same codec, size, frames, packets
    assert _duration(out) == pytest.approx(_duration(video_with_audio), abs=0.05)
    # Far quieter over the span than the input, and the same outside it.
    assert _mean_volume(out, 0.55, 0.4) < _mean_volume(video_with_audio, 0.55, 0.4) - 60
    assert _mean_volume(out, 1.3, 0.5) == pytest.approx(
        _mean_volume(video_with_audio, 1.3, 0.5), abs=0.5
    )


def _audio_start(path: Path) -> float:
    """`ffprobe -show_entries stream=start_time` of the first sound stream."""
    return float(
        subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
             "stream=start_time", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    )


@pytest.mark.parametrize("codec", ["aac", "pcm_s16le"])
def test_mute_counts_from_the_first_sample_when_the_sound_starts_late(
    tmp_path: Path, codec: str
) -> None:
    """A transcript's clock starts at the first sample; the filter's at the file's start.

    The render's sound starts where the input's did, to the millisecond, so the
    silence lands at the transcript's times in the render's own clock too
    (#224). AAC's encoder used to start the render's sound one 1024-sample frame
    (21 ms) early, so every mute sat 21 ms late in it.
    """
    late = tmp_path / "late.mov"
    _ffmpeg(
        "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=10:duration=4",
        "-itsoffset", "0.479", "-f", "lavfi", "-i",
        "sine=frequency=440:duration=3:sample_rate=48000",
        "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", codec,
        str(late),
    )
    out = media.mute(late, [(1.0, 1.5)], tmp_path / "clean.mov")
    assert _audio_start(out) == pytest.approx(_audio_start(late), abs=0.001)
    # The loudest sample of each 1.5 ms block at 16 kHz, which always holds a
    # crest of the 440 Hz sine (one every 1.14 ms): its height.
    level = np.abs(_samples(out))
    height = level[: len(level) // 24 * 24].reshape(-1, 24).max(axis=1)
    quiet = np.flatnonzero(height < 0.5 * height.max())
    runs = np.split(quiet, np.flatnonzero(np.diff(quiet) != 1) + 1)
    longest = max(runs, key=len)
    # Below half height is the middle of each fade onward, which the AAC
    # encoder's ringing around a fade does not move, as it does the first sample
    # under 1e-4. The middle of each fade is half of MUTE_FADE_S outside the span.
    half = media.MUTE_FADE_S / 2
    assert longest[0] * 0.0015 == pytest.approx(1.0 - half, abs=0.005)
    assert (longest[-1] + 1) * 0.0015 == pytest.approx(1.5 + half, abs=0.005)


def test_mute_reports_progress_in_seconds_written(ready_wav: Path, tmp_path: Path) -> None:
    seen: list[float] = []
    media.mute(ready_wav, [(0.1, 0.2)], tmp_path / "clean.wav", on_progress=seen.append)
    assert seen
    assert seen[-1] == pytest.approx(2.0, abs=0.1)


def test_mute_refuses_to_replace_an_output_unless_asked(ready_wav: Path, tmp_path: Path) -> None:
    out = tmp_path / "clean.wav"
    out.write_bytes(b"keep me")
    rendered: list[float] = []
    with pytest.raises(FileExistsError, match="already exists, and replacing it was not asked"):
        media.mute(ready_wav, [(0.1, 0.2)], out, on_progress=rendered.append)
    assert not rendered, "refused only after rendering, not before starting"
    assert out.read_bytes() == b"keep me"
    media.mute(ready_wav, [(0.1, 0.2)], out, replace=True)
    assert out.read_bytes() != b"keep me"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["clean.wav"]


def test_mute_never_writes_over_its_input(ready_wav: Path, tmp_path: Path) -> None:
    copy = tmp_path / "rec.wav"
    copy.write_bytes(ready_wav.read_bytes())
    with pytest.raises(ValueError, match="never writes over its input"):
        media.mute(copy, [(0.1, 0.2)], copy, replace=True)
    assert copy.read_bytes() == ready_wav.read_bytes()


def test_mute_keeps_the_container(ready_wav: Path, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"name it \*\.wav"):
        media.mute(ready_wav, [(0.1, 0.2)], tmp_path / "clean.m4a")
    assert not list(tmp_path.iterdir())


def test_an_interrupted_render_leaves_no_file_behind(
    video_with_audio: Path, tmp_path: Path
) -> None:
    def interrupt(_done: float) -> None:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        media.mute(video_with_audio, [(0.5, 1.0)], tmp_path / "clean.mov", on_progress=interrupt)
    assert not list(tmp_path.iterdir()), "an interrupted render left a file"


def test_mute_names_a_file_with_no_sound(video_without_audio: Path, tmp_path: Path) -> None:
    with pytest.raises(media.NoAudioStream):
        media.mute(video_without_audio, [(0.5, 1.0)], tmp_path / "clean.mov")
    assert not list(tmp_path.iterdir())
