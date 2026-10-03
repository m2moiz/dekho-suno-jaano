"""Starting a bleep render from the page, as a job (#215).

The real server app, the real job worker, the real dsj.hatao.render and the
real ffmpeg, on a tone ffmpeg makes in a temp directory: never one of the
owner's recordings. The checks are #128's: the input's bytes are unchanged,
each muted span reads far quieter in the output than in the input, the length
is kept to 0.05 s, and a picture is copied, not re-encoded away.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from dsj import hatao, media, runlock
from dsj.filetag import source_sidecar_for
from dsj.ui.server import create_app
from dsj.ui.store import Library

# editable words: " alpha" 0.3-0.65, " bravo" 0.8-1.15, " charlie" 1.3-1.65.
WORDS = [(" alpha", 0.3), (" bravo", 0.8), (" charlie", 1.3)]


def page() -> tuple[TestClient, str]:
    app, token = create_app(port=8721)
    client = TestClient(
        app, base_url="http://127.0.0.1:8721", headers={"Authorization": f"Bearer {token}"}
    )
    return client, token


def made(path: Path, *extra: str) -> Path:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
         "sine=frequency=440:duration=3", *extra, str(path)],
        check=True,
    )
    return path


def seeded(tmp_path: Path, recording: Path) -> int:
    payload = {
        "audio": str(recording), "engine": "parakeet", "model": "parakeet", "text": "",
        "unclear": [],
        "sentences": [{
            "start": 0.3, "end": 1.65, "text": "".join(w for w, _ in WORDS),
            "tokens": [{"t": t, "e": round(t + 0.35, 3), "w": w, "c": 0.9} for w, t in WORDS],
        }],
    }
    json_path = tmp_path / "talk.json"
    json_path.write_text(json.dumps(payload))
    with Library.open() as library:
        return library.record_run(json_path, engine="parakeet").id


def muting(client: TestClient, transcript_id: int, *words: str) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = client.get(f"/api/transcripts/{transcript_id}/edits").json()[
        "content"
    ]
    for entry in content:
        if entry.get("text", "").strip() in words:
            entry["muted"] = True
    return content


def finished(client: TestClient) -> dict[str, Any]:
    deadline = time.monotonic() + 30
    while True:
        listed: list[dict[str, Any]] = client.get("/api/renders").json()
        if listed and listed[-1]["state"] in ("done", "failed"):
            return listed[-1]
        assert time.monotonic() < deadline, f"waited 30 s; the renders read {listed}"
        time.sleep(0.05)


def mean_volume(path: Path, start: float, end: float) -> float:
    run = subprocess.run(
        ["ffmpeg", "-hide_banner", "-ss", str(start), "-t", str(end - start), "-i", str(path),
         "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    )
    found = re.search(r"mean_volume: (-?[\d.]+|-inf) dB", run.stderr)
    assert found, run.stderr
    return float(found.group(1))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_a_render_from_the_page_silences_the_muted_span_beside_the_recording(
    tmp_path: Path,
) -> None:
    recording = made(tmp_path / "talk.wav")
    before = sha(recording)
    transcript_id = seeded(tmp_path, recording)
    client, _ = page()
    reply = client.post(
        f"/api/transcripts/{transcript_id}/render",
        json={"content": muting(client, transcript_id, "bravo")},
    )
    assert reply.status_code == 202, reply.text
    assert reply.json()["spans"] == 1
    job = finished(client)
    assert job["state"] == "done", job
    out = Path(job["output"])
    assert out == tmp_path / "talk.bleeped.wav"
    assert source_sidecar_for(out).is_file()
    log = json.loads(out.with_name("talk.bleeped.bleeps.json").read_text())
    assert log["muted"] == [{"word": "bravo", "start": 0.8, "end": 1.15}]
    assert log["spans"] == [[0.7, 1.25]]
    # #128's checks: the input untouched, the span silent, the rest as it was.
    assert sha(recording) == before
    inside_in, inside_out = mean_volume(recording, 0.75, 1.2), mean_volume(out, 0.75, 1.2)
    after_in, after_out = mean_volume(recording, 1.5, 2.5), mean_volume(out, 1.5, 2.5)
    print(f"muted span 0.75-1.2 s: input {inside_in} dB, output {inside_out} dB; "
          f"untouched 1.5-2.5 s: input {after_in} dB, output {after_out} dB")
    assert inside_out < inside_in - 40
    assert abs(after_out - after_in) < 1
    assert abs(media.probe(out).duration_s - media.probe(recording).duration_s) < 0.05


def test_a_second_render_keeps_the_first(tmp_path: Path) -> None:
    recording = made(tmp_path / "talk.wav")
    transcript_id = seeded(tmp_path, recording)
    client, _ = page()
    for word in ("alpha", "charlie"):
        client.post(f"/api/transcripts/{transcript_id}/render",
                    json={"content": muting(client, transcript_id, word)})
        assert finished(client)["state"] == "done"
    assert (tmp_path / "talk.bleeped.wav").is_file()
    second = client.get("/api/renders").json()[-1]
    assert second["output"] == str(tmp_path / "talk.bleeped-2.wav")
    assert json.loads((tmp_path / "talk.bleeped-2.bleeps.json").read_text())["muted"][0][
        "word"
    ] == "charlie"


def test_a_picture_is_copied_and_the_sound_muted(tmp_path: Path) -> None:
    video = tmp_path / "screen.mov"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
         "testsrc2=size=160x120:rate=10:duration=3", "-f", "lavfi", "-i",
         "sine=frequency=440:duration=3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a",
         "aac", "-shortest", str(video)],
        check=True,
    )
    transcript_id = seeded(tmp_path, video)
    client, _ = page()
    client.post(f"/api/transcripts/{transcript_id}/render",
                json={"content": muting(client, transcript_id, "bravo")})
    job = finished(client)
    assert job["state"] == "done", job
    out = Path(job["output"])
    assert out.name == "screen.bleeped.mov"
    assert media.has_video(out)
    assert mean_volume(out, 0.75, 1.2) < mean_volume(video, 0.75, 1.2) - 40


def test_a_list_that_mutes_nothing_is_refused_and_nothing_is_written(tmp_path: Path) -> None:
    recording = made(tmp_path / "talk.wav")
    transcript_id = seeded(tmp_path, recording)
    client, _ = page()
    reply = client.post(f"/api/transcripts/{transcript_id}/render",
                        json={"content": muting(client, transcript_id)})
    assert reply.status_code == 422
    assert "Nothing in this list is muted" in reply.json()["message"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["talk.json", "talk.wav"]


def test_a_list_a_render_cannot_make_is_refused(tmp_path: Path) -> None:
    recording = made(tmp_path / "talk.wav")
    transcript_id = seeded(tmp_path, recording)
    client, _ = page()
    content = muting(client, transcript_id, "bravo")
    content[2], content[3] = content[3], content[2]
    reply = client.post(f"/api/transcripts/{transcript_id}/render", json={"content": content})
    assert reply.status_code == 422
    assert reply.json()["error"] == "RenderRefused"


def test_a_render_waits_its_turn_behind_a_run_holding_the_machine(tmp_path: Path) -> None:
    recording = made(tmp_path / "talk.wav")
    transcript_id = seeded(tmp_path, recording)
    client, _ = page()
    held = runlock.acquire({"pid": 4242, "out": "/tmp/other.json"})
    try:
        reply = client.post(f"/api/transcripts/{transcript_id}/render",
                            json={"content": muting(client, transcript_id, "bravo")})
    finally:
        import os

        os.close(held)
    assert reply.status_code == 409
    assert "pid 4242" in reply.json()["message"]
    assert not (tmp_path / "talk.bleeped.wav").exists()


def test_the_page_plays_a_finished_render_by_its_id_with_the_token_in_the_query(
    tmp_path: Path,
) -> None:
    recording = made(tmp_path / "talk.wav")
    transcript_id = seeded(tmp_path, recording)
    client, token = page()
    assert client.get("/api/renders/1/media").status_code == 404
    client.post(f"/api/transcripts/{transcript_id}/render",
                json={"content": muting(client, transcript_id, "bravo")})
    job = finished(client)
    bare = TestClient(client.app, base_url="http://127.0.0.1:8721")
    reply = bare.get(f"/api/renders/{job['id']}/media", params={"t": token})
    assert reply.status_code == 200
    assert reply.content == Path(job["output"]).read_bytes()
    assert bare.get(f"/api/renders/{job['id']}/media").status_code == 401


def test_words_the_render_capped_are_a_note_on_the_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#212's capped words, shown the way `dsj hatao` prints them on stderr."""
    recording = made(tmp_path / "talk.wav")
    transcript_id = seeded(tmp_path, recording)
    real = hatao.render

    class Capped:
        source_start, source_end, muted_end = 0.8, 3.0, 2.2

    def capping(*args: Any, **kwargs: Any) -> Any:
        done = real(*args, **kwargs)
        return type("Rendered", (), {"spans": done.spans, "untagged": done.untagged,
                                     "capped": (Capped(),)})()

    monkeypatch.setattr(hatao, "render", capping)
    monkeypatch.setattr(hatao, "MAX_WORD_S", 1.4, raising=False)
    client, _ = page()
    client.post(f"/api/transcripts/{transcript_id}/render",
                json={"content": muting(client, transcript_id, "bravo")})
    job = finished(client)
    assert job["notes"] == [
        "Capped 1 muted words whose transcript end ran past 1.4 s or into the next word; "
        "`capped` in talk.bleeped.bleeps.json lists them."
    ]
    log = json.loads((tmp_path / "talk.bleeped.bleeps.json").read_text())
    assert log["capped"] == [{"start": 0.8, "end": 3.0, "muted_to": 2.2}]
