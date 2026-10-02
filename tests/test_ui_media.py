"""A recording served by its library id, with byte ranges, behind #112's checks (#59).

Each test's library is its own (conftest points DSJ_LIBRARY into a temporary
directory). The 400 MB file is sparse: it reads as 400 MB to everything that
asks, and costs nothing on disk.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dsj.ui.server import create_app
from dsj.ui.store import Library

LOOPBACK = "http://127.0.0.1:8721"
SIZE = 400 * 1024 * 1024


def page() -> tuple[TestClient, str]:
    """A fresh `dsj ui` launch, asked the way its page asks."""
    app, token = create_app(port=8721)
    client = TestClient(app, base_url=LOOPBACK, headers={"Authorization": f"Bearer {token}"})
    return client, token


def added(media: Path) -> int:
    with Library.open() as library:
        return library.add_recording(media).id


@pytest.fixture
def big(tmp_path: Path) -> tuple[Path, int]:
    """A 400 MB recording with known bytes at 300,000,000, and its library id."""
    path = tmp_path / "long.mov"
    with path.open("wb") as f:
        f.truncate(SIZE)
        f.seek(300_000_000)
        f.write(bytes(range(64)))
    return path, added(path)


def test_a_range_far_into_a_400_mb_file_is_206_with_its_exact_content_range(
    big: tuple[Path, int],
) -> None:
    _, rid = big
    client, _ = page()
    reply = client.get(
        f"/api/recording/{rid}/media", headers={"Range": "bytes=300000000-300000063"}
    )
    assert reply.status_code == 206, reply.text[:200]
    assert reply.headers["content-range"] == f"bytes 300000000-300000063/{SIZE}"
    assert reply.content == bytes(range(64))
    assert reply.headers["content-type"] == "video/quicktime"


def test_head_says_ranges_are_accepted_and_sends_no_body(big: tuple[Path, int]) -> None:
    _, rid = big
    client, _ = page()
    reply = client.head(f"/api/recording/{rid}/media")
    assert reply.status_code == 200
    assert reply.headers["accept-ranges"] == "bytes"
    assert reply.headers["content-length"] == str(SIZE)
    assert reply.content == b""


def test_two_ranges_in_one_request_come_back_as_multipart(big: tuple[Path, int]) -> None:
    _, rid = big
    client, _ = page()
    reply = client.get(f"/api/recording/{rid}/media", headers={"Range": "bytes=0-1,100-101"})
    assert reply.status_code == 206
    assert reply.headers["content-type"].startswith("multipart/byteranges")


@pytest.mark.parametrize(
    "rid",
    [
        "%2E%2E",  # `..`, encoded so the client does not resolve it away first
        "1%2F..%2F1",  # `1/../1`, a slash inside the id
        "..%2Fetc%2Fpasswd",
        "%2Fetc%2Fpasswd",
        "-1",
        "1.0",
        "999",  # a number the library never had
    ],
)
def test_an_id_that_is_not_a_known_number_is_404(big: tuple[Path, int], rid: str) -> None:
    client, _ = page()
    reply = client.get(f"/api/recording/{rid}/media")
    assert reply.status_code == 404, (rid, reply.status_code)
    assert b"root:" not in reply.content


def test_no_token_is_401_and_a_foreign_host_is_403(big: tuple[Path, int]) -> None:
    _, rid = big
    app, token = create_app(port=8721)
    bare = TestClient(app, base_url=LOOPBACK)
    assert bare.get(f"/api/recording/{rid}/media").status_code == 401
    foreign = TestClient(
        app, base_url="http://attacker.example", headers={"Authorization": f"Bearer {token}"}
    )
    assert foreign.get(f"/api/recording/{rid}/media").status_code == 403


def test_a_moved_recording_is_404_naming_where_it_was_last_seen(tmp_path: Path) -> None:
    path = tmp_path / "talk.mp3"
    path.write_bytes(b"\xff\xfb" * 1000)
    rid = added(path)
    path.rename(tmp_path / "elsewhere.mp3")
    client, _ = page()
    reply = client.get(f"/api/recording/{rid}/media")
    assert reply.status_code == 404
    assert str(path) in reply.json()["detail"]


def test_another_file_now_at_the_same_path_is_not_served_as_this_recording(
    tmp_path: Path,
) -> None:
    path = tmp_path / "talk.mp3"
    path.write_bytes(b"\xff\xfb" * 1000)
    rid = added(path)
    path.write_bytes(b"\xff\xfb" * 2000)
    client, _ = page()
    assert client.get(f"/api/recording/{rid}/media").status_code == 404


def test_m4a_is_sent_as_audio_mp4_not_the_codec_name_python_guesses(tmp_path: Path) -> None:
    path = tmp_path / "standup.m4a"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
         "sine=frequency=440:duration=1", "-c:a", "aac", str(path)],
        check=True,
    )
    rid = added(path)
    client, _ = page()
    reply = client.get(f"/api/recording/{rid}/media")
    assert reply.status_code == 200
    assert reply.headers["content-type"] == "audio/mp4"
    assert len(reply.content) == path.stat().st_size


def test_a_media_element_carries_the_token_in_the_query_and_still_gets_ranges(
    big: tuple[Path, int],
) -> None:
    """An <audio> or <video> element sends no Authorization header, only its URL."""
    _, rid = big
    app, token = create_app(port=8721)
    element = TestClient(app, base_url=LOOPBACK)
    reply = element.get(
        f"/api/recording/{rid}/media?t={token}", headers={"Range": "bytes=300000000-300000063"}
    )
    assert reply.status_code == 206
    assert reply.headers["content-range"] == f"bytes 300000000-300000063/{SIZE}"
    assert element.head(f"/api/recording/{rid}/media?t={token}").status_code == 200
    assert element.get(f"/api/recording/{rid}/media?t=wrong").status_code == 401
    assert element.get(f"/api/recording/{rid}/media?t={token}&t={token}").status_code == 401


def test_the_query_token_opens_the_media_route_and_nothing_else(big: tuple[Path, int]) -> None:
    _, rid = big
    app, token = create_app(port=8721)
    element = TestClient(app, base_url=LOOPBACK)
    assert element.get(f"/api/recordings?t={token}").status_code == 401
    assert element.get(f"/api/transcripts/1?t={token}").status_code == 401
    assert element.post(f"/api/heartbeat?t={token}").status_code == 401
    assert element.post(f"/api/recording/{rid}/media?t={token}").status_code == 401
    assert element.get(f"/api/recording/{rid}/media/x?t={token}").status_code == 401


def test_the_query_token_does_not_get_past_the_host_check(big: tuple[Path, int]) -> None:
    _, rid = big
    app, token = create_app(port=8721)
    foreign = TestClient(app, base_url="http://attacker.example")
    assert foreign.get(f"/api/recording/{rid}/media?t={token}").status_code == 403


def tone(path: Path, seconds: float = 2) -> Path:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
         f"sine=frequency=440:duration={seconds}:sample_rate=16000", str(path)],
        check=True,
    )
    return path


def test_the_waveform_is_the_envelope_as_raw_bytes(tmp_path: Path) -> None:
    from dsj.media import ENVELOPE_RATE

    rid = added(tone(tmp_path / "talk.wav"))
    client, _ = page()
    reply = client.get(f"/api/recording/{rid}/waveform")
    assert reply.status_code == 200, reply.text
    assert reply.headers["content-type"] == "application/octet-stream"
    assert len(reply.content) == 2 * 2 * ENVELOPE_RATE


def test_opening_the_same_recording_again_recomputes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import dsj.media

    rid = added(tone(tmp_path / "talk.wav"))
    calls: list[Path] = []
    real = dsj.media.envelope

    def counted(media: Path) -> bytes:
        calls.append(media)
        return real(media)

    monkeypatch.setattr(dsj.media, "envelope", counted)
    first = page()[0].get(f"/api/recording/{rid}/waveform").content
    # A second launch of dsj ui: a new app, the same library and the same cache.
    second = page()[0].get(f"/api/recording/{rid}/waveform").content
    assert first == second
    assert len(calls) == 1


def test_the_cache_follows_the_contents_not_the_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import dsj.media
    from dsj.ui.routes.media import waveform_cache
    from dsj.ui.store import Library

    path = tone(tmp_path / "talk.wav")
    rid = added(path)
    page()[0].get(f"/api/recording/{rid}/waveform")
    with Library.open() as library:
        found = library.recording(rid)
    assert found is not None and found.content_id is not None
    assert waveform_cache(found.content_id).is_file()

    # Renamed and pointed at again: the same contents, so the same envelope file.
    moved = path.rename(tmp_path / "renamed.wav")
    with Library.open() as library:
        library.relink(rid, moved)
    def recomputed(_media: Path) -> bytes:
        pytest.fail("the envelope was computed again")

    monkeypatch.setattr(dsj.media, "envelope", recomputed)
    assert page()[0].get(f"/api/recording/{rid}/waveform").status_code == 200


def test_the_waveform_route_refuses_what_the_media_route_refuses(tmp_path: Path) -> None:
    path = tone(tmp_path / "talk.wav")
    rid = added(path)
    client, _ = page()
    assert client.get("/api/recording/..%2F1/waveform").status_code == 404
    assert client.get("/api/recording/999/waveform").status_code == 404
    app, token = create_app(port=8721)
    bare = TestClient(app, base_url=LOOPBACK)
    assert bare.get(f"/api/recording/{rid}/waveform").status_code == 401
    # The media element's query token is for the media route alone.
    assert bare.get(f"/api/recording/{rid}/waveform?t={token}").status_code == 401
    path.unlink()
    assert client.get(f"/api/recording/{rid}/waveform").status_code == 404
