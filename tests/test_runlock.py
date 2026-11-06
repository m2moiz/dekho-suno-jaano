"""The run lock's refusal names what holds it (#217).

A bleep render from the app holds the same lock a transcription does, so a
`dsj suno` refused while a render runs must say "render", not "another dsj
suno": the person reading it decides whether to wait by what is running.
"""

from __future__ import annotations

from pathlib import Path

from dsj.runlock import AlreadyRunning

LOCK = Path("/tmp/suno.lock")


def test_a_refusal_names_a_render_as_the_holder() -> None:
    said = str(AlreadyRunning(LOCK, {"pid": 48213, "out": "/x/call.bleeped.m4a", "kind": "render"}))
    assert said.startswith(
        "a bleep render from dsj ui (pid 48213) is running, writing /x/call.bleeped.m4a."
    ), said
    assert "another dsj suno" not in said
    assert "kill -0 48213" in said


def test_a_refusal_names_a_transcription_as_the_holder() -> None:
    said = str(AlreadyRunning(LOCK, {"pid": 7, "out": "/x/out.json", "kind": "transcription"}))
    assert said.startswith(
        "another dsj suno is already running on this machine: pid 7, writing /x/out.json."
    ), said


def test_a_holder_from_before_kinds_reads_as_a_transcription() -> None:
    """A lock file written by an older dsj carries no `kind`; it was always a transcription."""
    said = str(AlreadyRunning(LOCK, {"pid": 7, "out": "/x/out.json"}))
    assert said.startswith("another dsj suno is already running"), said
